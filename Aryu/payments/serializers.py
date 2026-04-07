from .models import *
from rest_framework import serializers
from django.utils import timezone
from django.db.models import Sum
from courses.models import Course
from aryuapp.models import Note, Student
from aryuapp.mixins import ContentType
import datetime, django.utils.timezone as tz
from django.utils import timezone
from decimal import Decimal
from aryuapp.mixins import NotesMixin
from batches.models import NewBatch
import uuid
class PaymentGatewaySerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentGateway
        fields = "__all__"
        read_only_fields = ["created_by", "created_at", "updated_at"]

    def create(self, validated_data):
        request = self.context.get("request")

        if request and request.user:
            role = getattr(request.user, "user_type", None)

            if role in ["trainer", "admin"]:
                validated_data["created_by"] = getattr(request.user, "trainer_id", None)
                validated_data["created_by_type"] = role

            elif role == "super_admin":
                validated_data["created_by"] = getattr(request.user, "user_id", None)
                validated_data["created_by_type"] = role

            elif role == "student":
                validated_data["created_by"] = getattr(request.user, "student_id", None)
                validated_data["created_by_type"] = role

            else:
                validated_data["created_by"] = getattr(request.user, "user_id", None)
                validated_data["created_by_type"] = role

        return super().create(validated_data)

class PaymentTransactionDetailSerializer(serializers.ModelSerializer):
    course_name = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()
    
    
    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "transaction_id",
            "amount",
            "course_name",
            "currency",
            "payment_status",
            
            "gateway",
            "created_at",
            "discount",
            "metadata"
        ]

    def get_course_name(self, obj):
        return obj.course.course_name if obj.course else None

    def get_payment_status(self, obj):
        # Just return the status of this transaction
        return obj.payment_status if obj.payment_status else "Pending"

   

class PaymentTransactionUpdateSerializer(serializers.ModelSerializer):
    total_course_fee = serializers.SerializerMethodField()
 
    class Meta:
        model = PaymentTransaction
        fields = [
            "payment_mode",
            "course",
            "amount",
            "discount",
            "total_after_discount",
            "currency",
            "payment_status",
            "transaction_id",
            "attachment",
            "description",
            "metadata",
            "total_course_fee",   # extra field to update course fee
        ]

    def get_total_course_fee(self, obj):
        if obj.course and hasattr(obj.course, 'fee'):
            return obj.course.fee
        return 0
class PaymentTransactionDeleteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = ["id", "is_archived"]
        read_only_fields = ["id"]


class PaymentCourseSerializer(serializers.Serializer):
    course_id = serializers.IntegerField()
    course_name = serializers.CharField()
    course_fee = serializers.FloatField()
    discount = serializers.FloatField()
    final_fee = serializers.FloatField()
    paid_amount = serializers.FloatField()
    balance = serializers.FloatField()
    transactions = PaymentTransactionDetailSerializer(many=True)


class StudentPaymentSummarySerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    registration_id = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
   
    courses = serializers.SerializerMethodField()  # NEW: nested per course

    class Meta:
        model = Student
        fields = [
            "student_id",
            "registration_id",
            "student_name",
            "email",
            "contact_no",
            "discount",
            # "payment_status",
            # "payment_mode",
            "courses",
        ]

    def get_student_name(self, obj):
        return f"{obj.first_name} ".strip()

    def get_registration_id(self, obj):
        return obj.registration_id

    def get_discount(self, obj):
        return float(getattr(obj, "discount", 0))
    

    def get_courses(self, obj):
        """
        Build per-course summary with transactions
        """
        courses_data = []
        

        # Iterate over student's batches (or courses)
        for batch in obj.new_batches.all():  # ✅ use .all()
            course = getattr(batch, "course", None)
            if not course:
                continue

            # Filter transactions belonging to this course
            txs = [
                tx for tx in obj.transactions.all()
                if tx.course_id == course.course_id
            ]

            total_paid = sum(
                float(tx.amount or 0) 
                for tx in txs 
                if tx.payment_status and tx.payment_status.lower() == "success"
            )

            course_fee = float(getattr(course, "fee", 0))
            student_discount = float(getattr(obj, "discount", 0))
            final_fee = course_fee - student_discount
            balance = max(final_fee - total_paid, 0.0)

            courses_data.append({
                "course_id": course.course_id,
                "course_name": course.course_name,
                "course_fee": course_fee,
                "discount": student_discount,
                "final_fee": final_fee,
                "paid_amount": total_paid,
                "balance": balance,
                "transactions": PaymentTransactionDetailSerializer(txs, many=True).data
            })

        return courses_data
    
class PaymentLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentLog
        fields = '__all__'

class PaymentTransactionCreateSerializer(serializers.ModelSerializer):
    emi_installment_id = serializers.IntegerField(required=False, allow_null=True)
    date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True)
    total_after_discount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    transaction_id = serializers.CharField(read_only=True)
    attachment = serializers.FileField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True)
    metadata = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = PaymentTransaction
        fields = [
            "student",
            "amount",
            "discount",
            "total_after_discount",
            "currency",
            "payment_status",
            "transaction_id",
            "attachment",
            "description",
            "metadata",
            "emi_installment_id",
            "date",
            "note",
        ]

    def validate(self, attrs):
        # ── FIX: idempotency guard ────────────────────────────────
        # If the same student + amount + status was already created in the
        # last 30 seconds, reject it as a duplicate.
        
        student = attrs.get("student")
        amount  = attrs.get("amount")
        payment_status  = attrs.get("payment_status")
        if student and amount and payment_status:
            cutoff = tz.now() - datetime.timedelta(seconds=30)
            duplicate = PaymentTransaction.objects.filter(
                student=student,
                amount=amount,
                payment_status=payment_status,
                is_archived=False,
                created_at__gte=cutoff,
            ).exists()
            if duplicate:
                raise serializers.ValidationError(
                    "A duplicate payment was detected. Please wait a moment before retrying."
                )
 
        # ── EMI validation ────────────────────────────────────────
        installment_id = attrs.get("emi_installment_id")
        if installment_id:
            try:
                installment = PaymentEMIInstallment.objects.get(pk=installment_id)
            except PaymentEMIInstallment.DoesNotExist:
                raise serializers.ValidationError("Invalid EMI installment.")
            if installment.paid:
                raise serializers.ValidationError("This EMI installment is already paid.")
            if attrs["amount"] != installment.amount:
                raise serializers.ValidationError(
                    f"Installment amount must be {installment.amount}"
                )
        return attrs
 
   
    def create(self, validated_data):
        emi_installment_id = validated_data.pop("emi_installment_id", None)
        note_text = validated_data.pop("note", None)
        date_value = validated_data.pop("date", None)  # remove it from validated_data

        # Ensure transaction_id exists
        if not validated_data.get("transaction_id"):
            validated_data["transaction_id"] = f"TXN{uuid.uuid4().hex[:8].upper()}"
        # Compute discount if not provided
        if not validated_data.get("discount"):
            student = validated_data.get("student")
            course = validated_data.get("course")
            # find the batch the student is enrolled in for this course
            batch = NewBatch.objects.filter(student=student, course=course).first()
            if batch:
                validated_data["discount"] = batch.discount or Decimal("0")



        # Compute total after discount
        amount = validated_data.get("amount", Decimal("0"))
        discount = validated_data.get("discount", Decimal("0"))
        validated_data["total_after_discount"] = amount - discount

        # Save date inside metadata if provided
        if date_value:
            metadata = validated_data.get("metadata") or {}
            metadata["payment_date"] = str(date_value)
            validated_data["metadata"] = metadata

        # Save payment_status & payment_mode
        status = validated_data.pop("payment_status", None)
        mode = validated_data.pop("payment_mode", None)
        if status:
            validated_data["payment_status"] = status
        if mode:
            validated_data["payment_mode"] = mode

        # Create the transaction
        transaction = super().create(validated_data)

        # Save note if provided
        if note_text:
            mixin = NotesMixin()
            mixin.save_notes(transaction, note_text, request=self.context.get("request"))

        # Mark EMI installment as paid
        if emi_installment_id:
            installment = PaymentEMIInstallment.objects.select_related("emi_plan").get(pk=emi_installment_id)
            installment.paid = True
            installment.paid_amount = transaction.amount
            installment.payment = transaction
            installment.paid_at = timezone.now()
            installment.save()

        return transaction
    
class StripePaymentSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    success_url = serializers.URLField()
    cancel_url = serializers.URLField()

class PayPalPaymentSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    success_url = serializers.URLField()
    cancel_url = serializers.URLField()



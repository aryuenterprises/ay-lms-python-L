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
from payments.services.invoice_service import InvoiceService
from webinar.models import WebinarRegistration
from aryuapp.models import Employer
import uuid
from collections import defaultdict
from aryuapp.models import Trainer
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
    invoice_url = serializers.SerializerMethodField()
    
    
    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "transaction_id",
            "amount",
            "course_name",
            "currency",
            "payment_status",
            "invoice_date",
            "invoice_url",
            "gateway",
            "created_at",
            "discount",
            "metadata",
            "payment_mode"
        ]

    def get_course_name(self, obj):
        return obj.course.course_name if obj.course else None

    def get_payment_status(self, obj):
        # Just return the status of this transaction
        return obj.payment_status if obj.payment_status else "Pending"
    
    def get_invoice_url(self, obj):

        if obj.invoice and hasattr(obj.invoice, "url"):
            return (
                "https://portal.aryuacademy.com/api"
                + obj.invoice.url
            )

        return None

class GenerateInvoiceSerializer(serializers.Serializer):

    transaction_id = serializers.IntegerField(
        required=True
    )

    regenerate = serializers.BooleanField(
        required=False,
        default=False
    )

    def validate_transaction_id(self, value):

        transaction = (
            PaymentTransaction.objects.filter(
                id=value,
                is_archived=False
            )
            .select_related(
                "student",
                "course",
                "employer",
                "webinar_registration"
            )
            .first()
        )

        if not transaction:
            raise serializers.ValidationError(
                "Transaction not found"
            )

        valid_statuses = [
            "success",
            "paid",
            "complete",
            "partial",
            "advanced",
            "done"
        ]

        if (
            not transaction.payment_status
            or transaction.payment_status.lower()
            not in valid_statuses
        ):
            raise serializers.ValidationError(
                "Invoice can only be generated for successful transactions"
            )

        self.transaction = transaction

        return value

class PaymentTransactionCreateSerializer(serializers.ModelSerializer):

    emi_installment_id = serializers.IntegerField(
        required=False,
        allow_null=True
    )

    employer_id = serializers.IntegerField(
        required=False,
        allow_null=True
    )

    webinar_registration_id = serializers.IntegerField(
        required=False,
        allow_null=True
    )

    billing_type = serializers.ChoiceField(
        choices=[
            "student",
            "company",
            "webinar"
        ],
        default="student"
    )

    note = serializers.CharField(
        required=False,
        allow_blank=True
    )

    date = serializers.DateField(
        required=False,
        allow_null=True
    )

    invoice_url = serializers.SerializerMethodField()

    screenshot_url = serializers.SerializerMethodField()

    class Meta:
        model = PaymentTransaction

        fields = [
        "student",
        "course",
        "amount",
        "course_fee",
        "phone",
        "gateway",
        "discount",
        "currency",
        "payment_status",
        "payment_mode",
        "attachment",
        "description",
        "metadata",
        "note",
        "date",
        "emi_installment_id",
        "billing_type",
        "employer_id",
        "webinar_registration_id",
        "invoice",
        "invoice_date",
        "invoice_url",
        "screenshot",
        "screenshot_url",
        "transaction_id"
    ]

    def get_invoice_url(self, obj):

        if obj.invoice and hasattr(obj.invoice, "url"):
            return (
                "https://portal.aryuacademy.com/api"
                + obj.invoice.url
            )

        return None

    def get_screenshot_url(self, obj):

        request = self.context.get("request")

        if obj.screenshot:
            return request.build_absolute_uri(
                obj.screenshot.url
            )

        return None
    
    def validate(self, data):
        invoice_date = data.get("invoice_date")

        # Prevent future payment date
        if invoice_date and invoice_date > timezone.localdate():
            raise serializers.ValidationError({
                "invoice_date": "Future date transactions are not allowed."
            })

        student = data.get("student")
        course = data.get("course")
        amount = data.get("amount")

        # 1. Validation for Course Payments
        if student and course and amount:
            course_fee = float(getattr(course, "fee", 0))
            
            # Check if a specific transaction discount is provided, otherwise use the student's global discount
            tx_discount = data.get("discount")
            discount = float(tx_discount) if tx_discount is not None else float(getattr(student, "discount", 0) or 0)
            
            total_after_discount = course_fee - discount
            
            # Fetch all valid transactions for THIS student and THIS specific course
            existing_paid = PaymentTransaction.objects.filter(
                student=student,
                course=course,
                is_archived=False,
                payment_status__in=["success", "done", "paid", "pending","complete","advanced"]
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            existing_paid = float(existing_paid)
            incoming_amount = float(amount)

            # 2. Block if it exceeds the remaining balance
            if (existing_paid + incoming_amount) > total_after_discount:
                allowed = max(0, total_after_discount - existing_paid)
                raise serializers.ValidationError({
                    "amount": f"Payment exceeds the total course fee after discount. "
                              f"Final fee: ₹{total_after_discount}, Already paid: ₹{existing_paid}. "
                              f"Maximum allowed payment is ₹{allowed}."
                })
        
        return data
    

    def create(self, validated_data):

        employer_id = validated_data.pop(
            "employer_id",
            None
        )

        webinar_registration_id = validated_data.pop(
            "webinar_registration_id",
            None
        )

        billing_type = validated_data.pop(
            "billing_type",
            "student"
        )

        note_text = validated_data.pop(
            "note",
            None
        )

        emi_installment_id = validated_data.pop(
            "emi_installment_id",
            None
        )

        date_value = validated_data.pop(
            "date",
            None
        )

        employer = None
        webinar_registration = None

        # ====================================
        # COMPANY BILLING
        # ====================================

        if billing_type == "company":

            employer = Employer.objects.filter(
                company_id=employer_id
            ).first()

            if not employer:
                raise serializers.ValidationError({
                    "employer_id":
                    "Valid employer required"
                })

        # ====================================
        # WEBINAR BILLING
        # ====================================

        if billing_type == "webinar":

            webinar_registration = (
                WebinarRegistration.objects.filter(
                    id=webinar_registration_id
                ).first()
            )

            if not webinar_registration:
                raise serializers.ValidationError({
                    "webinar_registration_id":
                    "Valid webinar registration required"
                })

        # ====================================
        # TRANSACTION ID
        # ====================================

        payment_mode = validated_data.get("payment_mode")

        if payment_mode in ["OFFLINE", "CHEQUE"]:
            # Auto generate transaction id
            validated_data["transaction_id"] = (
                f"TXN{uuid.uuid4().hex[:8].upper()}"
            )
        else:
            # User must enter transaction id
            transaction_id = validated_data.get("transaction_id")

            if not transaction_id:
                raise serializers.ValidationError({
                    "transaction_id": "Transaction ID is required for this payment mode."
                })

            validated_data["transaction_id"] = transaction_id

        # ====================================
        # DATE
        # ====================================

        if date_value:

            metadata = (
                validated_data.get("metadata")
                or {}
            )

            metadata["payment_date"] = str(
                date_value
            )

            validated_data["metadata"] = metadata

        # ====================================
        # CREATE TRANSACTION
        # ====================================

        transaction = PaymentTransaction.objects.create(
            employer=employer,
            webinar_registration=webinar_registration,
            billing_type=billing_type,
            **validated_data
        )

        # ====================================
        # NOTES
        # ====================================

        if note_text:

            mixin = NotesMixin()

            mixin.save_notes(
                transaction,
                note_text,
                request=self.context.get(
                    "request"
                )
            )

        # ====================================
        # EMI
        # ====================================

        if emi_installment_id:

            installment = (
                PaymentEMIInstallment.objects
                .select_related("emi_plan")
                .get(pk=emi_installment_id)
            )

            installment.paid = True
            installment.paid_amount = (
                transaction.amount
            )

            installment.payment = transaction

            installment.paid_at = timezone.now()

            installment.save()

        # ====================================
        # AUTO GENERATE INVOICE
        # ====================================

        if (
            transaction.payment_status
            and transaction.payment_status.lower()
            in ["success", "done", "paid"]
        ):

            InvoiceService.generate_invoice(
                transaction.id
            )

        return transaction 

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
            "invoice_date",
            "attachment",
            "description",
            "metadata",
            "total_course_fee",   # extra field to update course fee
        ]
        extra_kwargs = {
            "course": {"required": False},
            "amount": {"required": False},
            "payment_mode": {"required": False},
            "payment_status": {"required": False},
            "transaction_id": {"required": False},
            "attachment": {"required": False},
            "description": {"required": False},
            "metadata": {"required": False},
            "discount": {"required": False},
            "currency": {"required": False},
            "total_after_discount": {"required": False},
        }

    def get_total_course_fee(self, obj):
        if obj.course and hasattr(obj.course, 'fee'):
            return obj.course.fee
        return 0
    def validate(self, data):
        # ---------------- Future Date Validation ----------------
        invoice_date = data.get("invoice_date")
        if invoice_date and invoice_date > timezone.localdate():
            raise serializers.ValidationError({
                "invoice_date": "Future date transactions are not allowed."
            })

        instance = self.instance

        student = instance.student
        course = data.get("course", instance.course)
        amount = data.get("amount", instance.amount)

        if student and course:
            # Calculate total paid excluding the current transaction
            already_paid = (
                PaymentTransaction.objects.filter(
                    student=student,
                    course=course,
                    is_archived=False
                )
                .exclude(pk=instance.pk)
                .aggregate(total=Sum("amount"))["total"] or 0
            )

            # Calculate final fee (after discount if applicable)
            final_fee = (
                instance.total_after_discount
                if instance.total_after_discount
                else getattr(course, "fee", 0)
            )

            if already_paid + amount > final_fee:
                raise serializers.ValidationError({
                    "amount": (
                        f"Payment exceeds the total course fee after discount. "
                        f"Final fee: ₹{final_fee}, "
                        f"Already paid: ₹{already_paid}. "
                        f"Maximum allowed payment is ₹{final_fee - already_paid}."
                    )
                })

        return data

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

class CourseDropdownSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ['course_id', 'course_name', 'fee']

# Dropdown Serializer for Active Batches
class BatchDropdownSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewBatch
        fields = ['batch_id', 'title', 'course']

# Serializer to save Tutor Payment
class TrainerHeaderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trainer
        fields = ['trainer_id', 'full_name', 'email', 'contact_no']


# 2. Read Serializer (Used for GET - List & Single View)
class TutorPaymentReadSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.course_name', read_only=True)
    batch_title = serializers.CharField(source='batch.title', read_only=True)
    tutor_name = serializers.CharField(source='tutor.full_name', read_only=True, default=None)

    class Meta:
        model = TutorPayment
        fields = [
            'id',
            'tutor',             # <--- Foreign key field name on TutorPayment model
            'tutor_name',
            'course',
            'course_name',
            'batch',
            'batch_title',
            'course_fee',
            'payment_type',
            'tutor_payment',
            'payment_status',
            'payment_date',
            'notes',
            'created_at',
            'updated_at',
        ]


# 3. Write Serializer (Used for POST, PUT, PATCH - Add & Edit)
class TutorPaymentWriteSerializer(serializers.ModelSerializer):
    tutor = serializers.PrimaryKeyRelatedField(queryset=Trainer.objects.all())
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.all())
    batch = serializers.PrimaryKeyRelatedField(queryset=NewBatch.objects.all())

    class Meta:
        model = TutorPayment
        fields = [
            'id',
            'tutor',            # <--- Uses foreign key field 'tutor'
            'course',
            'batch',
            'course_fee',
            'payment_type',
            'tutor_payment',
            'payment_status',
            'payment_date',
            'notes',
        ]
        

class StudentPaymentSummarySerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    registration_id = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    aggregated_course_fee = serializers.SerializerMethodField()
    aggregated_paid_amount = serializers.SerializerMethodField()
    aggregated_due_amount = serializers.SerializerMethodField()
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
            "aggregated_course_fee",   
            "aggregated_paid_amount",  
            "aggregated_due_amount",
            "courses",
        ]

    def _get_course_calculations(self, obj):
        """
        Helper method to calculate the math ONCE per student and cache it.
        This prevents DRF from running the loop 4 times for the 4 MethodFields.
        """
        if hasattr(obj, '_cached_payment_data'):
            return obj._cached_payment_data

        courses_data = []
        total_course_fee = 0.0
        total_paid = 0.0
        total_due = 0.0

        for batch in obj.new_batches.all():
            course = getattr(batch, "course", None)
            if not course:
                continue

            txs = [
                tx for tx in obj.transactions.all()
                if tx.course_id == course.course_id
            ]

            paid_amount = sum(
                float(tx.amount or 0) 
                for tx in txs 
                if tx.payment_status and tx.payment_status.lower() in ["success", "done", "paid", "partial","advanced","complete"]
            )

            course_fee = float(course.fee or 0)
            discount = float(obj.discount or 0)
            
            # Calculate final numbers for the specific course
            total_after_discount = course_fee - discount
            due_amount = max(total_after_discount - paid_amount, 0.0)

            # Add to the global aggregates
            total_course_fee += total_after_discount
            total_paid += paid_amount
            total_due += due_amount

            courses_data.append({
                "course_id": course.course_id,
                "course_name": course.course_name,
                "course_fee": course_fee,
                "discount": discount,
                "total_after_discount": total_after_discount,
                "paid_amount": paid_amount,
                "due_amount": due_amount,
                "transactions": PaymentTransactionDetailSerializer(txs, many=True).data
            })

        # Cache the results on the object so the next MethodField can just grab it
        obj._cached_payment_data = {
            "courses": courses_data,
            "aggregated_course_fee": total_course_fee,
            "aggregated_paid_amount": total_paid,
            "aggregated_due_amount": total_due
        }
        
        return obj._cached_payment_data

    def get_student_name(self, obj):
        return f"{obj.first_name} ".strip()

    def get_registration_id(self, obj):
        return obj.registration_id

    def get_discount(self, obj):
        return float(getattr(obj, "discount", None) or 0)

    def get_courses(self, obj):
        return self._get_course_calculations(obj)["courses"]

    def get_aggregated_course_fee(self, obj):
        return self._get_course_calculations(obj)["aggregated_course_fee"]

    def get_aggregated_paid_amount(self, obj):
        return self._get_course_calculations(obj)["aggregated_paid_amount"]

    def get_aggregated_due_amount(self, obj):
        return self._get_course_calculations(obj)["aggregated_due_amount"] 


class PaymentLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentLog
        fields = '__all__'

class StripePaymentSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    success_url = serializers.URLField()
    cancel_url = serializers.URLField()

class PayPalPaymentSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    success_url = serializers.URLField()
    cancel_url = serializers.URLField()



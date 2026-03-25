from .models import *
from rest_framework import serializers
from django.utils import timezone
from django.db.models import Sum
from django.db import transaction as db_transaction
from decimal import Decimal
from courses.models import Course
from aryuapp.models import Note, Student
from aryuapp.mixins import ContentType

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

class PaymentTransactionUpdateSerializer(serializers.ModelSerializer):
    total_course_fee = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )
 
    class Meta:
        model = PaymentTransaction
        fields = [
            "gateway",
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
 
    def update(self, instance, validated_data):
        # Pop total_course_fee — it belongs to Course model, not PaymentTransaction
        total_course_fee = validated_data.pop("total_course_fee", None)
 
        # Recalculate total_after_discount if amount or discount changed
        amount   = validated_data.get("amount",   instance.amount)
        discount = validated_data.get("discount", instance.discount)
        validated_data["total_after_discount"] = amount - discount
 
        # Update the transaction fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
 
        # Update the course fee if provided
        if total_course_fee is not None and instance.course:
            Course.objects.filter(course_id=instance.course.course_id).update(
                fee=total_course_fee
            )
 
        return instance
class PaymentTransactionDetailSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    notes = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()
    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "transaction_id",
            "amount",
            "currency",
            "payment_status",
            "attachment_url",
            "metadata",
            "notes",
            "created_at",
        ]

    def get_attachment_url(self, obj):
        if obj.attachment and hasattr(obj.attachment, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.attachment.url
        return None
    
    def get_notes(self, obj):
        transaction_ct = ContentType.objects.get_for_model(obj)

        notes_qs = Note.objects.filter(
            content_type=transaction_ct,
            object_id=obj.pk
        ).order_by("-created_at")

        return [
            {
                "note_id": n.id,
                "reason": n.reason,
                "created_by": n.created_by,
                "status": n.status,
                "created_at": n.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for n in notes_qs
        ]

class StudentPaymentSummarySerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    registration_id = serializers.SerializerMethodField()

    total_course_fee = serializers.SerializerMethodField()
    paid_amount = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()

    transactions = PaymentTransactionDetailSerializer(many=True, read_only=True)

    class Meta:
        model = Student
        fields = [
            "student_name",
            "registration_id",
            "student_id",
            "total_course_fee",
            "paid_amount",
            "remaining_amount",
            "transactions",
        ]

    # -------------------------
    # BASIC DETAILS
    # -------------------------
    def get_student_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_registration_id(self, obj):
        return obj.registration_id

    # -------------------------
    # BASE TRANSACTION (IMPORTANT)
    # -------------------------
    def _student_course(self, obj):
        """
        Get course from student's batch
        """
        if not hasattr(obj, "_course_cache"):
            batch = (
                obj.new_batches
                .filter(is_archived=False)
                .select_related("course")
                .first()
            )
            obj._course_cache = batch.course if batch else None
        return obj._course_cache

    # -------------------------
    # TOTAL COURSE FEE
    # -------------------------
    def get_total_course_fee(self, obj):
        course = self._student_course(obj)
        return course.fee if course else 0

    # -------------------------
    # PAID AMOUNT (ONLY SUCCESS)
    # -------------------------
    def get_paid_amount(self, obj):
        return obj.transactions.filter(
            payment_status__in=["done", "Done"],
            is_archived=False
        ).aggregate(total=Sum("amount"))["total"] or 0

    # -------------------------
    # REMAINING AMOUNT (FINAL FIX)
    # -------------------------
    def get_remaining_amount(self, obj):
        total_fee = self.get_total_course_fee(obj)
        discount = obj.discount or 0
        paid = self.get_paid_amount(obj)

        remaining = (total_fee - discount) - paid
        return max(remaining, 0)

class PaymentLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentLog
        fields = '__all__'

class PaymentTransactionCreateSerializer(serializers.ModelSerializer):
    emi_installment_id = serializers.IntegerField(required=False)

    class Meta:
        model = PaymentTransaction
        fields = [
            "student",
            "course",
            "gateway",
            "amount",
            "discount",
            "total_after_discount",
            "currency",
            "payment_status",
            "transaction_id",
            "attachment", 
            "description",
            "metadata",
            "emi_installment_id"
        ]


    def validate(self, attrs):
        installment_id = attrs.get("emi_installment_id")

        if installment_id:
            try:
                installment = PaymentEMIInstallment.objects.get(pk=installment_id)
            except PaymentEMIInstallment.DoesNotExist:
                raise serializers.ValidationError("Invalid EMI installment.")

            # Check if already paid
            if installment.paid:
                raise serializers.ValidationError("This EMI installment is already paid.")

            # Amount should match installment amount
            if attrs["amount"] != installment.amount:
                raise serializers.ValidationError(
                    f"Installment amount must be {installment.amount}"
                )

        return attrs

    def create(self, validated_data):
        metadata = validated_data.get("metadata", {})
        emi_installment_id = validated_data.pop("emi_installment_id", None)

        student = validated_data["student"]
        amount = validated_data["amount"]

        with db_transaction.atomic():  # CRITICAL

            transaction_obj = super().create(validated_data)

            # =========================================
            # CASE 1: Paying existing EMI installment
            # =========================================
            if emi_installment_id:
                try:
                    installment = PaymentEMIInstallment.objects.select_related("emi_plan").get(
                        pk=emi_installment_id,
                        emi_plan__student=student  # security check
                    )
                except PaymentEMIInstallment.DoesNotExist:
                    raise serializers.ValidationError("Invalid EMI installment.")

                if installment.paid:
                    raise serializers.ValidationError("Installment already paid.")

                installment.paid = True
                installment.paid_amount = amount
                installment.payment = transaction_obj
                installment.paid_at = timezone.now()
                installment.save()

                return transaction_obj

            # =========================================
            # CASE 2: Create EMI plan from metadata
            # =========================================
            emi_data = metadata.get("emi")

            if emi_data:
                months = emi_data.get("months")
                total_fee = emi_data.get("total_fee")

                if not months or not total_fee:
                    raise serializers.ValidationError("Invalid EMI metadata provided.")

                # Prevent duplicate EMI plans
                emi = PaymentEMI.objects.filter(
                    student=student,
                    total_amount=total_fee,
                    months=months
                ).first()

                if not emi:
                    emi = PaymentEMI.objects.create(
                        student=student,
                        total_amount=total_fee,
                        months=months
                    )

                    installments = emi.create_installments()
                else:
                    installments = emi.installments.all().order_by("due_date")

                #  Safe decimal comparison
                if installments:
                    first = installments[0]

                    if Decimal(first.amount) == Decimal(amount):
                        if not first.paid:
                            first.paid = True
                            first.paid_amount = amount
                            first.payment = transaction_obj
                            first.paid_at = timezone.now()
                            first.save()

            return transaction_obj

class StripePaymentSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    success_url = serializers.URLField()
    cancel_url = serializers.URLField()

class PayPalPaymentSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    success_url = serializers.URLField()
    cancel_url = serializers.URLField()



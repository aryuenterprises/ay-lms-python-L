from .models import *
from rest_framework import serializers
from django.utils import timezone
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
    gateway_name = serializers.CharField(source="gateway.gatway_name", read_only=True)
    course_name = serializers.CharField(source="course.course_name", read_only=True)
    attachment_url = serializers.SerializerMethodField()
    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "transaction_id",
            "amount",
            "currency",
            "payment_status",
            "gateway",
            "discount",
            "total_after_discount",
            "gateway_name",
            "attachment_url",
            "course",
            "course_name",
            "description",
            "metadata",
            "notes",
            "created_at",
        ]

    def get_attachment_url(self, obj):
        if obj.attachment and hasattr(obj.attachment, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.attachment.url
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

    course_name = serializers.SerializerMethodField()
    total_course_fee = serializers.SerializerMethodField()
    paid_amount = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()

    transactions = PaymentTransactionDetailSerializer(many=True, read_only=True)
    emi_plans = serializers.SerializerMethodField()

    remaining_emi_count = serializers.SerializerMethodField()
    next_due_emi_date = serializers.SerializerMethodField()
    next_due_emi_amount = serializers.SerializerMethodField()
    total_pending_emi_amount = serializers.SerializerMethodField()
    overdue_emi_list = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "student_name",
            "registration_id",
            "student_id",
            "email",
            "contact_no",
            "current_address",
            "joining_date",

            "course_name",
            "total_course_fee",
            "paid_amount",
            "remaining_amount",

            "transactions",
            "remaining_emi_count",
            "emi_plans",
            "next_due_emi_date",
            "next_due_emi_amount",
            "total_pending_emi_amount",
            "overdue_emi_list",
        ]

    # --------------------------------------------------
    # BASIC DETAILS
    # --------------------------------------------------

    def get_student_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_registration_id(self, obj):
        return obj.registration_id

    # --------------------------------------------------
    # TRANSACTION HELPERS (cached per student)
    # --------------------------------------------------

    def _successful_transactions(self, obj):
        if not hasattr(obj, "_success_tx_cache"):
            obj._success_tx_cache = [
                tx for tx in obj.transactions.all()
                if tx.payment_status == "Success"
            ]
        return obj._success_tx_cache

    def _latest_success_tx(self, obj):
        if not hasattr(obj, "_latest_success_tx"):
            success_tx = self._successful_transactions(obj)
            obj._latest_success_tx = (
                max(success_tx, key=lambda t: t.created_at)
                if success_tx else None
            )
        return obj._latest_success_tx

    # --------------------------------------------------
    # COURSE INFO
    # --------------------------------------------------

    def get_total_course_fee(self, obj):
        last_tx = self._latest_success_tx(obj)
        return last_tx.course.fee if last_tx and last_tx.course else 0

    def get_course_name(self, obj):
        last_tx = self._latest_success_tx(obj)
        return last_tx.course.course_name if last_tx and last_tx.course else None

    # --------------------------------------------------
    # PAYMENT SUMMARY
    # --------------------------------------------------

    def get_paid_amount(self, obj):
        success_tx = self._successful_transactions(obj)
        return sum(tx.amount for tx in success_tx)

    def get_remaining_amount(self, obj):
        remaining = self.get_total_course_fee(obj) - self.get_paid_amount(obj)
        return max(remaining, 0)

    # --------------------------------------------------
    # EMI HELPERS
    # --------------------------------------------------

    def _all_installments(self, obj):
        if not hasattr(obj, "_installments_cache"):
            installments = []
            for emi in obj.emi_plans.all():
                installments.extend(list(emi.installments.all()))
            obj._installments_cache = installments
        return obj._installments_cache

    # --------------------------------------------------
    # EMI DETAILS
    # --------------------------------------------------

    def get_emi_plans(self, obj):
        return [
            {
                "months": emi.months,
                "total_amount": emi.total_amount,
                "installments": [
                    {
                        "due_date": ins.due_date,
                        "amount": ins.amount,
                        "paid": ins.paid,
                        "paid_amount": ins.paid_amount,
                        "paid_at": ins.paid_at,
                    }
                    for ins in emi.installments.all()
                ],
            }
            for emi in obj.emi_plans.all()
        ]

    # --------------------------------------------------
    # EMI SUMMARY
    # --------------------------------------------------

    def get_remaining_emi_count(self, obj):
        installments = self._all_installments(obj)
        return sum(1 for ins in installments if not ins.paid)

    def get_next_due_emi_date(self, obj):
        installments = [i for i in self._all_installments(obj) if not i.paid]
        if not installments:
            return None
        return min(installments, key=lambda i: i.due_date).due_date

    def get_next_due_emi_amount(self, obj):
        installments = [i for i in self._all_installments(obj) if not i.paid]
        if not installments:
            return None
        return min(installments, key=lambda i: i.due_date).amount

    def get_total_pending_emi_amount(self, obj):
        return sum(ins.amount for ins in self._all_installments(obj) if not ins.paid)

    def get_overdue_emi_list(self, obj):
        today = timezone.now().date()

        return [
            {
                "due_date": ins.due_date,
                "amount": ins.amount,
                "days_overdue": (today - ins.due_date).days,
            }
            for ins in self._all_installments(obj)
            if not ins.paid and ins.due_date < today
        ]

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
        course = validated_data["course"]

        amount = validated_data["amount"]
        discount = validated_data.get("discount", 0)

        validated_data["total_after_discount"] = amount - discount

        transaction = super().create(validated_data)

        if emi_installment_id:
            installment = PaymentEMIInstallment.objects.select_related("emi_plan").get(pk=emi_installment_id)

            # Validate installment belongs to same course
            if installment.emi_plan.course_id != course.id:
                raise serializers.ValidationError("This EMI installment does not belong to this course.")

            # Mark installment as paid
            installment.paid = True
            installment.paid_amount = transaction.amount
            installment.payment = transaction
            installment.paid_at = timezone.now()
            installment.save()

            return transaction

        emi_data = metadata.get("emi")

        if emi_data:
            months = emi_data.get("months")
            total_fee = emi_data.get("total_fee")

            if not months or not total_fee:
                raise serializers.ValidationError("Invalid EMI metadata provided.")

            # Create EMI plan for THIS COURSE ONLY
            emi = PaymentEMI.objects.create(
                student=student,
                course=course,                 # NEW: Important link to course
                total_amount=total_fee,
                months=months
            )

            # Create installments
            installments = emi.create_installments()

            # If first installment equals payment amount → Auto mark first as paid
            if installments and float(installments[0].amount) == float(transaction.amount):
                first = installments[0]
                first.paid = True
                first.paid_amount = transaction.amount
                first.payment = transaction
                first.paid_at = timezone.now()
                first.save()

        # Done
        return transaction

class StripePaymentSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    success_url = serializers.URLField()
    cancel_url = serializers.URLField()

class PayPalPaymentSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    success_url = serializers.URLField()
    cancel_url = serializers.URLField()



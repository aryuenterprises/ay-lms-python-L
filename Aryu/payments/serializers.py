import logging
from .models import *
from rest_framework import serializers
from django.utils import timezone
from django.db.models import Sum
from django.db import transaction as db_transaction
from courses.models import Course
from aryuapp.models import Note, Student, StudentCourse
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
from django.conf import settings

logger = logging.getLogger(__name__)

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
        return InvoiceService.get_invoice_url(obj, request=self.context.get("request"))

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
# class TutorPaymentReadSerializer(serializers.ModelSerializer):
#     course_name = serializers.CharField(source='course.course_name', read_only=True)
#     batch_title = serializers.CharField(source='batch.title', read_only=True)
#     tutor_name = serializers.CharField(source='tutor.full_name', read_only=True, default=None)

#     class Meta:
#         model = TutorPayment
#         fields = [
#             'id',
#             'tutor',             # <--- Foreign key field name on TutorPayment model
#             'tutor_name',
#             'course',
#             'course_name',
#             'batch',
#             'batch_title',
#             'course_fee',
#             'payment_type',
#             'tutor_payment',
#             'payment_status',
#             'payment_date',
#             'notes',
#             'created_at',
#             'updated_at',
#         ]

class TutorPaymentReadSerializer(serializers.ModelSerializer):
    tutor_name = serializers.CharField(source='tutor.name', read_only=True)  # Adjust source field name
    course_name = serializers.CharField(source='course.course_name', read_only=True)
    batch_title = serializers.CharField(source='batch.title', read_only=True)

    class Meta:
        model = TutorPayment
        fields = [
            'id',
            'tutor',
            'tutor_name',
            'course',
            'course_name',
            'batch',            # Returns array e.g., [25, 24]
            'course_fee',
            'payment_type',
            'tutor_payment',
            'payment_status',
            'payment_date',
            'notes',
            'created_at',
            'updated_at',
        ]

    def get_batch(self, obj):
        if not obj.batch:
            return []
        
        # If stored as string "25,24", parse it back to list [25, 24]
        if isinstance(obj.batch, str):
            try:
                return [int(b.strip()) for b in obj.batch.split(',') if b.strip().isdigit()]
            except ValueError:
                return [obj.batch]
                
        return [obj.batch]

# 3. Write Serializer (Used for POST, PUT, PATCH - Add & Edit)
# class TutorPaymentWriteSerializer(serializers.ModelSerializer):
#     tutor = serializers.PrimaryKeyRelatedField(queryset=Trainer.objects.all())
#     course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.all())
#     batch = serializers.PrimaryKeyRelatedField(queryset=NewBatch.objects.all())

#     class Meta:
#         model = TutorPayment
#         fields = [
#             'id',
#             'tutor',            # <--- Uses foreign key field 'tutor'
#             'course',
#             'batch',
#             'course_fee',
#             'payment_type',
#             'tutor_payment',
#             'payment_status',
#             'payment_date',
#             'notes',
#         ]

class TutorPaymentWriteSerializer(serializers.ModelSerializer):
    tutor = serializers.PrimaryKeyRelatedField(queryset=Trainer.objects.all())
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.all())
    # Accept a list of batch IDs from the payload e.g. [25, 26]
    batch = serializers.PrimaryKeyRelatedField(
        queryset=NewBatch.objects.all(), 
        many=True, 
        write_only=True
    )

    class Meta:
        model = TutorPayment
        fields = [
            'id',
            'tutor',
            'course',
            'batch',             # Expects array of IDs
            'course_fee',
            'payment_type',
            'tutor_payment',
            'payment_status',
            'payment_date',
            'notes',
        ]

    def create(self, validated_data):
        batches = validated_data.pop('batch', [])
        
        # If no batch list is provided, raise validation error
        if not batches:
            raise serializers.ValidationError({"batch": "At least one batch must be selected."})

        payments = []
        # Create a payment record for each selected batch
        for batch in batches:
            payment = TutorPayment.objects.create(batch=batch, **validated_data)
            payments.append(payment)

        # Return the first instance or a representative instance for response serialization
        return payments[0] if len(payments) == 1 else payments
class CourseOptionSerializer(serializers.ModelSerializer):
    # Maps 'fee' to 'course_fee' in JSON
    course_fee = serializers.DecimalField(source='fee', max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Course
        fields = ['course_id', 'course_name', 'course_fee', 'status', 'is_archived']


class BatchOptionSerializer(serializers.ModelSerializer):
    # Maps 'batch_id' to 'id' for frontend compatibility
    id = serializers.IntegerField(source='batch_id', read_only=True)

    class Meta:
        model = NewBatch
        fields = ['id', 'batch_id', 'title', 'status', 'is_archived']

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

    student_id = serializers.IntegerField(
        required=False,
        allow_null=True
    )

    registration_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True
    )

    course_id = serializers.IntegerField(
        required=False,
        allow_null=True
    )

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
            "student_id",
            "registration_id",
            "course",
            "course_id",
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
        return InvoiceService.get_invoice_url(obj, request=self.context.get("request"))

    def get_screenshot_url(self, obj):
        request = self.context.get("request")
        if obj.screenshot:
            return request.build_absolute_uri(
                obj.screenshot.url
            )
        return None

    def to_internal_value(self, data):
        if hasattr(data, "dict"):
            data = data.dict()
        elif hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        # 1. Resolve Student
        student_val = data.get("student")
        if student_val in [None, "", "null", "undefined"]:
            student_val = data.get("student_id") or data.get("registration_id")

        if student_val not in [None, "", "null", "undefined"]:
            student_obj = None
            if isinstance(student_val, int) or (isinstance(student_val, str) and str(student_val).strip().isdigit()):
                student_obj = Student.objects.filter(student_id=int(student_val), is_archived=False).first()
            if not student_obj and isinstance(student_val, str):
                student_obj = Student.objects.filter(registration_id=student_val.strip(), is_archived=False).first()
            if student_obj:
                data["student"] = student_obj.student_id

        # 2. Resolve Course
        course_val = data.get("course")
        if course_val in [None, "", "null", "undefined"]:
            course_val = data.get("course_id")

        if course_val not in [None, "", "null", "undefined"]:
            course_obj = None
            if isinstance(course_val, int) or (isinstance(course_val, str) and str(course_val).strip().isdigit()):
                course_obj = Course.objects.filter(course_id=int(course_val), is_archived=False).first()
            if course_obj:
                data["course"] = course_obj.course_id
        elif data.get("student"):
            # Auto-resolve course from student enrollments if not specified
            student_pk = data.get("student")
            sc = StudentCourse.objects.filter(student_id=student_pk, course__is_archived=False).select_related("course").first()
            if sc and sc.course:
                data["course"] = sc.course.course_id
            else:
                nb = NewBatch.objects.filter(students__student_id=student_pk, course__is_archived=False, is_archived=False).select_related("course").first()
                if nb and nb.course:
                    data["course"] = nb.course.course_id

        return super().to_internal_value(data)

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
            course_fee = float(getattr(course, "fee", 0) or 0)

            # Check if a specific transaction discount is provided, otherwise use the student's global discount
            tx_discount = data.get("discount")
            discount = float(tx_discount) if tx_discount is not None else float(getattr(student, "discount", 0) or 0)

            total_after_discount = max(course_fee - discount, 0.0)

            # Fetch all valid transactions for THIS student and THIS specific course
            existing_paid = PaymentTransaction.objects.filter(
                student=student,
                course=course,
                is_archived=False,
                payment_status__in=["success", "done", "paid", "pending", "complete", "advanced", "captured"]
            ).aggregate(total=Sum('amount'))['total'] or 0

            existing_paid = float(existing_paid)
            incoming_amount = float(amount)

            # 2. Block if it exceeds the remaining balance
            if (existing_paid + incoming_amount) > total_after_discount:
                allowed = max(0.0, total_after_discount - existing_paid)
                raise serializers.ValidationError({
                    "amount": f"Payment exceeds the total course fee after discount. "
                              f"Final fee: ₹{total_after_discount}, Already paid: ₹{existing_paid}. "
                              f"Maximum allowed payment is ₹{allowed}."
                })

        return data

    

    def create(self, validated_data):
        employer_id = validated_data.pop("employer_id", None)
        webinar_registration_id = validated_data.pop("webinar_registration_id", None)
        billing_type = validated_data.pop("billing_type", "student")
        note_text = validated_data.pop("note", None)
        emi_installment_id = validated_data.pop("emi_installment_id", None)
        date_value = validated_data.pop("date", None)
        validated_data.pop("student_id", None)
        validated_data.pop("registration_id", None)
        validated_data.pop("course_id", None)

        employer = None
        webinar_registration = None

        # ====================================
        # COMPANY BILLING
        # ====================================
        if billing_type == "company":
            employer = Employer.objects.filter(company_id=employer_id).first()
            if not employer:
                raise serializers.ValidationError({"employer_id": "Valid employer required"})

        # ====================================
        # WEBINAR BILLING
        # ====================================
        if billing_type == "webinar":
            webinar_registration = WebinarRegistration.objects.filter(id=webinar_registration_id).first()
            if not webinar_registration:
                raise serializers.ValidationError({"webinar_registration_id": "Valid webinar registration required"})

        # ====================================
        # TRANSACTION ID
        # ====================================
        payment_mode = validated_data.get("payment_mode")
        if payment_mode in ["OFFLINE", "CHEQUE"]:
            validated_data["transaction_id"] = f"TXN{uuid.uuid4().hex[:8].upper()}"
        else:
            transaction_id = validated_data.get("transaction_id")
            if not transaction_id:
                raise serializers.ValidationError({"transaction_id": "Transaction ID is required for this payment mode."})
            validated_data["transaction_id"] = transaction_id

        # ====================================
        # DATE
        # ====================================
        if date_value:
            metadata = validated_data.get("metadata") or {}
            metadata["payment_date"] = str(date_value)
            validated_data["metadata"] = metadata

        # ====================================
        # CREATE TRANSACTION ATOMICALLY
        # ====================================
        with db_transaction.atomic():
            transaction = PaymentTransaction.objects.create(
                employer=employer,
                webinar_registration=webinar_registration,
                billing_type=billing_type,
                **validated_data
            )

            # NOTES
            if note_text:
                mixin = NotesMixin()
                mixin.save_notes(
                    transaction,
                    note_text,
                    request=self.context.get("request")
                )

            # EMI
            if emi_installment_id:
                installment = (
                    PaymentEMIInstallment.objects
                    .select_related("emi_plan")
                    .get(pk=emi_installment_id)
                )
                installment.paid = True
                installment.paid_amount = transaction.amount
                installment.payment = transaction
                installment.paid_at = timezone.now()
                installment.save()

        # AUTO GENERATE INVOICE IF NOT ALREADY GENERATED
        if (
            transaction.payment_status
            and transaction.payment_status.lower() in ["success", "done", "paid"]
            and not transaction.invoice
        ):
            try:
                InvoiceService.generate_invoice(transaction.id)
            except Exception as inv_err:
                logger.error(f"Auto invoice generation failed for transaction {transaction.id}: {inv_err}")

        return transaction
 

class PaymentTransactionUpdateSerializer(serializers.ModelSerializer):
    total_course_fee = serializers.SerializerMethodField()
    course_id = serializers.IntegerField(required=False, allow_null=True)
 
    class Meta:
        model = PaymentTransaction
        fields = [
            "payment_mode",
            "course",
            "course_id",
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

    def to_internal_value(self, data):
        if hasattr(data, "dict"):
            data = data.dict()
        elif hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)
        course_val = data.get("course")
        if course_val in [None, "", "null", "undefined"]:
            course_val = data.get("course_id")
        if course_val not in [None, "", "null", "undefined"]:
            if isinstance(course_val, int) or (isinstance(course_val, str) and str(course_val).strip().isdigit()):
                course_obj = Course.objects.filter(course_id=int(course_val), is_archived=False).first()
                if course_obj:
                    data["course"] = course_obj.course_id
        return super().to_internal_value(data)

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


class StudentPaymentSummarySerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    registration_id = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    aggregated_course_fee = serializers.SerializerMethodField()
    aggregated_paid_amount = serializers.SerializerMethodField()
    aggregated_due_amount = serializers.SerializerMethodField()
    courses = serializers.SerializerMethodField()
    payment_history = serializers.SerializerMethodField()  # Full campaign + batch payment history

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
            "payment_history",
        ]

    def _get_course_calculations(self, obj):
        """
        Calculates payment data across ALL transactions (Campaigns + Batches)
        and caches it on the student instance to prevent duplicate DB loops.
        """
        if hasattr(obj, "_cached_payment_data"):
            return obj._cached_payment_data

        request = self.context.get("request")
        all_txs = [tx for tx in obj.transactions.all() if not tx.is_archived]

        # -------------------------------------------------------------
        # 1. Group transactions by Course (keyed by integer course_id)
        # -------------------------------------------------------------
        course_map = {}

        # Add courses from batches, student_courses, & batchcoursetrainer
        for batch in obj.new_batches.all():
            if batch.course and batch.course.course_id not in course_map:
                course_map[batch.course.course_id] = {
                    "course": batch.course,
                    "transactions": []
                }

        if hasattr(obj, "student_courses"):
            for sc in obj.student_courses.all():
                if sc.course and sc.course.course_id not in course_map:
                    course_map[sc.course.course_id] = {
                        "course": sc.course,
                        "transactions": []
                    }

        if hasattr(obj, "batchcoursetrainer_set"):
            for bct in obj.batchcoursetrainer_set.all():
                if bct.course and bct.course.course_id not in course_map:
                    course_map[bct.course.course_id] = {
                        "course": bct.course,
                        "transactions": []
                    }

        # Associate transactions to courses
        for tx in all_txs:
            if tx.course:
                if tx.course.course_id not in course_map:
                    course_map[tx.course.course_id] = {
                        "course": tx.course,
                        "transactions": []
                    }
                course_map[tx.course.course_id]["transactions"].append(tx)
            elif course_map:
                # If transaction has no explicit course, associate with student's primary/enrolled course
                first_course_id = next(iter(course_map))
                course_map[first_course_id]["transactions"].append(tx)

        courses_data = []
        total_course_fee = 0.0
        total_paid = 0.0
        total_due = 0.0

        # -------------------------------------------------------------
        # 2. Calculate per-course aggregates
        # -------------------------------------------------------------
        for c_id, c_entry in course_map.items():
            course = c_entry["course"]
            txs = c_entry["transactions"]
            txs_sorted = sorted(txs, key=lambda x: x.created_at, reverse=True)

            paid_amount = sum(
                float(tx.amount or 0)
                for tx in txs_sorted
                if tx.payment_status and str(tx.payment_status).lower() in [
                    "success", "done", "paid", "partial", "advanced", "complete", "captured"
                ]
            )

            course_fee = float(getattr(course, "fee", 0) or 0)
            discount = float(getattr(obj, "discount", 0) or 0)

            total_after_discount = max(course_fee - discount, 0.0)
            due_amount = max(total_after_discount - paid_amount, 0.0)

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
                "transactions": PaymentTransactionDetailSerializer(
                    txs_sorted, many=True, context=self.context
                ).data
            })

        # -------------------------------------------------------------
        # 3. Build complete payment history log (Campaigns + Batches)
        # -------------------------------------------------------------
        payment_history = []
        for tx in sorted(all_txs, key=lambda x: x.created_at, reverse=True):
            # Auto-repair/generate invoice PDF if missing on completed payments
            if not tx.invoice and str(tx.payment_status).lower() in ["success", "done", "paid", "complete"]:
                try:
                    tx = InvoiceService.generate_invoice(tx.id)
                except Exception as e:
                    logger.error(f"[Serializer Log] Missing invoice generation failed for tx {tx.id}: {str(e)}")

            invoice_url = InvoiceService.get_invoice_url(tx, request=request)

            payment_history.append({
                "transaction_id": tx.transaction_id,
                "course_id": tx.course.course_id if tx.course else None,
                "course_name": tx.course.course_name if tx.course else (tx.description or "Campaign Payment"),
                "amount": float(tx.amount or 0),
                "discount": float(getattr(tx, "discount", 0) or 0),
                "payment_status": tx.payment_status,
                "payment_mode": tx.payment_mode or (tx.metadata.get("mode") if tx.metadata else "Cash"),
                "currency": tx.currency or "INR",
                "gateway": tx.gateway.gatway_name if getattr(tx, "gateway", None) else None,
                "invoice_no": tx.invoice_no,
                "invoice_date": tx.invoice_date,
                "invoice_url": invoice_url,
                "created_at": tx.created_at,
            })

        # Cache calculation on object instance
        obj._cached_payment_data = {
            "courses": courses_data,
            "payment_history": payment_history,
            "aggregated_course_fee": total_course_fee,
            "aggregated_paid_amount": total_paid,
            "aggregated_due_amount": total_due,
        }

        return obj._cached_payment_data


    # -------------------------------------------------------------
    # Serializer Method Fields
    # -------------------------------------------------------------
    def get_student_name(self, obj):
        return f"{obj.first_name} {getattr(obj, 'last_name', '') or ''}".strip()

    def get_registration_id(self, obj):
        return obj.registration_id

    def get_discount(self, obj):
        return float(getattr(obj, "discount", None) or 0)

    def get_courses(self, obj):
        return self._get_course_calculations(obj)["courses"]

    def get_payment_history(self, obj):
        return self._get_course_calculations(obj)["payment_history"]

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


class StudentMinimalSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "student_id",
            "registration_id",
            "first_name",
            "last_name",
            "student_name",
            "email",
            "contact_no",
            "status",
            "is_archived",
        ]

    def get_student_name(self, obj):
        return f"{obj.first_name} {getattr(obj, 'last_name', '') or ''}".strip()



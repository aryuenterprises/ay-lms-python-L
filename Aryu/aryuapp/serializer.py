from .models import *
from rest_framework import serializers
from django.contrib.auth.hashers import make_password   
from .utils import get_protected_file_url
from decimal import Decimal, InvalidOperation
import mimetypes
from django.db.models import OuterRef, Subquery
from datetime import datetime, time
from django.utils import timezone
import calendar
from .mixins import LoggingMixin, NotesMixin
from collections import defaultdict
import json
import os
from aryuapp.mixins import NotesMixin
from django.conf import settings
import jwt
import holidays
import re
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError



class SettingsPicsSerializer(serializers.ModelSerializer):
    general_logo_url = serializers.SerializerMethodField()
    secondary_logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Settings
        fields = ["company_name", "general_logo_url", "secondary_logo_url"]

    def get_general_logo_url(self, obj):
        if obj.general_logo and hasattr(obj.general_logo, "url"):
            return "https://aylms.aryuprojects.com/api" + obj.general_logo.url
        return None

    def get_secondary_logo_url(self, obj):
        if obj.secondary_logo and hasattr(obj.secondary_logo, "url"):
            return "https://aylms.aryuprojects.com/api" + obj.secondary_logo.url
        return None

class SettingsSerializer(serializers.ModelSerializer):
    general_logo_url = serializers.SerializerMethodField()
    secondary_logo_url = serializers.SerializerMethodField()
    signature_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Settings
        fields = '__all__'

    def get_general_logo_url(self, obj):
        if obj.general_logo and hasattr(obj.general_logo, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.general_logo.url
        return None

    def get_secondary_logo_url(self, obj):
        if obj.secondary_logo and hasattr(obj.secondary_logo, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.secondary_logo.url
        return None

    def get_signature_url(self, obj):
        if obj.signature and hasattr(obj.signature, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.signature.url
        return None

    def create(self, validated_data):
        request = self.context.get("request")
        user = request.user
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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

class CMSSerilaizer(serializers.ModelSerializer):
    class Meta:
        model = CMS
        fields = '__all__'

    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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

class ModulePermissionSerializer(serializers.ModelSerializer):

    class Meta:
        model = ModulePermission
        fields = ["module_id", "module", "actions",'is_archived']
    
    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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

class RoleModulePermissionSerializer(serializers.ModelSerializer):
    module = serializers.CharField(source="module_permission.module", read_only=True)
    module_id = serializers.IntegerField(source="module_permission.module_id", read_only=True)

    class Meta:
        model = RoleModulePermission
        fields = ["id", "role", "module", 'module_id', "allowed_actions"]
        
    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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

class RoleSerializer(serializers.ModelSerializer):
    module_permissions = RoleModulePermissionSerializer(many=True, read_only=True)

    class Meta:
        model = Role
        fields = ["role_id", "name",'is_archived', "module_permissions"]
        
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

        # Create and return the Role instance
        return Role.objects.create(**validated_data)

class UserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.all(), source="role", write_only=True
    )
    password = serializers.CharField(write_only=True, required=True, min_length=6)

    class Meta:
        model = User
        fields = [
            "id", "full_name", "username", 'user_type', "email", "ph_no",
            "password", "is_active", "is_staff", "is_archived", 
            "role", "role_id", "created_at", "created_by"
        ]
        read_only_fields = ["id", "created_at", "created_by"]

    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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
                
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)  # Only updates provided fields

        if password:
            instance.set_password(password)

        instance.save()
        return instance

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
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "transaction_id",
            "order_id",
            "amount",
            "currency",
            "payment_status",
            "gateway",
            "description",
            "metadata",
            "created_at"
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

    # ----------------------------- BASIC DETAILS -----------------------------

    def get_student_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_registration_id(self, obj):
        return obj.registration_id

    # ------------------------------- TOTAL COURSE FEE ------------------------

    def get_total_course_fee(self, obj):
        """
        Get course fee directly from the course attached to the latest payment.
        """
        last_tx = (
            obj.transactions
            .filter(payment_status="Success")
            .select_related("course")
            .order_by("-created_at")
            .first()
        )

        if last_tx and last_tx.course:
            return last_tx.course.fee

        return 0
    
    def get_course_name(self, obj):
        """
        Get the course name from the latest successful payment transaction.
        """
        last_tx = (
            obj.transactions
            .filter(payment_status="Success")
            .select_related("course")
            .order_by("-created_at")
            .first()
        )

        if last_tx and last_tx.course:
            return last_tx.course.course_name

        return None

    # ------------------------ PAYMENT SUMMARY (All Transactions) -------------

    def get_paid_amount(self, obj):
        """
        Total paid across all successful payment transactions.
        """
        paid = obj.transactions.filter(payment_status="Success").aggregate(
            total=models.Sum("amount")
        )["total"]

        return paid or 0

    def get_remaining_amount(self, obj):
        return self.get_total_course_fee(obj) - self.get_paid_amount(obj)

    # ------------------------------ EMI HELPERS ------------------------------

    def _all_installments(self, obj):
        """
        Return all installments across all EMI plans.
        """
        emis = obj.emi_plans.all().prefetch_related("installments")
        installments = []
        for emi in emis:
            installments.extend(list(emi.installments.all()))
        return installments

    # ------------------------------ EMI SUMMARY ------------------------------

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

    def get_remaining_emi_count(self, obj):
        return sum(1 for ins in self._all_installments(obj) if not ins.paid)

    def get_next_due_emi_date(self, obj):
        pending = [ins for ins in self._all_installments(obj) if not ins.paid]
        if not pending:
            return None
        return min(pending, key=lambda ins: ins.due_date).due_date

    def get_next_due_emi_amount(self, obj):
        pending = [ins for ins in self._all_installments(obj) if not ins.paid]
        if not pending:
            return None
        return min(pending, key=lambda ins: ins.due_date).amount

    def get_total_pending_emi_amount(self, obj):
        return sum(ins.amount for ins in self._all_installments(obj) if not ins.paid)

    def get_overdue_emi_list(self, obj):
        today = timezone.now().date()
        overdue = [
            {
                "due_date": ins.due_date,
                "amount": ins.amount,
                "days_overdue": (today - ins.due_date).days,
            }
            for ins in self._all_installments(obj)
            if not ins.paid and ins.due_date < today
        ]
        return overdue

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
            "order_id",
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

class School_StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = School_Student
        fields = ['school_name', 'school_class', 'company_id']

class College_StudentSerializer(serializers.ModelSerializer):
    resume_url = serializers.SerializerMethodField(required=False)
    class Meta:
        model = College_Student
        fields = ['college_name', 'degree', 'company_id', 'year_of_study', 'resume', 'resume_url']

    def get_resume_url(self, obj):
        if obj.resume and hasattr(obj.resume, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.resume.url
        return None

class JobSeekerSerializer(serializers.ModelSerializer):
    resume_url = serializers.SerializerMethodField()
    
    class Meta:
        model = JobSeeker
        fields = ['passed_out_year', 'company_id', 'current_qualification', 'preferred_job_role', 'resume', 'resume_url',]
        extra_kwargs = {
            'student': {'required': False},
        }    
    
    def get_resume_url(self, obj):
        if obj.resume and hasattr(obj.resume, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.resume.url
        return None
    
class EmployeeSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Employee
        fields = ['student', 'company_id', 'company_name', 'designation', 'experience', 'skills']
        read_only_fields = ['student']
    
class StudentSimpleSerializer(serializers.ModelSerializer):
    submissions = serializers.SerializerMethodField()
    batch = serializers.SerializerMethodField()
    class Meta:
        model = Student
        fields = ['registration_id', 'profile_pic', 'batch', 'first_name', 'last_name', 'contact_no', 'email', 'submissions']

    def get_batch(self, obj):
        batch = Batch.objects.filter(
            batchcoursetrainer__student=obj,
            is_archived=False
        ).distinct()

        batch_data = list(BatchSerializer(batch, many=True).data)

        # NEW BATCH SUPPORT
        new_batches = NewBatch.objects.filter(
            students=obj,
            is_archived=False,
            status=True
        )

        for nb in new_batches:
            batch_data.append({
                "batch_id": nb.batch_id,
                "batch_name": nb.title,
                "title": nb.title
            })

        # remove duplicates by batch_id
        batch_data = list({b["batch_id"]: b for b in batch_data}.values())

        return batch_data

    def get_submissions(self, obj):
        submissions = Submission.objects.filter(student=obj, is_archived=False)
        return SubmissionSerializer(submissions, many=True).data

class StudentDetailSerializer(serializers.ModelSerializer):
    batch = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = ['registration_id', 'profile_pic', 'batch', 'first_name', 'last_name', 'contact_no', 'email', ]

    def get_course_name(self, obj):
        courses = Course.objects.filter(
            batchcoursetrainer__student=obj,
            is_archived=False,
            status__iexact='Active'
        ).distinct()

        course_names = [course.course_name for course in courses]

        # NEW BATCH SUPPORT
        new_batches = NewBatch.objects.filter(
            students=obj,
            is_archived=False,
            status=True
        ).select_related("course")

        for nb in new_batches:
            if nb.course and nb.course.status == "Active" and not nb.course.is_archived:
                course_names.append(nb.course.course_name)

        # remove duplicates
        return list(set(course_names))

class EmployerSerializer(serializers.ModelSerializer, NotesMixin):
    notes = serializers.SerializerMethodField()

    class Meta:
        model = Employer
        fields = [
            'company_id', 'email', 'company_name', 'contact_person', 'phone',
            'address', 'status', 'is_archived', 'created_by', 'created_at', 'notes'
        ]
        read_only_fields = ['company_id']

    def get_notes(self, obj):

        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model=obj.__class__.__name__.lower()
        ).order_by('-created_at')

        def resolve_name(created_by, created_by_type):
            if not created_by:
                return None

            # created_by is CHAR → cast to INT for FK lookup
            try:
                creator_id = int(created_by)
            except (TypeError, ValueError):
                return str(created_by)

            role = (created_by_type or "").lower()

            # 🔹 super_admin → users.id
            if role == "super_admin":
                user = User.objects.filter(id=creator_id).first()
                return user.full_name if user else str(created_by)

            # 🔹 admin → trainer.trainer_id
            if role == "admin":
                trainer = Trainer.objects.filter(trainer_id=creator_id).first()
                return trainer.full_name if trainer else str(created_by)

            # 🔹 fallback
            return str(created_by)

        return [
            {
                "note_id": note.id,
                "reason": note.reason,
                "created_by": resolve_name(note.created_by, note.created_by_type),
                "status": note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes_qs
        ]

    def validate_email(self, value):
        if not value:
            return None  # allow null/empty email
        value = value.lower().strip()
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")
        return value
    
    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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
    
    def update(self, instance, validated_data):
        # Extract notes from the request data if provided
        notes_text = validated_data.pop("notes", None)
        instance = super().update(instance, validated_data)
        # Save note if exists
        self.save_notes(instance, notes_text)
        return instance

class SubAdminSerializer(serializers.ModelSerializer, NotesMixin):
    password = serializers.CharField(write_only=True)  # hide in GET responses
    company_name = serializers.CharField(source="company.company_name", read_only=True)
    notes = serializers.SerializerMethodField()

    class Meta:
        model = SubAdmin
        fields = ['employer_id', 'role', 'full_name', 'username', 'email', 
                  'company', 'company_name', 'phone_no',  'password', 'designation', 'status', 'is_archived', 'created_by', 'created_at', 'notes']

    def get_notes(self, obj):

        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model=obj.__class__.__name__.lower()
        ).order_by('-created_at')

        def resolve_name(created_by, created_by_type):
            if not created_by:
                return None

            # created_by is CHAR → cast to INT for FK lookup
            try:
                creator_id = int(created_by)
            except (TypeError, ValueError):
                return str(created_by)

            role = (created_by_type or "").lower()
            print("Role:", role)
            print("Creator ID:", creator_id)

            # super_admin → users.id
            if role == "super_admin":
                user = User.objects.filter(id=creator_id).first()
                return user.full_name if user else str(created_by)

            # admin → trainer.trainer_id
            if role == "admin":

                trainer = Trainer.objects.filter(trainer_id=creator_id).first()
                print("Trainer:", trainer)
                return trainer.full_name if trainer else str(created_by)

            # fallback
            return str(created_by)

        return [
            {
                "note_id": note.id,
                "reason": note.reason,
                "created_by": resolve_name(note.created_by, note.created_by_type),
                "status": note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes_qs
        ]

    def create(self, validated_data):
        password = validated_data.pop('password')  # remove plain password
    
    # Add created_by before creating instance
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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

        # Create instance
        employer = SubAdmin(**validated_data)
        employer.password = make_password(password)  # hash password
        employer.save()
        return employer

    def validate_username(self, value):
        value = value
        instance = getattr(self, 'instance', None)
        student_qs = Student.objects.filter(username__iexact=value, is_archived=False)
        trainer_qs = Trainer.objects.filter(username__iexact=value, is_archived=False)
        employer_qs = SubAdmin.objects.filter(username__iexact=value, is_archived=False)

        if isinstance(instance, Student):
            student_qs = student_qs.exclude(registration_id=instance.registration_id)
        if isinstance(instance, Trainer):
            trainer_qs = trainer_qs.exclude(employee_id=instance.employee_id)
        if isinstance(instance, SubAdmin):
            employer_qs = employer_qs.exclude(employer_id=instance.employer_id)

        if student_qs.exists() or trainer_qs.exists() or employer_qs.exists():
            raise serializers.ValidationError("Username already exists")

        return value

    def validate_contact_no(self, value):
        value = value.strip()
        instance = getattr(self, 'instance', None)

        # Check students (excluding archived ones)
        student_qs = Student.objects.filter(contact_no__iexact=value, is_archived=False)
        # Check trainers (excluding archived ones)
        trainer_qs = Trainer.objects.filter(contact_no__iexact=value, is_archived=False)
        #check employer (exclude archived ones)
        employer_qs = SubAdmin.objects.filter(phone__iexact=value, is_archived=False)

        # Exclude current instance from check
        if instance:
            student_qs = student_qs.exclude(pk=instance.pk)
            trainer_qs = trainer_qs.exclude(pk=getattr(instance, 'employee_id', None))
            employer_qs = employer_qs.exclude(pk=getattr(instance, 'employer_id', None))

        if student_qs.exists() or trainer_qs.exists() or employer_qs.exists():
            raise serializers.ValidationError("Phone number already exists.")

        return value

    def validate_email(self, value):
        value = value.lower().strip()
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")

        allowed_domains = [
            'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com',
            'rediffmail.com', 'icloud.com', 'aryutechnologies.com', 'aryuacademy.com','farida.co.in',
        ]
        domain = value.split('@')[-1]
        if domain not in allowed_domains:
            raise serializers.ValidationError("Please use an accepted email domain.")

        instance = getattr(self, 'instance', None)
        qs = Student.objects.filter(email__iexact=value, is_archived=False)
        tqs = Trainer.objects.filter(email__iexact=value, is_archived=False)
        eqs = SubAdmin.objects.filter(email__iexact=value, is_archived=False)
        if instance:
            qs = qs.exclude(pk=instance.pk)
            tqs = tqs.exclude(pk=getattr(instance, 'employee_id', None))
            eqs = eqs.exclude(pk=getattr(instance, 'employer_id', None))

        if qs.exists() or tqs.exists() or eqs.exists():
            raise serializers.ValidationError("Email already exists.")

        return value
    
    def validate_password(self, value):
        # Minimum length
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")

        # At least one uppercase
        if not re.search(r'[A-Z]', value):
            raise serializers.ValidationError("Password must contain at least one uppercase letter.")

        # At least one lowercase
        if not re.search(r'[a-z]', value):
            raise serializers.ValidationError("Password must contain at least one lowercase letter.")

        # At least one digit
        if not re.search(r'\d', value):
            raise serializers.ValidationError("Password must contain at least one number.")

        # At least one special character
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', value):
            raise serializers.ValidationError("Password must contain at least one special character.")

        return value   
    
    def validate(self, attrs):
        # Get employer from attrs (update) or instance (existing object)
        employer = attrs.get("company") or getattr(self.instance, "company", None)

        # Get requested SubAdmin status (True/False)
        subadmin_status = attrs.get("status")

        # VALIDATION: Prevent activation if employer is inactive
        if subadmin_status is True and employer and employer.status is False:
            raise serializers.ValidationError({
                "status": "Cannot activate this SubAdmin because the Employer is deactivated."
            })

        return attrs

    def update(self, instance, validated_data):
        # Extract notes from the request data if provided
        notes_text = validated_data.pop("notes", None)
        instance = super().update(instance, validated_data)
        # Save note if exists
        self.save_notes(instance, notes_text)
        return instance
    
class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)

class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    new_password = serializers.CharField(write_only=True, min_length=6)

class CourseCategorySerializer(serializers.ModelSerializer):
    notes = serializers.SerializerMethodField()
    class Meta:
        model = CourseCategory
        fields = '__all__'
    
    def get_notes(self, obj):
    
        from aryuapp.models import Note

        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model='coursecategory'
        ).order_by('-created_at')

        # Convert "true"/"false" to boolean
        def convert_status(value):
            if isinstance(value, str):
                if value.lower() == "true":
                    return True
                if value.lower() == "false":
                    return False
            return value

        return [
            {
                "note_id": note.id,
                "reason": note.reason,
                "created_by": note.created_by,
                "status": note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes_qs
        ]

    def validate_category_name(self, value):
        request = self.context.get('request')
        trainer_id = getattr(request.user, 'trainer_id', None)  # or trainer_id if admin model uses trainer_id

        # Alphabet and space only
        if not re.match(r'^[A-Za-z ]+$', value):
            raise serializers.ValidationError("Category name can only contain alphabets and spaces.")

        # Check uniqueness for the same admin
        qs = CourseCategory.objects.filter(
            category_name__iexact=value,
            created_by=trainer_id,
            is_archived=False
        )
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError("You already have a category with this name.")

        return value
    
    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)

        # Check if category was deactivated
        if 'status' in validated_data and not validated_data['status']:
            instance.cascade_category_deactivation()

        return instance
    
class CourseSerializer(serializers.ModelSerializer):
    course_category = serializers.SlugRelatedField(
        slug_field='category_name',
        queryset=CourseCategory.objects.filter(is_archived=False),
    )
    category_details = CourseCategorySerializer(source='course_category', read_only=True)
    syllabus_info = serializers.SerializerMethodField()
    course_pic = serializers.ImageField(required=False, allow_null=True)
    syllabus = serializers.SerializerMethodField()  # Change here!
    course_pic_url = serializers.SerializerMethodField()
    batches = serializers.SerializerMethodField()
    topic = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()
    assignment = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            'course_id', 'course_name', 'course_category', 'category_details',
            'course_pic', 'course_pic_url', 'notes', 'currency_type', 'fee_type',
            'topic', 'syllabus', 'syllabus_info', 'assignment', 'batches',
            'duration', 'mode_of_delivery', 'fee', 'status', 'is_archived', 'is_featured', 'created_by', 'created_at'
        ]
        
    def get_notes(self, obj):
    
        from aryuapp.models import Note

        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model='course'
        ).order_by('-created_at')

        # Convert "true"/"false" to boolean
        def convert_status(value):
            if isinstance(value, str):
                if value.lower() == "true":
                    return True
                if value.lower() == "false":
                    return False
            return value

        return [
            {
                "note_id": note.id,
                "reason": note.reason,
                "created_by": note.created_by,
                "status": note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes_qs
        ]

    def get_batches(self, obj):
        batches_qs = obj.new_batches.filter(is_archived=False, status=True)
        return [
            {
                "batch_id": b.batch_id,
                "title": b.title,
                "start_date": b.start_date,
                "end_date": b.end_date,
                "start_time": b.start_time,
                "end_time": b.end_time,
                "trainer_id": b.trainer.trainer_id if b.trainer else None,
                "trainer_name": b.trainer.full_name if b.trainer else None,
            } for b in batches_qs
        ]
    
    def get_course_pic_url(self, obj):
        if obj.course_pic and hasattr(obj.course_pic, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.course_pic.url
        return None
    
    def get_syllabus(self, obj):
        if not obj.syllabus:
            return None

        try:
            if os.path.exists(obj.syllabus.path):
                return 'https://aylms.aryuprojects.com/api' + obj.syllabus.url
        except Exception:
            pass

        return None
    
    def get_assignment(self, obj):
        assignments = Assignment.objects.filter(course=obj, is_archived=False)
        return AssignmentSimpleSerializer(assignments, many=True).data if assignments else []

    def get_syllabus_info(self, obj):
        if not obj.syllabus:
            return []

        try:
            file_path = obj.syllabus.path  # absolute filesystem path

            # File missing on disk → return graceful response
            if not os.path.exists(file_path):
                return [{
                    "id": obj.pk,
                    "date": obj.updated_at.date().isoformat() if hasattr(obj, "updated_at") else None,
                    "file": {
                        "name": os.path.basename(obj.syllabus.name),
                        "type": None,
                        "size": None,
                        "url": None,
                        "missing": True
                    }
                }]

            filename = os.path.basename(obj.syllabus.name)
            mimetype, _ = mimetypes.guess_type(filename)

            return [{
                "id": obj.pk,
                "date": obj.updated_at.date().isoformat() if hasattr(obj, "updated_at") else None,
                "file": {
                    "name": filename,
                    "type": mimetype or "application/octet-stream",
                    "size": os.path.getsize(file_path),
                    "url": 'https://aylms.aryuprojects.com/api' + obj.syllabus.url,
                    "missing": False
                }
            }]

        except Exception:
            # Absolute safety net — API must never crash
            return []

    def validate_fee(self, value):
        if value is None:
            return value

        # Ensure value is int, float, or Decimal (reject strings/characters)
        if not isinstance(value, (int, float, Decimal)):
            raise serializers.ValidationError("Fee must be a number.")

        # Convert safely to Decimal
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise serializers.ValidationError("Fee must be a valid numeric value.")

        # Check maximum
        if value > Decimal('100000'):
            raise serializers.ValidationError("Fee cannot be more than 100,000.")

        # Check non-negative
        if value < 0:
            raise serializers.ValidationError("Fee cannot be negative.")

        return value
    
    def get_topic(self, obj):
        student = self.context.get("student")  # Could be None
        topics = Topic.objects.filter(course=obj, is_archived=False).order_by('created_date')

        # Prefetch StudentTopicStatus only if student is provided
        if student:
            sts_qs = StudentTopicStatus.objects.filter(student=student, topic__in=topics)
            sts_map = {sts.topic_id: sts for sts in sts_qs}
        else:
            sts_map = {}

        topic_data = []

        for topic in topics:
            topic_serialized = TopicSerializer(topic, context=self.context).data

            if student and topic.topic_id in sts_map:
                sts = sts_map[topic.topic_id]
                topic_serialized['student_comment'] = sts.notes
                topic_serialized['student_rating'] = sts.ratings
            else:
                topic_serialized['student_comment'] = None
                topic_serialized['student_rating'] = None

            topic_data.append(topic_serialized)

        return topic_data
    
    def validate_duration(self, value):
        if value:
            try:
                months = int(value)
                if months < 1 or months > 12:
                    raise serializers.ValidationError("Duration must be between 1 and 12 months.")
            except ValueError:
                raise serializers.ValidationError("Duration must be a number (months).")
        return value
    def validate(self, data):
        course_name = data.get('course_name')
        request = self.context.get('request')
        course_category = data.get('course_category')
        trainer_id = getattr(request.user, 'trainer_id', None)

        # Check duplicate course under same category for same creator
        if course_name and course_category:
            qs = Course.objects.filter(
                course_name__iexact=course_name,
                course_category=course_category,
                created_by=trainer_id,
                is_archived=False
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise serializers.ValidationError({
                    'course_name': 'This course already exists under the selected category.'
                })

        # Prevent activating course if category is inactive
        course_status = data.get('status')
        if self.instance:
            # If updating, use current value if not provided
            course_status = course_status if course_status is not None else self.instance.status
            course_category = course_category or self.instance.course_category

        if course_status is True and course_category and not course_category.status:
            raise serializers.ValidationError({
                'status': 'Cannot activate this course because the selected category is inactive.'
            })

        return data

    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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
    
    def update(self, instance, validated_data):
        # Capture status before update
        old_status = instance.status

        # Update the course instance
        instance = super().update(instance, validated_data)

        # Cascade deactivation if course is being set to Inactive
        new_status = validated_data.get('status', old_status)
        if new_status == "Inactive" and old_status != "Inactive":
            instance.deactivate_course(instance)

        return instance

class CourseSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ['course_id', 'course_name', 'course_pic', 'course_category']

class StudentSerializer(serializers.ModelSerializer):
    course_ids = serializers.CharField(write_only=True, required=False)
    course_detail = serializers.SerializerMethodField(read_only=True)
    category_id = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()
    school_student = School_StudentSerializer(required=False)
    college_student = College_StudentSerializer(required=False)
    jobseeker = JobSeekerSerializer(required=False)
    employee = EmployeeSerializer(required=False)

    class Meta:
        model = Student
        fields = [
            'student_id', 'profile_pic', 'role', 'first_name', 'last_name', 'username', 'password', 'registration_id', 'dob',
            'email', 'contact_no', 'current_address', 'permanent_address', 'city', 'state', 'country',
            'parent_guardian_name', 'parent_guardian_phone', 'internship','parent_guardian_occupation',
            'reference_number', 'student_type', 'status', 'notes',
            'school_student', 'college_student', 'jobseeker', 'employee',
            'course_detail','course_ids', 'category_id', 'category_name', 'joining_date', 'created_by', 'created_at',
        ]
        read_only_fields = ['registration_id']

    def get_school_student(self, obj):
        if hasattr(obj, 'school_student'):
            return School_StudentSerializer(obj.school_student).data
        return None
    
    def get_college_student(self, obj):
        if hasattr(obj, 'college_student'):
            return College_StudentSerializer(obj.college_student).data
        return None
    
    def get_course_detail(self, obj):
        # OLD SYSTEM COURSES
        courses = Course.objects.filter(
            batchcoursetrainer__student=obj,
                is_archived=False,
                status__iexact='Active'
            ).distinct()

        courses_list = list(courses)

        # NEW SYSTEM COURSES
        new_batches = NewBatch.objects.filter(
            students=obj,
            is_archived=False,
            status=True
        ).select_related("course")

        for nb in new_batches:
            if nb.course and nb.course.status == "Active" and not nb.course.is_archived:
                courses_list.append(nb.course)

        # Remove duplicate course objects
        unique_courses = {c.course_id: c for c in courses_list}.values()

        return CourseSerializer(unique_courses, many=True).data

    def validate_username(self, value):
        value = value
        instance = getattr(self, 'instance', None)
        student_qs = Student.objects.filter(username__iexact=value, is_archived=False)
        trainer_qs = Trainer.objects.filter(username__iexact=value, is_archived=False)

        if instance:
            student_qs = student_qs.exclude(student_id=instance.student_id)
            trainer_qs = trainer_qs.exclude(employee_id=instance.employee_id)

        if student_qs.exists() or trainer_qs.exists():
            raise serializers.ValidationError("Username already exists")

        return value

    def validate_contact_no(self, value):
        value = value.strip()
        instance = getattr(self, 'instance', None)

        # Check students (excluding archived ones)
        student_qs = Student.objects.filter(contact_no__iexact=value, is_archived=False)
        # Check trainers (excluding archived ones)
        trainer_qs = Trainer.objects.filter(contact_no__iexact=value, is_archived=False)

        # Exclude current instance from check
        if instance:
            student_qs = student_qs.exclude(pk=instance.pk)
            trainer_qs = trainer_qs.exclude(pk=getattr(instance, 'employee_id', None))

        if student_qs.exists() or trainer_qs.exists():
            raise serializers.ValidationError("Phone number already exists.")

        return value

    def validate_email(self, value):
        value = value.lower().strip()
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")

        allowed_domains = [
            'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com',
            'rediffmail.com', 'icloud.com', 'aryutechnologies.com','farida.co.in',
        ]
        domain = value.split('@')[-1]
        if domain not in allowed_domains:
            raise serializers.ValidationError("Please use an accepted email domain.")

        instance = getattr(self, 'instance', None)
        qs = Student.objects.filter(email__iexact=value, is_archived=False)
        if instance:
            qs = qs.exclude(pk=instance.pk)

        if qs.exists():
            raise serializers.ValidationError("Email already exists.")

        return value
    
    def validate_password(self, value):
        # Minimum length
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")

        # At least one uppercase
        if not re.search(r'[A-Z]', value):
            raise serializers.ValidationError("Password must contain at least one uppercase letter.")

        # At least one lowercase
        if not re.search(r'[a-z]', value):
            raise serializers.ValidationError("Password must contain at least one lowercase letter.")

        # At least one digit
        if not re.search(r'\d', value):
            raise serializers.ValidationError("Password must contain at least one number.")

        # At least one special character
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', value):
            raise serializers.ValidationError("Password must contain at least one special character.")

        return value

    def get_course(self, obj):
        courses = Course.objects.filter(
            batchcoursetrainer__student=obj,
            is_archived=False,
            status__iexact='Active'
        ).distinct()

        courses_list = list(courses)

        new_batches = NewBatch.objects.filter(
            students=obj,
            is_archived=False,
            status=True
        ).select_related("course")

        for nb in new_batches:
            if nb.course and nb.course.status == "Active" and not nb.course.is_archived:
                courses_list.append(nb.course)

        unique_courses = {c.course_id: c for c in courses_list}.values()

        return [{"course_id": course.course_id, "course_name": course.course_name} for course in unique_courses]

    def get_category_id(self, obj):
        categories = CourseCategory.objects.filter(
            courses__batchcoursetrainer__student=obj
        ).values_list('category_id', flat=True).distinct()

        category_ids = set(categories)

        new_batches = NewBatch.objects.filter(
            students=obj,
            is_archived=False,
            status=True
        ).select_related("course__course_category")

        for nb in new_batches:
            if nb.course and nb.course.course_category:
                category_ids.add(nb.course.course_category.category_id)

        return list(category_ids)


    def get_category_name(self, obj):
        categories = CourseCategory.objects.filter(
            courses__batchcoursetrainer__student=obj
        ).values_list('category_name', flat=True).distinct()

        category_names = set(categories)

        new_batches = NewBatch.objects.filter(
            students=obj,
            is_archived=False,
            status=True
        ).select_related("course__course_category")

        for nb in new_batches:
            if nb.course and nb.course.course_category:
                category_names.add(nb.course.course_category.category_name)

        return list(category_names)
    
    def raise_error(self, field, message):
        """Helper to raise user-friendly validation errors."""
        raise serializers.ValidationError({
            field: f"{field.replace('_', ' ').capitalize()} {message}"
        })

    def create(self, validated_data):
        plain_password = validated_data.get('password')
        password = validated_data.pop('password')
        validated_data['password'] = make_password(password)
        course_ids = validated_data.pop("course_ids", None)
        school_data = validated_data.pop('school_student', None)
        college_data = validated_data.pop('college_student', None)
        jobseeker_data = validated_data.pop('jobseeker', None)
        employee_data = validated_data.pop('employee', None)
        student_type = validated_data.get('student_type')
        
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

        student = Student.objects.create(**validated_data)
        student._plain_password = plain_password

        # Handle nested student types with company_id
        if student_type == 'school_student' and school_data:
            company_id = school_data.pop('company_id', None)
            School_Student.objects.create(student=student, company_id=company_id, **school_data)
        elif student_type == 'college_student' and college_data:
            company_id = college_data.pop('company_id', None)
            College_Student.objects.create(student=student, company_id=company_id, **college_data)
        elif student_type == 'jobseeker' and jobseeker_data:
            company_id = jobseeker_data.pop('company_id', None)
            JobSeeker.objects.create(student=student, company_id=company_id, **jobseeker_data)
        elif student_type == 'employee' and employee_data:
            company_id = employee_data.pop('company_id', None)
            Employee.objects.create(student=student, company_id=company_id, **employee_data)

        return student

    def validate(self, data):
        stype = data.get('student_type')

        if not stype or stype not in ["school_student", "college_student", "jobseeker", "employee"]:
            raise serializers.ValidationError({
                "student_type": "Invalid or missing student type."
            })

        if stype == "school_student":
            school = data.get("school_student") or {}
            if not school.get("school_name"):
                raise serializers.ValidationError({"school_name": "School name is required."})
            if not school.get("school_class"):
                raise serializers.ValidationError({"school_class": "School class is required."})

        elif stype == "college_student":
            college = data.get("college_student") or {}
            if not college.get("college_name"):
                raise serializers.ValidationError({"college_name": "College name is required."})
            if not college.get("degree"):
                raise serializers.ValidationError({"degree": "Degree is required."})
            if not college.get("year_of_study"):
                raise serializers.ValidationError({"year_of_study": "Year of study is required."})

        elif stype == "jobseeker":
            job = data.get("jobseeker") or {}
            if not job.get("passed_out_year"):
                raise serializers.ValidationError({"passed_out_year": "Passed out year is required."})
            if not job.get("current_qualification"):
                raise serializers.ValidationError({"current_qualification": "Current qualification is required."})
            if not job.get("preferred_job_role"):
                raise serializers.ValidationError({"preferred_job_role": "Preferred job role is required."})
            # for field in ["passed_out_year", "current_qualification", "preferred_job_role", "resume"]:
            #     if not job.get(field):
            #         raise serializers.ValidationError({f"{field}": f"{field.replace('_', ' ').title()} is required."})
        
        elif stype == 'employee':
            employee = data.get('employee') or {}
            if not employee.get('company_name'):
                raise serializers.ValidationError({'company_name': 'Company Name is required.'})
            if not employee.get('designation'):
                raise serializers.ValidationError({'designation': 'Designation is required.'})
            if not employee.get('experience'):
                raise serializers.ValidationError({'experience': 'Experience is required.'})
            if not employee.get('skills'):
                raise serializers.ValidationError({'skills': 'Skills are required.'})

        return data

class AttendanceSerializer(serializers.ModelSerializer):
    ip_address = serializers.CharField(write_only=True, required=False)

    # -------- OLD BATCH FIELDS (READ-ONLY) ----------
    batch = serializers.PrimaryKeyRelatedField(read_only=True)
    batch_id = serializers.IntegerField(source='batch.batch_id', read_only=True)
    batch_name = serializers.CharField(source='batch.batch_name', read_only=True)
    title = serializers.CharField(source='batch.title', read_only=True)

    # -------- NEW BATCH FIELDS (WRITE + READ) --------
    new_batch = serializers.PrimaryKeyRelatedField(queryset=NewBatch.objects.all(), required=False)
    new_batch_title = serializers.CharField(source='new_batch.title', read_only=True)

    course_name = serializers.CharField(source='course.course_name', read_only=True)
    student_name = serializers.SerializerMethodField()
    course_id = serializers.IntegerField(source='course.course_id', read_only=True)

    class Meta:
        model = Attendance
        fields = [
            'id', 'student', 'schedule_id', 'status', 'student_name',
            'course',

            # Old batch fields (read/write old data only)
            'batch', 'batch_id', 'batch_name', 'title',

            # New batch fields (required for new data)
            'new_batch', 'new_batch_title',

            'date', 'ip_address', 'course_name', 'course_id', 'marked_by_admin',
        ]
        read_only_fields = ['date', 'ip_address', 'batch_id', 'batch_name', 'title', 'new_batch_title']

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"

    # Format date to IST
    def to_representation(self, instance):
        data = super().to_representation(instance)
        dt = instance.date
        ist = pytz.timezone("Asia/Kolkata")

        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone=pytz.UTC)

        dt = timezone.localtime(dt, ist)
        data['date'] = dt.strftime('%Y-%m-%d %H:%M:%S')
        return data

    # ---------------- VALIDATION -----------------
    def validate(self, data):
        student = data.get('student')
        old_batch = data.get('batch')
        new_batch = data.get('new_batch')
        course = data.get('course')

        if not student:
            raise serializers.ValidationError("Student is required.")
        if not course:
            raise serializers.ValidationError("Course is required.")

        # ------------- NEW BATCH (PREFERRED FOR NEW DATA) ---------------
        if new_batch:
            # ensure student is present in new batch
            if not new_batch.students.filter(student_id=student.student_id).exists():
                raise serializers.ValidationError("Student is not assigned to this Batch.")
            return data

        raise serializers.ValidationError("Batch must be provided.")

    def create(self, validated_data):
        ip_address = validated_data.pop('ip_address', None)

        if 'date' not in validated_data or validated_data['date'] is None:
            validated_data['date'] = timezone.now()

        instance = Attendance(**validated_data)

        if ip_address:
            instance.ip_address = ip_address

        instance.save()
        return instance

class TopicSerializer(serializers.ModelSerializer):
    create_by = serializers.SlugRelatedField(
        slug_field='employee_id',
        queryset=Trainer.objects.all(),
        allow_null=True,
        required=False
    )
    course = serializers.PrimaryKeyRelatedField(read_only=True)  # make course read-only

    class Meta:
        model = Topic
        fields = ['topic_id','course','title','description','created_date','create_by','is_archived', 'created_at', 'created_by']
        read_only_fields = ['created_date', 'course', 'topic_id']
        
    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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
        
class StudentTopicStatusSerializer(serializers.ModelSerializer):
    topic_title = serializers.CharField(source='topic.title', read_only=True)
    course_id = serializers.IntegerField(source='topic.course.course_id', read_only=True)
    registration_id = serializers.CharField(write_only=True, required=False)
    updated_at = serializers.DateTimeField(read_only=True, format='%Y-%m-%d %H:%M:%S')

    class Meta:
        model = StudentTopicStatus
        fields = [
            'id',
            'student',          # Now writable
            'ratings',
            'registration_id',
            'topic',
            'notes',
            'topic_title',
            'course_id',
            'status',
            'updated_at'
        ]
        read_only_fields = ['updated_at']  # student NOT read-only anymore

class StudentProfileSerializer(serializers.ModelSerializer):
    course_detail = serializers.SerializerMethodField()
    course = serializers.SerializerMethodField()
    profile_pic = serializers.SerializerMethodField()
    school_student = serializers.SerializerMethodField()
    college_student = serializers.SerializerMethodField()
    jobseeker = serializers.SerializerMethodField()
    employee = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    studenttopicstatus= serializers.SerializerMethodField()
    assignment = serializers.SerializerMethodField()
    attendance = serializers.SerializerMethodField()
    batch = serializers.SerializerMethodField()
    joining_date = serializers.SerializerMethodField()
    dob = serializers.DateField(format="%Y-%m-%d")
    course_id = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()
    trainer = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            'student_id','registration_id', 'trainer', 'course_id', 'role', 'batch', 'first_name', 'joining_date', 'last_name', 'username', 'profile_pic', 'dob',
            'contact_no', 'current_address', 'permanent_address', 'city', 'state', 'country',
            'parent_guardian_name', 'parent_guardian_phone', 'parent_guardian_occupation', 'internship', 'reference_number', 
            'email', 'student_type', 'course', 'course_detail', 'joining_date', 'studenttopicstatus',
            'school_student', 'college_student', 'jobseeker', 'employee', 'assignment', 'attendance', 'status', 'created_at', 'created_by', 'notes'
        ]

    def _get_active_new_batches(self, obj):
        return NewBatch.objects.filter(
            students=obj,
            is_archived=False,
            status=True
        ).select_related("course")

    def get_course_id(self, obj):
        batch = self._get_active_new_batches(obj).first()
        return batch.course.course_id if batch and batch.course else None

    def get_studenttopicstatus(self, obj):
        trainer_courses = self.context.get("trainer_courses")

        qs = obj.topic_statuses.all()

        if trainer_courses:
            qs = [s for s in qs if s.topic.course_id in trainer_courses]

        return StudentTopicStatusSerializer(qs, many=True).data
    
    def get_trainer(self, obj):

        # Get all batches this student is enrolled in
        batches = obj.new_batches.filter(is_archived=False, status=True)

        # Get unique trainers from those batches
        trainers = {batch.trainer for batch in batches}

        # Serialize trainer info
        return [
            {
                "name": trainer.full_name,
                "email": trainer.email
            } for trainer in trainers
        ]
    
    def get_notes(self, obj):
        student_ct = ContentType.objects.get_for_model(obj)

        notes_qs = Note.objects.filter(
            content_type=student_ct,
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
    
    def get_batch(self, obj):
        final_batches = []
        seen = set()

        new_batches = obj.new_batches.filter(
            is_archived=False,
            status=True
        ).select_related("course", "trainer")

        for nb in new_batches:
            if nb.batch_id in seen:
                continue
            seen.add(nb.batch_id)

            final_batches.append({
                "batch_id": nb.batch_id,
                "batch_name": nb.title,
                "title": nb.title,
                "course_id": nb.course.course_id,
                "course_name": nb.course.course_name,
                "trainer_id": nb.trainer.employee_id if nb.trainer else None,
                "trainer_name": nb.trainer.full_name if nb.trainer else None,
                "type": "new",
            })

        old_batch_links = obj.batchcoursetrainer_set.select_related(
            "batch", "course", "trainer"
        ).filter(
            batch__is_archived=False,
            batch__status=True,
        )

        for bct in old_batch_links:
            batch = bct.batch

            if not batch or batch.batch_id in seen:
                continue
            seen.add(batch.batch_id)

            final_batches.append({
                "batch_id": batch.batch_id,
                "batch_name": batch.batch_name,
                "title": batch.title,
                "course_id": bct.course.course_id,
                "course_name": bct.course.course_name,
                "trainer_id": bct.trainer.employee_id,
                "trainer_name": bct.trainer.full_name,
                "type": "old",
            })

        return final_batches

    def get_profile_pic(self, obj):
        if obj.profile_pic and hasattr(obj.profile_pic, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.profile_pic.url
        return None

    def get_course(self, obj):
        courses = Course.objects.filter(
            batchcoursetrainer__student=obj,
            is_archived=False,
            status__iexact='Active'
        ).distinct()

        course_list = list(courses)

        new_batches = NewBatch.objects.filter(
            students=obj,
            is_archived=False,
            status=True
        ).select_related("course")

        for nb in new_batches:
            if nb.course and nb.course.status == "Active" and not nb.course.is_archived:
                course_list.append(nb.course)

        unique_courses = {c.course_id: c for c in course_list}.values()

        return [course.course_name for course in unique_courses]

    def get_course_detail(self, obj):
        trainer_courses = self.context.get("trainer_courses")

        qs = Course.objects.filter(
            batchcoursetrainer__student=obj,
            is_archived=False,
            status__iexact='Active'
        ).distinct()

        if trainer_courses:
            qs = qs.filter(course_id__in=trainer_courses)

        course_list = list(qs)

        # NEW BATCH SUPPORT
        new_batches = NewBatch.objects.filter(
            students=obj,
            is_archived=False,
            status=True
        ).prefetch_related("course")

        for nb in new_batches:
            if nb.course and nb.course.status == "Active" and not nb.course.is_archived:
                if not trainer_courses or nb.course.course_id in trainer_courses:
                    course_list.append(nb.course)

        unique_courses = {c.course_id: c for c in course_list}.values()

        return CourseSerializer(unique_courses, many=True).data

    def get_attendance(self, obj):
        trainer_courses = self.context.get("trainer_courses")

        qs = obj.attendance_set.all()

        if trainer_courses:
            qs = [a for a in qs if a.course_id in trainer_courses]

        return AttendanceSerializer(qs, many=True).data

    def get_school_student(self, obj):
        school = getattr(obj, 'school_student', None)
        return School_StudentSerializer(school).data if school else None
    
    def get_college_student(self, obj):
        college = getattr(obj, 'college_student', None)
        return College_StudentSerializer(college).data if college else None

    def get_jobseeker(self, obj):
        jobseeker = getattr(obj, 'jobseeker', None)
        return JobSeekerSerializer(jobseeker).data if jobseeker else None

    def get_joining_date(self, obj):
        if obj.joining_date:
            return obj.joining_date.strftime('%Y-%m-%d')
        return None
    
    def get_employee(self, obj):
        employee = getattr(obj, 'employee', None)
        return EmployeeSerializer(employee).data if employee else None

    def get_email(self, obj):
        return obj.email.lower() if obj.email else None
    
    def get_assignment(self, obj):
        trainer_courses = self.context.get("trainer_courses")

        # ===================== OLD SYSTEM COURSES =====================
        student_courses = Course.objects.filter(
            batchcoursetrainer__student=obj,
            is_archived=False
        ).distinct()

        student_courses_list = list(student_courses)

        # ===================== NEW SYSTEM COURSES =====================
        new_batches = NewBatch.objects.filter(
            students=obj,
            is_archived=False,
            status=True
        ).select_related("course")

        for nb in new_batches:
            if nb.course and not nb.course.is_archived:
                student_courses_list.append(nb.course)

        # Remove duplicates
        student_courses_list = list({c.course_id: c for c in student_courses_list}.values())

        # ===================== ASSIGNMENTS =====================
        latest_submission = Submission.objects.filter(
            assignment=OuterRef("pk"),
            student=obj
        ).order_by("-date").values("date")[:1]

        qs = Assignment.objects.filter(
            course__in=student_courses_list,
            is_archived=False
        ).annotate(
            latest_submitted_at=Subquery(latest_submission)
        )

        if trainer_courses:
            qs = qs.filter(course_id__in=trainer_courses)

        qs = qs.order_by("-latest_submitted_at", "-id")

        return AssignmentSerializer(
            qs, many=True,
            context={'request': self.context.get('request'), 'student': obj}
        ).data

class StudentUpdateSerializer(serializers.ModelSerializer):
    school_student = School_StudentSerializer(required=False)
    college_student = College_StudentSerializer(required=False)
    jobseeker = JobSeekerSerializer(required=False)
    employee = EmployeeSerializer(required=False)
    email = serializers.EmailField(validators=[], required=False)
    profile_pic = serializers.ImageField(required=False)
    username = serializers.CharField(required=False)
    student_type = serializers.CharField(required=False)
    parent_guardian_occupation = serializers.CharField(required=False)
    deactivation_reason = serializers.CharField(required=False, allow_blank=True)

    # Accept JSON array string like '[1, 2, 3]'
    course_ids = serializers.CharField(write_only=True, required=False)

    # For read-only display
    course = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            'first_name', 'last_name', 'email', 'contact_no', 'current_address', 'permanent_address',
            'city', 'state', 'country', 'parent_guardian_name', 'parent_guardian_phone', 'internship',
            'parent_guardian_occupation', 'student_type', 'dob', 'profile_pic', 'username',
            'course', 'course_ids', 'school_student', 'college_student', 'jobseeker', 'employee', 'status', 'deactivation_reason', 'notes'
        ]

    def get_course(self, obj):
        courses = Course.objects.filter(
            batchcoursetrainer__student=obj,
            is_archived=False,
            status__iexact='Active'
        ).distinct()

        course_list = list(courses)

        new_batches = NewBatch.objects.filter(
            students=obj,
            is_archived=False,
            status=True
        ).select_related("course")

        for nb in new_batches:
            if nb.course and nb.course.status == "Active" and not nb.course.is_archived:
                course_list.append(nb.course)

        unique_courses = {c.course_id: c for c in course_list}.values()

        return [course.course_name for course in unique_courses]

    def get_profile_pic_url(self, obj):
        if obj.profile_pic and hasattr(obj.profile_pic, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.profile_pic.url
        return None

    def validate_contact_no(self, value):
        value = value.strip()
        from aryuapp.models import Student, Trainer

        instance = getattr(self, 'instance', None)

        # Check for existing Student with same contact_no (excluding self if updating)
        student_qs = Student.objects.filter(contact_no__iexact=value, is_archived=False)
        if instance:
            student_qs = student_qs.exclude(pk=instance.pk)
        if student_qs.exists():
            raise serializers.ValidationError("Phone number already exists.")
        # Check if the phone number is already used by a Trainer
        if Trainer.objects.filter(contact_no__iexact=value).exists():
            raise serializers.ValidationError("Phone number already exists.")

        return value

    def validate_username(self, value):
        if len(value) > 50:
            raise serializers.ValidationError("username has not more than 50 characters.")
        return value

    def parent_guardian_occupation(self, value):
        if value and len(value) > 255:
            raise serializers.ValidationError("parent_guardian_address has not more than 255 characters.")
        return value

    def validate_email(self, value):
        value = value.lower()
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")

        # Accept only emails with these domains
        allowed_domains = [
            'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'rediffmail.com', 'icloud.com', 'aryutechnologies.com','farida.co.in',
        ]
        domain = value.split('@')[-1]
        if domain not in allowed_domains:
            raise serializers.ValidationError("Please enter a valid email domain (e.g., gmail.com, yahoo.com).")
        return value

    def update(self, instance, validated_data):
        deactivation_reason = validated_data.pop('deactivation_reason', None)
        course_ids_raw = validated_data.pop('course_ids', None)
        # Handle JSON array string
        course_ids = []
        if course_ids_raw:
            try:
                parsed = json.loads(course_ids_raw)
                if isinstance(parsed, list):
                    course_ids = [int(id) for id in parsed]
            except (json.JSONDecodeError, ValueError, TypeError):
                raise serializers.ValidationError({'course_ids': 'Invalid format. Use JSON array like [1, 2].'})

        school_data = validated_data.pop('school_student', None)
        college_data = validated_data.pop('college_student', None)
        jobseeker_data = validated_data.pop('jobseeker', None)
        employee_data = validated_data.pop('employee', None)

        username = validated_data.pop('username', None)
        if username and instance.username != username:
            instance.username = username

        for attr, value in validated_data.items():
            setattr(instance, attr, value)


        instance.save()

        if school_data:
            School_Student.objects.update_or_create(student=instance, defaults=school_data)
        if college_data:
            College_Student.objects.update_or_create(student=instance, defaults=college_data)
        if jobseeker_data:
            JobSeeker.objects.update_or_create(student=instance, defaults=jobseeker_data)
        if employee_data:
            Employee.objects.update_or_create(student=instance, defaults=employee_data)

        return instance

class RecordingSerializer(serializers.ModelSerializer):
    created_date = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    class Meta:
        model = Recordings
        fields = '__all__'
        read_only_fields = ['id', "created_date"]
        
    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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

class InvoiceSerializer(serializers.ModelSerializer):
    student = serializers.CharField(write_only=True)
    pdf_url = serializers.SerializerMethodField()
    class Meta:
        model = Invoice
        fields = [
            "student",
            "buyer_name",
            "buyer_address",
            "buyer_mobile",
            "description",
            "quantity",
            "rate",
            "per",
            "amount",
            "amount_in_words",
            "pdf_file",
            "pdf_url",
            "invoice_number",
            "date",
            "payment_terms",
            "created_at",
            "is_archived",
            "created_by",
        ]
        read_only_fields = ("invoice_number", "created_at")

    def create(self, validated_data):
        registration_id = validated_data.pop("student")
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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
        try:
            student_obj = Student.objects.get(registration_id=registration_id)
        except Student.DoesNotExist:
            raise serializers.ValidationError({"student": "Student with this registration ID does not exist"})
        validated_data["student"] = student_obj
        return super().create(validated_data)

    def get_pdf_url(self, obj):
        if obj.pdf_file and hasattr(obj.pdf_file, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.pdf_file.url
        return None
     
class CertificateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Certificate
        fields = '__all__'
        read_only_fields = ['certificate_number']

    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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
        
class TrainerSerializer(serializers.ModelSerializer):   

    profile_pic_url = serializers.SerializerMethodField()
    attendance = serializers.SerializerMethodField()
    role_name = serializers.CharField(source="role.name", read_only=True)
    batch = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()
    

    class Meta:
        model = Trainer
        fields = [
            'trainer_id', 'employee_id', 'role', 'role_name', 'batch', 'username', 'password',
            'full_name', 'user_type', 'profile_pic', 'profile_pic_url',
            'email', 'contact_no', 'gender', 'specialization',
            'working_hours', 'status',
            'attendance', 'status', 'created_at', 'created_by', 'notes', 'is_archived'
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False, 'allow_blank': True},
            'employee_id': {
                'error_messages': {
                    'max_length': "Employee ID cannot exceed 255 characters."
                }
            },
            'full_name': {
                'error_messages': {
                    'max_length': "Full Name cannot exceed 255 characters."
                }
            },
            'username': {
                'error_messages': {
                    'max_length': "Username cannot exceed 255 characters."
                }
            },
            'working_hours': {
                'error_messages': {
                    'max_length': "Working Hours cannot exceed 255 characters."
                }
            },
        }
    
    def get_notes(self, obj):
    
        from aryuapp.models import Note

        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model='trainer'
        ).order_by('-created_at')

        # Convert "true"/"false" strings to actual boolean
        def convert_status(value):
            if isinstance(value, str):
                if value.lower() == "true":
                    return True
                if value.lower() == "false":
                    return False
            return value

        return [
            {
                "note_id": note.id,
                "reason": note.reason,
                "created_by": note.created_by,
                "status": note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes_qs
        ]
    
    def run_validation(self, data=serializers.empty):
       
        try:
            return super().run_validation(data)
        except serializers.ValidationError as exc:
            new_errors = {}
            for field, messages in exc.detail.items():
                new_messages = []
                for msg in messages:
                    if "Ensure this field has no more than" in str(msg):
                        max_len = getattr(self.fields[field], 'max_length', None)
                        if max_len:
                            new_messages.append(f"Ensure this {field} has no more than {max_len} characters.")
                        else:
                            new_messages.append(str(msg))
                    else:
                        new_messages.append(str(msg))
                new_errors[field] = new_messages
            raise serializers.ValidationError(new_errors)

    def get_batch(self, obj):
        # -------- NEW SYSTEM BATCHES ONLY --------
        new_batches = NewBatch.objects.filter(
            trainer=obj,
            is_archived=False,
        ).prefetch_related('students', 'course')

        batch_data = []
        for nb in new_batches:
            students = [
                {
                    "student_id": getattr(s, "student_id", None),
                    "student_name": f"{s.first_name} {s.last_name}".strip(),
                    "registration_id": getattr(s, "registration_id", None)
                } for s in nb.students.all()
            ]

            batch_data.append({
                "batch_id": nb.batch_id,
                "batch_name": nb.title,
                "title": nb.title,
                "students": students,
                "course_id": nb.course.course_id if nb.course else None,
                "course_name": nb.course.course_name if nb.course else None,
            })

        return batch_data

    def get_attendance(self, obj):
        qs = obj.trainerattendance_set.all().order_by('-date')
        return TrainerAttendanceSerializer(qs, many=True).data if qs.exists() else []

    def validate_email(self, value):
        value = value.lower()
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")

        # Accept only emails with these domains
        allowed_domains = [
            'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'rediffmail.com', 'icloud.com', 'aryutechnologies.com', 'aryuenterprise.com', 'aryuacademy.com'
        ]
        domain = value.split('@')[-1]
        if domain not in allowed_domains:
            raise serializers.ValidationError("Please enter a valid  email domain (e.g., gmail.com, yahoo.com).")
        if Trainer.objects.filter(email__iexact=value, is_archived=False).exists():
            instance = getattr(self, 'instance', None)
            if instance and instance.email == value:
                return value
            raise serializers.ValidationError("Email already exists.")
        
        return value

    def validate_full_name(self, value):
        if not re.match(r'^[A-Za-z ]+$', value):
            raise serializers.ValidationError("Name must contain only letters and spaces.")
        return value

    def validate_username(self, value):
        value = value
        instance = getattr(self, 'instance', None)

        if instance and instance.username == value:
            # Username hasn't changed, skip validation
            return value

        from aryuapp.models import Student, Trainer
        if Student.objects.filter(username__iexact=value, is_archived=False).exists():
            raise serializers.ValidationError("Username already exists")
        if Trainer.objects.filter(username__iexact=value, is_archived=False).exists():
            raise serializers.ValidationError("Username already exists")
        
        return value

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Make password not required on update
        if self.instance:
            self.fields['password'].required = False

    def get_profile_pic_url(self, obj):
        if obj.profile_pic and hasattr(obj.profile_pic, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.profile_pic.url
        return None
    
    def create(self, validated_data):
        # Extract and hash the password
        password = validated_data.get('password')
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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
            
        if not password:
            raise serializers.ValidationError({"password": "Password is required."})
        validated_data['password'] = make_password(password)

        # Create the Trainer instance
        trainer = Trainer.objects.create(**validated_data)

        return trainer

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        if password:
            instance.password = make_password(password)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        return instance
    
class TrainerTravelExpenseImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = TrainerTravelExpenseImage
        fields = ['image_id', 'image', 'uploaded_at']

    def get_image(self, obj):
        if obj.image and hasattr(obj.image, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.image.url
        return None


class TrainerTravelExpenseSerializer(serializers.ModelSerializer):
    trainer_name = serializers.CharField(source='trainer.full_name', read_only=True)
    employee_id = serializers.CharField(source='trainer.employee_id', read_only=True)
    bills = TrainerTravelExpenseImageSerializer(many=True, read_only=True)

    class Meta:
        model = TrainerTravelExpense
        fields = [
            'expense_id',
            'trainer',
            'trainer_name',
            'employee_id',
            'travel_date',
            'description',
            'total_amount',
            'status',
            'remarks',
            'bills',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class TrainerAttendanceSerializer(serializers.ModelSerializer):
    date = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', required=False)

    # Read-only fields
    course_name = serializers.CharField(source='course.course_name', read_only=True)
    batch_name = serializers.CharField(source='batch.batch_name', read_only=True)
    trainer_name = serializers.CharField(source='trainer.full_name', read_only=True)
    title = serializers.SerializerMethodField()
    batch_id = serializers.IntegerField(source='batch.batch_id', read_only=True)
    course_id = serializers.IntegerField(source='course.course_id', read_only=True)

    extra_hours = serializers.SerializerMethodField()

    # New field for POST only (NewBatch)
    new_batch = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = TrainerAttendance
        fields = [
            'trainer', 'trainer_name',

            # old system readonly
            'batch_id', 'batch_name',

            # new system input
            'new_batch',

            'title', 'course_id', 'course_name',
            'topic', 'sub_topic', 'date',
            'status', 'marked_by_admin', 'extra_hours'
        ]

        read_only_fields = ['batch_id', 'batch_name', 'course_id', 'course_name', 'date']

    def get_title(self, obj):
        from aryuapp.models import NewBatch
        
        try:
            return obj.new_batch.title if obj.new_batch else obj.batch.title
        except:
            return "Title not available"

    def get_extra_hours(self, obj):
        from datetime import timedelta
        from aryuapp.models import ClassSchedule

        schedules = ClassSchedule.objects.filter(
            trainer=obj.trainer,
            batch=obj.batch,
            course=obj.course,
            scheduled_date=obj.date.date(),
            is_archived=False,
            is_class_cancelled=False
        )

        if not schedules.exists():
            return None

        total_extra = timedelta(0)
        for schedule in schedules:
            total_extra += schedule.get_extra_time()

        return str(total_extra) if total_extra.total_seconds() > 0 else None

    # -------------------------------------------
    #           VALIDATION FOR POST
    # -------------------------------------------
    def validate(self, data):
        trainer = data.get('trainer')

        # NEW BATCH POST FLOW (the only allowed POST)
        new_batch_id = self.initial_data.get('new_batch')

        if new_batch_id:
            from aryuapp.models import NewBatch

            try:
                new_batch = NewBatch.objects.get(pk=new_batch_id, is_archived=False)
            except NewBatch.DoesNotExist:
                raise serializers.ValidationError({"new_batch": "Batch not found."})

            # Ensure trainer matches
            if new_batch.trainer != trainer:
                raise serializers.ValidationError("Trainer not assigned to this Batch.")

            # Assign validated fields
            data['new_batch'] = new_batch
            data['batch'] = new_batch  # for backward DB compatibility (Batch FK)
            data['course'] = new_batch.course

            return data

        # If POST does NOT contain new_batch → reject
        if self.instance is None:  # Only for POST
            raise serializers.ValidationError(
                {"new_batch": "Batch is required for trainer attendance creation."}
            )

        # GET request for old attendance → allow without validation
        return data

    # -------------------------------------------
    #               CREATE OVERRIDE
    # -------------------------------------------
    def create(self, validated_data):
        # If we are using new_batch, ensure old batch is None
        if 'new_batch' in validated_data and validated_data['new_batch'] is not None:
            validated_data['batch'] = None

        # Default date
        if 'date' not in validated_data or validated_data['date'] is None:
            validated_data['date'] = timezone.now()

        return super().create(validated_data)

class AnnouncementSerializer(serializers.ModelSerializer):
    content_pic_url = serializers.SerializerMethodField()
    background_pic_url = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    updated_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    class Meta:
        model = Announcement
        fields = ['id', 'title', 'content', 'audience', 'content_pic', 'content_pic_url', 'background_pic', 'background_pic_url',  'created_at', 'updated_at', 'created_by']

    def get_content_pic_url(self, obj):
        if obj.content_pic and hasattr(obj.content_pic, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.content_pic.url
        return None
    
    def get_background_pic_url(self, obj):
        if obj.background_pic and hasattr(obj.background_pic, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.background_pic.url
        return None
    
    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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

class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = '__all__'
        read_only_fields = ['submitted_date']
    
class LeaveRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveRequest
        fields = '__all__'
        read_only_fields = ['leave_id', 'applied_date']
    
    def create(self, validated_data):
        leave = LeaveRequest.objects.create(**validated_data)
        return leave

    def update(self, instance, validated_data):
        instance.start_date = validated_data.get('start_date', instance.start_date)
        instance.end_date = validated_data.get('end_date', instance.end_date)
        instance.reason = validated_data.get('reason', instance.reason)
        instance.save()
        return instance
    
class BatchCourseTrainerSerializer(serializers.ModelSerializer):
    course_id = serializers.IntegerField(source='course.course_id')
    trainer_employee_id = serializers.CharField(source='trainer.employee_id')
    course_name = serializers.CharField(source='course.course_name', read_only=True)
    trainer_name = serializers.CharField(source='trainer.full_name', read_only=True)
    student_id = serializers.CharField(source='student.student_id', read_only=True)
    registration_id = serializers.CharField(source='student.registration_id', read_only=True)
    first_name = serializers.CharField(source='student.first_name', read_only=True)
    last_name = serializers.CharField(source='student.last_name', read_only=True)
    category_id = serializers.IntegerField(source='course.course_category.category_id', read_only=True)

    class Meta:
        model = BatchCourseTrainer
        fields = ['course_id', 'trainer_employee_id', 'category_id', 'course_name', 'trainer_name', 'student_id','registration_id', 'first_name', 'last_name']
        read_only_fields = ['course_name', 'trainer_name', 'registration_id', 'first_name', 'last_name']
    
class ClassScheduleSerializer(serializers.ModelSerializer):
    trainer_name = serializers.SerializerMethodField()
    course_name = serializers.CharField(source='course.course_name', read_only=True)
    batch_name = serializers.CharField(source='batch.batch_name', read_only=True)
    status_info = serializers.SerializerMethodField()
    start_time = serializers.TimeField(required=False)
    end_time = serializers.TimeField(required=False)
    scheduled_date = serializers.DateField(format='%Y-%m-%d', required=False)
    employee_id = serializers.CharField(write_only=True, required=False)
    title = serializers.SerializerMethodField()
    new_batch_id = serializers.IntegerField(source='new_batch.batch_id', read_only=True)
    batch_id = serializers.IntegerField(source='batch.batch_id', read_only=True)
    course_id = serializers.IntegerField(source='course.course_id', read_only=True)
    notes = serializers.SerializerMethodField()

    course_trainer_assignments = serializers.SerializerMethodField()

    class Meta:
        model = ClassSchedule
        fields = [
            'schedule_id', 'class_link', 'course_id', 'course_name', 'new_batch_id', 'new_batch',
            'batch_id', 'batch_name', 'title', 'employee_id', 'trainer_name',
            'scheduled_date', 'start_time', 'end_time', 'duration', 'is_class_cancelled', 'notes',
            'is_archived', 'is_online_class', 'status_info', 'course_trainer_assignments', 'meeting_link', 'created_at', 'created_by',
        ]
        read_only_fields = [ 'duration', 'meeting_link']
        
    def get_title(self, obj):
        if hasattr(obj, "batch") and obj.batch:
            return obj.batch.title

        if hasattr(obj, "new_batch") and obj.new_batch:
            return obj.new_batch.title

        return None

    def get_notes(self, obj):

        from aryuapp.models import Note

        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model='classschedule'
        ).order_by('-created_at')

        return [
            {
                "note_id": note.id,
                "reason": note.reason,
                "created_by": note.created_by,
                "status": note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes_qs
        ]

    def validate_employee_id(self, value):
        try:
            return Trainer.objects.get(employee_id=value)
        except Trainer.DoesNotExist:
            raise serializers.ValidationError("Invalid employee_id. Trainer not found.")
        
    def validate_batch_id(self, value):
        batch = None

        # Try Batch table
        try:
            batch = Batch.objects.get(batch_id=value)
        except Batch.DoesNotExist:
            batch = None

        # Try NewBatch table
        if batch is None:
            try:
                batch = NewBatch.objects.get(batch_id=value)
            except NewBatch.DoesNotExist:
                raise serializers.ValidationError("Batch ID not found in Batch")

        # Validate
        if batch.is_archived:
            raise serializers.ValidationError("Cannot create schedule for deleted batch.")

        if not batch.status:
            raise serializers.ValidationError("Cannot Create Schedule for Inactive Batch.")

        return batch
    
    def validate(self, data):
        course = data.get("course")
        batch = data.get("batch")

        # If updating, get existing values
        if self.instance:
            if not course:
                course = self.instance.course
            if not batch:
                batch = self.instance.batch

        # ---------- Validation 1: Course Category Active ----------
        if course and course.course_category and not course.course_category.status:
            raise serializers.ValidationError({
                "course": "Cannot create schedule because the course's category is inactive."
            })

        # ---------- Validation 2: Course Active ----------
        if course and course.status == "Inactive":
            raise serializers.ValidationError({
                "course": "Cannot create schedule because this course is inactive."
            })

        # ---------- Validation 3: Batch Active ----------
        if batch and not batch.status:
            raise serializers.ValidationError({
                "batch": "Cannot create schedule because this batch is inactive."
            })

        return data


    # --------------------------------------------------
    #  CREATE (Batch + NewBatch handling)
    # --------------------------------------------------
    def create(self, validated_data):
        request = self.context.get("request")

        # -------- Identify created_by and created_by_type ----------
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

        # ---------- Extract IDs from request ----------
        trainer_id = validated_data.pop("employee_id", None)
        batch_id = validated_data.pop("batch_id", None)

        # ---------- Assign trainer instance ----------
        if trainer_id:
            validated_data["trainer"] = Trainer.objects.get(pk=trainer_id)

        # ---------- Fetch the batch from BOTH tables ----------
        if batch_id:
            batch = None

            # Try Batch
            try:
                batch = Batch.objects.get(pk=batch_id)
            except Batch.DoesNotExist:
                pass

            # Try NewBatch
            if batch is None:
                try:
                    batch = NewBatch.objects.get(pk=batch_id)
                except NewBatch.DoesNotExist:
                    raise serializers.ValidationError({
                        "batch_id": "Batch not found in Batch or NewBatch."
                    })

            # Assign batch instance
            validated_data["batch"] = batch

        # ---------- Create schedule ----------
        class_schedule = super().create(validated_data)
        return class_schedule

    def get_trainer_name(self, obj):
        return obj.trainer.full_name if obj.trainer else None

    def get_status_info(self, obj):
        now = datetime.now()
        scheduled_start = datetime.combine(obj.scheduled_date, obj.start_time)
        scheduled_end = datetime.combine(obj.scheduled_date, obj.end_time)

        attendance_exists = TrainerAttendance.objects.filter(
            trainer=obj.trainer,
            course=obj.course,
            date__date=obj.scheduled_date
        ).exists()

        if attendance_exists and scheduled_start <= now <= scheduled_end:
            return "Ongoing"
        elif now > scheduled_end:
            # Class has ended
            attendance_exists = TrainerAttendance.objects.filter(
                trainer=obj.trainer,
                course=obj.course,
                date__date=obj.scheduled_date
            ).exists()
            return "Done" if attendance_exists else "Missed"
        else:
            return "Upcoming"

    def get_course_trainer_assignments(self, obj):
        # Directly filter BatchCourseTrainer for this class's course and trainer
        assignments = BatchCourseTrainer.objects.select_related('course', 'trainer', 'student').filter(
            batch_id=obj.batch_id,
            course_id=obj.course_id,
            trainer_id=obj.trainer_id
        )

        return [
            {
                "course_id": a.course.course_id,
                "trainer_employee_id": a.trainer.employee_id,
                "course_name": a.course.course_name,
                "trainer_name": a.trainer.full_name,
                "registration_id": a.student.registration_id,
                "student_names": f"{a.student.first_name} {a.student.last_name}"
            }
            for a in assignments
        ]
        
class RecurringScheduleSerializer(serializers.ModelSerializer):
    
    employee_id = serializers.CharField(write_only=True)

    # API input: "batch"
    # Model field: "new_batch"
    batch = serializers.PrimaryKeyRelatedField(
        source="new_batch",
        queryset=NewBatch.objects.filter(is_archived=False),
        required=True
    )

    class Meta:
        model = RecurringSchedule
        fields = "__all__"
        read_only_fields = ["trainer"]

    def create(self, validated_data):

        # ---------------- TRAINER ----------------
        employee_id = validated_data.pop("employee_id")

        try:
            trainer = Trainer.objects.get(employee_id=employee_id)
        except Trainer.DoesNotExist:
            raise serializers.ValidationError({"employee_id": "Trainer not found"})

        validated_data["trainer"] = trainer

        # ---------------- NEW BATCH ----------------
        new_batch = validated_data["new_batch"]

        if new_batch.is_archived:
            raise serializers.ValidationError({"batch": f"Batch '{new_batch.title}' is archived."})

        if not new_batch.status:
            raise serializers.ValidationError({"batch": f"Batch '{new_batch.title}' is inactive."})

        # ---------------- COURSE ----------------
        course = validated_data.get("course")

        if course:
            if course.status.lower() != "active":
                raise serializers.ValidationError({"course": f"Course '{course.course_name}' is inactive."})

            if course.course_category and not course.course_category.status:
                raise serializers.ValidationError(
                    {"course": f"Category '{course.course_category.category_name}' is inactive."}
                )

        # ---------------- CREATED BY ----------------
        request = self.context.get("request")
        role = getattr(request.user, "user_type", None)

        if request and request.user:
            if role in ["tutor", "admin"]:
                validated_data["created_by"] = str(getattr(request.user, "trainer_id", None))
            elif role == "super_admin":
                validated_data["created_by"] = str(getattr(request.user, "user_id", None))
            elif role == "student":
                validated_data["created_by"] = str(getattr(request.user, "student_id", None))
            else:
                validated_data["created_by"] = str(request.user.id)

            validated_data["created_by_type"] = role

        # ------------ CREATE RECURRING ROW ------------
        recurrence = super().create(validated_data)

        # ------------ GENERATE CHILD SCHEDULES ------------
        self.generate_schedules(new_batch, trainer, course, validated_data)

        return recurrence

    # ==========================================================
    #   INTERNAL FUNCTIONS -- NOW INCLUDED
    # ==========================================================

    def generate_schedules(self, batch, trainer, course, data):

        country = data.get("country", "IN")
        subdiv = data.get("subdiv", None)

        try:
            years = range(data["start_date"].year, data["end_date"].year + 1)
            public_holidays = holidays.CountryHoliday(country, subdiv=subdiv, years=years)
        except:
            public_holidays = {}

        current_date = data["start_date"]
        end_date = data["end_date"]

        recurrence_type = data.get("recurrence_type", "").lower()
        custom_days = [d.upper() for d in data.get("days_of_week", [])]
        days_map = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

        # Single-day
        if recurrence_type == "day":
            self._create_schedule(batch, trainer, course, data, current_date)
            return
        
        max_days = 365 * 2  # 2 years max
        loop_counter = 0

        # Multi-day
        while current_date <= end_date:
            loop_counter += 1
            if loop_counter > max_days:
                raise serializers.ValidationError(
                    "Recurrence range too large. Choose a shorter time period of maximum 2 years."
                )

            if current_date in public_holidays:
                current_date += timedelta(days=1)
                continue

            weekday = current_date.weekday()
            create_flag = True

            if recurrence_type == "daily":
                create_flag = True

            elif recurrence_type == "weekly":
                create_flag = weekday == data["start_date"].weekday()

            elif recurrence_type == "custom_days":
                create_flag = days_map[weekday] in custom_days

            if create_flag:
                self._create_schedule(batch, trainer, course, data, current_date)

            current_date += timedelta(days=1)

    def _create_schedule(self, batch, trainer, course, data, date):

        exists = ClassSchedule.objects.filter(
            new_batch=batch,
            trainer=trainer,
            course=course,
            scheduled_date=date,
            is_archived=False
        ).filter(
            start_time__lt=data["end_time"],
            end_time__gt=data["start_time"]
        ).exists()

        if exists:
            raise serializers.ValidationError(
                {"non_field_errors": f"Schedule already exists on {date}."}
            )

        ClassSchedule.objects.create(
            new_batch=batch,      # Store only in new_batch
            batch=None,           # No legacy batch
            trainer=trainer,
            course=course,
            scheduled_date=date,
            start_time=data["start_time"],
            end_time=data["end_time"],
            is_online_class=data.get("is_online_class", False),
            class_link=data.get("class_link", ""),
            created_by=data["created_by"],
            created_by_type=data["created_by_type"]
        )

class ClassScheduleSimpleSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source="course.course_name", read_only=True)
    trainer_name = serializers.CharField(source="trainer.full_name", read_only=True)
    title = serializers.CharField(source="NewBatch.title", read_only=True )
    status = serializers.SerializerMethodField()

    class Meta:
        model = ClassSchedule
        fields = ["schedule_id", "scheduled_date", "course_name", 'start_time', 'end_time', 'status', "trainer_name",  "title"]
        
    def get_status(self, sched):
        current_time = timezone.now()
        start_time = getattr(sched, "start_time", None) or time(9, 0)

        # Start datetime aware
        class_start_dt = timezone.make_aware(
            datetime.combine(sched.scheduled_date, start_time),
            timezone.get_current_timezone()
        )

        # End datetime
        if sched.duration:
            class_end_dt = class_start_dt + sched.duration
        else:
            if sched.end_time:
                class_end_dt = timezone.make_aware(
                    datetime.combine(sched.scheduled_date, sched.end_time),
                    timezone.get_current_timezone()
                )
            else:
                class_end_dt = class_start_dt + timedelta(hours=1)

        # Status logic
        if current_time < class_start_dt:
            return "upcoming"
        elif class_start_dt <= current_time <= class_end_dt:
            return "ongoing"
        elif class_end_dt < current_time:
            attendance_exists = TrainerAttendance.objects.filter(
                trainer=sched.trainer,
                batch=sched.batch,
                course=sched.course,
                date__date=sched.scheduled_date,
            ).exists()
            return "done" if attendance_exists else "missed"
        return "missed"

class BatchSerializer(serializers.ModelSerializer):
    course_trainer_assignments = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField()),
        write_only=True,
        required=False
    )
    scheduled_date = serializers.DateField(format='%Y-%m-%d')
    schedules = ClassScheduleSimpleSerializer(many=True, read_only=True)
    notes = serializers.SerializerMethodField()
    class Meta:
        model = Batch
        fields = [
            'batch_id', 'batch_name', 'title', 'scheduled_date','schedules',
            'end_date', 'is_archived', 'status', 'course_trainer_assignments', 'created_at', 'created_by', 'notes'
        ]
        read_only_fields = ['batch_id', 'batch_name']

    def get_notes(self, obj):

        from aryuapp.models import Note

        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model='batch'
        ).order_by('-created_at')

        return [
            {
                "note_id": note.id,
                "reason": note.reason,
                "created_by": note.created_by,
                "status": note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes_qs
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # --- Duration ---
        start = instance.scheduled_date
        end = instance.end_date
        if start and end:
            duration_days = (end - start).days + 1
            months = duration_days // 30
            days = duration_days % 30
            if months:
                data['duration'] = f"{months} Months {days} Days"
            else:
                data['duration'] = f"{days} Days"
        else:
            data['duration'] = None

        # --- Sorted schedules (date desc) ---
        sorted_schedules = instance.schedules.all().order_by('-scheduled_date', '-start_time')
        data['schedules'] = ClassScheduleSimpleSerializer(sorted_schedules, many=True).data
    
        # --- Weekly Schedule (group by weekday) ---
        schedule_by_day = defaultdict(list)
        for sch in instance.schedules.all():
            day_name = calendar.day_name[sch.scheduled_date.weekday()]  # Monday, Tuesday, etc
            st = sch.start_time.strftime("%I:%M %p")
            et = sch.end_time.strftime("%I:%M %p")
            schedule_by_day[day_name].append(f"{st}-{et}")

        # Merge into strings per day
        weekly_display = []
        weekday_order = {day: i for i, day in enumerate(calendar.day_name)}
        for day in sorted(schedule_by_day.keys(), key=lambda x: weekday_order[x]):
            times = ", ".join(schedule_by_day[day])
            weekly_display.append(f"{day} {times}")

        data['weekly_schedule'] = weekly_display

        # --- course_trainer_assignments ---
        data['course_trainer_assignments'] = [
            {
                'category_id': bct.course.course_category.category_id,
                "course_id": bct.course.course_id,
                "course_name": bct.course.course_name,
                "employee_id": bct.trainer.employee_id,
                "trainer_name": bct.trainer.full_name,
                "student_id": bct.student.student_id,
                "registration_id": bct.student.registration_id,
                "name": f"{bct.student.first_name} {bct.student.last_name}".strip()
            }
            for bct in BatchCourseTrainer.objects.filter(batch=instance)
                .select_related('course', 'trainer', 'student')
        ]

        return data

    def create(self, validated_data):
        trainer_map = validated_data.pop('course_trainer_assignments', [])
        
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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

        batch = super().create(validated_data)

        for entry in trainer_map:
            course_id = entry.get('course_id')
            employee_id = entry.get('employee_id')
            student_id = entry.get('student_id')

            try:
                trainer = Trainer.objects.get(employee_id=employee_id)
                student = Student.objects.get(student_id=student_id)
            except (Trainer.DoesNotExist, Student.DoesNotExist):
                raise serializers.ValidationError({
                    'course_trainer_assignments': f"Invalid trainer or student: ({employee_id}, {student_id})"
                })

            BatchCourseTrainer.objects.create(
                batch=batch,
                course_id=course_id,
                trainer=trainer,
                student=student
            )

        return batch

    def update(self, instance, validated_data):
        # Capture status before update
        old_status = instance.status

        # Pop trainer mapping if provided
        trainer_map = validated_data.pop('course_trainer_assignments', None)

        # Update batch fields
        batch = super().update(instance, validated_data)

        # Handle trainer assignments
        if trainer_map is not None:
            # Clear previous assignments only if new data provided
            instance.batchcoursetrainer.all().delete()

            for entry in trainer_map:
                course_id = entry.get('course_id')
                employee_id = entry.get('employee_id')
                student_id = entry.get('student_id')

                try:
                    trainer = Trainer.objects.get(employee_id=employee_id)
                    student = Student.objects.get(student_id=student_id)
                except (Trainer.DoesNotExist, Student.DoesNotExist):
                    raise serializers.ValidationError({
                        'course_trainer_assignments': f"Invalid trainer or student: ({employee_id}, {student_id})"
                    })

                BatchCourseTrainer.objects.create(
                    batch=batch,
                    course_id=course_id,
                    trainer=trainer,
                    student=student
                )

        # Cascade deactivation if batch is set to False
        new_status = validated_data.get('status', old_status)
        if new_status is False and old_status != False:
            instance.deactivate_batch(instance)

        return batch
    
class NewBatchSerializer(serializers.ModelSerializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.all())
    trainer = serializers.PrimaryKeyRelatedField(queryset=Trainer.objects.all())

    # Correct M2M Field
    students = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Student.objects.filter(is_archived=False),
        required=False
    )

    class Meta:
        model = NewBatch
        fields = [
            'batch_id', 'title', 'course', 'trainer',
            'start_date', 'end_date', 'start_time', 'end_time',
            'slots', 'status', 'students',
            'created_by', 'created_by_type', 'created_at', 'is_archived'
        ]
        read_only_fields = ['batch_id', 'created_by', 'created_by_type', 'created_at']

    def validate(self, attrs):
        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')
        start_time = attrs.get('start_time')
        end_time = attrs.get('end_time')
        slots = attrs.get('slots')

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError({'end_date': 'End date must be after start date.'})

        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError({'end_time': 'End time must be after start time.'})

        if slots is not None and slots <= 0:
            raise serializers.ValidationError({'slots': 'Slots must be greater than zero.'})

        return attrs

    def create(self, validated_data):
        students = validated_data.pop('students', [])
        slots = validated_data.get("slots", 0)

        if len(students) > slots and slots == 0:
            raise serializers.ValidationError({
                "students": "Cannot add students. Slots are full."
            })

        request = self.context.get("request")
        role = getattr(request.user, "user_type", None) if request and request.user else None

        # --------- FIXED: created_by always stores ID (not username) ---------
        if request and request.user:
            if role == "trainer":
                validated_data["created_by"] = str(getattr(request.user, "trainer_id", None))

            elif role == "admin":
                # Admin does NOT have admin_id – they have trainer_id
                validated_data["created_by"] = str(getattr(request.user, "trainer_id", None))

            elif role == "super_admin":
                validated_data["created_by"] = str(getattr(request.user, "user_id", None))

            elif role == "student":
                validated_data["created_by"] = str(getattr(request.user, "student_id", None))

            else:
                # fallback to user.id always
                validated_data["created_by"] = str(getattr(request.user, "user_id", None))

            validated_data["created_by_type"] = role
        # --------------------------------------------------------------

        batch = NewBatch.objects.create(**validated_data)

        if students:
            if batch.available_slots() <= 0 and len(students) > 0:
                raise serializers.ValidationError({
                    "students": "Cannot add students. Slots are full."
                })
            batch.students.set(students)

        return batch

    def update(self, instance, validated_data):
        students = validated_data.pop('students', None)

        # Validate slot rule only when students list is passed
        if students is not None:
            current_count = instance.students.count()
            new_count = len(students)
            available_slots = instance.slots - current_count

            # If available_slots == 0 → stop adding more
            if available_slots <= 0 and new_count > current_count:
                raise serializers.ValidationError({
                    "students": "Cannot add students. Slots are full."
                })

        # Update fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Set students only after validation
        if students is not None:
            instance.students.set(students)

        return instance

class StudentDetailSerializer(serializers.ModelSerializer):
    batch = serializers.SerializerMethodField()
    profile_pic = serializers.SerializerMethodField()
    class Meta:
        model = Student
        fields = [
            'registration_id', 'student_id', 'profile_pic', 'batch',
            'first_name', 'last_name', 'contact_no', 'email'
        ]

    def get_batch(self, obj):
        batches = obj.new_batches.all().values(
            "batch_id", "title", "course__course_id", "course__course_name"
        )
        return batches
    
    def get_profile_pic(self, obj):
        if obj.profile_pic and hasattr(obj.profile_pic, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.profile_pic.url
        return None

class TrainerForStudentSerializer(serializers.ModelSerializer):
    batch = serializers.SerializerMethodField()
    profile_pic = serializers.SerializerMethodField()
    class Meta:
        model = Trainer
        fields = [
            "employee_id",
            'trainer_id',
            "full_name",
            "profile_pic",
            "batch"
        ]

    def get_batch(self, obj):
        batches = obj.new_batches.all().values(
            "batch_id", "title",
            "course__course_id", "course__course_name"
        )
        return batches
    
    def get_profile_pic(self, obj):
        if obj.profile_pic and hasattr(obj.profile_pic, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.profile_pic.url
        return None

class TrainerSimpleSerializer(serializers.ModelSerializer):
    profile_pic = serializers.SerializerMethodField()
    class Meta:
        model = Trainer
        fields = ['employee_id', 'full_name',  'profile_pic']
        
    def get_profile_pic(self, obj):
        if obj.profile_pic and hasattr(obj.profile_pic, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.profile_pic.url
        return None

class SubmissionStudentSerializer(serializers.ModelSerializer):
    profile_pic = serializers.SerializerMethodField()
    student_name = serializers.SerializerMethodField()
    class Meta:
        model = Student
        fields = ['registration_id', 'student_name', 'first_name', 'last_name', 'profile_pic']
        
    def get_profile_pic(self, obj):
        if obj.profile_pic and hasattr(obj.profile_pic, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.profile_pic.url
        return None
    
    def get_student_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"

class SubmissionReplySerializer(serializers.ModelSerializer):
    trainer = TrainerSimpleSerializer(read_only=True)
    
    date = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    class Meta:
        model = SubmissionReply
        fields = ['id','trainer','text','date', 'is_archived']
   
class SubmissionSerializer(serializers.ModelSerializer):
    student = SubmissionStudentSerializer(read_only=True)
    replies = SubmissionReplySerializer(many=True, read_only=True)
    date = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    file = serializers.FileField(required=False, allow_null=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = ['id', 'assignment', 'student', 'text', 'file', 'file_url', 'date', 'replies', 'status', 'is_archived']
        read_only_fields = ['date']

    def get_file_url(self, obj):
        if obj.file and hasattr(obj.file, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.file.url
        return None
    
    def validate(self, data):
        assignment = data.get('assignment')
        if not assignment:
            raise serializers.ValidationError({"assignment": "Assignment is required."})

        course = getattr(assignment, 'course', None)
        if not course:
            raise serializers.ValidationError({"assignment": "Invalid assignment, course not found."})

        # Check course and category status
        if course.status == "Inactive":
            raise serializers.ValidationError({"course": "Cannot submit because this course is inactive."})

        if course.course_category and not course.course_category.status:
            raise serializers.ValidationError({"course": "Cannot submit because the course's category is inactive."})

        return data
    
class AssignmentSerializer(serializers.ModelSerializer):
    course = CourseSimpleSerializer(read_only=True)
    assigned_by = TrainerSerializer(read_only=True)
    submissions = serializers.SerializerMethodField()

    class Meta:
        model = Assignment
        fields = ['id', 'title', 'description', 'status', 'course', 'assigned_by', 'submissions', 'is_archived', 'created_at', 'created_by']
        
    def validate(self, attrs):
        title = attrs.get('title', '').strip()
        description = attrs.get('description', '').strip()

        if not title:
            raise serializers.ValidationError("Title cannot be empty or spaces only")
        if len(title) > 255:
            raise serializers.ValidationError("Title cannot exceed 255 characters.")
        if not description:
            raise serializers.ValidationError("Description cannot be empty or spaces only")
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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

    def get_submissions(self, obj):
        request = self.context.get('request')
        student = self.context.get('student')

        # Start with all active submissions
        submissions_qs = obj.submissions.filter(is_archived=False).order_by('-date')

        if student:
            submissions_qs = submissions_qs.filter(student=student)
        else:
            if request:
                auth_header = request.headers.get('Authorization')
                if auth_header and auth_header.startswith('Bearer '):
                    token = auth_header.split()[1]
                    try:
                        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
                        user_type = payload.get('user_type')

                        if user_type == 'admin':
                            # admin sees all submissions
                            submissions_qs = obj.submissions.filter(is_archived=False)
                        elif user_type == 'tutor':
                            employee_id = payload.get('employee_id')
                            student_ids = BatchCourseTrainer.objects.filter(
                                course=obj.course,
                                trainer__employee_id=employee_id
                            ).values_list('student__registration_id', flat=True)
                            submissions_qs = submissions_qs.filter(student__registration_id__in=student_ids)
                        elif user_type == 'employer':
                            company_name = payload.get('company_name')
                            student_ids = Student.objects.filter(
                                is_archived=False,
                                employee__company_name__iexact=company_name
                            ).values_list('registration_id', flat=True)
                            submissions_qs = submissions_qs.filter(student__registration_id__in=student_ids)
                        elif user_type == 'student':
                            reg_id = payload.get('registration_id')
                            submissions_qs = submissions_qs.filter(student__registration_id=reg_id)

                    except jwt.PyJWTError:
                        return []

        return SubmissionSerializer(submissions_qs, many=True, context={'request': request}).data
    
class AssignmentSimpleSerializer(serializers.ModelSerializer):
    submission_count = serializers.SerializerMethodField()
    class Meta:
        model = Assignment
        fields = ['id', 'title', 'course', 'submission_count', 'assigned_by', 'status']
        
    def get_submission_count(self, obj):
        return obj.submissions.count() 

class TestSerializer(serializers.ModelSerializer):
    course = CourseSimpleSerializer(source="course_id", read_only=True)
    test_completion = serializers.SerializerMethodField()

    class Meta:
        model = Test
        fields = [
            'test_id', 'test_name', 'description', 'duration',
            'total_marks', 'test_completion', 'course_id', 'course', 'is_archived', 'created_at', 'created_by'
        ]
        
    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

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
    
    def get_test_completion(self, obj):
        request = self.context.get("request")
        student = getattr(request.user, "student", None)  # 🔹 student linked with user

        if not student:
            return False  # not a student account

        return TestResult.objects.filter(student=student, test=obj).exists()

class TestQuestionsSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    class Meta:
        model = TestQuestions
        fields = ['question_id', 'test_id', 'question', 'type', 'options', 'marks', 'written_answer', 'mcq_correct_option', 'is_archived', 'created_at', 'created_by']

    def validate(self, data):
        q_type = data.get('type')
        if q_type.lower() == 'mcq' and not data.get('options'):
            raise serializers.ValidationError("MCQ questions must have options")
        return data

    def create(self, validated_data):
        request = self.context.get('request')
        if request and hasattr(request.user, 'trainer_id'):
            validated_data['created_by'] = request.user.trainer_id
        return super().create(validated_data)

class StudentAnswersSerializer(serializers.ModelSerializer):
    submitted_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    
    class Meta:
        model = StudentAnswers
        fields = [
            'answer_id',
            'student_id',
            'question_id',
            'test_id',
            'submitted_at',
            'selected_option',
            'written_answer',
            'is_correct'
        ]

    def validate_written_answer(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Written answer cannot be empty or spaces only")
        return value.strip()
    
    def create(self, validated_data):
        question = validated_data.get("question_id")

        # Snapshot question text
        validated_data["question_text"] = question.question

        # Determine the type of question
        if question.type == "mcq":
            # Save MCQ options and correct answer snapshot
            validated_data["options_snapshot"] = question.options
            validated_data["correct_answer_snapshot"] = question.mcq_correct_option
            validated_data["written_answer"] = None
        elif question.type == "written":
            # Save written answer snapshot in the existing field
            validated_data["correct_answer_snapshot"] = question.written_answer
            validated_data["options_snapshot"] = None

        return super().create(validated_data)

class TestResultSerializer(serializers.ModelSerializer):
    student = serializers.SerializerMethodField()
    submitted_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    evaluated_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    evaluated_by = serializers.SerializerMethodField()
    answers = serializers.SerializerMethodField()

    class Meta:
        model = TestResult
        fields = [
            'result_id', 'student_id', 'student', 'test_id',
            'evaluated_by', 'score', 'percentage', 'status',
            'time_taken', 'submitted_at', 'evaluated_at', 'answers'
        ]

    def get_student(self, obj):
        return StudentDetailSerializer(obj.student_id).data

    def get_evaluated_by(self, obj):
        if obj.evaluated_by:
            return {
                "employee_id": obj.evaluated_by.employee_id,
                "name": obj.evaluated_by.full_name
            }
        return None
    
    def get_answers(self, obj):
        student_answers = obj.student_id.student_answers.filter(test_id=obj.test_id)
        data = []
        for ans in student_answers:
            data.append({
                "answer_id": ans.answer_id,
                "question_id": ans.question_id.question_id if ans.question_id else None,
                "question": ans.question_text,
                "type": ans.question_id.type if ans.question_id else None,
                "options": ans.options_snapshot,
                "correct_answer": ans.correct_answer_snapshot,
                "submitted_answer": {
                    "selected_option": ans.selected_option,
                    "written_answer": ans.written_answer,
                    "is_correct": ans.is_correct
                },
                "submitted_at": ans.submitted_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        return data

class NotificationSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    course_id = serializers.SerializerMethodField()
    topic_id = serializers.SerializerMethodField()
    assignment_id = serializers.SerializerMethodField()
    test_id = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'student', 'student_name', 'course_id', 'assignment_id', 'topic_id', 'test_id',
            'trainer', 'sub_admin', 'message', 'is_read', 'created_at'
        ]

    def get_student_name(self, obj):
        if obj.student:
            return f"{obj.student.first_name} {obj.student.last_name}"
        return None

    def get_course_id(self, obj):
        try:
            """
            Return course_id for submission/submission_reply, topic status,
            test submission, and test result notifications.
            """
            if not obj.message or not obj.student:
                return None

            msg_lower = obj.message.lower()

            # --- Submission / Submission Reply notifications ---
            if msg_lower.startswith("submission"):
                submission = (
                    Submission.objects.filter(student=obj.student)
                    .select_related("assignment__course")
                    .order_by("-assignment__course__course_id")
                    .first()
                )
                if submission and submission.assignment and submission.assignment.course:
                    return submission.assignment.course.course_id

            # --- Topic status notifications ---
            elif "topic status" in msg_lower:
                sts = (
                    StudentTopicStatus.objects.filter(student=obj.student)
                    .select_related("topic__course")
                    .order_by("-updated_at")
                    .first()
                )
                if sts and sts.topic and sts.topic.course:
                    return sts.topic.course.course_id

            # --- Test submission notifications ---
            elif msg_lower.startswith("test_submission"):
                ans = (
                    StudentAnswers.objects.filter(student_id=obj.student)
                    .select_related("test_id__course_id")
                    .order_by("-submitted_at")
                    .first()
                )
                if ans and ans.test_id and ans.test_id.course_id:
                    return ans.test_id.course_id.course_id  # course_id field

            # --- Test result notifications ---
            elif msg_lower.startswith("test_result"):
                result = (
                    TestResult.objects.filter(student_id=obj.student)
                    .select_related("test_id__course_id")
                    .order_by("-evaluated_at")
                    .first()
                )
                if result and result.test_id and result.test_id.course_id:
                    return result.test_id.course_id.course_id  # course_id field

            return None

        except Exception as e:
            return {'success': False, 'message': str(e)}

    def get_topic_id(self, obj):
        """
        Only return topic_id for topic status notifications.
        """
        if obj.message and obj.student:
            if "topic status" in obj.message.lower():
                sts = (
                    StudentTopicStatus.objects.filter(student=obj.student)
                    .select_related("topic")
                    .order_by("-updated_at")  # most recent status
                    .first()
                )
                if sts and sts.topic:
                    return sts.topic.topic_id
        return None
    
    def get_test_id(self, obj):
        if obj.test:
            return obj.test.test_id
        return None

    def get_assignment_id(self, obj):
        
        if obj.message and obj.student:
            message_lower = obj.message.lower()
            if "submission" in message_lower:
                reply_or_submission = (
                    SubmissionReply.objects
                    .filter(submission__student=obj.student)
                    .select_related("submission__assignment")
                    .order_by("-date")
                    .first()
                )

                if not reply_or_submission:
                    reply_or_submission = (
                        Submission.objects
                        .filter(student=obj.student)
                        .select_related("assignment")
                        .order_by("-date")
                        .first()
                    )

                if reply_or_submission and reply_or_submission.submission and reply_or_submission.submission.assignment:
                    return reply_or_submission.submission.assignment.id  # reply_or_submission.submission.assignment.id

                if isinstance(reply_or_submission, Submission) and reply_or_submission.assignment:
                    return reply_or_submission.assignment.id

        return None

class ChatRoomSerializer(serializers.ModelSerializer):
    student = serializers.CharField(source="student.registration_id")
    trainer = serializers.CharField(source="trainer.employee_id")
    student_name = serializers.SerializerMethodField()
    trainer_name = serializers.SerializerMethodField()
    student_profile_pic = serializers.SerializerMethodField()
    trainer_profile_pic = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = [
            "id",
            "student",
            "student_name",
            "trainer",
            "trainer_name",
            "student_profile_pic",
            "trainer_profile_pic",
            "created_at",
        ]

    def get_student_profile_pic(self, obj):
        if obj.student and obj.student.profile_pic:
            return 'https://aylms.aryuprojects.com/api' + obj.student.profile_pic.url
        return None

    def get_trainer_profile_pic(self, obj):
        if obj.trainer and obj.trainer.profile_pic:
            return 'https://aylms.aryuprojects.com/api' + obj.trainer.profile_pic.url
        return None

    def get_student_name(self, obj):
        if obj.student:
            return f"{obj.student.first_name} {obj.student.last_name}".strip()
        return None

    def get_trainer_name(self, obj):
        if obj.trainer:
            return obj.trainer.full_name if hasattr(obj.trainer, "full_name") else f"{obj.trainer.first_name} {obj.trainer.last_name}".strip()
        return None

class MessageSerializer(serializers.ModelSerializer):
    upload_url = serializers.SerializerMethodField(read_only=True)  # for display
    audio_file_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "room", "sender_type", "sender_id", "content", 'upload', 'upload_url', 'audio_file', 'audio_file_url', "is_read", "is_deleted", "created_at", "updated_at"]

    def get_upload_url(self, obj):
        if obj.upload:
            return 'https://aylms.aryuprojects.com/api' + obj.upload.url
        return None

    def get_audio_file_url(self, obj):
        if obj.audio_file:
            return 'https://aylms.aryuprojects.com/api' + obj.audio_file.url
        return None

class TicketAttachmentSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    class Meta:
        model = TicketAttachment
        fields = ["attachment_id", "file", "created_at"]

    def get_file(self, obj):
        if obj.file and hasattr(obj.file, 'url'):
            return'https://aylms.aryuprojects.com/api' +obj.file.url
        return None



class TicketReplySerializer(serializers.ModelSerializer):
    sender_type = serializers.SerializerMethodField()
    sender_name = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)

    class Meta:
        model = TicketReply
        fields = ["reply_id", "sender_type", "sender_name", "message", "created_at"]

    def get_sender_type(self, obj):
        if obj.student: return "student"
        if obj.trainer: return "admin"
        if obj.super_admin: return "super_admin"
        return "unknown"

    def get_sender_name(self, obj):
        if obj.student: return f"{obj.student.first_name} {obj.student.last_name}"
        if obj.trainer: return obj.trainer.full_name or obj.trainer.username
        if obj.super_admin: return "Super Admin"
        return "Unknown"

class StudentTicketSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()
    updated_by_type = serializers.SerializerMethodField()
    student_id = serializers.IntegerField(source='student.student_id', read_only=True)
    contact_no = serializers.CharField(source='student.contact_no', read_only=True)
    email = serializers.CharField(source='student.email', read_only=True)
    attachments = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    updated_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    replies = serializers.SerializerMethodField()

    class Meta:
        model = StudentTicket
        fields = [
            "ticket_id", "subject", "message", "status", "priority", "student_id",
            "student_name", 'contact_no', "email", "created_at", "updated_at",
            "updated_by_name", "updated_by_type", "attachments", "replies"
        ]
        indexes = [
            models.Index(fields=['updated_at']),
            models.Index(fields=['status']),
        ]

    def get_updated_by_name(self, obj):
        if not obj.updated_by:
            return "System"
        
        # Handle different user types
        if hasattr(obj.updated_by, 'student_id'):  # Student
            return f"{obj.updated_by.first_name} {obj.updated_by.last_name}".strip()
        elif hasattr(obj.updated_by, 'trainer_id'):  # Trainer/Admin
            return getattr(obj.updated_by, 'full_name', obj.updated_by.username)
        elif hasattr(obj.updated_by, 'is_superuser') or getattr(obj.updated_by, 'user_type') == 'super_admin':
            return "Super Admin"
        else:
            return obj.updated_by.get_full_name() or obj.updated_by.username

    def get_updated_by_type(self, obj):
        if not obj.updated_by:
            return "system"
        if hasattr(obj.updated_by, 'student_id'):
            return "student"
        if hasattr(obj.updated_by, 'trainer_id'):
            return "admin"
        if getattr(obj.updated_by, 'user_type') == 'super_admin':
            return "super_admin"
        return "unknown"

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}".strip()
    
    def get_attachments(self, obj):
        # If you're using prefetch_related("attachments") in your view → obj.attachments exists
        attachments = obj.attachments.all() if hasattr(obj, 'attachments') else []
        return TicketAttachmentSerializer(attachments, many=True, read_only=True).data

    def get_replies(self, obj):
        # Now replies are ALWAYS prefetched → this will work
        replies = getattr(obj, 'replies', None)
        if replies is not None:
            return TicketReplySerializer(replies, many=True, context=self.context).data
        
        # Fallback (never needed now)
        return TicketReplySerializer(
            obj.replies.select_related("student", "trainer", "super_admin").order_by("created_at"),
            many=True,
            context=self.context
        ).data

class TicketDetailSerializer(serializers.ModelSerializer):
    replies = TicketReplySerializer(many=True)
    attachments = TicketAttachmentSerializer(many=True)

    class Meta:
        model = StudentTicket
        fields = [
            "ticket_id",
            "subject",
            "message",
            "status",
            "priority",
            "created_at",
            "replies",
            "attachments"
        ]

class UserPresenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPresence
        fields = ["user_type", "user_id", "is_online", "last_seen"]

class UserActivityLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserActivityLog
        fields = '__all__'

class LeadCallLogSerializer(serializers.ModelSerializer):
    called_by_name = serializers.CharField(source='called_by.username', read_only=True)
    notes = serializers.SerializerMethodField()

    class Meta:
        model = LeadCallLog
        fields = ['id', 'lead', 'called_by', 'called_by_name', 'call_time', 'call_status', 'notes']
        read_only_fields = ['call_time', 'called_by_name']

    def get_notes(self, obj):
        from aryuapp.models import Note
        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model='leadcalllog'
        ).order_by('-created_at')
        return [
            {
                "note_id": note.id,
                "reason": note.reason,
                "created_by": note.created_by,
                "status": note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes_qs
        ]

class LeadSerializer(serializers.ModelSerializer):
    call_logs = LeadCallLogSerializer(many=True, read_only=True)
    notes = serializers.SerializerMethodField()
    class Meta:
        model = Lead
        fields = '__all__'
        
    def get_notes(self, obj):
        from aryuapp.models import Note
        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model='lead'
        ).order_by('-created_at')
        return [
            {
                "note_id": note.id,
                "reason": note.reason,
                "created_by": note.created_by,
                "status": note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes_qs
        ]


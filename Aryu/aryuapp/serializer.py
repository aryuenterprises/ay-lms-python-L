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
from django.db import transaction
import jwt
import magic
import holidays
from django.http import QueryDict
import re
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from courses.models import Course
from courses.serializers import CourseSerializer, CourseSimpleSerializer,  StudentTopicStatusSerializer
from batches.models import NewBatch, Batch, BatchCourseTrainer
from batches.serializers import BatchSerializer


class SettingsPicsSerializer(serializers.ModelSerializer):
    general_logo_url = serializers.SerializerMethodField()
    secondary_logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Settings
        fields = ["company_name", "general_logo_url", "secondary_logo_url"]

    def get_general_logo_url(self, obj):
        if obj.general_logo and hasattr(obj.general_logo, "url"):
            return "https://portal.aryuacademy.com/api" + obj.general_logo.url
        return None

    def get_secondary_logo_url(self, obj):
        if obj.secondary_logo and hasattr(obj.secondary_logo, "url"):
            return "https://portal.aryuacademy.com/api" + obj.secondary_logo.url
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
            return 'https://portal.aryuacademy.com/api' + obj.general_logo.url
        return None

    def get_secondary_logo_url(self, obj):
        if obj.secondary_logo and hasattr(obj.secondary_logo, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.secondary_logo.url
        return None

    def get_signature_url(self, obj):
        if obj.signature and hasattr(obj.signature, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.signature.url
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
    
    # Changed required=False so that profile updates without changing the password don't crash.
    # Removed min_length=6 here so our strict validate_password logic handles length (8) exclusively.
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "id", "full_name", "username", 'user_type', "email", "ph_no",
            "password", "is_active", "is_staff", "is_archived", 
            "role", "role_id", "created_at", "created_by"
        ]
        read_only_fields = ["id", "created_at", "created_by"]

    def validate_password(self, value):
        """
        DRF Field-Level Validation Hook. Automatically triggers on create and update
        whenever the 'password' key is present in the payload.
        """
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")

        if not re.search(r'[A-Z]', value):
            raise serializers.ValidationError("Password must contain at least one uppercase letter.")

        if not re.search(r'[a-z]', value):
            raise serializers.ValidationError("Password must contain at least one lowercase letter.")

        if not re.search(r'\d', value):
            raise serializers.ValidationError("Password must contain at least one number.")

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', value):
            raise serializers.ValidationError("Password must contain at least one special character.")

        return value

    def validate(self, attrs):
        """
        Object-level validation. Ensure password is submitted during user creation.
        """
        # If we are creating a new instance, password must be present.
        if not self.instance and 'password' not in attrs:
            raise serializers.ValidationError({"password": "This field is required when creating a user."})
        return attrs

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
                
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()
        return instance


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
            return 'https://portal.aryuacademy.com/api' + obj.resume.url
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
            return 'https://portal.aryuacademy.com/api' + obj.resume.url
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

            # super_admin → users.id
            if role == "super_admin":
                user = User.objects.filter(id=creator_id).first()
                return user.full_name if user else str(created_by)

            # admin → trainer.trainer_id
            if role == "admin":

                trainer = Trainer.objects.filter(trainer_id=creator_id).first()
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
        trainer_qs = Trainer.objects.filter(username__iexact=value, is_archived=False)
        employer_qs = SubAdmin.objects.filter(username__iexact=value, is_archived=False)

        if isinstance(instance, Trainer):
            trainer_qs = trainer_qs.exclude(employee_id=instance.employee_id)
        if isinstance(instance, SubAdmin):
            employer_qs = employer_qs.exclude(employer_id=instance.employer_id)

        if trainer_qs.exists() or employer_qs.exists():
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
            'student_id', 'profile_pic', 'role', 'first_name', 'last_name', 'password', 'registration_id', 'dob',
            'email', 'contact_no', 'gender', 'alternate_mobile_no', 'internship_required', 'current_address', 'permanent_address', 'city', 'state',
            'country','source_type',
            'parent_guardian_name', 'parent_guardian_phone', 'internship','parent_guardian_occupation',
            'reference_number', 'reference_name', 'student_type', 'status', 'notes',
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
        courses = []

        # OLD SYSTEM
        bct_qs = getattr(obj, "batchcoursetrainer_set", None)
        if bct_qs:
            for bct in bct_qs.all():
                course = getattr(bct, "course", None)
                if course and course.status == "Active" and not course.is_archived:
                    courses.append(course)

        # NEW SYSTEM
        nb_qs = getattr(obj, "newbatch_set", None)
        if nb_qs:
            for nb in nb_qs.all():
                course = getattr(nb, "course", None)
                if course and course.status == "Active" and not course.is_archived:
                    courses.append(course)

        unique_courses = {c.course_id: c for c in courses}.values()

        return CourseSerializer(unique_courses, many=True).data
    
    def validate_profile_pic(self, file):
        """
        SECURITY GATEWAY: Deep inspect profile pictures for spoofing, XSS, and massive file sizes.
        """
        if not file:
            return file

        # 1. Size Limit (e.g., 5 MB maximum to prevent Memory/DoS attacks)
        MAX_IMAGE_SIZE = 5 * 1024 * 1024
        if file.size > MAX_IMAGE_SIZE:
            raise serializers.ValidationError("Profile picture size exceeds the 5MB limit.")

        # 2. Strict Extension Allowlist (Block .svg, .gif, .tiff, etc.)
        ext = os.path.splitext(file.name)[1].lower()
        allowed_extensions = {'.jpg', '.jpeg', '.png'}
        
        if ext not in allowed_extensions:
            raise serializers.ValidationError(
                f"Security Alert: Extension '{ext}' is not permitted. Only standard images (JPG, PNG, WEBP) are allowed."
            )

        # 3. Deep Content Inspection (Magic Number Check)
        # Read the binary header to ensure it's truly an image, not a renamed script.
        file_head = file.read(2048)
        file.seek(0)  # CRITICAL: Reset the file pointer so Django/Pillow can process it later

        true_mime_type = magic.from_buffer(file_head, mime=True)
        allowed_mimes = {'image/jpeg', 'image/png'}

        if true_mime_type not in allowed_mimes:
            raise serializers.ValidationError(
                "Security Alert: The file's internal binary format does not match a secure image type (Spoofed file)."
            )

        # 4. Block SVG Explicitly (Prevents Stored XSS attacks via XML)
        if 'svg' in true_mime_type.lower() or 'xml' in true_mime_type.lower():
            raise serializers.ValidationError("Security Alert: SVG images are blocked due to XSS vulnerabilities.")

        return file

    def validate_contact_no(self, value):

        value = value.strip()

        if Student.objects.filter(contact_no=value, is_archived=False).exists():
            raise serializers.ValidationError("Phone number already exists")

        if Trainer.objects.filter(contact_no=value, is_archived=False).exists():
            raise serializers.ValidationError("Phone number already exists")

        return value
    

    def validate_email(self, value):
        ALLOWED_EMAIL_DOMAINS = {
            "gmail.com",
            "yahoo.com",
            "hotmail.com",
            "outlook.com",
            "rediffmail.com",
            "icloud.com",
            "aryutechnologies.com",
            "farida.co.in",
        }
        value = value.lower().strip()
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")

        domain = value.split("@")[-1]
        if domain not in ALLOWED_EMAIL_DOMAINS:
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

    def _get_categories(self, obj):

        categories = {}

        # OLD SYSTEM
        bct_qs = getattr(obj, "batchcoursetrainer_set", None)
        if bct_qs:
            for bct in bct_qs.all():
                course = getattr(bct, "course", None)
                if course and course.course_category:
                    cat = course.course_category
                    categories[cat.category_id] = cat.category_name

        # NEW SYSTEM
        nb_qs = getattr(obj, "newbatch_set", None)
        if nb_qs:
            for nb in nb_qs.all():
                course = getattr(nb, "course", None)
                if course and course.course_category:
                    cat = course.course_category
                    categories[cat.category_id] = cat.category_name

        return categories
    
    def get_category_id(self, obj):
        return list(self._get_categories(obj).keys())

    def get_category_name(self, obj):
        return list(self._get_categories(obj).values())
    
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
        student_role = Role.objects.filter(name__iexact="Student").first()
        if student_role:
            validated_data["role"] = student_role
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
            'student_id','registration_id', 'gender', 'alternate_mobile_no', 'trainer', 'course_id', 'role', 'batch', 'first_name', 'joining_date', 'last_name', 'profile_pic', 'dob',
            'contact_no', 'current_address', 'permanent_address', 'internship_required','city', 'state', 'country',"source_type",
            'parent_guardian_name', 'parent_guardian_phone', 'parent_guardian_occupation', 'internship', 'reference_name', 'reference_number', 
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
        batches = obj.new_batches.filter(is_archived=False, status=True)

        trainers = {batch.trainer for batch in batches}

        result = []
        for trainer in trainers:
            if not trainer:
                continue

            result.append({
                "name": getattr(trainer, "full_name", None),
                "email": getattr(trainer, "email", None),
            })

        return result
    
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
            return 'https://portal.aryuacademy.com/api' + obj.profile_pic.url
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
            'city', 'state', 'reference_name', 'internship_required', 'alternate_mobile_no', 'gender','country', 'parent_guardian_name', 'parent_guardian_phone', 'internship',
            'parent_guardian_occupation', 'student_type', 'dob', 'profile_pic', "source_type",
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
            return 'https://portal.aryuacademy.com/api' + obj.profile_pic.url
        return None
    
    def validate_profile_pic(self, file):
        """
        SECURITY GATEWAY: Deep inspect profile pictures for spoofing, XSS, and massive file sizes.
        """
        if not file:
            return file

        # 1. Size Limit (e.g., 5 MB maximum to prevent Memory/DoS attacks)
        MAX_IMAGE_SIZE = 5 * 1024 * 1024
        if file.size > MAX_IMAGE_SIZE:
            raise serializers.ValidationError("Profile picture size exceeds the 5MB limit.")

        # 2. Strict Extension Allowlist (Block .svg, .gif, .tiff, etc.)
        ext = os.path.splitext(file.name)[1].lower()
        allowed_extensions = {'.jpg', '.jpeg', '.png'}
        
        if ext not in allowed_extensions:
            raise serializers.ValidationError(
                f"Security Alert: Extension '{ext}' is not permitted. Only standard images (JPG, PNG, WEBP) are allowed."
            )

        # 3. Deep Content Inspection (Magic Number Check)
        # Read the binary header to ensure it's truly an image, not a renamed script.
        file_head = file.read(2048)
        file.seek(0)  # CRITICAL: Reset the file pointer so Django/Pillow can process it later

        true_mime_type = magic.from_buffer(file_head, mime=True)
        allowed_mimes = {'image/jpeg', 'image/png'}

        if true_mime_type not in allowed_mimes:
            raise serializers.ValidationError(
                "Security Alert: The file's internal binary format does not match a secure image type (Spoofed file)."
            )

        # 4. Block SVG Explicitly (Prevents Stored XSS attacks via XML)
        if 'svg' in true_mime_type.lower() or 'xml' in true_mime_type.lower():
            raise serializers.ValidationError("Security Alert: SVG images are blocked due to XSS vulnerabilities.")

        return file

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
            return 'https://portal.aryuacademy.com/api' + obj.pdf_file.url
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
    employee_id = serializers.CharField(read_only=True)
    attendance      = serializers.SerializerMethodField()
    role_name       = serializers.CharField(source="role.name", read_only=True)
    batch           = serializers.SerializerMethodField()
    notes           = serializers.SerializerMethodField()
    joining_date = serializers.DateField(
        input_formats=["%Y-%m-%d"],
        required=False,
        allow_null=True
    )
    batch_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    courses = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Course.objects.all(),
        required=False
    )
 
    class Meta:
        model  = Trainer
        read_only_fields = ["employee_id"]
        fields = [
            # ── Identity ──────────────────────────────────────────────────
            "trainer_id", "employee_id", "role", "role_name",
            "username", "password",
            "full_name", "user_type", "tutor_type", 'dob',
 
            # ── Contact / Profile ─────────────────────────────────────────
            "profile_pic", "profile_pic_url",
            "email", "contact_no", "gender",
            "address", "city", "state", "country", "pincode",
 
            # ── Professional ──────────────────────────────────────────────
            "specialization", "working_hours", "experience",
            "last_company", "joining_date",
            "linkedin_profile", "short_bio", "courses", "batch_ids",
 
            # ── Financial ─────────────────────────────────────────────────
            "salary", "salary_type",
            "account_no", "account_holder_name",
            "bank_name", "ifsc_code",
            "upi_id", "gpay_no",
 
            # ── Documents ─────────────────────────────────────────────────
            "aadhar_card", "pan_card", "resume", "certificate", "photo",
 
            # ── Status / Meta ─────────────────────────────────────────────
            "status", "is_archived",
            "created_at", "created_by",
 
            # ── Nested / Computed ─────────────────────────────────────────
            "batch", "attendance", "notes",
        ]
        extra_kwargs = {
            "password": {
                "write_only": True,
                "required":   False,
                "allow_blank": True,
            },
            "full_name": {
                "error_messages": {
                    "max_length": "Full Name cannot exceed 255 characters."
                }
            },
            "username": {
                "error_messages": {
                    "max_length": "Username cannot exceed 255 characters."
                }
            },
            "working_hours": {
                "error_messages": {
                    "max_length": "Working Hours cannot exceed 255 characters."
                }
            },
        }
 
    # ── __init__ ─────────────────────────────────────────────────────────
 
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Password is never required on PATCH / PUT
        if self.instance:
            self.fields["password"].required = False
 
    # ── SerializerMethodFields ────────────────────────────────────────────
 
    def get_profile_pic_url(self, obj):
        if obj.profile_pic and hasattr(obj.profile_pic, "url"):
            return "https://portal.aryuacademy.com/api" + obj.profile_pic.url
        return None
 
    def get_notes(self, obj):
        """
        Uses prefetched_notes when available (zero extra query).
        Falls back to a direct queryset otherwise.
        """
        notes_qs = getattr(obj, "prefetched_notes", None)
        if notes_qs is None:
            notes_qs = obj.notes.order_by("-created_at")
 
        return [
            {
                "note_id":    note.id,
                "reason":     note.reason,
                "created_by": note.created_by,
                "status":     note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes_qs
        ]
 
    def get_attendance(self, obj):
        """
        Uses prefetched_attendance when available (zero extra query).
        """
        qs = getattr(obj, "prefetched_attendance", None)
        if qs is None:
            qs = obj.trainerattendance_set.order_by("-date")
        return TrainerAttendanceSerializer(qs, many=True).data if qs else []
 
    def get_batch(self, obj):
        """
        Uses prefetched_batches when available (zero extra query).
        Students and course are already joined via prefetch in the viewset,
        so iterating over nb.students.all() hits the prefetch cache.
        """
        batches = getattr(obj, "prefetched_batches", None)
        if batches is None:
            # Safe fallback (used outside the optimised viewset)
            batches = (
                NewBatch.objects
                .filter(trainer=obj, is_archived=False)
                .select_related("course")
                .prefetch_related("students")
            )
 
        result = []
        for nb in batches:
            result.append(
                {
                    "batch_id":    nb.batch_id,
                    "batch_name":  nb.title,
                    "title":       nb.title,
                    "course_id":   nb.course.course_id   if nb.course else None,
                    "course_name": nb.course.course_name if nb.course else None,
                    # students already in prefetch cache — no extra query
                    "students": [
                        {
                            "student_id":      s.student_id,
                            "student_name":    f"{s.first_name} {s.last_name}".strip(),
                            "registration_id": s.registration_id,
                        }
                        for s in nb.students.all()
                    ],
                }
            )
        return result
 
    # ── Validation ────────────────────────────────────────────────────────
 
    def run_validation(self, data=serializers.empty):
        try:
            return super().run_validation(data)
        except serializers.ValidationError as exc:
            new_errors = {}
            for field, messages in exc.detail.items():
                new_messages = []
                for msg in messages:
                    if "Ensure this field has no more than" in str(msg):
                        max_len = getattr(self.fields.get(field), "max_length", None)
                        if max_len:
                            new_messages.append(
                                f"Ensure this {field} has no more than {max_len} characters."
                            )
                            continue
                    new_messages.append(str(msg))
                new_errors[field] = new_messages
            raise serializers.ValidationError(new_errors)
 
    def validate_email(self, value):
        value = value.lower()
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")
 
        allowed_domains = {
            "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
            "rediffmail.com", "icloud.com",
            "aryutechnologies.com", "aryuenterprise.com", "aryuacademy.com",
        }
        domain = value.split("@")[-1]
        if domain not in allowed_domains:
            raise serializers.ValidationError(
                "Please enter a valid email domain (e.g., gmail.com, yahoo.com)."
            )
 
        instance = getattr(self, "instance", None)
        if instance and instance.email.lower() == value:
            return value  # unchanged — skip duplicate check
 
        if Trainer.objects.filter(email__iexact=value, is_archived=False).exists():
            raise serializers.ValidationError("Email already exists.")
 
        return value
 
    def validate_full_name(self, value):
        if not re.match(r"^[A-Za-z ]+$", value):
            raise serializers.ValidationError("Name must contain only letters and spaces.")
        return value
 
    # ── Create / Update ───────────────────────────────────────────────────
    def to_internal_value(self, data):

        # Convert QueryDict safely WITHOUT deepcopy
        if isinstance(data, QueryDict):
            mutable_data = {}
            for key in data.keys():
                values = data.getlist(key)

                # strip only strings
                cleaned = [v.strip() if isinstance(v, str) else v for v in values]

                # keep single value or list
                mutable_data[key] = cleaned[0] if len(cleaned) == 1 else cleaned
        else:
            mutable_data = dict(data)

        # ----------- HANDLE courses ----------
        courses = mutable_data.get("courses")
        if courses:
            try:
                mutable_data["courses"] = json.loads(courses)
            except:
                raise serializers.ValidationError({
                    "courses": "Invalid format. Expected [1,2,3]"
                })

        # ----------- HANDLE batch_ids ----------
        batch_ids = mutable_data.get("batch_ids")
        if batch_ids:
            try:
                mutable_data["batch_ids"] = json.loads(batch_ids)
            except:
                raise serializers.ValidationError({
                    "batch_ids": "Invalid format. Expected [1,2,3]"
                })

        return super().to_internal_value(mutable_data)

    def create(self, validated_data):
        batch_ids = validated_data.pop("batch_ids", [])
        courses = validated_data.pop("courses", [])  # extract M2M
        password = validated_data.get("password")
        if not password:
            raise serializers.ValidationError({"password": "Password is required."})

        request = self.context.get("request")

        if request and request.user:
            role = getattr(request.user, "user_type", None)
            role_map = {
                "trainer": ("trainer_id", role),
                "admin": ("trainer_id", role),
                "super_admin": ("user_id", role),
                "student": ("student_id", role),
            }
            id_attr, role_label = role_map.get(role, ("user_id", role))

            validated_data["created_by"] = getattr(request.user, id_attr, None)
            validated_data["created_by_type"] = role_label

        validated_data["password"] = make_password(password)

        trainer = Trainer.objects.create(**validated_data)

        # SET COURSES
        if courses:
            trainer.courses.set(courses)

        # ASSIGN BATCHES
        if batch_ids:
            NewBatch.objects.filter(batch_id__in=batch_ids).update(trainer=trainer)

        return trainer
 
    def update(self, instance, validated_data):
        batch_ids = validated_data.pop("batch_ids", None)
        courses = validated_data.pop("courses", None)

        password = validated_data.pop("password", None)
        if password:
            instance.password = make_password(password)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        # UPDATE COURSES
        if courses is not None:
            instance.courses.set(courses)

        # UPDATE BATCHES
        if batch_ids is not None:
            NewBatch.objects.filter(trainer=instance).update(trainer=None)
            NewBatch.objects.filter(batch_id__in=batch_ids).update(trainer=instance)

        return instance
      

class TrainerTravelExpenseImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = TrainerTravelExpenseImage
        fields = ['image_id', 'image', 'uploaded_at']

    def get_image(self, obj):
        if obj.image and hasattr(obj.image, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.image.url
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
            return 'https://portal.aryuacademy.com/api' + obj.profile_pic.url
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
            return 'https://portal.aryuacademy.com/api' + obj.profile_pic.url
        return None

class TrainerSimpleSerializer(serializers.ModelSerializer):
    profile_pic = serializers.SerializerMethodField()
    class Meta:
        model = Trainer
        fields = ['employee_id', 'full_name',  'profile_pic']
        
    def get_profile_pic(self, obj):
        if obj.profile_pic and hasattr(obj.profile_pic, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.profile_pic.url
        return None

class SubmissionStudentSerializer(serializers.ModelSerializer):
    profile_pic = serializers.SerializerMethodField()
    student_name = serializers.SerializerMethodField()
    class Meta:
        model = Student
        fields = ['registration_id', 'student_name', 'first_name', 'last_name', 'profile_pic']
        
    def get_profile_pic(self, obj):
        if obj.profile_pic and hasattr(obj.profile_pic, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.profile_pic.url
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
            return 'https://portal.aryuacademy.com/api' + obj.file.url
        return None

    def validate_file(self, file):
        """
        SECURITY GATEWAY: Deep inspect uploaded files for malware, spoofing, and dangerous payloads.
        """
        if not file:
            return file

        # 1. Size Limit (e.g., 15 MB max to prevent DoS)
        MAX_UPLOAD_SIZE = 15 * 1024 * 1024
        if file.size > MAX_UPLOAD_SIZE:
            raise serializers.ValidationError("File size exceeds the 15MB limit.")

        # 2. Strict Extension Allowlist
        ext = os.path.splitext(file.name)[1].lower()
        allowed_extensions = {
            # Code
            '.py', '.js', '.ts', '.html', '.css', '.java', '.cpp', '.c', '.cs', '.php', '.rb',
            # Documents / Archives
            '.txt', '.pdf', '.zip', '.rar', '.tar', '.gz'
        }
        
        if ext not in allowed_extensions:
            raise serializers.ValidationError(
                f"File extension '{ext}' is not permitted. Please upload code files or compress your project into a .zip archive."
            )

        # 3. Deep Content Inspection (Magic Number Check)
        # Read the first 2048 bytes to determine the true file type
        file_head = file.read(2048)
        file.seek(0)  # CRITICAL: Reset the file pointer so Django can save it properly later

        true_mime_type = magic.from_buffer(file_head, mime=True)

        # 4. Block Dangerous MIME Types explicitly (Executables, Scripts, XML Forgery)
        blocked_mimes = [
            'application/x-dosexec',      # Windows .exe
            'application/x-executable',   # Linux binaries
            'application/x-sh',           # Shell scripts
            'application/x-msdownload',   # Malicious DLLs/Binaries
            'application/xml',            # XML (Prevents XXE attacks)
            'text/xml',                   # XML
            'image/svg+xml',              # SVG (Can contain malicious JavaScript XSS)
        ]

        if true_mime_type in blocked_mimes:
            raise serializers.ValidationError(
                "Security Alert: Upload blocked. This file type contains potentially executable or malicious content. "
                "If you need to submit XML code, please compress it into a .zip file."
            )

        # 5. Sanity Check: Ensure the true MIME type roughly matches what we expect from coding files
        # Code files usually register as 'text/plain', 'text/x-c', 'text/html', etc.
        valid_mime_prefixes = ('text/', 'application/zip', 'application/x-rar', 'application/pdf', 'application/gzip', 'application/x-tar')
        
        if not true_mime_type.startswith(valid_mime_prefixes):
            raise serializers.ValidationError("Security Alert: The file extension does not match its internal binary contents (Spoofed file).")

        return file
    
    def validate(self, data):
        assignment = data.get('assignment')
        if not assignment:
            raise serializers.ValidationError({"assignment": "Assignment is required."})

        course = getattr(assignment, 'course', None)
        if not course:
            raise serializers.ValidationError({"assignment": "Invalid assignment, course not found."})

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


class TicketAttachmentSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    class Meta:
        model = TicketAttachment
        fields = ["attachment_id", "file", "created_at"]

    def get_file(self, obj):
        if obj.file and hasattr(obj.file, 'url'):
            return'https://portal.aryuacademy.com/api' +obj.file.url
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
    student_id = serializers.SerializerMethodField()
    contact_no = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    updated_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    replies = serializers.SerializerMethodField()

    class Meta:
        model = StudentTicket
        fields = [
            "ticket_id", "name", "phone", "subject", "message", "ticket_type","status", "priority", "student_id",
            "student_name", 'contact_no', "email", "created_at", "updated_at",
            "updated_by_name", "updated_by_type", "attachments", "replies"
        ]
        indexes = [
            models.Index(fields=['updated_at']),
            models.Index(fields=['status']),
        ]

    def get_student_id(self, obj):
        if obj.student:
            return obj.student.student_id
        return None
    
    def get_contact_no(self, obj):
        if obj.student:
            return obj.student.contact_no

        if obj.webinar_participant:
            return obj.webinar_participant.phone

        return None
    
    def get_email(self, obj):
        if obj.student:
            return obj.student.email

        if obj.webinar_participant:
            return obj.webinar_participant.email

        return None
    
    def get_updated_by_name(self, obj):
        if not obj.updated_by:
            return "System"

        if hasattr(obj.updated_by, 'student_id'):
            return f"{obj.updated_by.first_name} {obj.updated_by.last_name}".strip()

        if hasattr(obj.updated_by, 'trainer_id'):
            return getattr(obj.updated_by, 'full_name', obj.updated_by.username)

        if getattr(obj.updated_by, 'user_type', None) == 'super_admin':
            return "Super Admin"

        return getattr(obj.updated_by, 'username', 'Unknown')

    def get_updated_by_type(self, obj):
        if not obj.updated_by:
            return "system"

        if hasattr(obj.updated_by, 'student_id'):
            return "student"

        if hasattr(obj.updated_by, 'trainer_id'):
            return "admin"

        if getattr(obj.updated_by, 'user_type', None) == 'super_admin':
            return "super_admin"

        return "unknown"

    def get_student_name(self, obj):
        if obj.student:
            return f"{obj.student.first_name} {obj.student.last_name}".strip()

        if obj.webinar_participant:
            return obj.webinar_participant.name  # webinar uses name field

        return "Unknown"
    
    def get_attachments(self, obj):
        return TicketAttachmentSerializer(
            obj.attachments.all(),
            many=True,
            context=self.context
        ).data

    def get_replies(self, obj):
        return TicketReplySerializer(
            obj.replies.all(),
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

# COMMON MIXINS

class SafeUserSerializer(serializers.ModelSerializer):

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
        ]

    def get_full_name(self, obj):
        return obj.get_full_name()


# CHILD SERIALIZERS

class LeadCallLogSerializer(serializers.ModelSerializer):

    called_by_data = SafeUserSerializer(
        source="called_by",
        read_only=True
    )

    class Meta:
        model = LeadCallLog
        fields = [
            "id",
            "call_time",
            "duration_seconds",
            "call_status",
            "remarks",
            "recording_url",
            "next_followup_date",
            "called_by",
            "called_by_data",
        ]

        read_only_fields = [
            "id",
            "call_time",
        ]


class LeadDMLogSerializer(serializers.ModelSerializer):

    handled_by_data = SafeUserSerializer(
        source="handled_by",
        read_only=True
    )

    class Meta:
        model = LeadDMLog
        fields = [
            "id",
            "platform",
            "message_direction",
            "message",
            "created_at",
            "handled_by",
            "handled_by_data",
        ]

        read_only_fields = [
            "id",
            "created_at",
        ]


class LeadStatusHistorySerializer(serializers.ModelSerializer):

    changed_by_data = SafeUserSerializer(
        source="changed_by",
        read_only=True
    )

    class Meta:
        model = LeadStatusHistory
        fields = [
            "id",
            "old_status",
            "new_status",
            "remarks",
            "created_at",
            "changed_by",
            "changed_by_data",
        ]

        read_only_fields = [
            "id",
            "created_at",
        ]


class LeadFollowUpSerializer(serializers.ModelSerializer):

    assigned_to_data = SafeUserSerializer(
        source="assigned_to",
        read_only=True
    )

    class Meta:
        model = LeadFollowUp
        fields = [
            "id",
            "followup_date",
            "followup_time",
            "status",
            "completed_at",
            "assigned_to",
            "assigned_to_data",
        ]

        read_only_fields = [
            "id",
            "completed_at",
            "created_at",
        ]


# MAIN LEAD SERIALIZER

class LeadSerializer(serializers.ModelSerializer):

    # USER DETAILS
    # =========================

    followup_by_data = SafeUserSerializer(
        source="followup_by",
        read_only=True
    )

    handled_by_data = SafeUserSerializer(
        source="handled_by",
        read_only=True
    )

    # COUNTS
    # =========================

    total_call_logs = serializers.SerializerMethodField()
    total_dm_logs = serializers.SerializerMethodField()
    total_followups = serializers.SerializerMethodField()

    # DISPLAY HELPERS
    # =========================

    created_by_display = serializers.SerializerMethodField()

    full_address = serializers.SerializerMethodField()

    # NESTED DATA
    # =========================

    recent_call_logs = serializers.SerializerMethodField()
    recent_dm_logs = serializers.SerializerMethodField()

    class Meta:
        model = Lead

        fields = [

            # BASIC
            "id",
            "name",
            "phone",
            "alternate_phone",
            "email",
            "gender",
            "qualification",
            "user_type",

            # ADDRESS
            "address",
            "city",
            "state",
            "country",
            "pincode",
            "full_address",

            # COURSE
            "course",
            "course_interested_in",
            "interested",
            "reason_to_join",
            "reason_not_joining",
            "fee_discussed",
            "expected_join_month",

            # SOURCE
            "source",
            "source_campaign",
            "source_platform",
            "source_type",

            # FOLLOWUP
            "followup_by",
            "followup_by_data",
            "handled_by",
            "handled_by_data",
            "followup_date",
            "next_followup_date",
            "last_contacted_at",

            # TRACKING
            "no_of_dms",
            "no_of_calls",
            "no_of_followups",

            # STATUS
            "status",
            "lead_stage",
            "priority",

            # FLAGS
            "is_archived",
            "is_duplicate",
            "is_converted",

            # SYSTEM
            "joined_at",
            "created_at",
            "updated_at",

            # CREATOR
            "created_by",
            "created_by_type",
            "created_by_display",

            # OPTIMIZED COUNTS
            "total_call_logs",
            "total_dm_logs",
            "total_followups",

            # RECENT ACTIVITY
            "recent_call_logs",
            "recent_dm_logs",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "is_duplicate",
        ]

        extra_kwargs = {
            "phone": {
                "required": True,
            },
            "email": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
            },
            "name": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
            },
        }

    # VALIDATIONS
    # =====================================================

    def validate_phone(self, value):

        value = value.strip()

        cleaned = "".join(filter(str.isdigit, value))

        if len(cleaned) < 10:
            raise serializers.ValidationError(
                "Invalid phone number."
            )

        return cleaned

    def validate_email(self, value):

        if value:
            value = value.lower().strip()

        return value

    def validate(self, attrs):

        request = self.context.get("request")

        created_by = attrs.get("created_by")
        created_by_type = attrs.get("created_by_type")

        # PUBLIC API SECURITY
        # ==========================================

        if request and not request.user.is_authenticated:

            allowed_public_types = [
                "website",
                "landing_page",
                "meta_ads",
                "facebook",
                "instagram",
                "whatsapp",
                "api",
                "webhook",
            ]

            if created_by_type:
                if created_by_type.lower() not in allowed_public_types:
                    raise serializers.ValidationError({
                        "created_by_type": "Invalid public source type."
                    })

        # ADMIN CREATION
        # ==========================================

        if request and request.user.is_authenticated:

            if not created_by:
                attrs["created_by"] = str(request.user.id)

            if not created_by_type:
                if request.user.is_superuser:
                    attrs["created_by_type"] = "super_admin"
                else:
                    attrs["created_by_type"] = "admin"

        return attrs

    # CREATE
    # =====================================================

    @transaction.atomic
    def create(self, validated_data):

        phone = validated_data.get("phone")

        # DUPLICATE CHECK
        # ==========================================

        existing_lead = Lead.objects.filter(
            phone=phone
        ).first()

        if existing_lead:
            existing_lead.is_duplicate = True
            existing_lead.save(update_fields=["is_duplicate"])

        lead = Lead.objects.create(**validated_data)

        # INITIAL STATUS HISTORY
        # ==========================================

        LeadStatusHistory.objects.create(
            lead=lead,
            old_status=None,
            new_status=lead.status,
            remarks="Lead Created"
        )

        return lead

    # UPDATE
    # =====================================================

    @transaction.atomic
    def update(self, instance, validated_data):

        old_status = instance.status

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        # ==========================================
        # STATUS TRACKING
        # ==========================================

        if old_status != instance.status:

            request = self.context.get("request")

            changed_by_user = None

            if request and request.user.is_authenticated:

                changed_by_user = User.objects.filter(
                    id=request.user.user_id
                ).first()

            LeadStatusHistory.objects.create(
                lead=instance,
                old_status=old_status,
                new_status=instance.status,
                changed_by=changed_by_user,
                remarks="Status Updated"
            )

        return instance

    # =====================================================
    # HELPER METHODS
    # =====================================================

    def get_total_call_logs(self, obj):
        return getattr(
            obj,
            "call_logs_count",
            obj.call_logs.count()
        )

    def get_total_dm_logs(self, obj):
        return getattr(
            obj,
            "dm_logs_count",
            obj.dm_logs.count()
        )

    def get_total_followups(self, obj):
        return getattr(
            obj,
            "followups_count",
            obj.followups.count()
        )

    def get_created_by_display(self, obj):

        if obj.created_by_type and obj.created_by:
            return f"{obj.created_by_type} - {obj.created_by}"

        return None

    def get_full_address(self, obj):

        address_parts = [
            obj.address,
            obj.city,
            obj.state,
            obj.country,
            obj.pincode,
        ]

        return ", ".join(
            [part for part in address_parts if part]
        )

    def get_recent_call_logs(self, obj):

        queryset = obj.call_logs.all()[:5]

        return LeadCallLogSerializer(
            queryset,
            many=True
        ).data

    def get_recent_dm_logs(self, obj):

        queryset = obj.dm_logs.all()[:5]

        return LeadDMLogSerializer(
            queryset,
            many=True
        ).data


# LIGHTWEIGHT LIST SERIALIZER

class LeadListSerializer(serializers.ModelSerializer):

    followup_by_data = SafeUserSerializer(
        source="followup_by",
        read_only=True
    )

    handled_by_data = SafeUserSerializer(
        source="handled_by",
        read_only=True
    )

    call_logs = serializers.SerializerMethodField()

    class Meta:
        model = Lead

        fields = [
            "id",
            "name",
            "phone",
            "city",
            "course",
            "source",
            "status",
            "priority",
            "lead_stage",
            "call_logs",
            "followup_date",
            "next_followup_date",
            "created_at",
            "followup_by_data",
            "handled_by_data",
            "no_of_calls",
            "no_of_dms",
        ]

    def get_call_logs(self, obj):

        queryset = obj.call_logs.all()

        return LeadCallLogSerializer(
            queryset,
            many=True
        ).data


# PUBLIC LEAD SERIALIZER

class PublicLeadCreateSerializer(serializers.ModelSerializer):

    """
    Use this serializer for:
    - Website Forms
    - Meta Ads
    - WhatsApp Webhooks
    - Landing Pages
    - Public APIs
    """

    class Meta:
        model = Lead

        fields = [
            "name",
            "phone",
            "email",
            "city",
            "course",
            "source",
            "source_campaign",
            "source_platform",
            "source_type",
            "created_by",
            "created_by_type",
        ]

    def validate_phone(self, value):

        cleaned = "".join(filter(str.isdigit, value))

        if len(cleaned) < 10:
            raise serializers.ValidationError(
                "Invalid phone number."
            )

        return cleaned

    def create(self, validated_data):

        validated_data.setdefault(
            "status",
            "new"
        )

        validated_data.setdefault(
            "created_by_type",
            "public"
        )

        return Lead.objects.create(**validated_data)


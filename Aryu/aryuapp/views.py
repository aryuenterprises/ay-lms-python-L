import requests
from rest_framework.views import APIView
from .models import *
from .serializer import *
from rest_framework.viewsets import ReadOnlyModelViewSet, ViewSet
from rest_framework.exceptions import ValidationError, NotFound, AuthenticationFailed
from functools import reduce
from operator import or_
from .auth import CustomJWTAuthentication
from rest_framework.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.core.mail import EmailMessage
from num2words import num2words
from rest_framework.response import Response
import os, io
import razorpay
from django.views.decorators.csrf import csrf_exempt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated , AllowAny
from django.utils.dateparse import parse_datetime
import stripe
from django.core.validators import EmailValidator
from django.core.files.storage import default_storage
from collections import defaultdict
from datetime import datetime, time, timedelta, date
from rest_framework.decorators import action, api_view, permission_classes
from twilio.twiml.voice_response import VoiceResponse, Dial
from django.db.models.functions import TruncDate, Cast
from django.core.mail import send_mail, BadHeaderError
from django.db import IntegrityError, transaction
import time
from datetime import datetime, timedelta, time
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
import jwt
from django.http import HttpResponse
from django.db import IntegrityError
from django.utils.timezone import localtime
from django.conf import settings
from django.contrib.auth.hashers import *
from django.db.models import Q, Count, F, Max, ExpressionWrapper, Prefetch, DateField, Case, When, IntegerField
import holidays
from .utils import *
from .mixins import *

from live_quiz.models import AdminUser


class SettingsPicsViewSet(viewsets.ModelViewSet):
    login_required = False
    serializer_class = SettingsPicsSerializer
    queryset = Settings.objects.all().only("general_logo", "secondary_logo", "company_name")

    authentication_classes = ()   # ← Disable token auth
    permission_classes = ()       # ← Disable permission check

    def list(self, request, *args, **kwargs):

        settings_obj = Settings.objects.all().first()

        if not settings_obj:
            return Response({
                "success": False,
                "message": "No settings found"
            }, status=200)

        serializer = self.get_serializer(settings_obj)

        return Response({
            "success": True,
            "message": "Settings pics retrieved successfully.",
            "data": serializer.data
        }, status=200)

class SettingsViewSet(viewsets.ModelViewSet):
    queryset = Settings.objects.all()
    serializer_class = SettingsSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        user = self.request.user
        qs = Settings.objects.filter(is_archived=False)

        if user.user_type == "super_admin":
            user_id = getattr(user, "user_id", None)
            if user_id:
                # Admins created by this super admin
                admin_ids = Settings.objects.filter(
                    created_by_type="admin",
                    created_by__in=Settings.objects.filter(
                        created_by=user_id, created_by_type="super_admin"
                    ).values_list("created_by", flat=True)
                ).values_list("created_by", flat=True)

                qs = qs.filter(
                    Q(created_by=user_id, created_by_type="super_admin") |
                    Q(created_by__in=admin_ids, created_by_type="admin")
                )

        elif user.user_type == "admin":
            trainer_id = getattr(user, "trainer_id", None)
            if trainer_id:
                # Get the super admin who created this admin
                admin_obj = Trainer.objects.filter(trainer_id=trainer_id).first()
                super_admin_id = getattr(admin_obj, "created_by", None) if admin_obj else None

                qs = qs.filter(
                    Q(created_by=trainer_id, created_by_type="admin") | 
                    Q(created_by=super_admin_id, created_by_type="super_admin")
                )

        return qs

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        datas = serializer.data

        if datas:
            value = {a: b for a, b in datas[-1].items()}
        else:
            value = {}

        return Response({
            'success': True,
            'message': 'Settings details retrieved successfully.',
            'data': value
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response({
            'success': True,
            'message': 'Settings details created successfully.',
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response({
            'success': True,
            'message': 'Settings details updated successfully.',
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    def is_archived(self, request, pk=None):
        try:
            instance = self.get_object()
            instance.is_archived = True
            instance.save()
            return Response({'message': 'Settings details deleted successfully.'}, status=status.HTTP_200_OK)
        except Settings.DoesNotExist:
            return Response({'message': 'Settings details not found.'}, status=status.HTTP_200_OK)

class CmsViewSet(viewsets.ModelViewSet):
    queryset = CMS.objects.all()
    serializer_class = CMSSerilaizer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]


    def get_queryset(self):
        user = self.request.user
        qs = CMS.objects.filter(is_archived=False)

        if user.user_type == "super_admin":
            # Super admin sees their own CMS and those created by admins under them
            super_admin_id = getattr(user, "user_id", None)  # int
            if super_admin_id:
                # IDs of admins created by this super admin
                admin_ids = CMS.objects.filter(
                    created_by_type="admin",
                    created_by__in=CMS.objects.filter(
                        created_by=super_admin_id, created_by_type="super_admin"
                    ).values_list("created_by", flat=True)
                ).values_list("created_by", flat=True)

                # Filter CMS for super admin and their admins
                qs = qs.filter(
                    Q(created_by=super_admin_id, created_by_type="super_admin") |
                    Q(created_by__in=admin_ids, created_by_type="admin")
                )

        elif user.user_type == "admin":
            # Admin sees only CMS they created
            trainer_id = getattr(user, "trainer_id", None)  # int
            if trainer_id:
                qs = qs.filter(created_by=trainer_id, created_by_type="admin")

        return qs

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup = self.kwargs.get('pk') or self.kwargs.get('link')

        try:
            if lookup is not None:
                if str(lookup).isdigit():
                    obj = queryset.filter(pk=lookup).first()
                else:
                    obj = queryset.filter(link=lookup).first()
                if not obj:
                    raise Exception("CMS object not found")
                self.check_object_permissions(self.request, obj)
                return obj
            else:
                raise Exception("CMS object not found")
        except Exception as e:
            # Always return a JSON response with 200
            return Response({
                "success": False,
                "message": str(e)
            }, status=200)

    def list(self, request, *args, **kwargs):
        try:
            queryset = self.filter_queryset(self.get_queryset())
            serializer = self.get_serializer(queryset, many=True)
            return Response({
                'success': True,
                'message': 'CMS fetched successfully.',
                'data': serializer.data
            }, status=200)
        except Exception as e:
            return Response({'success': False, 'message': str(e)}, status=200)

    def create(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            if serializer.is_valid():
                self.perform_create(serializer)
                return Response({
                    'success': True,
                    'message': 'CMS created successfully.',
                    'data': serializer.data
                }, status=200)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=200)
        except Exception as e:
            return Response({'success': False, 'message': str(e)}, status=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if isinstance(instance, Response):
            return instance  # Return error response
        try:
            partial = kwargs.pop('partial', False)
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            if serializer.is_valid():
                self.perform_update(serializer)
                return Response({
                    'success': True,
                    'message': 'CMS updated successfully.',
                    'data': serializer.data
                }, status=200)
            else:
                return Response({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                }, status=200)
        except Exception as e:
            return Response({'success': False, 'message': str(e)}, status=200)

    def is_archived(self, request, *args, **kwargs):
        instance = self.get_object()
        if isinstance(instance, Response):
            return instance  # Return error response
        try:
            instance.is_archived = True
            instance.save()
            return Response({
                'success': True,
                'message': 'CMS archived successfully.'
            }, status=200)
        except Exception as e:
            return Response({'success': False, 'message': str(e)}, status=200)

def validate_password(value):
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

def verify_recaptcha_v3(token, action="login"):

    url = "https://www.google.com/recaptcha/api/siteverify"
    payload = {
        "secret": settings.RECAPTCHA_PRIVATE_KEY,
        "response": token
    }

    resp = requests.post(url, data=payload)
    result = resp.json()

    # Example Google response:
    # {
    #   "success": true,
    #   "score": 0.9,
    #   "action": "login",
    #   "challenge_ts": "2025-01-01T12:34:56Z",
    #   "hostname": "example.com"
    # }

    if not result.get("success", False):
        return False

    # Optional: Check action matches (recommended)
    if result.get("action") != action:
        return False

    score = result.get("score", 0)
    return score >= settings.RECAPTCHA_REQUIRED_SCORE

class Login(LoggingMixin, APIView):
    permission_classes = [AllowAny] 

    def post(self, request):
        try:
            username_or_email = request.data.get('username', '').rstrip()
            password = request.data.get('password', '').rstrip()

            # recaptcha_token = request.data.get("recaptcha_token")
            # if not recaptcha_token:
            #     return Response(
            #         {"success": False, "message": "reCAPTCHA token missing"},
            #         status=400,
            #     )

            # if not verify_recaptcha_v3(recaptcha_token, action="login"):
            #     return Response(
            #         {"success": False, "message": "reCAPTCHA verification failed"},
            #         status=400,
            #     )

            if not username_or_email or not password:
                return Response({'message': 'Username and password are required'}, status=status.HTTP_200_OK)
            
            if username_or_email != username_or_email.strip() or password != password.strip():
                return Response({'success': False, 'message': 'Invalid username or password'}, status=200)


            user = User.objects.filter(
                Q(username=username_or_email) | Q(email__iexact=username_or_email),
                is_active=True
            ).first()
            
            system_settings  = Settings.objects.first()

            if user and check_password(password, user.password):
                # fetch roles and permissions
                role = getattr(user, "role", None)
                role_permissions = []

                if role:
                    # Prefetch related module permissions
                    role_modules = RoleModulePermission.objects.filter(role=role).select_related("module_permission")
                    for rm in role_modules:
                        role_permissions.append({
                            "module_id": rm.module_permission.module_id,
                            "module_name": rm.module_permission.module,
                            "allowed_actions": rm.allowed_actions
                        })

                payload = {
                    "user_id": user.id,
                    "username": user.username,
                    "name": user.full_name,
                    "user_type": user.user_type,
                    "attendance_type": system_settings.attendance_options if system_settings else None,
                    "role_id": role.role_id if role else None,
                    "role_name": role.name if role else None,
                    "permissions": role_permissions,
                    "exp": int((timezone.now() + timedelta(minutes=30)).timestamp()),
                }
                token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

                return Response({
                    "success": True,
                    "message": "Login successful",
                    "token": token,
                    "user": {
                        "user_id": user.id,
                        "username": user.username,
                        "name": user.full_name,
                        "user_type": user.user_type,
                        "attendance_type": system_settings .attendance_options if system_settings  else None,
                        "role_id": role.role_id if role else None,
                        "role_name": role.name if role else None,
                        "permissions": role_permissions,
                    },
                    "exp": int((timezone.now() + timedelta(minutes=30)).timestamp()),
                }, status=200)

            # For Student login
            student = Student.objects.filter(
                Q(username=username_or_email) | Q(email__iexact=username_or_email),
                is_archived=False
            ).first()

            if student:
                if student.status == False:
                    return Response({'success': False, 'message': 'Your account is inactive. Please contact admin.'}, status=200)

            if student and check_password(password, student.password):
                payload = {
                    'registration_id': student.registration_id,
                    'student_id': student.student_id,
                    'username': student.username,
                    "name": student.first_name,
                    'user_type': 'student',
                    "attendance_type": system_settings .attendance_options if system_settings  else None,
                    'student_type': student.student_type,
                    "exp": int((timezone.now() + timedelta(minutes=30)).timestamp()),
                }
                token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
                return Response({
                    'success': True,
                    'message': 'Login successful',
                    'token': token,
                    'user': {
                        'registration_id': student.registration_id,
                        'student_id': student.student_id,
                        'username': student.username,
                        "name": student.first_name,
                        'user_type': 'student',
                        "attendance_type": system_settings .attendance_options if system_settings  else None,
                        'student_type': student.student_type,
                    },
                    "exp": int((timezone.now() + timedelta(minutes=30)).timestamp()),
                }, status=200)

            # For Trainer/Admin login
            trainer = Trainer.objects.filter(
                Q(username=username_or_email) | Q(email__iexact=username_or_email),
                is_archived=False
            ).first()
            
            if username_or_email != username_or_email.strip() or password != password.strip():
                return Response({'success': False, 'message': 'Invalid username or password'}, status=200)

            if trainer:
                if trainer.status and trainer.status.lower() == "inactive":
                    return Response({'success': False, 'message': 'Your account is inactive. Please contact admin.'}, status=200)
            
            if trainer:
                if check_password(password, trainer.password):
                    
                    # Fetch roles and permissions
                    role = getattr(trainer, "role", None)
                    role_permissions = []

                    if role:
                        # Prefetch related module permissions
                        role_modules = RoleModulePermission.objects.filter(role=role).select_related("module_permission")
                        for rm in role_modules:
                            role_permissions.append({
                                "module_id": rm.module_permission.module_id,
                                "module_name": rm.module_permission.module,
                                "allowed_actions": rm.allowed_actions
                            })
                            
                    # Prepare token
                    payload = {
                        'employee_id': trainer.employee_id,
                        'username': trainer.username,
                        'trainer_id': trainer.trainer_id,
                        'name': trainer.full_name,
                        "attendance_type": system_settings .attendance_options if system_settings  else None,
                        'role_id': role.role_id if role else None,
                        'role_name': role.name if role else None,
                        'permissions': role_permissions,
                        'user_type': trainer.user_type,
                        "exp": int((timezone.now() + timedelta(minutes=30)).timestamp()),
                    }
                    token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

                    

                    return Response({
                        'success': True,
                        'message': 'Login successful',
                        'token': token,
                        'user': {
                            'employee_id': trainer.employee_id,
                            'trainer_id': trainer.trainer_id,
                            'username': trainer.username,
                            'name': trainer.full_name,
                            'user_type': trainer.user_type,
                            "attendance_type": system_settings .attendance_options if system_settings  else None,
                            'role_id': role.role_id if role else None,
                            'role_name': role.name if role else None,
                            'permissions': role_permissions
                        },
                        "exp": int((timezone.now() + timedelta(minutes=30)).timestamp()),
                    }, status=200)

            #for employer login
            employer = SubAdmin.objects.filter(
                Q(username=username_or_email) | Q(email__iexact=username_or_email),
                is_archived=False
            ).first()
            
            if username_or_email != username_or_email.strip() or password != password.strip():
                return Response({'success': False, 'message': 'Invalid username or password'}, status=200)
            
            if employer:
                if employer.status == False:
                    return Response({'success': False, 'message': 'Your account is inactive. Please contact admin.'}, status=200)
                

            if employer:
                if check_password(password, employer.password):
                    payload = {
                        'employer_id': employer.employer_id,
                        'name': employer.full_name,
                        'company_name': employer.company.company_name,
                        'company_id': employer.company.company_id,
                        'username': employer.username,
                        'user_type': 'employer',
                        "exp": int((timezone.now() + timedelta(minutes=30)).timestamp()),
                    }
                    token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
                    return Response({
                        'success': True,
                        'message': 'Login successful',
                        'token': token,
                        'user': {
                            'employer_id': employer.employer_id,
                            'name': employer.full_name,
                            'company_name': employer.company.company_name,
                            'company_id': employer.company.company_id,
                            'username': employer.username,
                            'user_type': 'employer',
                            "exp": int((timezone.now() + timedelta(minutes=30)).timestamp()),
                        }
                    }, status=200)
                    
            return Response({'success': False, 'message': 'Invalid username or password'}, status=200)
        except Exception as e:
            return Response({'success': False, 'message': str(e)}, status=200)

    def get(self, request):
        return Response({'message': 'Send POST request to login.'})

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().select_related("role")
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = "id"

    def get_queryset(self):
        qs = super().get_queryset().filter(is_archived=False)  # exclude archived users
        role_id = self.request.query_params.get("role_id")
        if role_id:
            qs = qs.filter(role_id=role_id)
        return qs

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {"success": True, "message": "Users fetched successfully", "data": serializer.data},
            status=status.HTTP_200_OK
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"success": True, "message": "User created successfully", "data": serializer.data},
                status=status.HTTP_200_OK
            )
        # Direct field errors instead of generic message
        first_field, first_error = list(serializer.errors.items())[0]
        return Response(
            {"success": False, "message": f"{first_field} {first_error[0]}"},
            status=status.HTTP_200_OK
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", True)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                "success": True,
                "message": "User updated successfully",
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_archived = True
        instance.save()
        return Response(
            {"success": True, "message": "User archived successfully"},
            status=status.HTTP_200_OK
        )
    
class RoleModulePermissionViewSet(viewsets.ViewSet):
    queryset = RoleModulePermission.objects.select_related("role", "module_permission")
    serializer_class = RoleModulePermissionSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = "id"
    """
    Manage role-module permissions
    """

    def get_queryset(self):
        """Return queryset, optionally filtered by role_id"""
        try:
            qs = RoleModulePermission.objects.select_related("role", "module_permission")
            role_id = self.request.query_params.get("role_id")
            if role_id:
                qs = qs.filter(role_id=role_id)
            return qs
        except Exception:
            # Return empty queryset on error
            return RoleModulePermission.objects.none()

    def list(self, request):
        try:
            qs = self.get_queryset()
            serializer = RoleModulePermissionSerializer(qs, many=True)
            data = serializer.data

            # Rename allowed_actions -> actions in the response
            for item in data:
                item['actions'] = item.pop('allowed_actions', [])

            return Response({
                "success": True,
                "message": "Role permissions retrieved successfully",
                "data": data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)


    def create(self, request):
        """
        Assign module permissions to a role
        Payload example:
        {
            "role_id": 2,
            "module_permissions": [
                { "module_id": 1, "allowed_actions": ["read"] },
                { "module_id": 2, "allowed_actions": ["read","update"] }
            ]
        }
        """
        try:
            role_id = request.data.get("role_id")
            module_permissions = request.data.get("module_permissions", [])

            if not role_id or not module_permissions:
                return Response({"success": False, "message": "role_id and module_permissions are required"}, status=status.HTTP_200_OK)

            try:
                role = Role.objects.get(role_id=role_id)
            except Role.DoesNotExist:
                return Response({"success": False, "message": "Invalid role_id"}, status=status.HTTP_200_OK)

            created_permissions = []

            with transaction.atomic():
                for mp in module_permissions:
                    module_id = mp.get("module_id")
                    allowed_actions = mp.get("allowed_actions", [])

                    if not module_id or not allowed_actions:
                        continue

                    try:
                        module_perm = ModulePermission.objects.get(module_id=module_id)
                    except ModulePermission.DoesNotExist:
                        continue

                    role_module_perm, _ = RoleModulePermission.objects.update_or_create(
                        role=role,
                        module_permission=module_perm,
                        defaults={"allowed_actions": allowed_actions}
                    )
                    created_permissions.append(role_module_perm)

            serializer = RoleModulePermissionSerializer(created_permissions, many=True)
            return Response({"success": True, "message": "Role permissions created successfully", "data": serializer.data}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

    def update(self, request, pk=None):
        """
        Bulk update allowed_actions for a role.
        Payload example:
        {
            "role_id": 2,
            "module_permissions": [
                {"module_id": 1, "allowed_actions": ["read"]},
                {"module_id": 2, "allowed_actions": ["create","read"]}
            ]
        }

        If "module_permissions" is empty or missing, all module permissions for the role will be cleared.
        """
        try:
            role_id = request.data.get("role_id")
            module_permissions = request.data.get("module_permissions", [])

            if not role_id:
                return Response({"success": False, "message": "role_id is required"}, status=status.HTTP_200_OK)

            try:
                role = Role.objects.get(role_id=role_id)
            except Role.DoesNotExist:
                return Response({"success": False, "message": "Invalid role_id"}, status=status.HTTP_200_OK)

            existing_perms = RoleModulePermission.objects.filter(role=role)
            existing_module_ids = set(existing_perms.values_list("module_permission__module_id", flat=True))
            payload_module_ids = set(mp.get("module_id") for mp in module_permissions if mp.get("module_id"))

            with transaction.atomic():
                # 1. Update or create modules in the payload
                updated_perms = []
                for mp in module_permissions:
                    module_id = mp.get("module_id")
                    allowed_actions = mp.get("allowed_actions", [])

                    if not module_id:
                        continue

                    try:
                        module_perm = ModulePermission.objects.get(module_id=module_id)
                    except ModulePermission.DoesNotExist:
                        continue

                    role_module_perm, _ = RoleModulePermission.objects.update_or_create(
                        role=role,
                        module_permission=module_perm,
                        defaults={"allowed_actions": allowed_actions}
                    )
                    updated_perms.append(role_module_perm)

                # 2. Remove any existing modules not in the payload (clear)
                to_delete_ids = existing_module_ids - payload_module_ids
                if to_delete_ids:
                    RoleModulePermission.objects.filter(role=role, module_permission__module_id__in=to_delete_ids).delete()

            serializer = RoleModulePermissionSerializer(updated_perms, many=True)
            return Response({
                "success": True,
                "message": "Role module permissions updated successfully",
                "data": serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)
        
    def retrieve(self, request, pk=None):
        """Retrieve single role-module permission"""
        try:
            role_module_perm = RoleModulePermission.objects.select_related("role", "module_permission").get(pk=pk)
            serializer = RoleModulePermissionSerializer(role_module_perm)
            return Response({"success": True, "data": serializer.data})
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)
        
class RoleViewSet(viewsets.ViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = "role_id"

    def get_queryset(self):
        try:
            user = self.request.user
            user_type = getattr(user, "user_type", "").lower()
            admin_trainer_id = getattr(user, "trainer_id", None)
            user_created_id = getattr(user, "user_id", None) if user_type == "super_admin" else admin_trainer_id

            # Super admin: get admin IDs created by this super admin
            admin_ids = []
            if user_type == "super_admin" and user_created_id:
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_created_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

            # Base queryset
            qs = Role.objects.filter(is_archived=False).order_by("role_id")

            # Apply filtering
            if user_type == "admin" and admin_trainer_id:
                qs = qs.filter(created_by=admin_trainer_id)
            elif user_type == "super_admin":
                qs = qs.filter(
                    Q(created_by=user_created_id, created_by_type="super_admin") |
                    Q(created_by__in=admin_ids, created_by_type="admin")
                )

            # Optional: filter by role_id if passed as query param
            role_id = self.request.query_params.get("role_id")
            if role_id:
                qs = qs.filter(role_id=role_id)

            return qs
        except Exception:
            return Role.objects.none()

    def list(self, request):
        """List all roles with module permissions"""
        try:
            qs = self.get_queryset()
            data = []
            for role in qs:
                role_perms = RoleModulePermission.objects.filter(role=role).select_related("module_permission")
                perms_serializer = RoleModulePermissionSerializer(role_perms, many=True)
                data.append({
                    "role_id": role.role_id,
                    "name": role.name,
                    "module_permissions": perms_serializer.data,
                    'is_archived': role.is_archived
                })
            return Response({"success": True, "message": "Roles retrieved successfully", "data": data}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data,
            context={'request': request}  # pass request here
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({
            "success": True,
            "message": "Role created successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    def update(self, request, pk=None):
        """Update role name"""
        try:
            role = Role.objects.get(role_id=pk)
            name = request.data.get("name")
            if not name:
                return Response({"success": False, "message": "Role name is required"}, status=status.HTTP_200_OK)

            role.name = name
            role.save()
            return Response({"success": True, "message": "Role updated successfully", "data": {"role_id": role.role_id, "name": role.name}}, status=status.HTTP_200_OK)
        except Role.DoesNotExist:
            return Response({"success": False, "message": "Role not found"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)
    
    def retrieve(self, request, pk=None):
        """Retrieve single role with permissions"""
        try:
            role = Role.objects.get(pk=pk)
            role_perms = RoleModulePermission.objects.filter(role=role).select_related("module_permission")
            perms_serializer = RoleModulePermissionSerializer(role_perms, many=True)
            data = {
                "role_id": role.role_id,
                "name": role.name,
                "module_permissions": perms_serializer.data
            }
            module = ModulePermission.objects.filter(is_archived=False).order_by("module_id")
            module_serializer = ModulePermissionSerializer(module, many=True)
            return Response({"success": True, "data": data, "modules": module_serializer.data})
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)
        
    def is_archived(self, request, pk=None):
        try:
            role = Role.objects.get(role_id=pk)
            role.is_archived = True
            role.save()
            return Response({"success": True, "message": "Role deleted successfully"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

class ModulePermissionViewSet(viewsets.ViewSet):
    query_set = ModulePermission.objects.all()
    serializer_class = ModulePermissionSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = "module_id"
    """
    Manage modules and their actions
    """

    def get_queryset(self):
        try:
            return ModulePermission.objects.filter(is_archived=False).order_by("module_id")
        except Exception:
            return ModulePermission.objects.none()

    def list(self, request):
        """List all modules with actions"""
        try:
            qs = self.get_queryset()
            serializer = ModulePermissionSerializer(qs, many=True)
            return Response({"success": True, "message": "Module permissions retrieved successfully", "data": serializer.data}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

    def create(self, request):
        """
        Create a module permission
        Payload example:
        {
            "module": "Student",
            "actions": ["create","read","update","delete"]
        }
        """
        try:
            module_name = request.data.get("module")
            actions = request.data.get("actions", [])

            if not module_name or not actions:
                return Response({"success": False, "message": "module and actions are required"}, status=status.HTTP_200_OK)

            module, created = ModulePermission.objects.get_or_create(module=module_name)
            module.actions = actions
            module.save()

            serializer = ModulePermissionSerializer(module)
            return Response({"success": True, "message": "Module permission created successfully", "data": serializer.data}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

    def update(self, request, pk=None):
        
        if not pk:
            return Response(
                {"success": False, "message": "Module ID (pk) is required"},
                status=status.HTTP_200_OK
            )

        try:
            module = ModulePermission.objects.get(module_id=pk)
        except ModulePermission.DoesNotExist:
            return Response(
                {"success": False, "message": "Module not found"},
                status=status.HTTP_200_OK
            )

        # Use partial=True so only provided fields are updated
        serializer = ModulePermissionSerializer(module, data=request.data, partial=True, context={"request": request})
        
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"success": True, "message": "Module permission updated successfully", "data": serializer.data},
                status=status.HTTP_200_OK
            )

        # Return first field error
        first_field, first_error = list(serializer.errors.items())[0]
        return Response(
            {"success": False, "message": f"{first_field} {first_error[0]}"},
            status=status.HTTP_200_OK
        )
        
    def retrieve(self, request, pk=None):
        """Retrieve single module permission by id"""
        try:
            module = ModulePermission.objects.get(module_id=pk)
            serializer = ModulePermissionSerializer(module)
            return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)
        except ModulePermission.DoesNotExist:
            return Response({"success": False, "message": "Module not found"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)
    
    def is_archived(self, request, pk=None):
        try:
            modules = ModulePermission.objects.get(module_id=pk)
            modules.is_archived = True
            modules.save()
            return Response({"success": True, "message": "Module deleted successfully"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

class UserDashboardView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    
    def _get_creator_id(self, payload):
        """
        super_admin → payload['user_id']
        admin → payload['trainer_id']
        """
        if payload.get("user_type") == "super_admin":
            return str(payload.get("user_id"))
        return str(payload.get("trainer_id"))

    def _get_allowed_creator_ids(self, payload):

        user_type = payload.get("user_type")
        creator = self._get_creator_id(payload)
        allowed = {creator}

        if user_type == "super_admin":
            # find all admins created by this super admin
            admin_ids = Trainer.objects.filter(
                created_by=creator,
                created_by_type="super_admin",
                is_archived=False
            ).values_list("trainer_id", flat=True)

            allowed.update([str(x) for x in admin_ids])

        elif user_type == "admin":
            # find parent super admin
            admin_obj = Trainer.objects.filter(trainer_id=int(creator)).first()
            if admin_obj and admin_obj.created_by:
                allowed.add(str(admin_obj.created_by))

        return list(allowed)

    def get(self, request):
        token = self._get_token_from_header(request)
        if not token:
            return Response({"success": False, "message": "Authorization token missing."}, status=200)

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return Response({"success": False, "message": "Token expired."}, status=200)
        except jwt.InvalidTokenError:
            return Response({"success": False, "message": "Invalid token."}, status=200)

        user_type = payload.get("user_type")
        if not user_type:
            return Response({"success": False, "message": "User type missing in token."}, status=200)

        try:
            if user_type == "student":
                return self._get_student_dashboard(payload)
            elif user_type == "tutor":
                return self._get_trainer_dashboard(payload)
            elif user_type == "admin":
                return self._get_admin_dashboard(payload)
            elif user_type == "employer":
                return self._get_employer_dashboard(payload)
            elif user_type == "super_admin":
                return self._get_super_admin_dashboard(payload)
            else:
                return Response({"success": False, "message": "Unknown user type."}, status=200)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    def _get_token_from_header(self, request):
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header.split(" ")[1]
        return None

    def _get_student_dashboard(self, payload):
        student_id = payload.get("student_id")
        if not student_id:
            return Response({"success": False, "message": "Student ID missing."}, status=200)

        try:
            student = Student.objects.get(student_id=student_id)

            # --- OLD SYSTEM ---
            upcoming_old_batches = Batch.objects.filter(
                batchcoursetrainer__student=student,
                scheduled_date__gte=date.today(),
                is_archived=False,
                status=True
            ).distinct().values('batch_name', 'scheduled_date', 'end_date', 'title')

            # --- NEW SYSTEM ---
            upcoming_new_batches = NewBatch.objects.filter(
                students=student,
                start_date__gte=date.today(),
                is_archived=False,
                status=True
            ).values('title', 'start_date')

            batch_data = []

            # OLD batches formatting
            for batch in upcoming_old_batches:
                formatted_date = batch['scheduled_date'].strftime('%Y-%m-%d') if batch['scheduled_date'] else None
                batch_data.append({
                    'batch_name': batch['batch_name'],
                    'title': batch['title'],
                    'scheduled_date': formatted_date,
                    'end_date': batch['end_date'],
                })

            # NEW batches formatting
            for nb in upcoming_new_batches:
                formatted_date = nb['start_date'].strftime('%Y-%m-%d') if nb['start_date'] else None
                batch_data.append({
                    'batch_name': nb['title'],      # NewBatch has no batch_name
                    'title': nb['title'],
                    'scheduled_date': formatted_date,
                    'end_date': None
                })

            # OLD system course ids
            assigned_course_ids_old = BatchCourseTrainer.objects.filter(
                student=student
            ).values_list('course_id', flat=True)

            # NEW system course ids
            assigned_course_ids_new = NewBatch.objects.filter(
                students=student,
                is_archived=False,
                status=True
            ).values_list('course_id', flat=True)

            assigned_course_ids = list(set(list(assigned_course_ids_old) + list(assigned_course_ids_new)))

            assigned_mappings_old = BatchCourseTrainer.objects.filter(student=student)

            assigned_trainer_ids_old = assigned_mappings_old.values_list('trainer_id', flat=True)
            assigned_batch_ids_old = assigned_mappings_old.values_list('batch_id', flat=True)

            # NEW SYSTEM
            assigned_new_batches = NewBatch.objects.filter(
                students=student,
                is_archived=False,
                status=True
            )

            assigned_trainer_ids_new = assigned_new_batches.values_list('trainer_id', flat=True)
            assigned_batch_ids_new = assigned_new_batches.values_list('batch_id', flat=True)

            assigned_trainer_ids = list(set(list(assigned_trainer_ids_old) + list(assigned_trainer_ids_new)))
            assigned_batch_ids = list(set(list(assigned_batch_ids_old) + list(assigned_batch_ids_new)))

            schedule_qs = ClassSchedule.objects.filter(
                is_archived=False
            ).filter(
                Q(batch_id__in=assigned_batch_ids) |
                Q(new_batch_id__in=assigned_batch_ids)
            ).filter(
                course_id__in=assigned_course_ids,
                trainer_id__in=assigned_trainer_ids
            ).order_by('-scheduled_date', '-start_time')

            all_schedules = []
            current_time = timezone.now()

            for sched in schedule_qs:
                start_time = getattr(sched, 'start_time', None) or time(9, 0)

                class_start_dt = timezone.make_aware(
                    datetime.combine(sched.scheduled_date, start_time),
                    timezone.get_current_timezone()
                )

                # Determine end datetime
                if sched.duration:
                    class_end_dt = class_start_dt + sched.duration
                elif sched.end_time:
                    class_end_dt = timezone.make_aware(
                        datetime.combine(sched.scheduled_date, sched.end_time),
                        timezone.get_current_timezone()
                    )
                else:
                    class_end_dt = class_start_dt + timedelta(hours=1)

                buffer = timedelta(minutes=5)
                window_start = class_start_dt - buffer
                window_end = class_end_dt + buffer

                attended = Attendance.objects.filter(
                    student=student,
                    date__gte=window_start,
                    date__lte=window_end
                ).filter(
                    Q(status__icontains="Login") |
                    Q(status__icontains="Logout") |
                    Q(status__icontains="Present")
                ).exists()

                # Status calculation
                if sched.is_class_cancelled:
                    att_status = 'cancelled'
                elif current_time < class_start_dt:
                    att_status = "upcoming"
                elif class_start_dt <= current_time <= class_end_dt:
                    att_status = "ongoing"
                elif attended:
                    att_status = "completed"
                else:
                    att_status = "missed"

                batch_obj = sched.batch if sched.batch else getattr(sched, "new_batch", None)
                # batch_name fallback
                if hasattr(batch_obj, "batch_name") and batch_obj.batch_name:
                    batch_name = batch_obj.batch_name
                elif hasattr(batch_obj, "title"):
                    batch_name = batch_obj.title
                else:
                    batch_name = None

                all_schedules.append({
                    "schedule_id": sched.schedule_id,
                    "course_id": getattr(sched.course, "course_id", None),
                    "course_name": getattr(sched.course, "course_name", None),
                    "batch_id": getattr(batch_obj, "batch_id", None),
                    "batch_name": batch_name,
                    "title": getattr(batch_obj, "title", None),
                    "trainer_id": sched.trainer.employee_id if sched.trainer else None,
                    "trainer_name": sched.trainer.full_name if sched.trainer else None,
                    "scheduled_date": sched.scheduled_date,
                    "is_online": sched.is_online_class,
                    'is_class_cancelled': sched.is_class_cancelled,
                    "attendance_status": attended,
                    "class_link": sched.class_link,
                    "start_time": start_time.strftime("%I:%M %p"),
                    "end_time": class_end_dt.strftime("%I:%M %p"),
                    "attended": attended,
                    "status": att_status,
                })

            next_two_schedules = schedule_qs.filter(
                scheduled_date__gte=date.today()
            ).order_by('scheduled_date', 'start_time')[:2]

            upcoming_schedules = []

            for sched in next_two_schedules:
                start_time = getattr(sched, 'start_time', time(9, 0))
                class_start_dt = datetime.combine(sched.scheduled_date, start_time)
                duration_td = sched.duration or timedelta(hours=1)
                now = datetime.now()

                # Class status
                if sched.is_class_cancelled:
                    sch_status = 'cancelled'
                elif class_start_dt > now:
                    sch_status = 'upcoming'
                elif class_start_dt <= now <= class_start_dt + duration_td:
                    sch_status = 'ongoing'
                else:
                    sch_status = 'completed'

                # Duration string
                hours, remainder = divmod(int(duration_td.total_seconds()), 3600)
                minutes = remainder // 60
                duration_str = (
                    f"{hours} hour{'s' if hours != 1 else ''}"
                    + (f" {minutes} minutes" if minutes else "")
                )

                batch_obj = sched.batch if sched.batch else getattr(sched, "new_batch", None)

                if batch_obj:
                    batch_name = (
                        getattr(batch_obj, "batch_name", None)
                        or getattr(batch_obj, "title", None)
                    )
                    title = getattr(batch_obj, "title", None)
                else:
                    batch_name = None
                    title = None

                # Final append
                upcoming_schedules.append({
                    'course_name': sched.course.course_name,
                    'batch_name': batch_name,
                    'title': title,
                    'trainer_name': sched.trainer.full_name,
                    'start_time': sched.start_time.strftime('%I:%M %p'),
                    'scheduled_date': sched.scheduled_date.strftime('%Y-%m-%d'),
                    'class_link': sched.class_link,
                    'is_online': sched.is_online_class,
                    'is_class_cancelled': sched.is_class_cancelled,
                    'duration': duration_str,
                    'status': sch_status,
                })

            # featured courses
            featured_courses = Course.objects.filter(is_featured=True)[:5]
            course_data = CourseSerializer(featured_courses, many=True).data

            now = timezone.localtime()

            past_or_ongoing_qs = ClassSchedule.objects.filter(
                batch__batchcoursetrainer__student=student,
                is_archived=False
            ).filter(
                Q(scheduled_date__lt=date.today()) |
                Q(scheduled_date=date.today(), start_time__lte=now.time())
            ).order_by('scheduled_date', 'start_time')

            total_classes = 0
            attended_classes = 0
            absent_classes = 0
            cancelled_classes = 0

            for sched in past_or_ongoing_qs:
                start_time = getattr(sched, 'start_time', time(9,0))
                end_time = getattr(sched, 'end_time', None) or (start_time + timedelta(hours=1))

                class_start_dt = timezone.make_aware(datetime.combine(sched.scheduled_date, start_time))
                class_end_dt = timezone.make_aware(datetime.combine(sched.scheduled_date, end_time))

                buffer = timedelta(minutes=5)
                window_start = class_start_dt - buffer
                window_end = class_end_dt + buffer

                attended = Attendance.objects.filter(
                    student=student,
                    date__gte=window_start,
                    date__lte=window_end
                ).filter(
                    Q(status__icontains="Login") |
                    Q(status__icontains="Logout") |
                    Q(status__icontains="Present")
                ).exists()

                total_classes += 1
                if sched.is_class_cancelled:
                    cancelled_classes += 1
                elif attended:
                    attended_classes += 1
                else:
                    absent_classes += 1

            attendance_percentage = (attended_classes / total_classes * 100) if total_classes > 0 else 0

            # Course, Assignment, Topic, Announcement logic unchanged …
            assigned_courses = Course.objects.filter(
                new_batches__students=student,
                is_archived=False
            ).distinct()

            all_assignments = Assignment.objects.filter(
                course__in=assigned_courses,
                is_archived=False
            )
            total_assignments = all_assignments.count()

            submitted_assignment_ids = Submission.objects.filter(
                student=student,
                assignment__in=all_assignments
            ).values_list('assignment_id', flat=True).distinct()

            done_assignments = len(submitted_assignment_ids)
            pending_assignments = max(0, total_assignments - done_assignments)

            topics = Topic.objects.filter(
                course__in=assigned_courses,
                is_archived=False
            )
            total_topics = topics.count()

            completed_topic_ids = StudentTopicStatus.objects.filter(
                student=student,
                topic__in=topics,
                status=True
            ).values_list('topic_id', flat=True).distinct()

            completed_topics = len(completed_topic_ids)
            progress_percent = (completed_topics / total_topics * 100) if total_topics > 0 else 0

            student_admin_id = str(student.created_by).strip() if student.created_by else None
            admin = Trainer.objects.filter(trainer_id=student_admin_id).first()
            super_admin_id = str(admin.created_by).strip() if admin and admin.created_by else None

            filters = Q(audience__in=["all", "students"], is_archived=False)
            if student_admin_id and super_admin_id:
                filters &= Q(created_by__in=[student_admin_id, super_admin_id])
            elif student_admin_id:
                filters &= Q(created_by=student_admin_id)
            elif super_admin_id:
                filters &= Q(created_by=super_admin_id)

            announcements = Announcement.objects.filter(filters).order_by("-created_at")[:5]
            announcement_data = AnnouncementSerializer(announcements, many=True).data

            notifications = Notification.objects.filter(
                student=student,
                is_read=False
            ).count()

            chat_rooms = ChatRoom.objects.filter(student=student)
            unread_messages_count = Message.objects.filter(
                room__in=chat_rooms,
                is_read=False,
                is_deleted=False,
                sender_type="trainer"
            ).count()

            return Response({
                "success": True,
                "user_type": "student",
                "student_name": f"{student.first_name} {student.last_name}",
                "upcoming_batches": batch_data,
                "attendance": {
                    "total": total_classes,
                    "present": attended_classes,
                    "absent": absent_classes,
                    "cancelled_classes": cancelled_classes,
                    "percentage": round(attendance_percentage, 2)
                },
                "schedule": all_schedules,
                "upcoming_schedules": upcoming_schedules,
                "assignments": {
                    "total": total_assignments,
                    "done": done_assignments,
                    "pending": pending_assignments
                },
                "student_progress": {
                    "total_topics": total_topics,
                    "completed_topics": completed_topics,
                    "progress_percent": round(progress_percent, 2)
                },
                "notifications": notifications,
                "unread_messages": unread_messages_count,
                "featured_courses": course_data,
                "announcements": announcement_data
            }, status=200)

        except Student.DoesNotExist:
            return Response({"success": False, "message": "Student not found."}, status=200)

    def _get_trainer_dashboard(self, payload):
        employee_id = payload.get("employee_id")
        if not employee_id:
            return Response({"success": False, "message": "Trainer ID missing."}, status=200)

        try:
            trainer = Trainer.objects.get(employee_id=employee_id)

            # ===========================================================
            # OLD SYSTEM UPCOMING BATCHES
            # ===========================================================
            upcoming_batches_old = Batch.objects.filter(
                batchcoursetrainer__trainer=trainer,
                scheduled_date__gte=date.today(),
                is_archived=False,
                status=True
            ).distinct().values('batch_name', 'scheduled_date', 'end_date', 'title')

            batch_data = []
            for batch in upcoming_batches_old:
                formatted_date = batch['scheduled_date'].strftime('%Y-%m-%d') if batch['scheduled_date'] else None
                batch_data.append({
                    "title": batch['title'],
                    "scheduled_date": formatted_date,
                    "end_date": batch['end_date']
                })

            # ===========================================================
            # NEW SYSTEM UPCOMING BATCHES
            # ===========================================================
            upcoming_batches_new = NewBatch.objects.filter(
                trainer=trainer,
                start_date__gte=date.today(),
                is_archived=False,
                status=True
            ).values("title", "start_date", "end_date")

            for nb in upcoming_batches_new:
                batch_data.append({
                    "title": nb["title"],
                    "scheduled_date": nb["start_date"].strftime('%Y-%m-%d'),
                    "end_date": nb["end_date"]
                })

            # ===========================================================
            # MERGE: OLD + NEW (already appended)
            # ===========================================================

            # Trainer schedules (old + new)
            schedule_qs = ClassSchedule.objects.filter(
                trainer=trainer,
                is_archived=False
            ).select_related("batch", "new_batch", "course").order_by("-scheduled_date", "-start_time")

            all_schedules = []
            current_time = timezone.now()

            for sched in schedule_qs:
                start_time = getattr(sched, 'start_time', None) or time(9, 0)

                # Combine date + time
                class_start_dt = timezone.make_aware(
                    datetime.combine(sched.scheduled_date, start_time),
                    timezone.get_current_timezone()
                )

                # Default 1 hour
                class_end_dt = class_start_dt + timedelta(hours=1)

                # Override with end_time/duration
                try:
                    if getattr(sched, 'end_time', None):
                        class_end_dt = timezone.make_aware(
                            datetime.combine(sched.scheduled_date, sched.end_time),
                            timezone.get_current_timezone()
                        )
                    elif getattr(sched, 'duration', None):
                        class_end_dt = class_start_dt + sched.duration
                except:
                    class_end_dt = class_start_dt + timedelta(hours=1)

                # Buffer window
                buffer = timedelta(minutes=5)
                window_start = class_start_dt - buffer
                window_end = class_end_dt + buffer

                attendance_qs = TrainerAttendance.objects.filter(
                    trainer=sched.trainer,
                    batch=sched.batch if sched.batch else None,
                    course=sched.course,
                    date__gte=window_start,
                    date__lte=window_end,
                    status__in=["Login", "Logout", "Present"]
                )

                # Status
                if sched.is_class_cancelled:
                    status_info = "cancelled"
                elif current_time < class_start_dt:
                    status_info = "upcoming"
                elif class_start_dt <= current_time <= class_end_dt:
                    status_info = "ongoing"
                else:
                    status_info = "completed" if attendance_qs.exists() else "missed"

                latest_log = attendance_qs.order_by("-date").first()
                attendance_status = latest_log.status if latest_log else None

                # -------- BATCH INFO FIX FOR NEW BATCH ---------
                if sched.batch:   # old batch
                    batch_title = sched.batch.title
                else:             # new batch
                    batch_title = sched.new_batch.title if sched.new_batch else None

                all_schedules.append({
                    "schedule_id": sched.schedule_id,
                    "course_id": getattr(sched.course, "course_id", None),
                    "course_name": getattr(sched.course, "course_name", None),
                    "batch_id": getattr(sched.batch, "batch_id", getattr(sched.new_batch, "batch_id", None)),
                    "batch_name": getattr(sched.batch, "batch_name", None),  # old only
                    "title": batch_title,  # << unified
                    "trainer_id": sched.trainer.employee_id if sched.trainer else None,
                    "trainer_name": sched.trainer.full_name if sched.trainer else None,
                    "scheduled_date": sched.scheduled_date,
                    "is_class_cancelled": sched.is_class_cancelled,
                    "class_link": getattr(sched, "class_link", None),
                    "start_time": start_time.strftime("%I:%M %p"),
                    "end_time": class_end_dt.strftime("%I:%M %p"),
                    "attendance_status": attendance_status,
                    "status": status_info,
                })

            # Assignments logic untouched
            trainer_assignments = Assignment.objects.filter(assigned_by=trainer, is_archived=False)
            total_assignments = trainer_assignments.count()
            submissions_count = Submission.objects.filter(assignment__in=trainer_assignments).count()

            trainer_admin_id = payload.get('trainer_id')
            trainer_obj = Trainer.objects.filter(trainer_id=trainer_admin_id).first()
            super_admin_id = str(trainer_obj.created_by).strip() if trainer_obj and trainer_obj.created_by else None

            filters = Q(audience__in=["all", "trainers"], is_archived=False)
            if trainer_admin_id and super_admin_id:
                filters &= (Q(created_by__in=[trainer_admin_id, super_admin_id]) |
                            Q(created_by__icontains=trainer_admin_id) |
                            Q(created_by__icontains=super_admin_id))
            elif trainer_admin_id:
                filters &= (Q(created_by=trainer_admin_id) | Q(created_by__icontains=trainer_admin_id))
            elif super_admin_id:
                filters &= (Q(created_by=super_admin_id) | Q(created_by__icontains=super_admin_id))

            announcements = Announcement.objects.filter(filters).order_by("-created_at")[:5]
            announcement_data = AnnouncementSerializer(announcements, many=True).data

            chat_rooms = ChatRoom.objects.filter(trainer=trainer)
            unread_messages_count = Message.objects.filter(
                room__in=chat_rooms,
                is_read=False,
                is_deleted=False,
                sender_type="student"
            ).count()

            return Response({
                "success": True,
                "user_type": "tutor",
                "trainer_name": trainer.full_name,
                "upcoming_batches": batch_data,
                "schedule": all_schedules,
                "assignments": {
                    "total": total_assignments,
                    "submissions": submissions_count
                },
                "unread_messages": unread_messages_count,
                "announcements": announcement_data
            }, status=200)

        except Trainer.DoesNotExist:
            return Response({"success": False, "message": "Trainer not found."}, status=200)
     
    def _get_super_admin_dashboard(self, payload):
            
        if payload.get("user_type") != "super_admin":
            return Response({"success": False, "message": "Unauthorized"}, status=200)

        allowed_ids = self._get_allowed_creator_ids(payload)

        total_students = Student.objects.filter(is_archived=False).filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()

        active_students = Student.objects.filter(is_archived=False, status=True).filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()
        inactive_students = total_students - active_students

        total_trainers = Trainer.objects.filter(is_archived=False, user_type='tutor').filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()

        active_trainers = Trainer.objects.filter(is_archived=False, status__iexact="Active", user_type='tutor').filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()
        inactive_trainers = total_trainers - active_trainers

        total_courses = Course.objects.filter(is_archived=False).filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()
        total_active_courses = Course.objects.filter(is_archived=False, status = "Active").filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()
        total_batches = NewBatch.objects.filter(is_archived=False).filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()
        total_active_batches = NewBatch.objects.filter(is_archived=False, status=True).filter(
                Q(created_by_type="super_admin", created_by__in=allowed_ids) |
                Q(created_by_type="admin", created_by__in=allowed_ids)
            ).count()

        batchwise_student_count = (
            NewBatch.objects
            .filter(created_by__in=allowed_ids, is_archived=False, status=True)
            .annotate(student_count=Count('students', distinct=True))
            .values('title', 'batch_id', 'student_count')
            .order_by('title')
        )


        return Response({
            "success": True,
            "user_type": "super_admin",
            "data": {
                "total_trainers": total_trainers,
                "active_trainers": active_trainers,
                "total_students": total_students,
                "active_students": active_students,
                "total_courses": total_courses,
                "active_courses": total_active_courses,

                "total_batches": total_batches,
                "active_batches": total_active_batches,

                "batchwise_student_count": list(batchwise_student_count),
            }
        }, status=200)
    
    # ==========================================================
    # ADMIN DASHBOARD (HIERARCHY READY)
    # ==========================================================
    def _get_admin_dashboard(self, payload):

        if payload.get("user_type") != "admin":
            return Response({"success": False, "message": "Unauthorized"}, status=200)

        allowed_ids = self._get_allowed_creator_ids(payload)
        today = date.today()
        now_time = datetime.now().time()

        # ============================
        # COUNTS
        # ============================
        total_students = Student.objects.filter(is_archived=False).filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()

        active_students = Student.objects.filter(is_archived=False, status=True).filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()
        inactive_students = total_students - active_students

        total_trainers = Trainer.objects.filter(is_archived=False, user_type='tutor').filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()

        active_trainers = Trainer.objects.filter(is_archived=False, status__iexact="Active", user_type='tutor').filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()
        inactive_trainers = total_trainers - active_trainers

        total_courses = Course.objects.filter(is_archived=False).filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()
        total_active_courses = Course.objects.filter(is_archived=False, status = "Active").filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()
        total_batches = NewBatch.objects.filter(is_archived=False).filter(
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        ).count()
        total_active_batches = NewBatch.objects.filter(is_archived=False, status=True).filter(
                Q(created_by_type="super_admin", created_by__in=allowed_ids) |
                Q(created_by_type="admin", created_by__in=allowed_ids)
            ).count()

        batchwise_student_count = (
            NewBatch.objects
            .filter(created_by__in=allowed_ids, is_archived=False, status=True)
            .annotate(student_count=Count('students', distinct=True))
            .values('title', 'batch_id', 'student_count')
            .order_by('title')
        )

        # ============================
        # TRAINER LOGIN TREND (7 DAYS)
        # ============================
        last_7_days = [today - timedelta(days=i) for i in range(6, -1, -1)]

        trainer_login_trend = (
            TrainerAttendance.objects
            .filter(
                date__date__range=[last_7_days[0], last_7_days[-1]],
                status__iexact="Login",
                trainer__created_by__in=allowed_ids
            )
            .annotate(date_only=TruncDate("date"))
            .values("date_only")
            .annotate(login_count=Count("trainer", distinct=True))
            .order_by("date_only")
        )

        # Ensure missing days appear as 0
        trainer_login_trend_dict = {item["date_only"]: item["login_count"] for item in trainer_login_trend}

        trainer_login_trend_final = [
            {
                "date": day.strftime("%Y-%m-%d"),
                "login_count": trainer_login_trend_dict.get(day, 0),
            }
            for day in last_7_days
        ]
        
        # ============================
        # ATTENDANCE TREND (7 DAYS)
        # ============================
        attendance_trend = (
            Attendance.objects
            .filter(
                date__date__range=[last_7_days[0], last_7_days[-1]],
                student__created_by__in=allowed_ids
            )
            .annotate(date_only=TruncDate("date"))
            .values("date_only")
            .annotate(
                total=Count("id"),
                present=Count("id", filter=Q(status__iexact="Login"))
            )
            .order_by("date_only")
        )

        attendance_dict = {
            item["date_only"]: {
                "present": item["present"],
                "total": item["total"]
            }
            for item in attendance_trend
        }

        attendance_trend_final = []
        for day in last_7_days:
            data = attendance_dict.get(day, {"present": 0, "total": 0})
            attendance_pct = (data["present"] / data["total"] * 100) if data["total"] > 0 else 0

            attendance_trend_final.append({
                "date": day.strftime("%Y-%m-%d"),
                "present": data["present"],
                "total": data["total"],
                "percentage": round(attendance_pct, 2)
            })

        todays_classes = ClassSchedule.objects.filter(
            scheduled_date=today,
            is_archived=False,
            created_by__in=allowed_ids
        )

        ongoing = upcoming = done = missed = 0

        for cls in todays_classes:
            start, end = cls.start_time, cls.end_time
            attendance_exists = TrainerAttendance.objects.filter(
                trainer=cls.trainer,
                course=cls.course,
                date__date=today
            ).exists()

            if start <= now_time <= end:
                ongoing += 1
            elif end < now_time:
                done += 1 if attendance_exists else 0
                missed += 0 if attendance_exists else 1
            else:
                upcoming += 1

        total_classes = todays_classes.count()

        # ============================
        # ATTENDANCE %
        # ============================
        today_att = Attendance.objects.filter(date__date=today)
        total_att_today = today_att.count()
        present_today = today_att.filter(status__iexact="Login").count()
        attendance_today_percent = (
            (present_today / total_att_today * 100) if total_att_today > 0 else 0
        )

        # ============================
        # ANNOUNCEMENTS
        # ============================
        announcements = Announcement.objects.filter(
            is_archived=False,
            created_by__in=allowed_ids
        ).order_by("-created_at")

        announcement_data = AnnouncementSerializer(announcements, many=True).data

        # ============================
        # FINAL DATA
        # ============================
        return Response({
            "success": True,
            "message": "Admin dashboard loaded.",
            "data": {
                "total_students": total_students,
                "active_students": active_students,
                "inactive_students": inactive_students,
                "total_trainers": total_trainers,
                "active_trainers": active_trainers,
                "inactive_trainers": inactive_trainers,
                "trainer_login_trend": trainer_login_trend_final,
                "attendance_trend": attendance_trend_final,
                "total_courses": total_courses,
                "active_courses": total_active_courses,
                "total_batches": total_batches,
                "active_batches": total_active_batches,
                "batchwise_student_count": list(batchwise_student_count),
                "todays_classes": {
                    "total": total_classes,
                    "ongoing": ongoing,
                    "upcoming": upcoming,
                    "completed": done,
                    "missed": missed
                },
                "attendance_today_percent": round(attendance_today_percent, 2),
                "announcements": announcement_data
            }
        }, status=200)
    
    
    def _get_employer_dashboard(self, payload):
        """Build Employer Dashboard stats filtered by company_id"""

        company_id = payload.get("company_id")
        if not company_id:
            return Response({
                "success": False,
                "message": "company_id missing in payload",
                "data": {}
            }, status=200)

        employer = SubAdmin.objects.filter(company_id=company_id).first()
        if not employer:
            return Response({
                "success": False,
                "message": f"Employer with company_id '{company_id}' not found",
                "data": {}
            }, status=200)

        # --- Students ---
        students_qs = Student.objects.filter(
            Q(school_student__company_id=company_id) |
            Q(college_student__company_id=company_id) |
            Q(jobseeker__company_id=company_id) |
            Q(employee__company_id=company_id),
            is_archived=False
        ).distinct()

        total_students = students_qs.count()
        active_students = total_students

        # --- Attendance per student ---
        student_attendance = []

        for student in students_qs:
            # Get all courses for this student (through BatchCourseTrainer)
            student_courses = Course.objects.filter(
                batchcoursetrainer__student=student
            ).distinct()

            total_classes = 0
            attended_classes = 0

            for course in student_courses:
                scheduled_qs = ClassSchedule.objects.filter(
                    course=course,
                    batch__batchcoursetrainer__student=student,
                    is_archived=False
                ).distinct()

                total_scheduled = scheduled_qs.count()
                present_count = 0

                for sched in scheduled_qs:
                    if Attendance.objects.filter(
                        student=student,
                        course=course,
                        batch=sched.batch,
                        date__date=sched.scheduled_date,
                        status__iexact="Login"
                    ).exists():
                        present_count += 1

                total_classes += total_scheduled
                attended_classes += present_count

            attendance_percent = round(
                (attended_classes / total_classes * 100), 2
            ) if total_classes > 0 else 0

            student_attendance.append({
                "student": f"{student.first_name} {student.last_name}",
                "attendance_percent": attendance_percent
            })

        avg_attendance_percent = round(
            sum(s["attendance_percent"] for s in student_attendance) / total_students,
            2
        ) if total_students > 0 else 0

        # --- Attendance Logs (Today) ---
        today_scheduled_classes = ClassSchedule.objects.filter(
            batch__batchcoursetrainer__student__in=students_qs,
            scheduled_date=date.today(),
            is_archived=False
        ).distinct()

        present_today = 0
        absent_today = 0

        for student in students_qs:
            student_classes_today = today_scheduled_classes.filter(
                batch__batchcoursetrainer__student=student
            )

            for sched in student_classes_today:
                if Attendance.objects.filter(
                    student=student,
                    course=sched.course,
                    batch=sched.batch,
                    date__date=date.today(),
                    status__iexact="Login"
                ).exists():
                    present_today += 1
                else:
                    absent_today += 1

        total_classes = ClassSchedule.objects.filter(
            batch__batchcoursetrainer__student__in=students_qs,
            is_archived=False
        ).distinct().count()

        low_performers = [s for s in student_attendance if s["attendance_percent"] < 65]

        # --- Assignments Section ---
        # Get all courses linked to company students
        courses = Course.objects.filter(
            batchcoursetrainer__student__in=students_qs
        ).distinct()

        total_assignments = Assignment.objects.filter(
            course__in=courses,
            is_archived=False
        ).distinct()

        total_assignments_count = total_assignments.count()

        submitted_assignments = Submission.objects.filter(
            student__in=students_qs,
            assignment__in=total_assignments
        ).distinct()

        submitted_assignments_count = submitted_assignments.count()
        pending_assignments_count = total_assignments_count - submitted_assignments_count

        submission_rate = round(
            (submitted_assignments_count / total_assignments_count * 100), 2
        ) if total_assignments_count > 0 else 0

        # --- Per-course assignment breakdown ---
        course_stats_list = []

        for course in courses:
            course_assignments = Assignment.objects.filter(
                course=course, is_archived=False
            )
            total_assignments_count = course_assignments.count()

            students_info = []

            course_students = Student.objects.filter(
                batchcoursetrainer__course=course,
                batchcoursetrainer__student__in=students_qs
            ).distinct()

            for student in course_students:
                submitted_ids = Submission.objects.filter(
                    student=student,
                    assignment__in=course_assignments
                ).values_list("assignment_id", flat=True).distinct()

                submitted_count = len(submitted_ids)
                pending_count = total_assignments_count - submitted_count

                students_info.append({
                    "student_id": student.registration_id,
                    "student_name": f"{student.first_name} {student.last_name}",
                    "submitted": submitted_count,
                    "pending": pending_count
                })

            course_stats_list.append({
                "course_id": course.course_id,
                "course_name": course.course_name,
                "total_assignments": total_assignments_count,
                "total_students": len(students_info),
                "students": students_info
            })

        # --- Schedules ---
        student_ids = students_qs.values_list('registration_id', flat=True)

        schedule_qs = ClassSchedule.objects.filter(
            new_batch__student__registration_id__in=student_ids,
            is_archived=False
        ).annotate(
            start_datetime=ExpressionWrapper(
                F('scheduled_date') + F('start_time'),
                output_field=DateField()
            )
        ).distinct().order_by('-scheduled_date')

        now = datetime.now()
        all_schedules = []

        for sched in schedule_qs:
            start_time = getattr(sched, 'start_time', time(9, 0))
            class_start_dt = datetime.combine(sched.scheduled_date, start_time)
            duration_td = sched.duration or timedelta(hours=1)
            class_end_dt = class_start_dt + duration_td

            if class_end_dt < now:
                status = 'completed'
            elif class_start_dt > now:
                status = 'upcoming'
            else:
                status = 'ongoing'

            hours, remainder = divmod(duration_td.total_seconds(), 3600)
            minutes, _ = divmod(remainder, 60)
            duration_str = f"{int(hours):02d}:{int(minutes):02d}"

            all_schedules.append({
                "course_name": sched.course.course_name,
                "batch_name": sched.batch.batch_name,
                "title": sched.batch.title,
                "trainer_name": sched.trainer.full_name,
                "scheduled_date": sched.scheduled_date.strftime('%Y-%m-%d'),
                "class_link": sched.class_link,
                "start_time": sched.start_time.strftime('%I:%M %p') if sched.start_time else None,
                "end_time": sched.end_time.strftime('%I:%M %p') if sched.end_time else None,
                "duration": duration_str,
                "status": status,
            })

        # --- Announcements ---
        admin_id = payload.get('trainer_id')
        announcements = Announcement.objects.filter(
            is_archived=False,
            created_by=admin_id
        ).filter(Q(audience="all")).order_by("-created_at")[:5]

        announcement_data = AnnouncementSerializer(announcements, many=True).data

        # --- Final Data ---
        data = {
            "students": {
                "total": total_students,
                "active": active_students,
                "avg_attendance_percent": avg_attendance_percent,
            },
            "attendance": {
                "total_classes": total_classes,
                "avg_attendance_rate": avg_attendance_percent,
                "today": {
                    "present": present_today,
                    "absent": absent_today
                },
                "low_performers": low_performers
            },
            "upcoming_schedules": all_schedules,
            "assignments": {
                "total": total_assignments_count,
                "submitted": submitted_assignments_count,
                "pending": pending_assignments_count,
                "submission_rate": submission_rate,
                "per_courses": course_stats_list
            },
            "announcements": announcement_data
        }

        company = Employer.objects.filter(company_id=company_id).first()
        company_name = company.company_name if company else company_id

        return Response({
            "success": True,
            "message": f"Dashboard for Company {company_name}",
            "data": data
        }, status=200)
        
class ReportsViewSet(ViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    
    def list(self, request):
        user = request.user
        user_type = getattr(user, "user_type", "").lower()
        admin_trainer_id = getattr(user, "trainer_id", None)
        user_created_id = getattr(user, "user_id", None) if user_type == "super_admin" else admin_trainer_id

        # Get admins for super admin
        admin_ids = []
        if user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

        # --- Organizations ---
        org_qs = Employer.objects.filter(is_archived=False)
        if user_type == "admin" and admin_trainer_id:
            org_qs = org_qs.filter(created_by=admin_trainer_id)
        elif user_type == "super_admin":
            org_qs = org_qs.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )
        organization = org_qs.values('company_name', 'company_id')

        # --- Students ---
        student_qs = Student.objects.filter(is_archived=False)
        if user_type == "admin" and admin_trainer_id:
            student_qs = student_qs.filter(created_by=admin_trainer_id)
        elif user_type == "super_admin":
            student_qs = student_qs.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )
        student_list = [
            {
                "registration_id": s['registration_id'],
                "student_id": s['student_id'],
                "student_name": f"{s['first_name']} {s['last_name']}"
            } for s in student_qs.values('first_name', 'last_name', 'registration_id', 'student_id')
        ]

        # --- Trainers ---
        trainer_qs = Trainer.objects.filter(is_archived=False)
        if user_type == "admin" and admin_trainer_id:
            trainer_qs = trainer_qs.filter(created_by=admin_trainer_id)
        elif user_type == "super_admin":
            trainer_qs = trainer_qs.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )
        trainer = trainer_qs.values('full_name', 'employee_id')

        return Response({
            "success": True,
            "message": "Reports",
            "organizations_list": organization,
            "students_list": student_list,
            "trainers_list": trainer
        }, status=200)

    def get_reports(self, request):
        user = request.user
        user_type = getattr(user, "user_type", "").lower()
        admin_trainer_id = getattr(user, "trainer_id", None)
        user_created_id = getattr(user, "user_id", None) if user_type == "super_admin" else admin_trainer_id

        # Get admins for super admin
        admin_ids = []
        if user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

        organization_id = request.query_params.get("organization_id")
        student_id = request.query_params.get("student_id")
        trainer_id = request.query_params.get("trainer_id")

        if student_id or organization_id:
            return self._admin_report(organization_id, student_id, admin_trainer_id, user_type, user_created_id, admin_ids)
        elif trainer_id:
            return self._trainer_report(trainer_id)
        else:
            return Response({"success": False, "message": "Provide student_id, organization_id, or trainer_id"}, status=200)

    # ---------------- Admin / Organization / Student Report ----------------
    def _admin_report(self, organization_id=None, student_id=None, admin_trainer_id=None,
                      user_type=None, user_created_id=None, admin_ids=None):
        try:
            # --- Filter students based on admin/super_admin ---
            students_qs = Student.objects.filter(is_archived=False)
            if student_id:
                if user_type == "admin":
                    students_qs = students_qs.filter(student_id=student_id, created_by=admin_trainer_id)
                elif user_type == "super_admin":
                    students_qs = students_qs.filter(
                        student_id=student_id
                    ).filter(
                        Q(created_by_type="super_admin", created_by=user_created_id) |
                        Q(created_by_type="admin", created_by__in=admin_ids)
                    )
            elif organization_id:
                students_qs = students_qs.filter(
                    Q(employee__company_id=organization_id) |
                    Q(school_student__company_id=organization_id) |
                    Q(college_student__company_id=organization_id) |
                    Q(jobseeker__company_id=organization_id),
                ).distinct()
                if user_type == "admin":
                    students_qs = students_qs.filter(created_by=admin_trainer_id)
                elif user_type == "super_admin":
                    students_qs = students_qs.filter(
                        Q(created_by_type="super_admin", created_by=user_created_id) |
                        Q(created_by_type="admin", created_by__in=admin_ids)
                    )
            else:
                return Response({"success": False, "message": "organization_id or student_id required"}, status=200)
                
            total_students = students_qs.count()
            student_reports = []

            for student in students_qs:
                # Get enrollments
                enrollments = NewBatch.objects.filter(students=student).values_list("batch_id", "course_id")
                
                # Build schedule filter
                schedule_filter = Q()
                for batch_id, course_id in enrollments:
                    schedule_filter |= Q(batch_id=batch_id, course_id=course_id)
                
                # Fetch schedules the student is enrolled in (past or ongoing only)
                now = timezone.localtime()
                scheduled_qs = ClassSchedule.objects.filter(
                    schedule_filter,
                    is_archived=False
                ).filter(
                    Q(scheduled_date__lt=date.today()) |
                    Q(scheduled_date=date.today(), start_time__lte=now.time())
                ).distinct().order_by('scheduled_date', 'start_time')
                
                total_classes = scheduled_qs.count()
                attended_classes = 0
                class_cancelled = 0

                for sched in scheduled_qs:
                    start_time = getattr(sched, 'start_time', time(9, 0))
                    end_time = getattr(sched, 'end_time', None) or (start_time + timedelta(hours=1))

                    class_start_dt = timezone.make_aware(datetime.combine(sched.scheduled_date, start_time))
                    class_end_dt = timezone.make_aware(datetime.combine(sched.scheduled_date, end_time))

                    # Add buffer of 5 minutes before and after
                    buffer = timedelta(minutes=5)
                    window_start = class_start_dt - buffer
                    window_end = class_end_dt + buffer

                    # Check if student attended this schedule
                    attendance_exists = Attendance.objects.filter(
                        student=student,
                        date__gte=window_start,
                        date__lte=window_end
                    ).filter(
                        Q(status__icontains="Login") |
                        Q(status__icontains="Logout") |
                        Q(status__icontains="Present")
                    ).exists()
                    
                    if sched.is_class_cancelled:
                        class_cancelled += 1

                    if attendance_exists:
                        attended_classes += 1

                absent_classes = total_classes - attended_classes
                attendance_percent = round((attended_classes / total_classes * 100), 2) if total_classes > 0 else 0

                student_reports.append({
                    "student_id": student.registration_id,
                    "student_name": f"{student.first_name} {student.last_name}",
                    "total_classes": total_classes,
                    "total_cancelled_classes": class_cancelled,
                    "attended_classes": attended_classes,
                    "absent_classes": absent_classes,
                    "attendance_percent": attendance_percent
                })

            attendance_summary = []

            # Get all schedules for all students
            schedule_qs = ClassSchedule.objects.filter(
                new_batch__student__in=students_qs,
                is_archived=False,
                scheduled_date__lte=date.today()
            ).select_related("course", "batch").order_by("scheduled_date").distinct()

            # Group by (date, course, batch)
            for sched in schedule_qs:
                class_date = sched.scheduled_date
                course = sched.course
                batch = sched.batch

                # Students enrolled in this batch & course
                enrolled_students = Student.objects.filter(
                    new_batch=batch,
                    new_batch__course=course,
                    is_archived=False
                ).distinct()

                present_count = 0
                absent_count = 0
                cancelled_classes = 0
                absent_names = []

                for student in enrolled_students:
                    attended = Attendance.objects.filter(
                        student=student,
                        status__in=["Login", "Logout"],
                        date__date=class_date
                    ).exists()

                    if sched.is_class_cancelled:
                        cancelled_classes += 1
                    elif attended:
                        present_count += 1
                    else:
                        absent_count += 1
                        absent_names.append(f"{student.first_name} {student.last_name}")

                attendance_summary.append({
                    "course_id": course.course_id,
                    "course_name": course.course_name,
                    "date": class_date.strftime("%Y-%m-%d"),
                    "batch_id": batch.batch_id,
                    "batch_name": batch.batch_name,
                    "title": batch.title,
                    "present_count": present_count,
                    "absent_count": absent_count,
                    "absent_names": absent_names,
                    "class_cancelled": cancelled_classes,
                })
            student = students_qs.first() if students_qs.exists() else None
            # Get all courses the student is enrolled in
            student_courses = Course.objects.filter(newbatch__student=student, is_archived=False).distinct()

            # Get all assignments for those courses
            all_assignments = Assignment.objects.filter(
                course__in=student_courses,
                is_archived=False
            )

            # Total assignments (across all enrolled courses)
            total_assignments = all_assignments.count()

            # Unique submitted assignments
            submitted_assignment_ids = Submission.objects.filter(
                student=student,
                is_archived=False,
                assignment__in=all_assignments
            ).values_list('assignment_id', flat=True).distinct()

            submitted_assignments = len(submitted_assignment_ids)
            pending_assignments = max(total_assignments - submitted_assignments, 0)

            # # --- Test details per student ---
            test_summary = []

            for student in students_qs:
                # Get student's courses
                student_courses = Course.objects.filter(
                    new_batch__student=student
                )

                # Tests in those courses
                tests_qs = Test.objects.filter(
                    course_id__in=student_courses,
                    is_archived=False
                ).distinct()

                # Completed tests
                completed_tests_qs = TestResult.objects.filter(
                    student_id=student,
                    test_id__in=tests_qs
                ).distinct('test_id')

                completed_count = completed_tests_qs.count()
                pending_count = tests_qs.count() - completed_count

                # Include details
                test_details = []

                for t in tests_qs:
                    # Has the student submitted answers?
                    submitted_answers = StudentAnswers.objects.filter(
                        student_id=student.student_id,
                        test_id=t.test_id
                    ).exists()

                    # Has the test been evaluated?
                    test_result = TestResult.objects.filter(
                        student_id=student.student_id,
                        test_id=t.test_id
                    ).first()

                    if not submitted_answers:
                        status = "pending"  # Student hasn’t submitted yet
                    elif submitted_answers and not test_result:
                        status = "waiting_for_result"  # Submitted but result not yet published
                    else:
                        status = "success"  # Result published

                    test_details.append({
                        "test_id": t.test_id,
                        "test_name": t.test_name,
                        "course_name": t.course_id.course_name,
                        "duration": t.duration,
                        "total_marks": t.total_marks,
                        "status": status
                    })

                test_summary.append({
                    "student_id": student.registration_id,
                    "student_name": f"{student.first_name} {student.last_name}",
                    "test_details": test_details,
                    "completed_tests": completed_count,
                    "pending_tests": pending_count,
                })
            # Get all courses the student is enrolled in
            student_courses = Course.objects.filter(new_batch__student=student).distinct()

            # Get all active tests for those courses
            all_tests = Test.objects.filter(
                course_id__in=student_courses,
                is_archived=False
            )

            # Total tests (across all enrolled courses)
            total_tests = all_tests.count()

            # Unique completed tests (TestResult)
            completed_test_ids = TestResult.objects.filter(
                student_id=student,
                test_id__in=all_tests
            ).values_list('test_id', flat=True).distinct()

            completed_tests = len(completed_test_ids)
            pending_tests = max(total_tests - completed_tests, 0)

            # Courses stats
            courses = Course.objects.filter(new_batch__student__in=students_qs).distinct()
            course_stats_list = []

            for course in courses:
                course_assignments = Assignment.objects.filter(course=course, is_archived=False)
                students_info = []

                for student in students_qs:
                    # Check if student is enrolled in this course
                    if not NewBatch.objects.filter(students=student, course=course).exists():
                        continue

                    # Count distinct assignments submitted by the student
                    submitted_count = Submission.objects.filter(
                        student=student,
                        assignment__in=course_assignments
                    ).values('assignment_id').distinct().count()

                    pending_count = course_assignments.count() - submitted_count

                    students_info.append({
                        "student_id": student.registration_id,
                        "student_name": f"{student.first_name} {student.last_name}",
                        "submitted": submitted_count,
                        "pending": pending_count
                    })

                course_stats_list.append({
                    "course_id": course.course_id,
                    "course_name": course.course_name,
                    "total_assignments": course_assignments.count(),
                    "total_students": len(students_info),
                    "students": students_info
                })

            # Step 1: Get students for the organization/student
            students_qs = Student.objects.filter(is_archived=False)
            if student_id:
                students_qs = students_qs.filter(student_id=student_id)
            elif organization_id:
                students_qs = students_qs.filter(
                    Q(employee__company_id=organization_id) |
                    Q(school_student__company_id=organization_id) |
                    Q(college_student__company_id=organization_id) |
                    Q(jobseeker__company_id=organization_id)
                )

            # Filter by admin/super admin
            if user_type == "admin" and admin_trainer_id:
                students_qs = students_qs.filter(created_by=admin_trainer_id)
            elif user_type == "super_admin":
                students_qs = students_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )

            student_ids = list(students_qs.values_list("student_id", flat=True))
            if not student_ids:
                return Response({"success": False, "message": "No students found"}, status=200)

            # Step 2: Get enrollments for these students
            enrollments_qs = NewBatch.objects.filter(
                students__in=student_ids
            ).values_list("batch_id", "course_id", "trainer_id", "student_id")

            # Build mapping: student -> (batch, course) -> trainers
            student_enrollment_map = {}
            for batch_id, course_id, trainer_id, student_id in enrollments_qs:
                student_enrollment_map.setdefault(student_id, {}).setdefault((batch_id, course_id), set()).add(trainer_id)

            # Step 3: Build schedule filter
            schedule_filter = Q()
            for student_id, enrollments in student_enrollment_map.items():
                for (batch_id, course_id), _ in enrollments.items():
                    schedule_filter |= Q(batch_id=batch_id, course_id=course_id)

            # Step 4: Fetch all schedules (past + future) for these enrollments
            schedule_qs = ClassSchedule.objects.filter(
                schedule_filter,
                is_archived=False
            ).select_related("course", "trainer", "batch").order_by("scheduled_date", "start_time")

            # Step 5: Build response
            all_schedules = []
            now = timezone.now()

            for sched in schedule_qs:
                start_time = sched.start_time or time(9, 0)
                class_start_dt = timezone.make_aware(
                    datetime.combine(sched.scheduled_date, start_time),
                    timezone.get_current_timezone()
                )
                if sched.duration:
                    class_end_dt = class_start_dt + sched.duration
                elif getattr(sched, "end_time", None):
                    class_end_dt = timezone.make_aware(
                        datetime.combine(sched.scheduled_date, sched.end_time),
                        timezone.get_current_timezone()
                    )
                else:
                    class_end_dt = class_start_dt + timedelta(hours=1)

                # Add buffer 5 min before and after
                buffer = timedelta(minutes=5)
                window_start = class_start_dt - buffer
                window_end = class_end_dt + buffer

                # Students enrolled in this schedule
                enrolled_students_ids = [
                    student_id for student_id in student_ids
                    if (sched.batch_id, sched.course_id) in student_enrollment_map.get(student_id, {})
                ]

                # Attendance count: check if student attended within window
                attendance_qs = Attendance.objects.filter(
                    student_id__in=enrolled_students_ids,
                    batch=sched.batch,
                    course=sched.course,
                    date__gte=window_start,
                    date__lte=window_end,
                    status__in=["Login", "Logout", "Present"]
                ).values_list("student_id", flat=True)

                attended_students_ids = set(attendance_qs)
                total_students = len(enrolled_students_ids)
                attended_count = len(attended_students_ids)
                absent_count = total_students - attended_count

                # Status calculation
                if sched.is_class_cancelled:
                    att_status = 'Cancelled'
                if now < class_start_dt:
                    att_status = "Upcoming"
                elif attended_count > 0:
                    att_status = "Present"
                else:
                    att_status = "Absent"

                all_schedules.append({
                    "schedule_id": sched.schedule_id,
                    "course_id": getattr(sched.course, "course_id", None),
                    "course_name": getattr(sched.course, "course_name", None),
                    "batch_name": getattr(sched.batch, "batch_name", None),
                    "title": getattr(sched.batch, "title", None),
                    "batch_id": getattr(sched.batch, "batch_id", None),
                    "category_id": getattr(sched.course.course_category, "category_id", None) if sched.course and sched.course.course_category else None,
                    "trainer_id": sched.trainer.employee_id if sched.trainer else None,
                    "trainer_name": sched.trainer.full_name if sched.trainer else None,
                    "scheduled_date": sched.scheduled_date,
                    "class_link": sched.class_link,
                    "start_time": start_time.strftime("%I:%M %p"),
                    "end_time": class_end_dt.strftime("%I:%M %p"),
                    "attended_count": attended_count,
                    'is_class_cancelled': sched.is_class_cancelled,
                    "absent_count": absent_count,
                    "status": att_status,
                })

            course = Course.objects.filter(batchcoursetrainer__student=student).values('course_id', 'course_name', 'course_category').distinct()
            batch = Batch.objects.filter(
                batchcoursetrainer__student=student,
                is_archived=False,
            ).values(
                'batch_id',
                'batch_name',
                'title',
                'batchcoursetrainer__course_id'
            ).distinct()

            category = CourseCategory.objects.filter(
                courses__batchcoursetrainer__student=student
            ).values(
                'category_id',
                'category_name'
            ).distinct()
            
            # ---------------- Payment Report ----------------
            payment_report_list = []
            
            if student_id:
                students_qs = students_qs.filter(student_id=student_id)

            for student in students_qs:
                # Courses the student is enrolled in
                student_courses = Course.objects.filter(
                    batchcoursetrainer__student=student,
                    is_archived=False
                ).distinct()

                # Total expected fee
                expected_fee = student_courses.aggregate(
                    total=models.Sum('fee')
                )['total'] or 0

                # All transactions for this student
                transactions = PaymentTransaction.objects.filter(student=student).order_by('-created_at')

                # Total paid (successful transactions only)
                total_paid = transactions.filter(payment_status__iexact='Success').aggregate(
                    total=models.Sum('amount')
                )['total'] or 0

                # Balance
                balance = max(expected_fee - total_paid, 0)

                # Transaction details
                transaction_details = []
                for txn in transactions:
                    transaction_details.append({
                        "transaction_id": txn.transaction_id,
                        "order_id": txn.order_id,
                        "gateway": txn.gateway.gatway_name if txn.gateway else None,
                        "amount": float(txn.amount),
                        "currency": txn.currency,
                        "payment_status": txn.payment_status,
                        "description": txn.description,
                        "metadata": txn.metadata,
                        "created_at": txn.created_at.strftime("%Y-%m-%d %I:%M:%S %p")
                    })

                payment_report_list.append({
                    "student_id": student.registration_id,
                    "student_name": f"{student.first_name} {student.last_name}",
                    "course_fee": float(expected_fee),
                    "total_paid": float(total_paid),
                    "balance": float(balance),
                    "transactions": transaction_details
                })
            
            return Response({
                "success": True,
                "student_count": total_students,
                'total_assignments': total_assignments,
                "course": course,
                "batch": batch,
                "category": category,
                'completed_assignments': submitted_assignments,
                'total_tests': total_tests,
                'completed_tests': completed_tests,
                'pending_tests': pending_tests,
                'pending_assignments': pending_assignments,
                "students": student_reports,
                "courses": course_stats_list,
                "payment_report": payment_report_list,
                "schedules": all_schedules,
                "attendance_summary": attendance_summary,
                "test_summary": test_summary
            })
        except Exception as e:
            return Response({"success": False, "message": str(e)})

    # ---------------- Trainer Report ----------------
    def _trainer_report(self, trainer_id):
        try:
            IST = pytz.timezone("Asia/Kolkata")
            now = datetime.now(IST)

            # Get all schedules for this trainer
            schedule_qs = ClassSchedule.objects.filter(
                trainer__employee_id=trainer_id,
                is_archived=False
            ).select_related("batch", "course").order_by("scheduled_date", "start_time")

            # Get all attendance records for this trainer
            attendance_qs = TrainerAttendance.objects.filter(trainer__employee_id=trainer_id)

            report = []

            for sched in schedule_qs:
                day = sched.scheduled_date
                start_dt = IST.localize(datetime.combine(day, sched.start_time or time(9, 0)))
                end_dt = IST.localize(datetime.combine(day, sched.end_time or (sched.start_time or time(9, 0)) + timedelta(hours=1)))

                # Add buffer of 5 minutes before and after
                buffer = timedelta(minutes=5)
                window_start = start_dt - buffer
                window_end = end_dt + buffer

                # Filter attendance within this window
                att_records = [
                    att for att in attendance_qs
                    if window_start <= att.date.astimezone(IST) <= window_end
                    and att.batch.batch_id == sched.batch.batch_id
                    and att.course.course_id == sched.course.course_id
                ]

                # Determine status
                if sched.is_class_cancelled:
                    status = "Cancelled"
                elif now < start_dt:
                    status = "Upcoming"
                elif att_records:
                    status = "Present"
                else:
                    status = "Absent"

                # Compute working hours and first login / last logout
                total_work = timedelta()
                first_login = None
                last_logout = None

                for att in att_records:
                    att_time = att.date.astimezone(IST)
                    if att.status.lower() == "login":
                        if not first_login or att_time < first_login:
                            first_login = att_time
                    elif att.status.lower() == "logout":
                        if not last_logout or att_time > last_logout:
                            last_logout = att_time

                # If logged in but no logout, assume now as logout
                if first_login and not last_logout:
                    last_logout = now

                if first_login and last_logout:
                    total_work = last_logout - first_login

                # Format total working hours
                total_seconds = int(total_work.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                formatted_working_hours = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

                # Append to report
                report.append({
                    "schedule_id": sched.schedule_id,
                    "batch_id": sched.batch.batch_id,
                    "batch_name": sched.batch.batch_name,
                    "title": sched.batch.title,
                    "course_id": sched.course.course_id,
                    "course_name": sched.course.course_name,
                    "category_id": sched.course.course_category.category_id if sched.course.course_category else None,
                    "trainer_id": sched.trainer.employee_id if sched.trainer else None,
                    "trainer_name": sched.trainer.full_name if sched.trainer else None,
                    "scheduled_date": day.strftime("%Y-%m-%d"),
                    "start_time": sched.start_time.strftime("%I:%M %p") if sched.start_time else None,
                    "end_time": sched.end_time.strftime("%I:%M %p") if sched.end_time else None,
                    "status": status,
                    'is_class_cancelled':sched.is_class_cancelled,
                    "total_working_hours": formatted_working_hours,
                    "login": first_login.strftime("%I:%M %p") if first_login else None,
                    "logout": last_logout.strftime("%I:%M %p") if last_logout else None
                })

            # Get related info
            course = Course.objects.filter(batchcoursetrainer__trainer__employee_id=trainer_id)\
                .values('course_id', 'course_name', 'course_category').distinct()
            batch = BatchCourseTrainer.objects.filter(trainer__employee_id=trainer_id, batch__is_archived=False)\
                .values('batch__batch_id', 'batch__batch_name', 'batch__title', 'course__course_id', 'course__course_name')\
                .distinct()
            category = CourseCategory.objects.filter(courses__batchcoursetrainer__trainer__employee_id=trainer_id)\
                .values('category_id', 'category_name').distinct()

            return Response({
                "success": True,
                "employee_id": trainer_id,
                "report": report,
                "courses": course,
                "batches": batch,
                "category": category
            })
        except Exception as e:
            return Response({"success": False, "message": str(e)})

class PaymentGatewayViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        """
        Return gateways depending on the user's role.
        Super admin sees all, admin/trainer sees their own.
        """
        user = self.request.user
        role = getattr(user, "user_type", None)

        qs = PaymentGateway.objects.all()

        if role in ["trainer", "admin"]:
            trainer_id = getattr(user, "trainer_id", None)
            qs = qs.filter(created_by=trainer_id, created_by_type=role)
        elif role == "super_admin":
            user_id = getattr(user, "user_id", None)
            qs = qs.filter(created_by=user_id, created_by_type=role)
        # students normally should not see gateways
        elif role == "student":
            qs = PaymentGateway.objects.none()

        return qs.order_by("-created_at")

    def list(self, request):
        queryset = self.get_queryset()
        serializer = PaymentGatewaySerializer(queryset, many=True)
        return Response({"success": True, "data": serializer.data})

    def create(self, request):
        serializer = PaymentGatewaySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "message": "Payment gateway created successfully.", "data": serializer.data}, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        try:
            queryset = self.get_queryset()  # <-- no arguments here
            gateway = queryset.filter(pk=pk).first()
            if not gateway:
                return Response({"success": False, "message": "Payment gateway not found."}, status=200)

            serializer = PaymentGatewaySerializer(gateway)
            return Response({"success": True, "data": serializer.data}, status=200)
        except Exception as e:
            return Response({"success": False, "message": f"Error retrieving data: {str(e)}"}, status=200)


    def update(self, request, pk=None):
        try:
            queryset = self.get_queryset()  # <-- no arguments here
            instance = queryset.filter(pk=pk).first()
            if not instance:
                return Response({"success": False, "message": "Payment gateway not found."}, status=200)

            partial = request.method == "PATCH"
            serializer = PaymentGatewaySerializer(instance, data=request.data, partial=partial, context={"request": request})
            if serializer.is_valid():
                serializer.save()
                return Response({
                    "success": True,
                    "message": "Payment gateway updated successfully.",
                    "data": serializer.data
                }, status=200)
            else:
                return Response({"success": False, "message": serializer.errors}, status=200)
        except Exception as e:
            return Response({"success": False, "message": f"Error updating gateway: {str(e)}"}, status=200)

    def destroy(self, request, pk=None):
        """
        Soft delete (archive) instead of actual deletion.
        """
        try:
            gateway = PaymentGateway.objects.filter(pk=pk).first()
            if not gateway:
                return Response({"success": False, "message": "Payment gateway not found."}, status=status.HTTP_200_OK)

            gateway.is_archived = True
            gateway.save(update_fields=["is_archived"])
            return Response({"success": True, "message": "Payment gateway archived successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": f"Error archiving gateway: {str(e)}"}, status=status.HTTP_200_OK)

class PaymentTransactionViewSet(viewsets.ViewSet):
    
    def get_queryset(self):
        return PaymentTransaction.objects.all()
    
    def list(self, request):
        user = request.user
        user_type = getattr(user, "user_type", "")
        user_created_id = getattr(user, "trainer_id", None)

        # For super_admin, created_id comes from user_id
        if user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)

        # ---------------- Fetch only students who have payments ----------------
        students_qs = Student.objects.filter(
            transactions__isnull=False,
            is_archived=False
        ).prefetch_related(
            Prefetch("transactions", queryset=PaymentTransaction.objects.select_related("course", "gateway")),
            Prefetch("emi_plans", queryset=PaymentEMI.objects.select_related("course").prefetch_related("installments"))
        )


        # ---------------- Apply hierarchy filters ----------------
        if user_type == "admin" and user_created_id:
            # Admin sees students created by them
            students_qs = students_qs.filter(created_by=user_created_id)

        elif user_type == "super_admin" and user_created_id:
            # Super admin sees students created by them + admin created students
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

            students_qs = students_qs.filter(
                Q(created_by_type='super_admin', created_by=user_created_id) |
                Q(created_by_type='admin', created_by__in=admin_ids)
            )

        else:
            # Non-admin / Non-super admin sees nothing
            students_qs = Student.objects.none()
            
        all_students = Student.objects.filter(
            status=True,
            is_archived=False
        )

        # Apply hierarchy filter for ALL STUDENTS
        if user_type == "admin" and user_created_id:
            all_students = all_students.filter(created_by=user_created_id)

        elif user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

            all_students = all_students.filter(
                Q(created_by_type='super_admin', created_by=user_created_id) |
                Q(created_by_type='admin', created_by__in=admin_ids)
            )

        else:
            all_students = Student.objects.none()

        # ---------------- Serialize summaries ----------------
        student_payment_summary_serializer = StudentPaymentSummarySerializer(
            students_qs, many=True
        )

        # ---------------- Simple student details list ----------------
        student_list = [
            {
                "student_id": s.student_id,
                "registration_id": s.registration_id,
                "student_name": f"{s.first_name} {s.last_name}",
                "email": s.email,
                "phone": s.contact_no
            }
            for s in all_students
        ]

        return Response({
            "success": True,
            "student_payment_summaries": student_payment_summary_serializer.data,
            "students": student_list
        }, status=200)

    def retrieve(self, request, pk=None):
        try:
            student = Student.objects.prefetch_related("transactions").get(student_id=pk)
        except Student.DoesNotExist:
            return Response({"success": False, "message": "Student not found"}, status=200)

        serializer = StudentPaymentSummarySerializer(student)
        return Response({
            "success": True,
            "student_payment_summary": serializer.data
        })
    
    def create(self, request):
        serializer = PaymentTransactionCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        transaction = serializer.save()

        # Return full details
        return Response({
            "success": True,
            'message': "Payment created successfully",
            "payment_transaction": PaymentTransactionDetailSerializer(transaction).data
        })

from django.conf import settings as django_settings
from stripe import _error as stripe_error
class StripePaymentViewSet(viewsets.ViewSet):

    @action(detail=False, methods=['post'])
    def create_payment(self, request):
        serializer = StripePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        student_id = getattr(request.user, "student_id", None)
        try:
            student = Student.objects.get(student_id=student_id)
        except Student.DoesNotExist:
            return Response({"success": False, "message": "Student does not exist."}, status=200)

        # Fetch Stripe gateway from DB
        stripe_gateway = PaymentGateway.objects.filter(gatway_name__icontains="stripe").first()
        # if not stripe_gateway:
        #     return Response({"success": False, "message": "Stripe is disabled or not configured"}, status=200)

        stripe.api_key = stripe_gateway.secret_key
        amount_in_paise = int(data['amount'] * 100)

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': stripe_gateway.currency or 'INR',
                        'product_data': {'name': 'Course Payment'},
                        'unit_amount': amount_in_paise,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=data['success_url'],
                cancel_url=data['cancel_url'],
            )
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

        PaymentTransaction.objects.create(
            student=student,
            gateway=stripe_gateway,
            amount=data['amount'],
            currency=stripe_gateway.currency or 'INR',
            payment_status='pending',
            order_id=session.id,
            description="Payment via Stripe",
        )

        return Response({"success": True, "checkout_url": session.url})

    @csrf_exempt
    @action(detail=False, methods=['post'], url_path='webhook')
    def stripe_webhook(self, request):
        # Fetch Stripe gateway credentials
        stripe_gateway = PaymentGateway.objects.filter(gatway_name__icontains="stripe", is_enabled=True).first()
        if not stripe_gateway or not stripe_gateway.webhook_secret:
            return HttpResponse(status=400)

        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, stripe_gateway.webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError):
            return HttpResponse(status=200)

        # --------------- Handle Stripe Events ----------------
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            transaction = PaymentTransaction.objects.filter(order_id=session.get('id')).first()
            if transaction:
                transaction.payment_status = "done"
                transaction.transaction_id = session.get('payment_intent')
                transaction.save()

        elif event['type'] == 'checkout.session.expired':
            session = event['data']['object']
            transaction = PaymentTransaction.objects.filter(order_id=session.get('id')).first()
            if transaction:
                transaction.payment_status = "failed"
                transaction.save()

        elif event['type'] == 'payment_intent.payment_failed':
            intent = event['data']['object']
            transaction = PaymentTransaction.objects.filter(transaction_id=intent.get('id')).first()
            if transaction:
                transaction.payment_status = "failed"
                transaction.save()

        return HttpResponse(status=200)

    def generate_invoice(self, transaction):
            student = transaction.student
            settings_obj = Settings.objects.first()

            # Convert amount to words
            amount_words = num2words(transaction.amount, to='currency', lang='en_IN')

            # Create Invoice object (auto-generates invoice_number)
            invoice = Invoice.objects.create(
                student=student,
                buyer_name=student.full_name,
                buyer_address=getattr(student, "address", ""),
                buyer_mobile=getattr(student, "mobile", ""),
                description=transaction.description,
                quantity=1,
                rate=transaction.amount,
                amount=transaction.amount,
                per="Nos",
                amount_in_words=amount_words,
                payment_terms="Immediate",
                created_by=transaction.created_by,
                created_by_type=transaction.created_by_type,
            )

            # Generate PDF
            pdf_buffer = io.BytesIO()
            pdf = canvas.Canvas(pdf_buffer, pagesize=A4)
            pdf.setTitle(f"Invoice {invoice.invoice_number}")
            pdf.drawString(50, 800, f"Invoice No: {invoice.invoice_number}")
            pdf.drawString(50, 780, f"Date: {invoice.date}")
            pdf.drawString(50, 760, f"Company: {settings_obj.company_name}")
            pdf.drawString(50, 740, f"Bank: {settings_obj.bank_name} A/C: {settings_obj.bank_account_no} IFSC: {settings_obj.bank_ifsc}")
            pdf.drawString(50, 720, f"Student: {invoice.buyer_name}")
            pdf.drawString(50, 700, f"Description: {invoice.description}")
            pdf.drawString(50, 680, f"Amount: {invoice.amount} INR ({invoice.amount_in_words})")
            pdf.drawString(50, 660, f"Declaration: {settings_obj.declaration or ''}")
            pdf.showPage()
            pdf.save()
            pdf_buffer.seek(0)

            # Save PDF to invoice model
            file_name = f"invoice_{invoice.invoice_number}.pdf"
            invoice.pdf_file.save(file_name, pdf_buffer)
            invoice.save()

            # Send email to student
            if student.email:
                email = EmailMessage(
                    subject=f"Invoice {invoice.invoice_number}",
                    body=f"Dear {student.full_name},\n\nPlease find attached your invoice.",
                    to=[student.email]
                )
                email.attach(file_name, pdf_buffer.getvalue(), 'application/pdf')
                email.send()

import paypalrestsdk

class PayPalPaymentViewSet(viewsets.ViewSet):

    @action(detail=False, methods=['post'])
    def create_payment(self, request):
        serializer = PayPalPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        student_id = getattr(request.user, "student_id", None)
        try:
            student = Student.objects.get(student_id=student_id)
        except Student.DoesNotExist:
            return Response({"success": False, "message": "Student does not exist."}, status=200)

        settings_obj = Settings.objects.first()
        if not settings_obj or not getattr(settings_obj, "paypal_enabled", False):
            return Response({"success": False, "message": "PayPal is disabled in settings."}, status=200)

        # Fetch PayPal keys from PaymentGateway
        paypal_gateway = PaymentGateway.objects.filter(gatway_name__icontains="paypal").first()
        if not paypal_gateway:
            return Response({"success": False, "message": "PayPal keys not configured."}, status=200)

        paypalrestsdk.configure({
            "mode": "sandbox",  # or "live"
            "client_id": paypal_gateway.public_key,
            "client_secret": paypal_gateway.secret_key
        })

        payment = paypalrestsdk.Payment({
            "intent": "sale",
            "payer": {"payment_method": "paypal"},
            "redirect_urls": {
                "return_url": data['success_url'],
                "cancel_url": data['cancel_url'],
            },
            "transactions": [{
                "amount": {
                    "total": str(data['amount']),
                    "currency": "USD"
                },
                "description": "Course Payment"
            }]
        })

        if payment.create():
            PaymentTransaction.objects.create(
                student=student,
                gateway=paypal_gateway,
                amount=data['amount'],
                currency=paypal_gateway.currency or "USD",
                payment_status="pending",
                order_id=payment.id,
                description="Payment via PayPal",
            )

            for link in payment.links:
                if link.rel == "approval_url":
                    return Response({"success": True, "approval_url": str(link.href)})

            return Response({"success": False, "message": "No approval URL found."}, status=200)
        else:
            return Response({"success": False, "message": payment.error}, status=200)

    @csrf_exempt
    @action(detail=False, methods=['post'], url_path='webhook')
    def paypal_webhook(self, request):
        settings_obj = Settings.objects.first()
        if not settings_obj or not getattr(settings_obj, "paypal_enabled", False):
            return HttpResponse(status=400)

        paypal_gateway = PaymentGateway.objects.filter(gatway_name__icontains="paypal").first()
        if not paypal_gateway:
            return HttpResponse(status=400)

        event = request.data
        event_type = event.get('event_type')
        resource = event.get('resource', {})

        if event_type in ["PAYMENT.SALE.COMPLETED", "CHECKOUT.ORDER.APPROVED"]:
            order_id = resource.get('id') or resource.get('invoice_id')
            transaction = PaymentTransaction.objects.filter(order_id=order_id).first()
            if transaction:
                transaction.payment_status = "done"
                transaction.transaction_id = resource.get('id')
                transaction.save()
                # Reuse your existing invoice generator
                StripePaymentViewSet().generate_invoice(transaction)

        return HttpResponse(status=200)

class RazorpayPaymentViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_client(self):
        gateway = PaymentGateway.objects.filter(gatway_name__icontains="razorpay_test").first()
        if not gateway:
            return None, None
        client = razorpay.Client(auth=(gateway.public_key, gateway.secret_key))
        return client, gateway

    # -------------------------
    # Create Razorpay Payment Link
    # -------------------------
    @action(detail=False, methods=['post'])
    def create(self, request):
        amount = float(request.data.get("amount", 0))
        currency = request.data.get("currency", "INR")
        success_url = request.data.get("success_url")
        cancel_url = request.data.get("failure_url")

        if not amount or not success_url or not cancel_url:
            return Response({"success": False, "message": "Amount, success_url, and cancel_url are required"}, status=400)

        student_id = getattr(request.user, "student_id", None)
        student = Student.objects.filter(student_id=student_id).first()
        if not student:
            return Response({"success": False, "message": "Student not found"}, status=404)

        client, gateway = self._get_client()
        if not client:
            return Response({"success": False, "message": "Razorpay not configured"}, status=400)

        try:
            payment_link_data = {
                "amount": int(amount * 100),  # in paise
                "currency": currency,
                "accept_partial": False,
                "description": f"Payment by {student.student_id}",
                "customer": {
                    "name": student.first_name + " " + student.last_name,
                    "email": student.email,
                    "contact": student.contact_no
                },
                "notify": {"sms": True, "email": True},
                "reminder_enable": True,
                "callback_url": success_url,
                "callback_method": "get"
            }

            payment_link = client.payment_link.create(payment_link_data)

            # Save transaction as pending
            PaymentTransaction.objects.create(
                student=student,
                gateway=gateway,  # link your PaymentGateway if needed
                amount=amount,
                currency=currency,
                payment_status="pending",
                order_id=payment_link.get("id"),
                description="Payment via Razorpay Link",
                created_at=timezone.now()
            )

            return Response({
                "success": True,
                "payment_url": payment_link.get("short_url"),  # direct payment link
                "order_id": payment_link.get("id")
            })

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=500)

    # -------------------------
    # Verify Razorpay Payment
    # -------------------------
    @csrf_exempt
    @action(detail=False, methods=['post'], url_path="verify")
    def verify_payment(self, request):
        payment_id = request.data.get("razorpay_payment_id")
        order_id = request.data.get("razorpay_order_id")
        signature = request.data.get("razorpay_signature")

        if not payment_id or not order_id or not signature:
            return Response({"success": False, "message": "Required parameters missing"}, status=400)

        client, _ = self._get_client()
        if not client:
            return Response({"success": False, "message": "Razorpay not configured"}, status=400)

        # Verify signature
        try:
            params = {
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature
            }
            client.utility.verify_payment_signature(params)

            transaction = PaymentTransaction.objects.filter(order_id=order_id).first()
            if transaction:
                transaction.payment_status = "done"
                transaction.transaction_id = payment_id
                transaction.save()

                # Generate invoice
                StripePaymentViewSet().generate_invoice(transaction)

            return Response({"success": True, "message": "Payment verified successfully"})
        except razorpay.errors.SignatureVerificationError:
            return Response({"success": False, "message": "Payment verification failed"}, status=200)

@api_view(['GET'])
def stripe_success(request):
    return Response({"success": True, "message": "Payment successful!"})

@api_view(['GET'])
def stripe_cancel(request):
    return Response({"success": False, "message": "Payment canceled!"})

class SubAdminViewSet(viewsets.ModelViewSet):
    serializer_class = SubAdminSerializer
    queryset = SubAdmin.objects.all()
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset().filter(is_archived=False)

        user_created_id = None
        if user.user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)
        elif user.user_type == "admin":
            user_created_id = getattr(user, "trainer_id", None)

        # --- Admin IDs for this super admin ---
        admin_ids = []
        if user.user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

        # --- Super Admin view ---
        if user.user_type == "super_admin" and user_created_id:
            qs = qs.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )

        # --- Admin view (FIXED) ---
        elif user.user_type == "admin" and user_created_id:

            # Find super admin who created this admin
            super_admin_id = Trainer.objects.filter(
                trainer_id=user_created_id,
                created_by_type="super_admin"
            ).values_list("created_by", flat=True).first()

            qs = qs.filter(
                Q(created_by_type="super_admin", created_by=super_admin_id) |
                Q(created_by_type="admin", created_by=user_created_id)
            )

        return qs.order_by('-employer_id')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        user = request.user
        user_created_id = None
        if user.user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)
        elif user.user_type == "admin":
            user_created_id = getattr(user, "trainer_id", None)

        # --- Admin IDs for super admin ---
        admin_ids = []
        if user.user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

        # --- Companies filtering ---
        companies = Employer.objects.filter(is_archived=False).order_by('-created_at')
        if user.user_type == "super_admin" and user_created_id:
            companies = companies.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )
        elif user.user_type == "admin" and user_created_id:

            # Find the super admin who created this admin
            super_admin_id = Trainer.objects.filter(
                trainer_id=user_created_id,
                created_by_type="super_admin"
            ).values_list("created_by", flat=True).first()

            companies = companies.filter(
                Q(created_by_type="super_admin", created_by=super_admin_id) |
                Q(created_by_type="admin", created_by=user_created_id)
            )

        company_data = companies.values("company_id", "company_name")

        return Response({
            "success": True,
            "message": "SubAdmins retrieved successfully",
            "data": serializer.data,
            "companies": company_data
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        user = request.user
        
        # Ensure module_id points to Sub_Admin
        subadmin_module = ModulePermission.objects.filter(module__iexact="Organization Employer").first()
        if not subadmin_module:
            return Response({"success": False, "message": "Sub Admin module not found"}, status=200)

        if not has_permission(user, module_id=subadmin_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)

        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "SubAdmin created successfully",
                "data": serializer.data
            }, status=status.HTTP_200_OK)

        error_dict = serializer.errors

        if error_dict:
            # Get the first key (field name)
            first_field = list(error_dict.keys())[0]

            # Access the first error message from that field's list
            first_error_message = error_dict[first_field][0]

        return Response({
            "success": False,
            "message": first_error_message
        }, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        user = request.user

        # Ensure module_id points to Sub_Admin
        subadmin_module = ModulePermission.objects.filter(module__iexact="Organization Employer").first()
        if not subadmin_module:
            return Response({"success": False, "message": "Sub_Admin module not found"}, status=200)

        if not has_permission(user, module_id=subadmin_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)
        
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request':request})

        # Save notes if provided in request
        notes_text = request.data.get("notes")
        if notes_text:
            mixin = NotesMixin()
            mixin.save_notes(instance, notes_text, request=request)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "SubAdmin updated successfully",
                "data": serializer.data
            }, status=status.HTTP_200_OK)

        error_dict = serializer.errors

        if error_dict:
            # Get the first key (field name)
            first_field = list(error_dict.keys())[0]

            # Access the first error message from that field's list
            first_error_message = error_dict[first_field][0]

        return Response({
            "success": False,
            "message": first_error_message
        }, status=status.HTTP_200_OK)
        
    def is_archived(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_archived = True
        instance.save()
        return Response({
            "success": True,
            "message": "SubAdmin Deleted successfully"
        }, status=status.HTTP_200_OK)
        
    @action(detail=True, methods=['patch'], url_path='reset_password')
    def reset_password(self, request, pk=None):
        try:
            """
            Reset student password (admin only)
            """
            # Authenticate using your custom JWT
            auth = CustomJWTAuthentication()
            try:
                user, _ = auth.authenticate(request)
            except AuthenticationFailed as e:
                return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

            # Ensure only admin can reset
            if not hasattr(user, 'user_type') or user.user_type.lower() not in ['admin', 'super_admin']:
                return Response(
                    {"success": False, "message": "Only admin or super admin users can reset Sub admin passwords."},
                    status=status.HTTP_200_OK
                )

            # Get new password
            new_password = request.data.get('new_password')
            if not new_password:
                return Response({"success": False, "message": "New password is required."}, status=status.HTTP_200_OK)
            
            try:
                validate_password(new_password)
            except serializers.ValidationError as e:
                return Response({"success": False, "message": str(e.detail[0])}, status=status.HTTP_200_OK)

            try:
                subadmin = self.get_object()
            except SubAdmin.DoesNotExist:
                return Response({"success": False, "message": "Sub admin not found."}, status=status.HTTP_200_OK)

            # Update subadmin password directly
            subadmin.password = make_password(new_password)
            subadmin.save()

            return Response({"success": True, "message": "Password reset successfully."}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

class EmployerViewSet(viewsets.ModelViewSet):
    serializer_class = EmployerSerializer
    queryset = Employer.objects.all()
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset().filter(is_archived=False)

        # Identify user created id
        user_created_id = None
        if user.user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)
        elif user.user_type == "admin":
            user_created_id = getattr(user, "trainer_id", None)

        admin_ids = []
        if user.user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

        if user.user_type == "super_admin" and user_created_id:
            qs = qs.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )
        elif user.user_type == "admin" and user_created_id:
            qs = qs.filter(
                created_by_type="admin",
                created_by=user_created_id
            )

        return qs.order_by("-company_id")

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        return Response({
            "success": True,
            "message": "Employers retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        
        serializer = self.get_serializer(data=request.data)
        user = request.user
        
        # Ensure module_id points to Organization
        employer_module = ModulePermission.objects.filter(module__iexact="Organizations").first()
        if not employer_module:
            return Response({"success": False, "message": "Organization module not found"}, status=200)

        if not has_permission(user, module_id=employer_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)
        
        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "Employer created successfully",
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        # Flatten errors to a single string
        error_messages = []
        for field, messages in serializer.errors.items():
            for msg in messages:
                msg_str = str(msg)
                if "Ensure this field" in msg_str:
                    # Replace "this field" with actual field name
                    msg_str = msg_str.replace("this field", field)
                    error_messages.append(f"{msg_str}")
                else:
                    # Generic prepend
                    error_messages.append(f"Ensure the {field} {msg_str}")

        error_message = ". ".join(error_messages) + "."

        return Response({
            "success": False,
            "message": error_message
        }, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        
        user = request.user

        # Ensure module_id points to Organization
        organization_module = ModulePermission.objects.filter(module__iexact="Organizations").first()
        if not organization_module:
            return Response({"success": False, "message": "Organization module not found"}, status=200)

        if not has_permission(user, module_id=organization_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)

        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={"request":request})
        # Save notes if provided in request
        notes_text = request.data.get("notes")
        if notes_text:
            mixin = NotesMixin()
            mixin.save_notes(instance, notes_text, request=request)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "Employer updated successfully",
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        # Flatten errors to a single string
        error_messages = []
        for field, messages in serializer.errors.items():
            for msg in messages:
                msg_str = str(msg)
                if "Ensure this field" in msg_str:
                    # Replace "this field" with actual field name
                    msg_str = msg_str.replace("this field", field)
                    error_messages.append(f"{msg_str}")
                else:
                    # Generic prepend
                    error_messages.append(f"Ensure the {field} {msg_str}")

        error_message = ". ".join(error_messages) + "."
        return Response({
            "success": False,
            "message": error_message,
        }, status=status.HTTP_200_OK)

    def is_archived(self, request, pk=None):
        instance = self.get_object()
        instance.is_archived = True
        instance.save()
        return Response({
            "success": True,
            "message": "Employer deleted successfully",
            "data": {}
        }, status=status.HTTP_200_OK)

class EmployerDashboardViewSet(ViewSet):
    lookup_field = 'company_id'
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    """
    Employees, Courses, Attendance for a company (filtered by company_name)
    """

    def employees(self, request, company_id=None):
        """List all employees for the given company"""
        try:
            if not company_id:
                return Response({
                    "success": False,
                    "message": "Company ID not provided",
                }, status=200)

            # Filter only employees (students linked to a company)
            students_qs = Student.objects.filter(
                is_archived=False
            ).filter(
                Q(employee__company_id=company_id) |
                Q(school_student__company_id=company_id) |
                Q(college_student__company_id=company_id) |
                Q(jobseeker__company_id=company_id)
            ).distinct().select_related('employee').prefetch_related(
                Prefetch(
                    'batchcoursetrainer_set__course',  # follow BatchCourseTrainer relation to course
                    queryset=Course.objects.filter(is_archived=False),
                    to_attr='assigned_courses'  # store them in student.assigned_courses
                )
            ).order_by('-registration_id')

            serializer = StudentProfileSerializer(students_qs, many=True, context={'request': request})

            courses = Course.objects.filter(is_archived=False, status__iexact='Active')
            courses_list = [
                {
                    "course_id": course.course_id,
                    "course_name": course.course_name,
                    "category_id": course.course_category.category_id,
                    "category_name": course.course_category.category_name,
                }
                for course in courses
            ]

            return Response({
                "success": True,
                "data": serializer.data,
                "courses": courses_list
            }, status=200)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e),
                "data": {}
            }, status=200)

    def attendance(self, request, company_id=None):
        """Return attendance logs for all employees in the given company"""
        try:
            if not company_id:
                return Response({"success": False, "message": "Company ID not provided", "data": {}}, status=200)

            attendance_qs = Attendance.objects.filter(
                student__is_archived=False
            ).filter(
                Q(student__employee__company_id=company_id) |
                Q(student__school_student__company_id=company_id) |
                Q(student__college_student__company_id=company_id) |
                Q(student__jobseeker__company_id=company_id)
            ).values(
                "student__registration_id","student__first_name", "student__last_name",  'batch__batch_name', "course__course_name", "ip_address", "date", "status", 'course__course_id', 'batch__batch_id', 'batch__title',
            ).order_by('-date')

            ist = pytz.timezone('Asia/Kolkata')
            logs=[]

            for att in attendance_qs:
                # Convert to IST
                date_ist = att['date']
                if date_ist.tzinfo is None:
                    # naive datetime, assume UTC first then convert to IST
                    date_ist = pytz.utc.localize(date_ist).astimezone(ist)
                else:
                    # aware datetime, convert to IST
                    date_ist = date_ist.astimezone(ist)
                    
                logs.append({
                    "name": att.get("student__first_name", "") + " " + att.get("student__last_name", ""),
                    "course": att.get("course__course_name", ""),
                    "course_id": att.get("course__course_id", ""),
                    "status": att.get("status", ""),
                    "batch": att.get("batch__batch_name", ""),
                    "title": att.get("batch__title", ""),
                    'batch_id': att.get("batch__batch_id", ""),
                    "ip": att.get("ip_address", ""),
                    "date_time": date_ist.strftime("%Y-%m-%d %I:%M:%S %p")
                })
            courses = Course.objects.filter(is_archived=False, status__iexact='Active')
            courses_list = [
                {
                    "course_id": course.course_id,
                    "course_name": course.course_name,
                    "category_id": course.course_category.category_id,
                    "category_name": course.course_category.category_name,
                }
                for course in courses
            ]
            batches = Batch.objects.filter(is_archived=False, status = True)
            batch_list = [
                {
                    'batch_id':batch.batch_id,
                    'title': batch.title,
                    'batch_name': batch.batch_name,
                }
                for batch in batches
            ]

            return Response({"success": True, 
                             "attendance_logs": logs,
                             "course":courses_list,
                             "batch":batch_list
                             }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e), "data": {}}, status=200)

def jwt_required(view_func):
    def wrapped_view(request, *args, **kwargs):
        token = request.META.get('HTTP_AUTHORIZATION')
        if not token:
            raise AuthenticationFailed("No token provided")

        try:
            token = token.replace("Bearer ", "")
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])

            if payload.get('exp') < int(datetime.now().timestamp()):
                raise AuthenticationFailed("Token has expired")

            # You could attach user info to request here if needed
            request.user_payload = payload

        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Token has expired")
        except jwt.DecodeError:
            raise AuthenticationFailed("Invalid token")

        return view_func(request, *args, **kwargs)
    return wrapped_view

@api_view(['GET'])
@jwt_required
def protected_view(request):
    return Response({'message': 'You are authorized'})

    
def flatten_errors(errors, parent_key=''):
    error_messages = []

    if isinstance(errors, dict):
        for field, value in errors.items():
            # Build full field path for nested fields
            full_key = f"{parent_key}.{field}" if parent_key else field
            error_messages.extend(flatten_errors(value, full_key))
    elif isinstance(errors, list):
        for msg in errors:
            msg_str = str(msg)
            if "this field" in msg_str:
                # Replace "this field" with actual field path
                msg_str = msg_str.replace("this field", parent_key)
            else:
                msg_str = f"Ensure {msg_str}"
            error_messages.append(msg_str)
    else:
        error_messages.append(f"Ensure {errors}")

    return error_messages

class StudentRegistration(viewsets.ModelViewSet):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def perform_create(self, serializer):

        user = self.request.user  # this is JWTUser from your CustomJWTAuthentication
        admin_trainer_id = getattr(user, "trainer_id", None)

        serializer.save(created_by=admin_trainer_id)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        user = request.user
        
        # Ensure module_id points to Students
        student_module = ModulePermission.objects.filter(module__iexact="Students").first()
        if not student_module:
            return Response({"success": False, "message": "Students module not found"}, status=200)

        if not has_permission(user, module_id=student_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)
        
        # Validate without raising exception
        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "success": False,
                "message": error_message
            }, status=status.HTTP_200_OK)

        # Save and return proper response
        student = serializer.save()
        headers = self.get_success_headers(serializer.data)

        return Response({
            "success": True,
            "message": "Student registered successfully.",
            "registration_id": student.registration_id  # or other relevant field
        }, status=status.HTTP_201_CREATED, headers=headers)


class StudentListAPIView(viewsets.ViewSet):

    def get(self, request):
        try:
            user = request.user
            user_type = user.user_type  # super_admin / admin / trainer / student

            if user_type == "super_admin":
                creator_id = user.user_id  # super admin ID from User table
                super_admin_id = creator_id

            elif user_type == "admin":
                creator_id = user.trainer_id  # admin ID from Trainer table
                super_admin_id = None  # will be discovered below

            elif user_type == "trainer":
                creator_id = user.trainer_id  # trainer ID
                super_admin_id = None

            elif user_type == "student":
                creator_id = user.student_id  # student ID
                super_admin_id = None

            else:
                creator_id = None
                super_admin_id = None

            admin_ids = []

            if user_type == "super_admin":
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=creator_id,
                        created_by_type="super_admin",
                        user_type="admin"
                    ).values_list("trainer_id", flat=True)
                )

            if user_type == "admin":
                admin_obj = Trainer.objects.filter(trainer_id=creator_id).first()
                if admin_obj and admin_obj.created_by_type == "super_admin":
                    super_admin_id = admin_obj.created_by

            students_qs = Student.objects.filter(is_archived=False)

            if user_type == "super_admin":
                students_qs = students_qs.filter(
                    Q(created_by=creator_id, created_by_type="super_admin") |
                    Q(created_by__in=admin_ids, created_by_type="admin")
                )

            elif user_type == "admin":
                students_qs = students_qs.filter(
                    Q(created_by=creator_id, created_by_type="admin") |
                    Q(created_by=super_admin_id, created_by_type="super_admin")
                )

            elif user_type == "trainer":
                students_qs = Student.objects.none()

            elif user_type == "student":
                students_qs = students_qs.filter(student_id=creator_id)

            else:
                students_qs = Student.objects.none()

            students_qs = students_qs.select_related(
                "school_student", "college_student",
                "jobseeker", "employee"
            ).prefetch_related(
                Prefetch(
                    "notes",
                    queryset=Note.objects.all().order_by("-created_at"),
                    to_attr="prefetched_notes"
                )
            )

            response_data = []

            for s in students_qs:

                notes = [{
                    "note_id": n.id,
                    "reason": n.reason,
                    "status": n.status,
                    "created_by": n.created_by,
                    "created_at": n.created_at,
                } for n in getattr(s, "prefetched_notes", [])]

                # Resolve company
                company_id = None
                if hasattr(s, "employee") and s.employee.company_id:
                    company_id = s.employee.company_id.company_id
                elif hasattr(s, "jobseeker") and s.jobseeker.company_id:
                    company_id = s.jobseeker.company_id.company_id
                elif hasattr(s, "college_student") and s.college_student.company_id:
                    company_id = s.college_student.company_id.company_id
                elif hasattr(s, "school_student") and s.school_student.company_id:
                    company_id = s.school_student.company_id.company_id

                # ---------------------------------------------------------
                #  AGGREGATE ALL BATCH/COURSE/CATEGORY FROM OLD + NEW
                # ---------------------------------------------------------

                batch_id_list = []
                title_list = []
                course_id_list = []
                course_name_list = []
                category_id_list = []
                category_name_list = []

                # ---------------------------------------
                # OLD SYSTEM BATCHES (Batch + BCT)
                # ---------------------------------------
                old_bct = BatchCourseTrainer.objects.filter(
                    student=s,
                    batch__is_archived=False
                ).select_related("batch", "course__course_category")

                for b in old_bct:
                    batch = b.batch
                    course = b.course
                    category = course.course_category if course else None

                    batch_id_list.append(batch.batch_id)
                    title_list.append(batch.title or batch.batch_name)
                    course_id_list.append(course.course_id if course else None)
                    course_name_list.append(course.course_name if course else None)
                    category_id_list.append(category.category_id if category else None)
                    category_name_list.append(category.category_name if category else None)

                # ---------------------------------------
                # NEW SYSTEM BATCHES (NewBatch)
                # ---------------------------------------
                new_batches = NewBatch.objects.filter(
                    students=s,
                    is_archived=False
                ).select_related("course__course_category")

                for nb in new_batches:
                    course = nb.course
                    category = course.course_category if course else None

                    batch_id_list.append(nb.batch_id)
                    title_list.append(nb.title)
                    course_id_list.append(course.course_id if course else None)
                    course_name_list.append(course.course_name if course else None)
                    category_id_list.append(category.category_id if category else None)
                    category_name_list.append(category.category_name if category else None)

                # Remove duplicates while preserving order
                def unique_list(values):
                    return list(dict.fromkeys(v for v in values if v is not None))

                batch_id_list = unique_list(batch_id_list)
                title_list = unique_list(title_list)
                course_id_list = unique_list(course_id_list)
                course_name_list = unique_list(course_name_list)
                category_id_list = unique_list(category_id_list)
                category_name_list = unique_list(category_name_list)

                response_data.append({
                    "registration_id": s.registration_id,
                    "student_id": s.student_id,
                    "first_name": s.first_name,
                    "last_name": s.last_name,
                    "username": s.username,
                    "dob": s.dob,
                    "email": s.email,
                    "contact_no": s.contact_no,
                    "current_address": s.current_address,
                    "permanent_address": s.permanent_address,
                    "city": s.city,
                    "company_id": company_id,
                    "parent_guardian_name": s.parent_guardian_name,
                    "parent_guardian_phone": s.parent_guardian_phone,
                    "parent_guardian_occupation": s.parent_guardian_occupation,
                    "reference_number": s.reference_number,
                    "state": s.state,
                    "student_type": s.student_type,
                    "country": s.country,
                    "status": s.status,
                    "notes": notes,
                    "joining_date": s.joining_date,
                    "created_by": s.created_by,
                    "created_by_type": s.created_by_type,
                    "created_at": s.created_at,
                    "batch_id": batch_id_list,
                    "batch_title": title_list,
                    "course_id": course_id_list,
                    "course_name": course_name_list,
                    "category_id": category_id_list,
                    "category_name": category_name_list,
                    "profile_pic": (
                        f"https://aylms.aryuprojects.com/api{s.profile_pic.url}"
                        if s.profile_pic else None
                    ),

                    "school_student": (
                        School_StudentSerializer(s.school_student).data
                        if hasattr(s, "school_student") else None
                    ),
                    "college_student": (
                        College_StudentSerializer(s.college_student).data
                        if hasattr(s, "college_student") else None
                    ),
                    "jobseeker": (
                        JobSeekerSerializer(s.jobseeker).data
                        if hasattr(s, "jobseeker") else None
                    ),
                    "employee": (
                        EmployeeSerializer(s.employee).data
                        if hasattr(s, "employee") else None
                    ),
                })

            # SUPER ADMIN
            if user_type == "super_admin":
                role_filter = (
                    Q(created_by=creator_id, created_by_type="super_admin") |
                    Q(created_by__in=admin_ids, created_by_type="admin")
                )

            # ADMIN
            elif user_type == "admin":
                role_filter = (
                    Q(created_by=creator_id, created_by_type="admin") |
                    Q(created_by=super_admin_id, created_by_type="super_admin")
                )

            # OTHERS → no access
            else:
                role_filter = Q(created_by=-1)

            # ===============================================================
            # COURSES
            # ===============================================================
            courses = list(
                Course.objects.filter(is_archived=False).filter(role_filter).values(
                    "course_id",
                    "course_name",
                    category_id=F("course_category_id"),
                    category_name=F("course_category__category_name")
                )
            )

            # ===============================================================
            # CATEGORIES
            # ===============================================================
            categories = list(
                CourseCategory.objects.filter(is_archived=False).filter(role_filter).values(
                    "category_id", "category_name"
                )
            )

            # ===============================================================
            # COMPANIES
            # ===============================================================
            companies = list(
                Employer.objects.filter(is_archived=False, status=True).filter(role_filter).values(
                    "company_id", "company_name"
                )
            )

            # ===============================================================
            # OLD SYSTEM BATCHES (using Batch table for filtering)
            # ===============================================================
            all_batches = []

            old_batches = Batch.objects.filter(is_archived=False).filter(role_filter)

            old_bct = BatchCourseTrainer.objects.filter(
                batch__in=old_batches
            ).select_related("batch", "course__course_category")

            for bct in old_bct:
                course = bct.course
                category = course.course_category if course else None

                all_batches.append({
                    "batch_id": bct.batch.batch_id,
                    "title": getattr(bct.batch, "title", bct.batch.batch_name),
                    "course_id": course.course_id if course else None,
                    "course_name": course.course_name if course else None,
                    "category_id": category.category_id if category else None,
                    "category_name": category.category_name if category else None,
                    "created_at": bct.batch.created_at
                })

            # ===============================================================
            # NEW SYSTEM BATCHES
            # ===============================================================
            new_batches = NewBatch.objects.filter(
                is_archived=False,
                status=True
            ).filter(role_filter).select_related("course__course_category")

            for nb in new_batches:
                course = nb.course
                category = course.course_category if course else None

                all_batches.append({
                    "batch_id": nb.batch_id,
                    "title": nb.title,
                    "course_id": course.course_id if course else None,
                    "course_name": course.course_name if course else None,
                    "category_id": category.category_id if category else None,
                    "category_name": category.category_name if category else None,
                    "created_at": nb.created_at
                })

            all_batches = sorted(all_batches, key=lambda x: x["created_at"], reverse=True)
            
            all_batches = list({b["batch_id"]: b for b in all_batches}.values())

            return Response({
                "success": True,
                "students": response_data,
                "courses": courses,
                "categories": categories,
                "batches": all_batches,
                "companies": companies
            }, status=200)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=200)


class StudentTicketViewSet(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    # Optimized base queryset with prefetch
    def get_queryset(self):
        return StudentTicket.objects.select_related(
            "student", 
            "handled_by_trainer", 
            "handled_by_superadmin"
        ).prefetch_related(
            "attachments",
            Prefetch(
                "replies",
                queryset=TicketReply.objects.select_related(
                    "student", "trainer", "super_admin"
                ).order_by("created_at")
            )
        ).annotate(replies_count=Count("replies"))

    # GET: List or Detail

    def get(self, request):
        user_type = getattr(request.user, "user_type", None)

        # My Tickets (Student)
        if request.query_params.get("type") == "iron_man":
            if user_type != "student":
                return Response({"success": False, "message": "Access denied"}, status=403)

            queryset = self.get_queryset().filter(student__student_id=request.user.student_id)

            # Get counts in ONE query
            counts = queryset.aggregate(
                new=Count(Case(When(status="new", then=1), output_field=IntegerField())),
                in_progress=Count(Case(When(status="in_progress", then=1), output_field=IntegerField())),
                closed=Count(Case(When(status="closed", then=1), output_field=IntegerField())),
            )

            tickets = queryset.order_by("-ticket_id")

            return Response({
                "success": True,
                "new": counts["new"] or 0,
                "in_progress": counts["in_progress"] or 0,
                "closed": counts["closed"] or 0,
                "tickets": StudentTicketSerializer(tickets, many=True, context={'request': request}).data
            })

        # All Tickets (Admin / SuperAdmin)
        if request.query_params.get("type") == "wonder_women":
            if user_type not in ("admin", "super_admin"):
                return Response({"success": False, "message": "Access denied"}, status=403)

            scope = self.get_admin_scope(request.user)
            queryset = self.get_queryset().filter(scope)

            # Get counts
            counts = queryset.aggregate(
                new=Count(Case(When(status="new", then=1), output_field=IntegerField())),
                in_progress=Count(Case(When(status="in_progress", then=1), output_field=IntegerField())),
                closed=Count(Case(When(status="closed", then=1), output_field=IntegerField())),
            )

            tickets = queryset.order_by("-ticket_id")

            return Response({
                "success": True,
                "new": counts["new"] or 0,
                "in_progress": counts["in_progress"] or 0,
                "closed": counts["closed"] or 0,
                "tickets": StudentTicketSerializer(tickets, many=True, context={'request': request}).data
            })

        # Ticket Detail (unchanged)
        if request.query_params.get("natasha"):
            try:
                ticket_id = int(request.query_params["natasha"])
            except ValueError:
                return Response({"success": False, "message": "Invalid ticket_id"}, status=400)

            ticket = self.get_queryset().filter(ticket_id=ticket_id).first()
            if not ticket:
                return Response({"success": False, "message": "Ticket not found"}, status=404)

            return Response({
                "success": True,
                "data": TicketDetailSerializer(ticket, context={'request': request}).data
            })

        return Response({"success": False, "message": "Invalid request"}, status=400)

    # POST: Create, Reply, or Close
    def post(self, request):
        # Reply to ticket
        if request.query_params.get("bat_man"):
            return self.reply_to_ticket(request)

        # Close ticket
        if request.query_params.get("close"):
            return self.close_ticket(request)

        # Default: Create new ticket
        return self.create_ticket(request)

    # Create new ticket
    from .utils import get_real_user
    def create_ticket(self, request):
        
        if getattr(request.user, "user_type", None) != "student":
            return Response({"success": False, "message": "Only students can create tickets"}, status=status.HTTP_403_FORBIDDEN)

        student = Student.objects.filter(student_id=getattr(request.user, "student_id", None)).first()
        if not student:
            return Response({"success": False, "message": "Student not found"}, status=status.HTTP_400_BAD_REQUEST)

        subject = request.data.get("subject", "").strip()
        message = request.data.get("message", "").strip()
        priority = request.data.get("priority", "medium")

        if not subject or not message:
            return Response({"success": False, "message": "Subject and message are required"}, status=status.HTTP_400_BAD_REQUEST)

        real_user = self.get_real_user(request.user)

        ticket = StudentTicket.objects.create(
            student=student,
            subject=subject,
            message=message,
            priority=priority,
            status="new",
            updated_by=real_user
        )

        # Handle attachments
        for file in request.FILES.getlist("attachments"):
            TicketAttachment.objects.create(ticket=ticket, file=file)

        ticket = self.get_queryset().get(pk=ticket.pk)

        return Response({
            "success": True,
            "message": "Ticket created successfully",
            "data": StudentTicketSerializer(ticket, context={'request': request}).data
        }, status=status.HTTP_201_CREATED)

    # Reply to ticket
    def reply_to_ticket(self, request):
        try:
            ticket_id = int(request.query_params["bat_man"])
        except (ValueError, TypeError):
            return Response({"success": False, "message": "Invalid reply_to"}, status=status.HTTP_400_BAD_REQUEST)

        ticket = StudentTicket.objects.filter(ticket_id=ticket_id).first()
        if not ticket:
            return Response({"success": False, "message": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

        message = request.data.get("message", "").strip()
        if not message:
            return Response({"success": False, "message": "Message is required"}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        ut = getattr(user, "user_type", None)

        # Permission check for student
        if ut == "student" and ticket.student.student_id != getattr(user, "student_id", None):
            return Response({"success": False, "message": "You can only reply to your own tickets"}, status=status.HTTP_403_FORBIDDEN)

        reply_data = {"ticket": ticket, "message": message}

        if ut == "student":
            reply_data["student"] = ticket.student
        elif ut == "admin":
            trainer = Trainer.objects.filter(username=user.username).first()
            if not trainer:
                return Response({"success": False, "message": "Trainer profile not found"}, status=status.HTTP_400_BAD_REQUEST)
            reply_data["trainer"] = trainer
            ticket.handled_by_trainer = trainer
        elif ut == "super_admin":
            reply_data["super_admin"] = user
            ticket.handled_by_superadmin = user
        else:
            return Response({"success": False, "message": "Invalid user type"}, status=status.HTTP_403_FORBIDDEN)

        # Create reply
        reply = TicketReply.objects.create(**reply_data)
        real_user = self.get_real_user(request.user)
        # Update ticket status
        ticket.status = "in_progress"
        ticket.updated_by = real_user
        ticket.save(update_fields=[
            "status",
            "handled_by_trainer",
            "handled_by_superadmin",
        ])

        # Serialize and return the new reply
        serialized_reply = TicketReplySerializer(reply, context={'request': request}).data

        return Response({
            "success": True,
            "message": "Reply added successfully",
            "reply": serialized_reply
        }, status=status.HTTP_201_CREATED)

    # Close ticket
    def close_ticket(self, request):
        try:
            ticket_id = int(request.query_params["close"])
        except (ValueError, TypeError):
            return Response({"success": False, "message": "Invalid ticket ID"}, status=status.HTTP_400_BAD_REQUEST)

        ticket = StudentTicket.objects.filter(ticket_id=ticket_id).first()
        if not ticket:
            return Response({"success": False, "message": "Ticket not found"}, status=status.HTTP_404_NOT_FOUND)

        ticket.status = "closed"
        real_user = self.get_real_user(request.user)
        ticket.updated_by = real_user
        ticket.save(update_fields=["status"])
        return Response({"success": True, "message": "Ticket closed successfully"}, status=status.HTTP_200_OK)

    # Admin scope
    def get_admin_scope(self, user):
        ut = getattr(user, "user_type", None)

        # ---------------- SUPER ADMIN ----------------
        if ut == "super_admin":
            user_id = getattr(user, "user_id", None)
            if not user_id:
                return Q(pk__isnull=True)

            user_id_str = str(user_id)   # 🔧 CAST TO STRING

            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_id_str,
                    created_by_type="super_admin",
                    user_type="admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

            admin_ids_str = [str(i) for i in admin_ids]  # 🔧 CAST TO STRING

            return (
                Q(student__created_by=user_id_str, student__created_by_type="super_admin") |
                Q(student__created_by__in=admin_ids_str, student__created_by_type="admin")
            )

        # ---------------- ADMIN ----------------
        elif ut == "admin":
            trainer_id = getattr(user, "trainer_id", None)
            if not trainer_id:
                return Q(pk__isnull=True)

            trainer_id_str = str(trainer_id)  # 🔧 CAST TO STRING

            super_admin_id = Trainer.objects.filter(
                trainer_id=trainer_id,
                created_by_type="super_admin"
            ).values_list("created_by", flat=True).first()

            super_admin_id_str = str(super_admin_id) if super_admin_id else None  # 🔧 CAST TO STRING

            return (
                Q(student__created_by=trainer_id_str, student__created_by_type="admin") |
                Q(student__created_by=super_admin_id_str, student__created_by_type="super_admin")
            )

        return Q(pk__isnull=True)
    
    def patch(self, request):
        if request.query_params.get("wanda"):
            return self.edit_reply(request)

        return Response({"success": False, "message": "Invalid PATCH request"}, status=status.HTTP_400_BAD_REQUEST)

    def edit_reply(self, request):
        user_type = getattr(request.user, "user_type", None)
        if user_type not in ("admin", "super_admin"):
            return Response({"success": False, "message": "Only admin can edit replies"}, status=status.HTTP_403_FORBIDDEN)

        try:
            reply_id = int(request.query_params["wanda"])
        except (ValueError, TypeError):
            return Response({"success": False, "message": "Invalid edit_reply ID"}, status=status.HTTP_400_BAD_REQUEST)

        reply = TicketReply.objects.filter(reply_id=reply_id).first()
        if not reply:
            return Response({"success": False, "message": "Reply not found"}, status=status.HTTP_404_NOT_FOUND)

        # Security: Only the admin who wrote it can edit
        if user_type == "admin":
            trainer = Trainer.objects.filter(username=request.user.username).first()
            if reply.trainer != trainer:
                return Response({"success": False, "message": "You can only edit your own replies"}, status=status.HTTP_403_FORBIDDEN)
        elif user_type == "super_admin":
            if reply.super_admin != request.user:
                return Response({"success": False, "message": "You can only edit your own replies"}, status=status.HTTP_403_FORBIDDEN)

        new_message = request.data.get("message", "").strip()
        if not new_message:
            return Response({"success": False, "message": "Message is required"}, status=status.HTTP_400_BAD_REQUEST)

        reply.message = new_message
        reply.save(update_fields=["message"])

        # Also update the parent ticket's updated_by
        ticket = reply.ticket
        real_user = self.get_real_user(request.user)
        ticket.updated_by = real_user
        ticket.save(update_fields=[])

        return Response({
            "success": True,
            "message": "Reply updated successfully",
            "reply": TicketReplySerializer(reply, context={'request': request}).data
        }, status=status.HTTP_200_OK)


class AttendanceViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = Attendance.objects.all()
    serializer_class = AttendanceSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    # Determine which batch to use (new_batch preferred)
    def get_active_batch(self, obj):
        return obj.new_batch if obj.new_batch else obj.batch

    # Determine course for new_batch or old
    def get_active_course(self, obj):
        if obj.new_batch:
            return obj.new_batch.course
        return obj.course

    # 1) DAILY ATTENDANCE FETCH
    def get_queryset(self):
        student_id = self.request.query_params.get('student')
        if not student_id:
            return Attendance.objects.none()

        today = timezone.localtime().date()

        return Attendance.objects.filter(
            student__student_id=student_id,
            date__date=today
        ).order_by('-date')

    # LIST API → Today's attendance + batches
    def list(self, request, student_id=None):
        if not student_id:
            return Response({'success': False, 'message': 'student_id is required.', 'data': {}}, status=200)

        ist = pytz.timezone("Asia/Kolkata")
        today = timezone.localtime().date()

        student = Student.objects.filter(student_id=student_id).first()
        if not student:
            return Response({"success": False, "message": "Student not found.", "data": {}}, status=200)
        # --------------- FETCH TODAY ATTENDANCE -----------------
        ist = pytz.timezone("Asia/Kolkata")
        today = timezone.now().astimezone(ist).date()
        start_datetime = datetime.combine(today, time.min)
        end_datetime = datetime.combine(today, time.max)

        # Make them timezone-aware in IST
        start_datetime = ist.localize(start_datetime)
        end_datetime = ist.localize(end_datetime)
        
        attendance_qs = Attendance.objects.filter(
            student=student,
            date__range=(start_datetime, end_datetime)
        ).order_by('-date')

        # --------------- BOTH BATCH SOURCES ---------------------
        old_batches = Batch.objects.filter(
            batchcoursetrainer__student=student,
            is_archived=False,
            status=True
        ).distinct()

        new_batches = NewBatch.objects.filter(
            students=student,
            is_archived=False,
            status=True
        ).distinct()

        batch_data = []

        # ---- OLD BATCH DATA ----
        for batch in old_batches:
            course_obj = batch.batchcoursetrainer.first().course if batch.batchcoursetrainer.exists() else None
            todays_schedules = batch.schedules.filter(
                scheduled_date=today,
                is_archived=False
            ).select_related('course', 'trainer')

            batch_data.append({
                "type": "old_batch",
                "batch_id": batch.batch_id,
                "batch_name": batch.batch_name,
                "title": batch.title,
                "course": course_obj.course_id if course_obj else None,
                "course_name": course_obj.course_name if course_obj else None,
                "schedules": [
                    {
                        "schedule_id": s.schedule_id,
                        "scheduled_date": s.scheduled_date,
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "duration": s.duration,
                        "employee_id": s.trainer.employee_id if s.trainer else None,
                        "trainer_name": s.trainer.full_name if s.trainer else None,
                        "meeting_link": s.class_link,
                        "is_online_class": s.is_online_class,
                        "status_info": getattr(s, "status_info", None),
                    }
                    for s in todays_schedules
                ]
            })

        # ---- NEW BATCH DATA ----
        for nb in new_batches:
            todays_schedules = ClassSchedule.objects.filter(
                new_batch=nb,
                scheduled_date=today,
                is_archived=False
            ).select_related("course", "trainer")

            batch_data.append({
                "type": "new_batch",
                "batch_id": nb.batch_id,
                "batch_name": nb.title,
                "title": nb.title,
                "course": nb.course.course_id,
                "course_name": nb.course.course_name,
                "schedules": [
                    {
                        "schedule_id": s.schedule_id,
                        "scheduled_date": s.scheduled_date,
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "duration": s.duration,
                        "employee_id": s.trainer.employee_id if s.trainer else None,
                        "trainer_name": s.trainer.full_name if s.trainer else None,
                        "meeting_link": s.class_link,
                        "is_online_class": s.is_online_class,
                    }
                    for s in todays_schedules
                ]
            })

        serializer = AttendanceSerializer(attendance_qs, many=True)
        return Response({
            "success": True,
            "data": serializer.data,
            "batches": batch_data
        }, status=200)
    
    def create(self, request, *args, **kwargs):
        student_id = request.data.get('student')
        course_id = request.data.get('course')
        new_batch_id = request.data.get('new_batch')  # <-- changed
        marked_by = request.data.get('marked_by')

        if not student_id or not course_id or not new_batch_id:
            return Response({
                'message': 'student, course, and new_batch are required.',
                'success': False
            }, status=status.HTTP_200_OK)

        # Fetch Student
        try:
            student = Student.objects.get(student_id=student_id)
        except Student.DoesNotExist:
            return Response({'message': 'Student not found.', 'success': False}, status=status.HTTP_200_OK)

        # Fetch Course
        try:
            course = Course.objects.get(pk=course_id)
        except Course.DoesNotExist:
            return Response({'message': 'Course not found.', 'success': False}, status=status.HTTP_200_OK)

        # Fetch NEW Batch (main one from now)
        try:
            new_batch = NewBatch.objects.get(pk=new_batch_id)
        except NewBatch.DoesNotExist:
            return Response({'message': 'NewBatch not found.', 'success': False}, status=status.HTTP_200_OK)

        # Block deleted students
        if student.is_archived:
            return Response({'message': 'Deleted students cannot mark attendance.', 'success': False}, status=status.HTTP_200_OK)

        # Admin settings
        settings = Settings.objects.first()
        attendance_options = settings.attendance_options if settings else []

        # Student marking
        if marked_by == 'student':
            if 'by_student' not in attendance_options and 'automatic_by_link' not in attendance_options:
                return Response({'success': False, 'message': 'Student attendance disabled by admin.'}, status=200)

        # VALIDATION: Ensure student belongs to this new batch
        if not new_batch.students.filter(student_id=student.student_id).exists():
            return Response({'success': False, 'message': 'Student is not part of this new batch.'}, status=200)

        # VALIDATION: Ensure student-course matches new batch course
        if new_batch.course_id != course.course_id:
            return Response({'success': False, 'message': 'Course does not match the new batch.'}, status=200)

        # Check class schedule
        today = localtime().date()
        class_scheduled = ClassSchedule.objects.filter(
            new_batch=new_batch,    # <-- only new batch schedules now
            course=course,
            scheduled_date=today,
            is_archived=False
        ).exists()

        if not class_scheduled:
            return Response({'success': False, 'message': 'No class scheduled today.'}, status=200)

        # Status
        status_value = request.data.get('status', 'Present')
        if status_value not in ['Present', 'Absent']:
            status_value = 'Absent'

        # Capture IP
        ip_address = None
        if marked_by == 'student':
            x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
            ip_address = x_forwarded.split(',')[0].strip() if x_forwarded else request.META.get('REMOTE_ADDR')

        # Build data for serializer
        data = request.data.copy()
        data['new_batch'] = new_batch_id       # <-- assign here
        data['batch'] = None                   # <-- old batch becomes null for new records
        if ip_address:
            data['ip_address'] = ip_address
        data['marked_by_admin'] = True if marked_by == 'trainer' else False

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return Response({
            'message': 'Attendance recorded successfully.',
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='<str:student_id>/adumneoie')
    def admin_mark_attendance(self, request, student_id=None):
        try:
            student_id = request.data.get("student")
            course_id = request.data.get("course")
            new_batch_id = request.data.get("new_batch")  # <--- CHANGED
            date_str = request.data.get("date")
            status_val = request.data.get("status", "Present")

            if not all([student_id, course_id, new_batch_id, date_str]):
                return Response({
                    "success": False,
                    "message": "student, course, new_batch, and date are required."
                }, status=200)

            # Fetch instances
            try:
                student = Student.objects.get(student_id=student_id)
                course = Course.objects.get(pk=course_id)
                new_batch = NewBatch.objects.get(pk=new_batch_id)
            except (Student.DoesNotExist, Course.DoesNotExist, NewBatch.DoesNotExist):
                return Response({"success": False, "message": "Invalid student/course/new_batch."}, status=200)

            # Parse DateTime
            scheduled_date = parse_datetime(date_str)
            if not scheduled_date:
                return Response({
                    "success": False,
                    "message": "Invalid datetime format. Use ISO 8601 (YYYY-MM-DDTHH:MM:SSZ)."
                }, status=200)

            # Validate student belongs to new batch
            if not new_batch.students.filter(student_id=student.student_id).exists():
                return Response({"success": False, "message": "Student is not in this new batch."}, status=200)

            # Validate course matches new batch course
            if new_batch.course_id != course.course_id:
                return Response({"success": False, "message": "Course does not belong to this new batch."}, status=200)

            # Prevent duplicate attendance for same day
            if Attendance.objects.filter(
                student=student,
                new_batch=new_batch,
                course=course,
                date__date=scheduled_date.date()
            ).exists():
                return Response({"success": False, "message": "Attendance already marked."}, status=200)

            # Create attendance with new_batch, old batch always null
            attendance = Attendance.objects.create(
                student=student,
                new_batch=new_batch,      # <--- MAIN CHANGE
                batch=None,               # <--- Ensures no new old-batch data
                course=course,
                date=scheduled_date,
                status=status_val,
                ip_address=request.META.get("REMOTE_ADDR"),
                marked_by_admin=True
            )

            return Response({
                "success": True,
                "message": f"Admin marked attendance as {status_val}",
                "data": AttendanceSerializer(attendance).data,
            }, status=201)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    @action(detail=False, methods=['get'], url_path='full_logs/(?P<student_id>[^/.]+)')
    def full_logs(self, request, student_id=None):
        if not student_id:
            return Response({'success': False, 'message': 'student_id is required'}, status=200)

        # Optional filters
        month = request.query_params.get('month')
        year = request.query_params.get('year')

        queryset = Attendance.objects.filter(student__student_id=student_id)

        if month:
            queryset = queryset.filter(date__month=int(month))
        if year:
            queryset = queryset.filter(date__year=int(year))

        logs = []
        grouped = {}

        for att in queryset.order_by('-date'):
            # --------------------------------------------
            # 1. CHOOSE BATCH SOURCE (new_batch > old batch)
            # --------------------------------------------
            using_new_batch = att.new_batch_id is not None

            if using_new_batch:
                batch_id = att.new_batch.batch_id
                batch_title = att.new_batch.title
            else:
                batch_id = att.batch.batch_id if att.batch else None
                batch_title = att.batch.title if att.batch else None

            # ----------------------------
            # 2. KEY MUST SUPPORT BOTH
            # ----------------------------
            key = (
                att.new_batch_id if using_new_batch else att.batch_id,
                att.course_id,
                att.schedule_id_id
            )
            
            utc = pytz.UTC
            ist = pytz.timezone("Asia/Kolkata")
            
            def to_ist(dt):
                if dt is None:
                    return None
                # Make datetime timezone-aware
                if dt.tzinfo is None:
                    dt = utc.localize(dt)   # stored as UTC but naive
                return dt.astimezone(ist).strftime("%I:%M:%S %p")
            # ------------------------------------
            # 3. INITIALIZE GROUP ENTRY
            # ------------------------------------
            if key not in grouped:
                grouped[key] = {
                    'attendance_id': att.id,
                    'student_name': f"{att.student.first_name} {att.student.last_name}",
                    'batch_id': batch_id,
                    'title': batch_title,
                    'course_id': att.course.course_id,
                    'course_name': att.course.course_name,
                    'date': att.date.strftime('%Y-%m-%d %H:%M:%S'),
                    'status': att.status,
                    'login_time': att.date.strftime('%Y-%m-%d %I:%M:%S %p') if att.status.lower() in ['present', 'login'] else None,
                    'logout_time': att.date.strftime('%Y-%m-%d %I:%M:%S %p') if att.status.lower() == 'logout' else None,
                }
            else:
                # ------------------------------------
                # 4. MERGE MULTIPLE STATUS ENTRIES
                # ------------------------------------
                if att.status.lower() == 'login':
                    grouped[key]['login_time'] = att.date.strftime('%Y-%m-%d %I:%M:%S %p')
                    grouped[key]['status'] = 'Present'

                elif att.status.lower() == 'logout':
                    grouped[key]['logout_time'] = att.date.strftime('%Y-%m-%d %I:%M:%S %p')
                    grouped[key]['status'] = 'Present'

                elif att.status.lower() in ['absent', 'cancelled']:
                    grouped[key]['status'] = att.status.capitalize()

        logs = list(grouped.values())

        return Response({
            'success': True,
            'message': f'Full attendance logs for student {student_id}',
            'data': logs
        }, status=200)

    @action(detail=True, methods=['get'], url_path='status')
    def attendance_status(self, request, student_id=None):
        ist = pytz.timezone("Asia/Kolkata")
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")

        # Parse start and end dates
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").astimezone(ist).date() if start_date_str else None
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else timezone.now().astimezone(ist).date()
        except ValueError:
            return Response({
                "success": False,
                "message": "Invalid date format. Use YYYY-MM-DD."
            }, status=status.HTTP_200_OK)

        # Fetch student
        try:
            student = Student.objects.get(student_id=student_id)
        except Student.DoesNotExist:
            return Response({
                "success": False,
                "message": "Student not found."
            }, status=status.HTTP_200_OK)

        # ---------------------------------------------------------------------
        # SUPPORT BOTH: old BatchSchedule AND new NewBatch-generated schedules
        # ---------------------------------------------------------------------

        # OLD batch schedules (existing)
        scheduled_old = ClassSchedule.objects.filter(
            batch__batchcoursetrainer__student=student,
            scheduled_date__lte=end_date,
            is_archived=False
        ).select_related("course", "batch", "trainer")

        # NEW batch schedules
        scheduled_new = ClassSchedule.objects.filter(
            new_batch__students=student,
            scheduled_date__lte=end_date,
            is_archived=False
        ).select_related("course", "new_batch", "trainer")

        # Combine both
        scheduled_classes = (scheduled_old | scheduled_new).order_by("-scheduled_date", "-start_time")

        class_statuses = []
        attended_count = 0
        not_attended_count = 0

        for sched in scheduled_classes:

            # -----------------------------------------------------------------
            # DETECT IF IT IS OLD BATCH OR NEW BATCH
            # -----------------------------------------------------------------
            using_new_batch = hasattr(sched, "new_batch") and sched.new_batch is not None

            if using_new_batch:
                batch_name = sched.new_batch.title
                title = sched.new_batch.title
                batch_obj = None
                new_batch_obj = sched.new_batch
            else:
                batch_name = sched.batch.batch_name
                title = sched.batch.title
                batch_obj = sched.batch
                new_batch_obj = None

            # -----------------------------------------------------------------
            # TRAINER attendance check
            # -----------------------------------------------------------------
            trainer_attendance = TrainerAttendance.objects.filter(
                Q(
                    course=sched.course,
                    date__date=sched.scheduled_date,
                    trainer=sched.trainer
                ) & (Q(status__iexact="Login") | Q(status__iexact="Logout"))
            ).exists()

            if not trainer_attendance:
                status_str = "Leave"
            else:
                # -------------------------------------------------------------
                # STUDENT attendance check for both batch types
                # -------------------------------------------------------------
                if using_new_batch:
                    student_attendance = Attendance.objects.filter(
                        student=student,
                        course=sched.course,
                        new_batch=new_batch_obj,
                        date__date=sched.scheduled_date
                    ).exists()
                else:
                    student_attendance = Attendance.objects.filter(
                        student=student,
                        course=sched.course,
                        batch=batch_obj,
                        date__date=sched.scheduled_date
                    ).exists()

                status_str = "Present" if student_attendance else "Absent"

                if student_attendance:
                    attended_count += 1
                else:
                    not_attended_count += 1

            class_statuses.append({
                "id": sched.schedule_id,
                "date": sched.scheduled_date.strftime("%Y-%m-%d"),
                "start_time": sched.start_time.strftime("%I:%M %p"),
                "course": sched.course.course_name,
                "batch": batch_name,
                "title": title,
                "trainer": sched.trainer.full_name if sched.trainer else None,
                "status": status_str
            })

        total_classes = attended_count + not_attended_count
        attendance_percentage = (attended_count / total_classes * 100) if total_classes > 0 else 0

        return Response({
            "success": True,
            "student": student.first_name + " " + student.last_name,
            "total_classes": total_classes,
            "attended": attended_count,
            "not_attended": not_attended_count,
            "attendance_percentage": round(attendance_percentage, 2),
            "classes": class_statuses
        }, status=status.HTTP_200_OK)

class StudentProfileViewSet(LoggingMixin, NotesMixin, viewsets.ModelViewSet):
    queryset = (
        Student.objects.all()
        .select_related(
            "employee",
            "school_student",
            "college_student",
            "jobseeker",
            "role",
            "trainer",
        )
        .prefetch_related(
            "topic_statuses__topic__course",
            "attendance_set__course",
            "new_batches__course",
            "new_batches__trainer",
            "batchcoursetrainer_set__course",
            "batchcoursetrainer_set__trainer",
            Prefetch(
                "attendance_set",
                queryset=Attendance.objects.select_related("course"),
            ),
        )
    )

    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    http_method_names = ['get', 'patch', 'put']
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    lookup_field = 'student_id'    
    lookup_url_kwarg = 'student_id'
    
    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return StudentUpdateSerializer
        return StudentProfileSerializer  # Read-only profile view
    
    def partial_update(self, request, *args, **kwargs):
        try:
            student = kwargs.get('student_id')
            if not student:
                return Response({"success": False, "message": "Student ID missing"}, status=200)

            try:
                student = Student.objects.get(student_id=student)
            except Student.DoesNotExist:
                return Response({"success": False, "message": "Student not found"}, status=200)

            serializer = self.get_serializer(student, data=request.data, partial=True)
            user = request.user

            # Ensure module_id points to Students
            student_module = ModulePermission.objects.filter(module__iexact="Students").first()
            if not student_module:
                return Response({"success": False, "message": "Students module not found"}, status=200)

            # if not has_permission(user, module_id=student_module.module_id, actions=["update"]):
            #     return Response({"success": False, "message": "You do not have permission"}, status=200)

            # Validate without raising exception
            if not serializer.is_valid():
                error_messages = flatten_errors(serializer.errors)
                error_message = ". ".join(error_messages) + "."
                return Response({
                    "success": False,
                    "message": error_message
                }, status=status.HTTP_200_OK)

            # Save valid data
            serializer.save()
            student.refresh_from_db()

            # Save notes if provided in request
            notes_text = request.data.get("notes")
            if notes_text:
                mixin = NotesMixin()
                mixin.save_notes(student, notes_text, request=request)

            # Use full profile serializer for response
            response_serializer = StudentProfileSerializer(student, context={'request': request})

            return Response({
                "success": True,
                "message": "Profile updated successfully.",
                "data": response_serializer.data
            }, status=200)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='courses')
    def get_courses_taken(self, request, student_id=None):
        student = Student.objects.filter(student_id=student_id).first()

        if not student:
            return Response(
                {"success": False, "message": "Student not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        new_courses_qs = Course.objects.filter(
            new_batches__students=student,
            new_batches__is_archived=False
        ).distinct()

        if new_courses_qs.exists():
            data = CourseSerializer(
                new_courses_qs,
                many=True,
                context={"student": student}
            ).data

            return Response({
                "success": True,
                "message": f"{student.first_name} {student.last_name} has taken {new_courses_qs.count()} course(s).",
                "data": data
            })

        return Response({
            "success": False,
            "message": f"No course assigned to {student.first_name} {student.last_name}."
        })
            
    @action(detail=True, methods=['get'], url_path='courses/<course_id>')
    def get_courses(self, request, student_id=None, course_id=None):
        student = self.get_object()

        # Check if student is linked with the given course in BatchCourseTrainer
        bct = NewBatch.objects.filter(
            students=student,
            course__course_id=course_id
        ).select_related("course").first()

        if not bct:
            return Response({
                "success": False,
                "message": f"Course {course_id} not found for {student.first_name} {student.last_name}.",
                "data": []
            }, status=status.HTTP_200_OK)

        course_data = CourseSerializer(bct.course).data
        return Response({
            "success": True,
            "message": f"Course {course_id} details for {student.first_name} {student.last_name}.",
            "data": course_data
        }, status=status.HTTP_200_OK)       

    @action(
        detail=True,
        methods=['patch'],
        url_path=r'(?P<student_id>[^/]+)/archive'
    )
    def archive_student(self, request, student_id=None):
        student = Student.objects.get(student_id=student_id)
        student.is_archived = True
        student.save()

        return Response({
            "success": True,
            "message": f"Student {student.first_name} {student.last_name} deleted successfully."
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated], url_path='change_password')
    def change_password(self, request, *args, **kwargs):
        registration_id = kwargs.get('registration_id')

        try:
            student = Student.objects.get(registration_id=registration_id)
        except Student.DoesNotExist:
            return Response({"error": "Student not found"}, status=status.HTTP_200_OK)

        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")

        if not old_password or not new_password:
            return Response({"error": "Both old_password and new_password are required"}, status=status.HTTP_200_OK)

        # Check old password
        if not check_password(old_password, student.password):
            return Response({"error": "Old password is incorrect"}, status=status.HTTP_200_OK)

        # Update password
        student.password = make_password(new_password)
        student.save()

        return Response({"success": "Password updated successfully"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='admin_reset_password')
    def admin_reset_password(self, request, *args, **kwargs):

        # Extract student_id from URL manually (IMPORTANT)
        student_id = kwargs.get(self.lookup_url_kwarg)

        try:
            student = Student.objects.get(student_id=student_id)
        except Student.DoesNotExist:
            return Response({"success": False, "message": "Student not found."}, status=200)

        # Authenticate admin
        auth = CustomJWTAuthentication()
        try:
            user, _ = auth.authenticate(request)
        except AuthenticationFailed as e:
            return Response({"success": False, "message": str(e)}, status=200)

        if not hasattr(user, 'user_type') or user.user_type.lower() != 'admin':
            return Response({"success": False, "message": "Only admin users can reset student passwords."}, status=200)

        new_password = request.data.get('new_password')
        if not new_password:
            return Response({"success": False, "message": "New password is required."}, status=200)

        try:
            validate_password(new_password)
        except serializers.ValidationError as e:
            return Response({"success": False, "message": str(e.detail[0])}, status=200)

        # Update password securely
        student.password = make_password(new_password)
        student.save()

        return Response({"success": True, "message": "Password reset successfully."}, status=200)
        
    @cache_api(prefix="student_profile", timeout=300)
    def retrieve(self, request, student_id=None):
        try:
            student = Student.objects.get(student_id=student_id)
        except Student.DoesNotExist:
            return Response({
                "success": False,
                "message": "Student not found"
            }, status=status.HTTP_200_OK)

        serializer = StudentProfileSerializer(student, context={'request': request})
        return Response({
            "success": True,
            "message": "Student profile retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)


class TrainerStudentMappingAPI(APIView):

    def get(self, request):
        trainer_id = request.GET.get("trai")
        student_id = request.GET.get("stud")

        if trainer_id:
            try:
                trainer = Trainer.objects.get(trainer_id=trainer_id)
            except Trainer.DoesNotExist:
                return Response({
                    "success": False,
                    "message": "Trainer not found"
                }, status=200)

            # NEW BATCH STUDENTS
            new_batch_students = Student.objects.filter(
                new_batches__trainer=trainer
            ).distinct()

            data = StudentDetailSerializer(new_batch_students, many=True).data

            return Response({
                "success": True,
                "trainer_id": trainer_id,
                "students": data
            }, status=200)

        if student_id:
            try:
                student = Student.objects.get(student_id=student_id)
            except Student.DoesNotExist:
                return Response({
                    "success": False,
                    "message": "Student not found"
                }, status=200)

            trainers = Trainer.objects.filter(
                new_batches__students=student
            ).distinct()

            data = TrainerForStudentSerializer(trainers, many=True).data

            return Response({
                "success": True,
                "student_id": student_id,
                "trainers": data
            }, status=200)

        return Response({
            "success": False,
            "message": "Pass either trainer_id or student_id"
        }, status=200)

class ForgotPasswordView(APIView):
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']

            # Find user
            if not (Student.objects.filter(email=email).exists() or Trainer.objects.filter(email=email).exists()):
                return Response({"success": False, "message": "Email not found"}, status=200)
            
            # Validate email format
            validator = EmailValidator()
            try:
                validator(email)
            except ValidationError:
                return Response({"success": False, "message": "Invalid email format"}, status=200)

            otp = generate_complex_otp()
            PasswordResetOTP.objects.create(email=email, otp=otp)
            send_otp_email(email, otp)

            return Response({"success": True, "message": f"OTP sent to {email}"}, status=200)
        return Response({"success": False, "message": "Invalid email format"}, status=200)


# STEP 2: Verify OTP only
class VerifyOTPView(APIView):
    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']

            try:
                otp_record = PasswordResetOTP.objects.filter(email=email, otp=otp).latest('created_at')
            except PasswordResetOTP.DoesNotExist:
                return Response({"success": False, "message": "Invalid OTP"}, status=200)

            if otp_record.is_expired():
                return Response({"success": False, "message": "OTP expired"}, status=200)

            otp_record.is_verified = True
            otp_record.save()

            return Response({"success": True, "message": "OTP verified successfully"}, status=200)
        return Response(serializer.errors, status=200)


# STEP 3: Reset password (only if OTP verified)
class ResetPasswordView(APIView):
    def post(self, request):
        email = request.data.get("email")
        new_password = request.data.get("new_password")

        if not email or not new_password:
            return Response({"success": False, "message": "Email and password are required"}, status=200)

        try:
            validate_password(new_password)
        except ValueError as e:
            return Response({"success": False, "message": str(e)}, status=200)

        # --- Check OTP ---
        otp_record = PasswordResetOTP.objects.filter(email=email).order_by('-created_at').first()
        if not otp_record:
            return Response({"success": False, "message": "OTP not verified"}, status=200)

        if otp_record.is_expired():
            return Response({"success": False, "message": "OTP expired"}, status=200)

        # --- Find user ---
        student = Student.objects.filter(email=email).first()
        trainer = Trainer.objects.filter(email=email).first()

        if not (student or trainer):
            return Response({"success": False, "message": "User not found"}, status=200)

        user = student if student else trainer
        user.password = make_password(new_password)
        user.save()

        # Invalidate OTP
        otp_record.delete()

        return Response({"success": True, "message": "Password reset successful"}, status=200)
    
class ResendOTPView(APIView):
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)  # reuse same serializer
        if serializer.is_valid():
            email = serializer.validated_data['email']

            # Check if user exists
            if not (Student.objects.filter(email=email).exists() or Trainer.objects.filter(email=email).exists()):
                return Response({"success": False, "message": "Email not found"}, status=200)

            # Delete old OTPs for clean re-send
            PasswordResetOTP.objects.filter(email=email).delete()

            # Generate new OTP
            otp = generate_complex_otp()
            PasswordResetOTP.objects.create(email=email, otp=otp)

            # Re-send email
            send_otp_email(email, otp)

            return Response({
                "success": True,
                "message": f"New OTP sent to {email}"
            }, status=200)

        return Response(serializer.errors, status=200)

class RecordingsView(viewsets.ModelViewSet):
    serializer_class = RecordingSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        user = self.request.user
        student_id = self.kwargs.get('student_id')

        qs = Recordings.objects.filter(is_archived=False).order_by('-id')

        # filter by student_id if passed
        if student_id:
            qs = qs.filter(student__student_id=student_id)

        # filter for admin-specific recordings
        if user.user_type == "admin" and getattr(user, "trainer_id", None):
            qs = qs.filter(created_by=user.trainer_id)

        return qs

    def get_object(self):
        student_id = self.kwargs.get('student_id')
        recording_id = self.kwargs.get('recording_id')
        try:
            return Recordings.objects.get(
                student__student_id=student_id,
                id=recording_id
            )
        except Recordings.DoesNotExist:
            return Response({
                "success": False,
                "message": "Recording not found"
            }, status=status.HTTP_200_OK)
        except Recordings.MultipleObjectsReturned:
            return Response({
                "success": False,
                "message": "Multiple recordings found, please specify a unique recording_id"
            }, status=status.HTTP_200_OK)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True, context={"request": request})
        return Response({
            "success": True,
            "message": "Recordings list retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
        
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            recording = serializer.save()
            return Response({
                "success": True,
                "message": "Recording created successfully",
                "data": RecordingSerializer(recording, context={"request": request}).data
            }, status=status.HTTP_201_CREATED)
        formatted = []
        errors = serializer.errors
        for field, msgs in errors.items():
            for msg in msgs:
                if msg.startswith("This"):
                    formatted.append(f"{field} is required")
                else:
                    formatted.append(f"{field} {msg}")
                
        return Response({
            "success": False,
            "message": " | ".join(formatted)
        }, status=status.HTTP_200_OK)
        
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if serializer.is_valid(raise_exception=True):
            self.perform_update(serializer)
            return Response({
                "success": True,
                "message": "Recording updated successfully",
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                "success": False,
                "message": "Validation failed",
                "errors": serializer.errors
            }, status=status.HTTP_200_OK)
    
    def is_archived(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_archived = True
        instance.save()
        return Response({
            "success": True,
            "message": "Recording deleted successfully"
        })
        

class InvoiceCreateView(viewsets.ModelViewSet):
    queryset = Invoice.objects.all().order_by('-created_at')
    serializer_class = InvoiceSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        if serializer.is_valid():
            invoice = serializer.save()
            return Response({
                "success": True,
                "message": "Invoice created successfully",
                "data": InvoiceSerializer(invoice, context={"request": request}).data
            }, status=status.HTTP_201_CREATED)
        return Response({
            "success": False,
            "message": "Validation failed",
            "errors": serializer.errors
        }, status=status.HTTP_200_OK)

    def list(self, request, *args, **kwargs):
        user = request.user
        trainer_id = getattr(user, "trainer_id", None)  # current admin/trainer

        # Base queryset: non-archived invoices
        queryset = Invoice.objects.filter(is_archived=False)

        # Filter by invoices created by this admin
        if user.user_type == "admin" and trainer_id:
            queryset = queryset.filter(created_by=str(trainer_id))  # match DB type

        serializer = self.get_serializer(queryset.order_by('-created_at'), many=True, context={"request": request})
        return Response({
            "success": True,
            "message": "Invoice list retrieved successfully",
            "data": serializer.data
        }, status=200)


class InvoiceDetailView(viewsets.ReadOnlyModelViewSet):
    serializer_class = InvoiceSerializer
    lookup_field = 'registration_id'
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        user = self.request.user
        registration_id = self.kwargs.get('registration_id')

        qs = Invoice.objects.filter(
            student__registration_id=registration_id,
            is_archived=False
        )

        # restrict to invoices created by this admin
        if user.user_type == "admin" and getattr(user, "trainer_id", None):
            qs = qs.filter(created_by=user.trainer_id)

        return qs.order_by('-created_at')

    def retrieve(self, request, *args, **kwargs):
        try:
            invoice = self.get_object()
            serializer = self.get_serializer(invoice, context={"request": request})
            return Response({
                "success": True,
                "message": "Invoice retrieved successfully",
                "data": serializer.data
            })
        except NotFound:
            return Response({
                "success": False,
                "message": "Invoice not found"
            }, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        invoice = self.get_object()
        serializer = self.get_serializer(invoice, data=request.data, partial=partial)
        if serializer.is_valid():
            invoice = serializer.save()
            return Response({
                "success": True,
                "message": "Invoice updated successfully",
                "data": InvoiceSerializer(invoice, context={"request": request}).data
            }, status=status.HTTP_200_OK)
        return Response({
            "success": False,
            "message": "Validation failed",
            "errors": serializer.errors
        }, status=status.HTTP_200_OK)
        
    def destroy(self, request, *args, **kwargs):
        invoice = self.get_object()
        invoice.is_archived = True
        return Response({
            "success": True,
            "message": "Invoice deleted successfully"
        }, status=status.HTTP_200_OK)
        
class InvoiceListViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        user = self.request.user
        qs = Invoice.objects.filter(is_archived=False)

        # If user is admin, filter invoices created by them
        if user.user_type == "admin" and getattr(user, "trainer_id", None):
            qs = qs.filter(created_by=user.trainer_id)

        return qs.order_by('-created_at')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True, context={"request": request})
        return Response({
            "success": True,
            "message": "Active invoices retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    

class CertificateViewSet(viewsets.ModelViewSet):
    queryset = Certificate.objects.all()
    serializer_class = CertificateSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        certificate_number = self.request.query_params.get('certificate_number')
        if certificate_number:
            return Certificate.objects.filter(certificate_number=certificate_number)
        certificate = Certificate.objects.all().order_by('certificate_number')
        return certificate
    
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "success": True,
            "message": "Certificates retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'], url_path='<student_id>' )
    def student_certificates(self, request, student_id=None):
        certificates = Certificate.objects.filter(student=student_id)
        serializer = CertificateSerializer(certificates, many=True)
        return Response({
            "success": True,
            "message": "Certificates retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    
# def send_certificate_email(student_email, certificate):
#     """
#     Send course completion certificate to student via email
#     """
#     subject = f"Your Certificate for {certificate.course_name}"
#     # Render a HTML template with certificate info
#     message = render_to_string('emails/certificate_email.html', {
#         'student_name': certificate.student_name,
#         'course_name': certificate.course_name,
#         'certificate_number': certificate.certificate_number,
#         'issued_date': certificate.issued_date,
#         'course_duration': certificate.course_duration,
#         'organization_name': certificate.organization_name,
#         'notes': certificate.notes,
#     })
    
#     email = EmailMessage(
#         subject,
#         message,
#         settings.DEFAULT_FROM_EMAIL,
#         [student_email]
#     )
#     email.content_subtype = "html"
#     email.send(fail_silently=False)    

class CourseCategoryViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = CourseCategory.objects.all()
    serializer_class = CourseCategorySerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'category_id' 

CURRENCIES = [
    {"code": "USD", "name": "United States Dollar", "symbol": "$"},
    {"code": "EUR", "name": "Euro", "symbol": "€"},
    {"code": "GBP", "name": "British Pound Sterling", "symbol": "£"},
    {"code": "INR", "name": "Indian Rupee", "symbol": "₹"},
    {"code": "JPY", "name": "Japanese Yen", "symbol": "¥"},
    {"code": "AUD", "name": "Australian Dollar", "symbol": "A$"},
    {"code": "CAD", "name": "Canadian Dollar", "symbol": "C$"},
    {"code": "CHF", "name": "Swiss Franc", "symbol": "CHF"},
    {"code": "CNY", "name": "Chinese Yuan", "symbol": "¥"},
    {"code": "SAR", "name": "Saudi Riyal", "symbol": "﷼"},
    {"code": "AED", "name": "UAE Dirham", "symbol": "د.إ"},
    {"code": "SGD", "name": "Singapore Dollar", "symbol": "S$"},
    {"code": "ZAR", "name": "South African Rand", "symbol": "R"},
    {"code": "BRL", "name": "Brazilian Real", "symbol": "R$"},
    {"code": "RUB", "name": "Russian Ruble", "symbol": "₽"},
    {"code": "KRW", "name": "South Korean Won", "symbol": "₩"},
    {"code": "MXN", "name": "Mexican Peso", "symbol": "$"},
    {"code": "SEK", "name": "Swedish Krona", "symbol": "kr"},
    {"code": "NZD", "name": "New Zealand Dollar", "symbol": "NZ$"},
    {"code": "THB", "name": "Thai Baht", "symbol": "฿"},
]

@api_view(['GET'])
def currency_list(request):
    return Response({"currencies": CURRENCIES})

class CourseCategoryViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = CourseCategory.objects.all()
    serializer_class = CourseCategorySerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'category_id' 

    def get_queryset(self):
        user = self.request.user
        base_queryset = CourseCategory.objects.filter(is_archived=False)

        # Identify user created id
        user_created_id = None
        if user.user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)
        elif user.user_type == "admin":
            user_created_id = getattr(user, "trainer_id", None)

        # Get admin IDs for this super admin
        admin_ids = []
        if user.user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

        # Filter based on role
        if user.user_type == "super_admin" and user_created_id:
            base_queryset = base_queryset.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )
        elif user.user_type == "admin" and user_created_id:
            base_queryset = base_queryset.filter(
                created_by_type="admin",
                created_by=user_created_id
            )

        return base_queryset.order_by('-category_id')
    
    def handle_validation_error(self, exc):
        if isinstance(exc.detail, dict):
            key = next(iter(exc.detail))
            message = exc.detail[key][0] if isinstance(exc.detail[key], list) else exc.detail[key]
        else:
            message = str(exc.detail)

        return Response({
            "success": False,
            "message": message
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        category_name = request.data.get('category_name', '').strip()
        user = request.user

        # Ensure module_id points to Course Categories
        category_module = ModulePermission.objects.filter(module__iexact="Category").first()
        if not category_module:
            return Response({"success": False, "message": "Course Categories module not found"}, status=200)

        if not has_permission(user, module_id=category_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)

        # 🔹 Initialize serializer here
        serializer = self.get_serializer(data=request.data)

        # Check for an active category with the same name (case-insensitive)
        active_qs = CourseCategory.objects.filter(
            category_name__iexact=category_name,
            is_archived=False
        )

        if active_qs.exists():
            return Response({
                "success": False,
                "message": f"Category '{category_name}' already exists.",
            }, status=status.HTTP_200_OK)

        # Check if an archived category exists
        archived_qs = CourseCategory.objects.filter(
            category_name__iexact=category_name,
            is_archived=True,  # fixed: was incorrectly False
            status=True
        )

        if archived_qs.exists():
            # Reactivate the archived category
            category = archived_qs.first()
            category.is_archived = False  # fixed: restore to active
            category.save()

            serializer = self.get_serializer(category)
            return Response({
                "success": True,
                "message": f"Category '{category_name}' created successfully (reactivated).",
                "data": serializer.data
            }, status=status.HTTP_200_OK)

        # 🔹 Validate new category
        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "success": False,
                "message": error_message
            }, status=status.HTTP_200_OK)

        # 🔹 Create a new category
        serializer.save()
        return Response({
            "success": True,
            "message": f"Category '{category_name}' created successfully.",
            "data": serializer.data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        user = request.user
        
        # Ensure module_id points to Course Categories
        category_module = ModulePermission.objects.filter(module__iexact="Category").first()
        if not category_module:
            return Response({"success": False, "message": "Course Categories module not found"}, status=200)

        if not has_permission(user, module_id=category_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)
        
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})

        if not serializer.is_valid():
            # Extract the first error message
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."

            return Response({
                "message": error_message,
                "success": False
            }, status=status.HTTP_200_OK)
        
        # Save notes if provided in request
        notes_text = request.data.get("notes")
        if notes_text:
            mixin = NotesMixin()
            mixin.save_notes(instance, notes_text, request=request)

        self.perform_update(serializer)
        return Response({
            "success": True,
            "message": "Category updated successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='archive')
    def archive_category(self, request, *args, **kwargs):
        category = self.get_object()
        category.is_archived = True
        category.save()

        return Response({
            "success": True,
            "message": f"Category '{category.category_name}' deleted successfully."
        }, status=status.HTTP_200_OK)

class CourseViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = Course.objects.filter(is_archived=False)
    serializer_class = CourseSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'course_id'
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        category_id = self.request.query_params.get('course_category')
        base_queryset = Course.objects.filter(is_archived=False).select_related('course_category')

        user = self.request.user
        user_created_id = None
        if user.user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)
        elif user.user_type == "admin":
            user_created_id = getattr(user, "trainer_id", None)

        # Get admin IDs created by this super admin
        admin_ids = []
        if user.user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

        # Filter courses based on role
        if user.user_type == "super_admin" and user_created_id:
            base_queryset = base_queryset.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )
        elif user.user_type == "admin" and user_created_id:
            base_queryset = base_queryset.filter(
                created_by_type="admin",
                created_by=user_created_id
            )

        # Optional: filter by category if provided
        if category_id:
            base_queryset = base_queryset.filter(course_category_id=category_id)

        return base_queryset.order_by('-course_id')

    def list(self, request, *args, **kwargs):
        try:
            queryset = self.get_queryset()
            serializer = self.get_serializer(queryset, many=True)

            # filter categories based on user role
            user = request.user
            user_created_id = None
            if user.user_type == "super_admin":
                user_created_id = getattr(user, "user_id", None)
            elif user.user_type == "admin":
                user_created_id = getattr(user, "trainer_id", None)

            admin_ids = []
            if user.user_type == "super_admin" and user_created_id:
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_created_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

            category_qs = CourseCategory.objects.filter(is_archived=False)
            if user.user_type == "super_admin" and user_created_id:
                category_qs = category_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                category_qs = category_qs.filter(created_by_type="admin", created_by=user_created_id)

            category_data = CourseCategorySerializer(category_qs, many=True).data

            if not queryset.exists():
                return Response({
                    "success": False,
                    "message": "No courses found for the selected category.",
                    "categories": category_data,
                    'currencies':CURRENCIES
                }, status=200)

            return Response({
                "success": True,
                "message": "Courses fetched successfully.",
                "data": serializer.data,
                "categories": category_data,
                'currencies':CURRENCIES
            }, status=200)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e),
            }, status=200)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        user = request.user
        
        # Ensure module_id points to Courses
        courses_module = ModulePermission.objects.filter(module__iexact="Course").first()
        if not courses_module:
            return Response({"success": False, "message": "Courses module not found"}, status=200)

        if not has_permission(user, module_id=courses_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)
        
        if not serializer.is_valid():
            # Extract the first error message
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."

            return Response({
                "message": error_message,
                "success": False
            }, status=status.HTTP_200_OK)

        self.perform_create(serializer)

        return Response({
            "message": "Course added successfully",
            "success": True,
            "data": serializer.data
        }, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        user = request.user

        # Ensure module_id points to Courses
        courses_module = ModulePermission.objects.filter(module__iexact="Course").first()
        if not courses_module:
            return Response({"success": False, "message": "Courses module not found"}, status=200)

        if not has_permission(user, module_id=courses_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)

        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})

        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "message": error_message,
                "success": False,
            }, status=status.HTTP_200_OK)

        validated_data = serializer.validated_data
        new_status = validated_data.get("status", instance.status)
        new_category = validated_data.get("course_category", instance.course_category)

        # Check if category is deleted or inactive before saving
        if new_status == "Active":
            if not new_category or getattr(new_category, "is_archived", False):
                return Response({
                    "success": False,
                    "message": "The category for this course has been deleted. Please choose another category before activating the course."
                }, status=200)

            if not getattr(new_category, "status", False):
                return Response({
                    "success": False,
                    "message": f"Cannot activate this course because its category '{new_category.category_name}' is inactive."
                }, status=200)
        
        # Save notes if provided in request
        notes_text = request.data.get("notes")
        if notes_text:
            mixin = NotesMixin()
            mixin.save_notes(instance, notes_text, request=request)

        # If validation passed, save changes
        self.perform_update(serializer)

        # Syllabus message logic
        had_syllabus_before = bool(instance.syllabus)
        has_syllabus_now = bool(serializer.instance.syllabus)
        if 'syllabus' in request.FILES:
            if not had_syllabus_before and has_syllabus_now:
                main_message = "Syllabus uploaded successfully"
            elif had_syllabus_before and has_syllabus_now:
                main_message = "Syllabus updated successfully"
            else:
                main_message = "Course updated successfully"
        else:
            main_message = "Course updated successfully"

        return Response({
            "message": main_message,
            "success": True,
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='batches')
    def get_batches(self, request, *args, **kwargs):
        course = self.get_object()  # this is a Course instance
        # Get distinct active batches
        batches = NewBatch.objects.filter(course=course, is_archived=False, status=True).distinct()

        serializer = NewBatchSerializer(batches, many=True)
        return Response({
            "success": True,
            "message": f"Batches for course {course.course_name} fetched successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='archive')
    def archive_course(self, request, *args, **kwargs):
        course = self.get_object()
        course.is_archived = True
        course.save()
 
        return Response({
            "success": True,
            "message": f"Course {course.course_name} deleted successfully."
        }, status=status.HTTP_200_OK)
        
class TopicViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = TopicSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        course_id = self.kwargs.get('course_id')
        try:
            course = Course.objects.get(course_id=course_id)
        except Course.DoesNotExist:
            raise NotFound("Course not found or deleted.")
        return Topic.objects.filter(course=course, is_archived=False).order_by('created_date')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "success": True,
            "message": "Topics fetched successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        course_id = self.kwargs.get('course_id')
        try:
            course = Course.objects.get(course_id=course_id, is_archived=False)
        except Course.DoesNotExist:
            return Response(
                {"success": False, "message": "Course not found or deleted."},
                status=status.HTTP_200_OK
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(course=course)
        return Response(
            {
                "success": True,
                "message": "Topic created successfully.",
                "data": serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    # Combine update and partial_update here
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)  # Check if partial update was requested

        instance = self.get_object()  # fetch existing object
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response({
            "success": True,
            "message": "Topic updated successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

        
class StudentTopicStatusViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = StudentTopicStatusSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        student_id = self.request.query_params.get('student_id')
        course_id = self.request.query_params.get('course_id')

        queryset = StudentTopicStatus.objects.select_related('student', 'topic', 'topic__course')

        if student_id:
            queryset = queryset.filter(student__student_id=student_id, student__is_archived=False)

        if course_id:
            queryset = queryset.filter(topic__course__course_id=course_id, topic__is_archived=False)

        return queryset.order_by('topic__created_date')

    def list(self, request, *args, **kwargs):
        course_id = self.kwargs.get('course_id')
        student_id = self.kwargs.get('student_id')

        # Validate course
        course = Course.objects.filter(course_id=course_id).first()
        if not course:
            return Response({
                "success": False,
                "message": "Course not found or deleted.",
                "all_topics": [],
                "completed_topics": []
            }, status=status.HTTP_200_OK)

        # Validate student
        student = Student.objects.filter(student_id=student_id, is_archived=False).first()
        if not student:
            return Response({
                "success": False,
                "message": "Student not found or archived.",
                "all_topics": [],
                "completed_topics": []
            }, status=status.HTTP_200_OK)

        # Get all topics for the course
        topics = Topic.objects.filter(course=course, is_archived=False).order_by('created_date')

        # Get completed statuses for student (not just IDs now)
        completed_statuses = StudentTopicStatus.objects.filter(
            student=student,
            topic__in=topics,
            status=True
        ).select_related('topic', 'topic__course')

        # Serialize completed topic statuses
        completed_serializer = StudentTopicStatusSerializer(completed_statuses, many=True)

        # Get topic_ids marked as completed
        completed_topic_ids = set(completed_statuses.values_list('topic_id', flat=True))

        # Build all_topics list
        all_topics = []
        for topic in topics:
            all_topics.append({
                "topic_id": topic.topic_id,
                "title": topic.title,
                "description": topic.description,
                "created_date": topic.created_date.strftime('%Y-%m-%d %H:%M:%S') if topic.created_date else None,
                "is_completed": topic.topic_id in completed_topic_ids
            })

        if not student:
            return Response({
                "success": False,
                "message": "Student not found or archived.",
                "all_topics": all_topics,
                "completed_topics": []
            }, status=status.HTTP_200_OK)

        return Response({
            "success": True,
            "message": "Topics with completion status fetched successfully.",
            "all_topics": all_topics,
            "completed_topics": completed_serializer.data
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        data = request.data.copy()

        # Try to get student_id and topic from URL kwargs if not in data
        student_id = data.get('student_id') or self.kwargs.get('student_id')
        topic_id = data.get('topic') or self.kwargs.get('topic')

        if not student_id or not topic_id:
            raise ValidationError("Both student_id and topic are required.")

        try:
            student = Student.objects.get(student_id=student_id, is_archived=False)
            topic = Topic.objects.get(pk=topic_id, is_archived=False)
        except Student.DoesNotExist:
            return Response({
                "success": False,
                "message": "Student with this student_id not found."
            }, status=status.HTTP_200_OK)
        except Topic.DoesNotExist:
            return Response({
                "success": False,
                "message": "Topic not found."
            }, status=status.HTTP_200_OK)

        # Prepare data for serializer
        data['student'] = student.pk
        data['topic'] = topic.pk

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return Response({
            "success": True,
            "message": "Topic created successfully.",
            "data": serializer.data
        }, status=status.HTTP_201_CREATED)

class TrainerViewSet(NotesMixin, LoggingMixin, viewsets.ModelViewSet):
    queryset = Trainer.objects.all()
    serializer_class = TrainerSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'employee_id'

    def get_queryset(self):
        employee_id = self.request.query_params.get('employee_id')
        if employee_id:
            return Trainer.objects.filter(employee_id=employee_id)
        return Trainer.objects.filter(is_archived=False).order_by('employee_id')
    
    def retrieve(self, request, *args, **kwargs):
        try:
            trainer = self.get_object()  # gets Trainer by employee_id due to lookup_field
        except Trainer.DoesNotExist:
            return Response({
                "success": False,
                "message": "Trainer not found."
            }, status=status.HTTP_200_OK)
            
        course_ids = BatchCourseTrainer.objects.filter(
            trainer=trainer
        ).values_list('course_id', flat=True).distinct()

        courses = Course.objects.filter(
            batchcoursetrainer__trainer=trainer,
            is_archived=False,
            status__iexact='Active'
        ).distinct().values('course_id', 'course_name')
        
        batch = Batch.objects.filter(
            batchcoursetrainer__trainer=trainer,
            is_archived=False,
            status=True,
        ).values("batch_id", "batch_name", "title").distinct()

        serializer = self.get_serializer(trainer)
        return Response({
            "success": True,
            "message": "Trainer profile retrieved successfully.",
            "data": serializer.data,
            "course": list(courses),
            "batch": list(batch)
        }, status=status.HTTP_200_OK)
        
        
    def perform_create(self, serializer):
        """
        Automatically set `created_by` to the trainer_id of the new trainer.
        """
        trainer = serializer.save()  # save the trainer first to get trainer_id
        if not trainer.created_by:
            trainer.created_by = str(trainer.trainer_id)
            trainer.save(update_fields=['created_by'])

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        user = request.user
        
        # Ensure module_id points to Tutors
        tutors_module = ModulePermission.objects.filter(module__iexact="Tutors").first()
        if not tutors_module:
            return Response({"success": False, "message": "Tutors module not found"}, status=200)

        if not has_permission(user, module_id=tutors_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)

        if not serializer.is_valid():
            return Response({
                "success": False,
                "message": self._get_first_error_message(serializer.errors)
            }, status=200)

        try:
            trainer = serializer.save()
        except IntegrityError as e:
            # Check for duplicate email
            if 'email' in str(e):
                return Response({
                    "success": False,
                    "message": "Email already exists"
                }, status=200)
            # You can add other checks here too if needed
            return Response({
                "success": False,
                "message": "Something went wrong while creating the trainer"
            }, status=200)

        headers = self.get_success_headers(serializer.data)
        user_type = getattr(trainer, 'user_type', None)

        return Response({
            "success": True,
            "message": "Trainer created successfully.",
            "user_type": user_type
        }, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', True)
        
        user = request.user
        
        # Ensure module_id points to Tutors
        tutors_module = ModulePermission.objects.filter(module__iexact="Tutors").first()
        if not tutors_module:
            return Response({"success": False, "message": "Tutors module not found"}, status=200)

        if not has_permission(user, module_id=tutors_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)
                
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        # Save note if present in payload
        notes_text = request.data.get("notes")
        if notes_text:
            self.save_notes(instance, notes_text, request=request)

        instance.refresh_from_db()

        return Response({
            "success": True,
            "message": "Trainer Profile updated successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
        
    @action(detail=True, methods=['get'], url_path='courses')
    def get_courses_taken(self, request, employee_id=None):
        try:
            trainer = self.get_object()  # Trainer retrieved using lookup_field
        except Trainer.DoesNotExist:
            return Response({
                "success": False,
                "message": "Trainer not found."
            }, status=status.HTTP_200_OK)

        # ========== 1. Courses from Old Batch Model ==========
        active_old_batches = BatchCourseTrainer.objects.filter(
            trainer=trainer,
            batch__status=True,
            batch__is_archived=False
        )

        course_ids_old = active_old_batches.values_list('course_id', flat=True)

        # ========== 2. Courses from NewBatch Model ==========
        active_new_batches = NewBatch.objects.filter(
            trainer=trainer,
            status=True,
            is_archived=False
        )

        course_ids_new = active_new_batches.values_list('course_id', flat=True)

        # ========== Combine & Remove Duplicates ==========
        all_course_ids = set(list(course_ids_old) + list(course_ids_new))

        courses = Course.objects.filter(
            course_id__in=all_course_ids,
            is_archived=False
        ).distinct()

        serializer = CourseSerializer(courses, many=True)

        return Response({
            "success": True,
            "message": f"Courses assigned to trainer {trainer.full_name}.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
        
    @action(detail=False, methods=['get'], url_path='admins')
    def list_admins(self, request):
        try:
            user = request.user
            user_created_id = getattr(user, "trainer_id", None)  # For admin
            if user.user_type == "super_admin":
                user_created_id = getattr(user, "user_id", None)  # Super admin


            # =============================
            # 1. Get admin IDs for super admin
            # =============================
            admin_ids = []
            if user.user_type == "super_admin" and user_created_id:
                # Get employee_id of admins created by this super admin
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_created_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

            # =============================
            # 2. Trainers queryset
            # =============================
            trainers_qs = Trainer.objects.filter(user_type='admin',is_archived=False)

            if user.user_type == "super_admin":
                trainers_qs = trainers_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                trainers_qs = trainers_qs.filter(
                    created_by=user_created_id,
                    created_by_type="admin"
                )

            # Select only required fields
            trainers_qs = trainers_qs.order_by("-trainer_id")

            trainer_data = [
                {
                    "employee_id": t.employee_id,
                    "full_name": t.full_name,
                    "role": t.role.role_id if t.role else None,
                    "role_name": t.role.name if t.role else None,
                    "username": t.username,
                    "user_type": t.user_type,
                    "trainer_id": t.trainer_id,
                    'email': t.email,
                    'contact_no': t.contact_no,
                    'status': t.status,
                    "notes": self.get_notes_reasons(t, request),
                    'gender': t.gender,
                    'specialization': t.specialization,
                    'working_hours': t.working_hours,
                }

                for t in trainers_qs
            ]
            trainers_count = trainers_qs.count()
            roles = Role.objects.filter(is_archived=False).values("role_id", "name")
            role = RoleSerializer(roles, many=True).data

            return Response({
                "success": True,
                "trainer_data": trainer_data,
                "trainers_count": trainers_count,
                "roles": role
            }, status=200)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=200)
            
    @action(detail=False, methods=['get'], url_path='ad_employee/(?P<employee_id>[^/.]+)')
    def admin_profile(self, request, employee_id=None):
        try:
            trainer = Trainer.objects.get(employee_id=employee_id, is_archived=False)
        except Trainer.DoesNotExist:
            return Response({
                "success": False,
                "message": "Trainer not found."
            }, status=status.HTTP_200_OK)

        serializer = self.get_serializer(trainer)
        return Response({
            "success": True,
            "message": "Trainer profile retrieved successfully.",
            "data": serializer.data,
        }, status=status.HTTP_200_OK)
        
    @action(detail=True, methods=['get'], url_path='batches')
    def get_batches(self, request, employee_id=None):
        # self.get_object() will fetch the Trainer based on employee_id
        trainer = self.get_object()  # Trainer instance

        # Fetch all distinct batches assigned to this trainer via BatchCourseTrainer
        batches = Batch.objects.filter(
            batchcoursetrainer__trainer=trainer,
            is_archived=False,
            status=True,
        ).distinct()
        
        #active courses
        active_courses = Course.objects.filter(
            batchcoursetrainer__trainer=trainer,
            is_archived=False,
            status__iexact='Active'
        ).values("course_id", "course_name", 'course_category').distinct()
        
        # Active categories (only categories linked to trainer's active courses)
        active_categories = CourseCategory.objects.filter(
            courses__batchcoursetrainer__trainer=trainer,
            courses__is_archived=False,
            courses__status__iexact='Active',
            is_archived=False,
            status=True
        ).values("category_id", "category_name").distinct()

        serializer = BatchSerializer(batches, many=True)
        return Response({
            "success": True,
            "message": f"Batches assigned to trainer {trainer.full_name} fetched successfully.",
            "data": serializer.data,
            "active_course": list(active_courses),
            "active_category": list(active_categories)
        }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['get'], url_path='courses/<course_id>')
    def get_courses(self, request, employee_id=None, course_id=None):
        trainer = self.get_object()

        # Check if student is linked with the given course in BatchCourseTrainer
        bct = BatchCourseTrainer.objects.filter(
            trainer=trainer,
            course__course_id=course_id
        ).select_related("course").first()

        if not bct:
            return Response({
                "success": False,
                "message": f"Course {course_id} not found for {trainer.full_name}.",
                "data": []
            }, status=status.HTTP_200_OK)

        course_data = CourseSerializer(bct.course).data
        return Response({
            "success": True,
            "message": f"Course {course_id} details for {trainer.full_name}.",
            "data": course_data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='students')
    def student_list(self, request, employee_id=None):
        try:
            trainer = self.get_object()
        except Trainer.DoesNotExist:
            return Response({
                "success": False,
                "message": f"No Trainer found with employee_id '{employee_id}'"
            }, status=status.HTTP_200_OK)

        old_students = Student.objects.filter(
            batchcoursetrainer__trainer=trainer,
            batchcoursetrainer__batch__status=True,
            batchcoursetrainer__batch__is_archived=False,
            batchcoursetrainer__course__status="Active",
            batchcoursetrainer__course__is_archived=False,
            is_archived=False
        ).values(
            "student_id", "registration_id", "first_name", "last_name",
            "status", "joining_date", "student_type"
        ).distinct()

        new_students = Student.objects.filter(
            new_batches__trainer=trainer,
            new_batches__status=True,            # Active batch
            new_batches__is_archived=False,      # Not archived
            is_archived=False
        ).values(
            "student_id", "registration_id", "first_name", "last_name",
            "status", "joining_date", "student_type"
        ).distinct()

        merged = {}

        # old system students
        for s in old_students:
            merged[s["student_id"]] = s

        # new system students
        for s in new_students:
            merged[s["student_id"]] = s   # overwrite or add

        final_students = list(merged.values())

        # Sort by registration_id (just like original)
        final_students = sorted(final_students, key=lambda x: x["registration_id"])

        return Response({
            "success": True,
            "message": f"Students assigned to trainer {trainer.full_name}.",
            "data": final_students
        }, status=status.HTTP_200_OK)
    
    @cache_api(prefix="trainer_student_profile", timeout=300)
    @action(detail=False, methods=['get'], url_path=r'(?P<student_id>[^/]+)')
    def trainer_student_profile(self, request, employee_id=None, student_id=None):
        trainer = Trainer.objects.filter(employee_id=employee_id, is_archived=False).first()
        if not trainer:
            return Response({"success": False, "message": "Trainer not found"}, status=200)

        # ⚡ PRELOAD EVERYTHING IN ONE QUERY
        student = (Student.objects
                .filter(student_id=student_id, is_archived=False, status=True)
                .select_related("role", "trainer", "school_student",
                                "college_student", "jobseeker", "employee")
                .prefetch_related(
                    "topic_statuses__topic",
                    "attendance_set",
                    "new_batches__course",
                    "new_batches__trainer",
                )
                .first())

        if not student:
            return Response({"success": False, "message": "Student not found"}, status=200)

        # courses assigned to trainer
        trainer_courses = (NewBatch.objects
                        .filter(trainer=trainer, students=student)
                        .values_list('course_id', flat=True))

        serializer = StudentProfileSerializer(
            student,
            context={"request": request, "trainer_courses": trainer_courses}
        )

        return Response({
            "success": True,
            "message": "Student profile fetched",
            "data": serializer.data
        }, status=200)
            
    @action(detail=True, methods=['patch'], url_path='reset_password')
    def reset_password(self, request, employee_id=None):
        """
        Reset student password (admin only)
        """
        # Authenticate using your custom JWT
        auth = CustomJWTAuthentication()
        try:
            user, _ = auth.authenticate(request)
        except AuthenticationFailed as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

        # Ensure only admin can reset
        # Ensure only admin or super admin can reset
        if not hasattr(user, 'user_type') or user.user_type.lower() not in ['admin', 'super_admin']:
            return Response(
                {"success": False, "message": "Only super admin or admin users can reset Trainer passwords."},
                status=status.HTTP_200_OK
            )

        # Get new password
        new_password = request.data.get('new_password')
        if not new_password:
            return Response({"success": False, "message": "New password is required."}, status=status.HTTP_200_OK)
        
        try:
            validate_password(new_password)
        except serializers.ValidationError as e:
            return Response({"success": False, "message": str(e.detail[0])}, status=status.HTTP_200_OK)

        try:
            trainer = self.get_object()   # uses registration_id because of lookup_field
        except Trainer.DoesNotExist:
            return Response({"success": False, "message": "Trainer not found."}, status=status.HTTP_200_OK)

        # Update trainer password directly
        trainer.password = make_password(new_password)  # if storing plain text
        trainer.save()

        return Response({"success": True, "message": "Password reset successfully."}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='archive')
    def archive_trainer(self, request, employee_id=None):
        try:
            trainer = self.get_object()
        except Trainer.DoesNotExist:
            return Response({
                "success": False,
                "message": f"No Trainer found with employee_id '{employee_id}'"
            }, status=status.HTTP_200_OK)

        trainer.is_archived = True
        trainer.save()

        return Response({
            "success": True,
            "message": f"Trainer {trainer.trainer_id} deleted successfully."
        }, status=status.HTTP_200_OK)

    def _get_first_error_message(self, errors):
        if isinstance(errors, dict):
            for field_errors in errors.values():
                if isinstance(field_errors, list) and field_errors:
                    return str(field_errors[0])
                elif isinstance(field_errors, dict):
                    return self._get_first_error_message(field_errors)
        return "Validation failed."
    
class TrainerListAPIView(LoggingMixin, NotesMixin, APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get(self, request):
        try:
            user = request.user
            user_created_id = getattr(user, "trainer_id", None)
            super_admin_id = None

            # If super admin → user_created_id = super admin id
            if user.user_type == "super_admin":
                user_created_id = getattr(user, "user_id", None)
                super_admin_id = user_created_id

            # Get admin IDs created by super admin
            admin_ids = []
            if user.user_type == "super_admin" and user_created_id:
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_created_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

            # Determine super admin of an admin
            if user.user_type == "admin" and user_created_id:
                admin_record = Trainer.objects.filter(trainer_id=user_created_id).first()
                if admin_record and admin_record.created_by_type == "super_admin":
                    super_admin_id = admin_record.created_by

            # Trainer Queryset
            trainers_qs = Trainer.objects.filter(
                user_type='tutor',
                is_archived=False
            )

            if user.user_type == "super_admin":
                trainers_qs = trainers_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )

            elif user.user_type == "admin" and user_created_id:
                filters = Q(created_by=user_created_id, created_by_type="admin")
                if super_admin_id:
                    filters |= Q(created_by=super_admin_id, created_by_type="super_admin")
                trainers_qs = trainers_qs.filter(filters)

            # Prefetch notes
            trainers_qs = trainers_qs.prefetch_related(
                Prefetch(
                    "notes",
                    queryset=Note.objects.all().order_by("-created_at"),
                    to_attr="prefetched_notes"
                )
            ).order_by("-trainer_id")

            trainer_data = []

            for t in trainers_qs:
                notes = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "status": n.status,
                        "created_by": n.created_by,
                        "created_at": n.created_at,
                    }
                    for n in getattr(t, "prefetched_notes", [])
                ]

                # ============================================
                #      AGGREGATED: OLD BATCH + NEW BATCH
                # ============================================

                batch_ids = []
                titles = []
                course_ids = []
                course_names = []
                category_ids = []
                category_names = []

                # ---------------- OLD BATCH ----------------
                old_bct = BatchCourseTrainer.objects.filter(
                    trainer=t,
                    batch__is_archived=False
                ).select_related("batch", "course__course_category")

                for bct in old_bct:
                    batch_ids.append(bct.batch.batch_id)
                    titles.append(bct.batch.title or bct.batch.batch_name)

                    course = bct.course
                    course_ids.append(course.course_id)
                    course_names.append(course.course_name)

                    category = course.course_category
                    category_ids.append(category.category_id if category else None)
                    category_names.append(category.category_name if category else None)

                # ---------------- NEW BATCH ----------------
                new_batches = NewBatch.objects.filter(
                    trainer=t,
                    is_archived=False
                ).select_related("course__course_category")

                for nb in new_batches:
                    batch_ids.append(nb.batch_id)
                    titles.append(nb.title)

                    course = nb.course
                    course_ids.append(course.course_id)
                    course_names.append(course.course_name)

                    category = course.course_category
                    category_ids.append(category.category_id if category else None)
                    category_names.append(category.category_name if category else None)

                # Remove duplicates while keeping order
                batch_ids = list(dict.fromkeys(batch_ids))
                titles = list(dict.fromkeys(titles))
                course_ids = list(dict.fromkeys(course_ids))
                course_names = list(dict.fromkeys(course_names))
                category_ids = list(dict.fromkeys(category_ids))
                category_names = list(dict.fromkeys(category_names))

                trainer_data.append({
                    "employee_id": t.employee_id,
                    "full_name": t.full_name,
                    "role": t.role.role_id if t.role else None,
                    "username": t.username,
                    "user_type": t.user_type,
                    "trainer_id": t.trainer_id,
                    "email": t.email,
                    "contact_no": t.contact_no,
                    "status": t.status,
                    "gender": t.gender,
                    "specialization": t.specialization,
                    "working_hours": t.working_hours,
                    "notes": notes,

                    # ------------------------------------------
                    #        AGGREGATED FIELDS ADDED HERE
                    # ------------------------------------------
                    "batch_id": batch_ids,
                    "title": titles,
                    "course_id": course_ids,
                    "course_name": course_names,
                    "category_id": category_ids,
                    "category_name": category_names,
                })

            trainers_count = trainers_qs.count()

            # Courses, categories, batches, students same logic
            all_courses = Course.objects.filter(is_archived=False, status__iexact="Active")
            all_categories = CourseCategory.objects.filter(is_archived=False, status=True)
            all_batches = Batch.objects.filter(is_archived=False, status=True)

            if user.user_type == "super_admin":
                all_courses = all_courses.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
                all_categories = all_categories.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
                all_batches = all_batches.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                filters = Q(created_by=user_created_id)
                if super_admin_id:
                    filters |= Q(created_by=super_admin_id)
                all_courses = all_courses.filter(filters)
                all_categories = all_categories.filter(filters)
                all_batches = all_batches.filter(filters)

            all_courses = list(
                all_courses.values("course_id", "course_name", "course_category")
            )

            # Rename 'course_category' to 'category_id'
            for course in all_courses:
                course["category_id"] = course.pop("course_category")

            all_categories = list(all_categories.values("category_id", "category_name"))

            # ---------------- BUILD BATCH LIST ----------------
            all_batches = Batch.objects.filter(is_archived=False, status=True)
            if user.user_type == "super_admin":
                all_batches = all_batches.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                filters = Q(created_by=user_created_id, created_by_type="admin")
                if super_admin_id:
                    filters |= Q(created_by=super_admin_id, created_by_type="super_admin")
                all_batches = all_batches.filter(filters)

            all_batches = all_batches.prefetch_related(
                Prefetch(
                    "batchcoursetrainer",
                    queryset=BatchCourseTrainer.objects.select_related("course__course_category"),
                    to_attr="related_courses",
                )
            )

            batch_list = []
            for batch in all_batches:
                if hasattr(batch, "related_courses") and batch.related_courses:
                    course = batch.related_courses[0].course
                    batch_list.append({
                        "batch_id": batch.batch_id,
                        "batch_name": batch.batch_name,
                        "title": batch.title,
                        "course_id": course.course_id,
                        "course_name": course.course_name,
                        "category_id": course.course_category.category_id if course.course_category else None,
                        "category_name": course.course_category.category_name if course.course_category else None,
                    })
                else:
                    batch_list.append({
                        "batch_id": batch.batch_id,
                        "batch_name": batch.batch_name,
                        "title": batch.title,
                        "course_id": None,
                        "course_name": None,
                        "category_id": None,
                        "category_name": None,
                    })

            # Students
            all_students = Student.objects.filter(is_archived=False, status=True)
            if user.user_type == "super_admin":
                all_students = all_students.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                filters = Q(created_by=user_created_id)
                if super_admin_id:
                    filters |= Q(created_by=super_admin_id)
                all_students = all_students.filter(filters)

            student_list = [
                {
                    "registration_id": s.registration_id,
                    "student_id": s.student_id,
                    "full_name": f"{s.first_name} {s.last_name}".strip()
                }
                for s in all_students
            ]

            roles = Role.objects.filter(is_archived=False)
            role = RoleSerializer(roles, many=True).data

            return Response({
                "success": True,
                "trainer_data": trainer_data,
                "trainers_count": trainers_count,
                "courses": all_courses,
                "categories": all_categories,
                "batches": batch_list,
                "students": student_list,
                "roles": role
            }, status=200)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=200)
   
class TrainerTravelExpenseViewSet(viewsets.ModelViewSet):
    queryset = TrainerTravelExpense.objects.all().order_by('-created_at')
    serializer_class = TrainerTravelExpenseSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        trainer_id = self.kwargs.get('trainer_id')
        if trainer_id:
            return self.queryset.filter(trainer__trainer_id=trainer_id, is_archived=False).order_by('-created_at')
        return self.queryset.none()

    def list(self, request, *args, **kwargs):
        """
        List all expenses for the trainer
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        trainer_id = self.kwargs.get('trainer_id')
        trainer = Trainer.objects.filter(trainer_id=trainer_id).first()
        if not trainer:
            return Response({"success": False, "message": "Trainer not found"}, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expense = serializer.save(trainer=trainer)

        # handle bills from request.FILES
        bills = request.FILES.getlist('bills')
        for bill in bills:
            TrainerTravelExpenseImage.objects.create(expense=expense, image=bill)

        return Response({"success": True, "data": self.get_serializer(expense).data}, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        expense_id = self.kwargs.get('expense_id')
        expense = TrainerTravelExpense.objects.filter(expense_id=expense_id, is_archived=False).first()
        if not expense:
            return Response({"success": False, "message": "Expense not found"}, status=status.HTTP_200_OK)

        serializer = self.get_serializer(expense)
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        user = request.user
        expense_id = self.kwargs.get('expense_id')  # get from URL
        instance = TrainerTravelExpense.objects.filter(expense_id=expense_id, is_archived=False).first()
        
        if not instance:
            return Response({"success": False, "message": "Expense not found"}, status=status.HTTP_200_OK)

        if user.user_type not in ["admin", "super_admin"]:
            return Response({"detail": "Not authorized to update status."}, status=status.HTTP_200_OK)

        instance.status = request.data.get('status', instance.status)
        instance.remarks = request.data.get('remarks', instance.remarks)
        instance.save()
        
        serializer = self.get_serializer(instance)
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    def is_archived(self, request, *args, **kwargs):
        expense_id = self.kwargs.get('expense_id')
        expense = TrainerTravelExpense.objects.filter(expense_id=expense_id).first()
        if not expense:
            return Response({"success": False, "message": "Expense not found"}, status=status.HTTP_200_OK)

        expense.is_archived = True
        expense.save()
        return Response({"success": True, "message": "Expense deleted successfully"}, status=status.HTTP_200_OK)

class TrainerAttendanceViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = TrainerAttendanceSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        employee_id = self.kwargs.get('employee_id') or self.request.query_params.get('trainer')
        if not employee_id:
            return TrainerAttendance.objects.none().order_by('-date')
        today = get_ist_now().date()
        
        # only today's attendance
        return TrainerAttendance.objects.filter(
            trainer__employee_id=employee_id,
            date__date=today
        ).order_by('-date')

    def list(self, request, *args, **kwargs):
        employee_id = self.kwargs.get('employee_id') or request.query_params.get('trainer')

        if not employee_id:
            return Response({"success": False, "message": "Trainer employee_id is required."}, status=200)

        # ----------------- Today's Attendance -----------------
        ist = pytz.timezone("Asia/Kolkata")

        # Get now in IST
        now_ist = timezone.now().astimezone(ist)

        # IST today's start & end
        start_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        end_ist = now_ist.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Convert IST → UTC (because DB stores in UTC)
        start_utc = start_ist.astimezone(pytz.utc)
        end_utc = end_ist.astimezone(pytz.utc)

        # Final queryset (100% correct)
        queryset = TrainerAttendance.objects.filter(
            trainer__employee_id=employee_id,
            date__range=(start_utc, end_utc)
        ).order_by('-date')

        # ------------------- Attendance Data -------------------
        attendance_data = [
            {
                "trainer": att.trainer.employee_id,
                "trainer_name": att.trainer.full_name,
                "title": att.new_batch.title if att.new_batch else (att.batch.title if att.batch else None),
                "course_id": att.course.course_id,
                "course_name": att.course.course_name,
                "batch_id": att.new_batch.batch_id if att.new_batch else (att.batch_id if att.batch else None),
                "topic": getattr(att, 'topic', ""),
                "sub_topic": getattr(att, 'sub_topic', ""),
                "date": att.date.astimezone(ist).strftime("%Y-%m-%d %I:%M:%S %p"),
                "status": att.status,
                "marked_by_admin": att.marked_by_admin,
                "extra_hours": getattr(att, 'extra_hours', None)
            }
            for att in queryset
        ]

        # ------------------- Trainer Info -------------------
        try:
            trainer = Trainer.objects.get(employee_id=employee_id)
        except Trainer.DoesNotExist:
            return Response({"success": False, "message": "Trainer not found."}, status=200)

        # ------------------- New Batches -------------------
        new_batches = NewBatch.objects.filter(trainer=trainer, is_archived=False, status=True)
        new_batch_data = [
            {
                "batch_id": batch.batch_id,
                "batch_name": batch.title,
                "title": batch.title,
                "course": batch.course.course_id,
                "course_name": batch.course.course_name
            }
            for batch in new_batches
        ]

        # ------------------- Old Batches -------------------
        old_batch_ids = BatchCourseTrainer.objects.filter(trainer=trainer).values_list("batch_id", flat=True).distinct()
        old_batches = Batch.objects.filter(batch_id__in=old_batch_ids, is_archived=False, status=True)

        old_batch_data = []
        for batch in old_batches:
            course_obj = BatchCourseTrainer.objects.filter(batch=batch, trainer=trainer).first()
            old_batch_data.append({
                "batch_id": batch.batch_id,
                "batch_name": batch.batch_name,
                "title": batch.title,
                "course": course_obj.course.course_id if course_obj else None,
                "course_name": course_obj.course.course_name if course_obj else None,
            })

        # ------------------- Combine -------------------
        final_batches = new_batch_data + old_batch_data

        return Response({
            "success": True,
            "message": "Trainer today's attendance and batches fetched.",
            "data": attendance_data,  # all today logs
            "batches": final_batches  # full batch list
        }, status=200)
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=False)

        if not serializer.is_valid():
            flat_errors = {
                key: value[0] if isinstance(value, list) and value else value
                for key, value in serializer.errors.items()
            }
            return Response({
                'success': False,
                'message': flat_errors
            }, status=status.HTTP_200_OK)

        trainer_employee_id = request.data.get('trainer')
        course_id = request.data.get('course')
        batch_id = request.data.get('new_batch')   # This is NEW BATCH ID now

        if not all([trainer_employee_id, course_id, batch_id]):
            return Response({
                'success': False,
                'message': 'Trainer, course, and batch are required.'
            }, status=status.HTTP_200_OK)

        # Fetch trainer
        try:
            trainer = Trainer.objects.get(employee_id=trainer_employee_id)
        except Trainer.DoesNotExist:
            return Response({'success': False, 'message': 'Trainer not found.'}, status=status.HTTP_200_OK)

        # Fetch course
        try:
            course = Course.objects.get(pk=course_id)
        except Course.DoesNotExist:
            return Response({'success': False, 'message': 'Course not found.'}, status=status.HTTP_200_OK)

        # 🚀 Fetch NEW batch
        try:
            new_batch = NewBatch.objects.get(batch_id=batch_id, is_archived=False)
        except NewBatch.DoesNotExist:
            return Response({'success': False, 'message': 'Batch not found.'}, status=status.HTTP_200_OK)

        # 🔹 Validate trainer-course-batch assignment (NewBatch version)
        is_course_assigned = (
            new_batch.course_id == course.course_id and
            new_batch.trainer_id == trainer.trainer_id
        )

        if not is_course_assigned:
            return Response({
                'success': False,
                'message': 'This course is not assigned to the trainer for this batch.'
            }, status=status.HTTP_200_OK)

        # 🔹 Check if trainer has this course scheduled today
        today = localtime().date()
        class_scheduled = ClassSchedule.objects.filter(
            trainer=trainer,
            course=course,
            new_batch=new_batch,    # Use new batch mapping
            scheduled_date=today,
            is_archived=False
        ).exists()

        if not class_scheduled:
            return Response({
                'success': False,
                'message': 'No class scheduled today for this trainer, course, and batch.'
            }, status=status.HTTP_200_OK)

        # 🔹 All validations passed → create attendance
        self.perform_create(serializer)

        return Response({
            'message': 'Attendance recorded successfully',
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_201_CREATED)

    def format_hhmmss(self, total_seconds):
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
    
    @action(detail=True, methods=['get'], url_path='full_logs')
    def full_logs(self, request, employee_id=None, *args, **kwargs):
        employee_id = employee_id
        month = request.query_params.get("month")
        year = request.query_params.get("year")
        
        user = request.user

        allowed_types = ["super_admin", "admin", "tutor"]

        if user.user_type not in allowed_types:
            return Response({
                "success": False,
                "message": "You are not authorized to access this API"
            }, status=403)

        if not employee_id:
            return Response({"success": False, "message": "employee_id is required"}, status=200)

        trainer = Trainer.objects.filter(employee_id=employee_id).first()
        if not trainer:
            return Response({"success": False, "message": "Trainer not found"}, status=200)

        full_name = trainer.full_name

        # Base queryset
        queryset = TrainerAttendance.objects.filter(
            trainer__employee_id=employee_id
        ).order_by("-date")

        # Filter monthly logs only if both provided
        monthly_filter = False
        if month and year:
            monthly_filter = True
            queryset = queryset.filter(
                date__month=int(month),
                date__year=int(year)
            )

        serializer = self.get_serializer(queryset, many=True)
        logs = serializer.data

        from collections import defaultdict
        grouped_logs = defaultdict(list)

        for log in logs:
            log_date = log["date"].split(" ")[0]
            grouped_logs[log_date].append(log)

        final_logs = []
        monthly_total_seconds = 0

        # Process each day's logs
        for log_date, day_logs in grouped_logs.items():
            work_start = None
            break_start = None
            break_seconds = 0
            total_seconds = 0
            first_login = None
            last_logout = None

            # sort logs of the day
            day_logs = sorted(day_logs, key=lambda x: x["date"], reverse=True)

            for log in day_logs:
                status = log["status"].lower()
                log_time = datetime.strptime(log["date"], "%Y-%m-%d %H:%M:%S")

                if status == "login":
                    if not first_login:
                        first_login = log_time
                    work_start = log_time

                elif status == "logout":
                    last_logout = log_time
                    if work_start:
                        total_seconds += (log_time - work_start).total_seconds() - break_seconds
                        work_start = None
                        break_seconds = 0

                elif status == "break out" and work_start:
                    break_start = log_time

                elif status == "break in" and break_start:
                    break_seconds += (log_time - break_start).total_seconds()
                    break_start = None

            # Daily total
            total_seconds = max(total_seconds, 0)
            total_time_str = self.format_hhmmss(total_seconds)

            # Add to monthly total
            if monthly_filter:
                monthly_total_seconds += total_seconds

            # EXTRA WORKING HOURS (sum of schedule extra time)
            schedules = ClassSchedule.objects.filter(
                trainer=trainer,
                scheduled_date=log_date,
                is_archived=False,
                is_class_cancelled=False
            )

            extra_time = timedelta(0)
            for s in schedules:
                extra_time += s.get_extra_time()

            extra_str = str(extra_time)

            # Assign full_name, daily totals, extra hours
            for log in day_logs:
                log["trainer_full_name"] = full_name
                log["working_hours"] = total_time_str
                log["extra_working_hours"] = extra_str
                log["first_login_time"] = first_login.strftime("%I:%M:%S %p") if first_login else None
                log["last_logout_time"] = last_logout.strftime("%I:%M:%S %p") if last_logout else None
                final_logs.append(log)

        # COURSES (unchanged)
        course = Course.objects.filter(
            batchcoursetrainer__trainer__employee_id=employee_id,
            is_archived=False
        ).values("course_id", "course_name").distinct()

        # OLD BATCHES (Batch)
        old_batches = Batch.objects.filter(
            batchcoursetrainer__trainer__employee_id=employee_id,
            is_archived=False,
            status=True
        ).values("batch_id", "batch_name", "title").distinct()

        # NEW BATCHES (NewBatch)
        new_batches_qs = NewBatch.objects.filter(
            trainer=trainer,
            is_archived=False,
            status=True
        ).select_related("course")

        # Convert new batch into old-batch response format
        new_batches = [
            {
                "batch_id": nb.batch_id,
                "batch_name": nb.title,      # Mapping -> Batch.batch_name
                "title": nb.title,
            }
            for nb in new_batches_qs
        ]

        # COMBINE BOTH
        all_batches = list(old_batches) + list(new_batches)

        # Final response
        response = {
            "success": True,
            "message": f"Full attendance logs for {full_name}",
            "data": final_logs,
            "course": list(course),
            "batch": all_batches
        }

        # Monthly working hours
        if monthly_filter:
            response["monthly_total_working_hours"] = self.format_hhmmss(int(monthly_total_seconds))

        return Response(response, status=200)
        
    from datetime import datetime, timedelta
    from django.utils.dateparse import parse_datetime
    from django.db.models import Q

    @action(detail=False, methods=['post'], url_path='<str:employee_id>/adumneoie')
    def admin_mark_attendance(self, request, employee_id=None):
        try:
            employee_id = request.data.get("trainer")
            course_id = request.data.get("course")
            batch_id = request.data.get("batch")
            date_str = request.data.get("date")
            status_val = request.data.get("status", "Login")

            if not all([employee_id, course_id, batch_id, date_str]):
                return Response({
                    "success": False,
                    "message": "Trainer, course, batch, and date are required."
                }, status=200)

            # ---------- Trainer & Course ----------
            try:
                trainer = Trainer.objects.get(employee_id=employee_id)
            except Trainer.DoesNotExist:
                return Response({"success": False, "message": "Trainer not found"}, status=200)

            try:
                course = Course.objects.get(pk=course_id)
            except Course.DoesNotExist:
                return Response({"success": False, "message": "Course not found"}, status=200)

            # ---------- Handle Both Batch & NewBatch ----------
            batch = None
            new_batch = None

            # Try NewBatch first
            new_batch = NewBatch.objects.filter(batch_id=batch_id, is_archived=False).first()

            if new_batch:
                batch_obj = new_batch  # use new batch object
            else:
                # fallback to old batch
                batch = Batch.objects.filter(pk=batch_id, is_archived=False).first()
                if not batch:
                    return Response({"success": False, "message": "Batch not found"}, status=200)
                batch_obj = batch

            # ---------- Date Parsing ----------
            scheduled_date = parse_datetime(date_str)
            if not scheduled_date:
                return Response({
                    "success": False,
                    "message": "Invalid datetime format. Use ISO 8601 (YYYY-MM-DDTHH:MM:SSZ)."
                }, status=200)

            # ---------- Prevent Duplicate Attendance ----------
            if TrainerAttendance.objects.filter(
                trainer=trainer,
                batch_id=batch_id,
                course=course,
                date__date=scheduled_date.date(),
            ).filter(
                Q(status="Login") | Q(status="Logout")
            ).exists():
                return Response({"success": False, "message": "Attendance already marked."}, status=200)

            # ---------- Create Attendance ----------
            attendance = TrainerAttendance.objects.create(
                trainer=trainer,
                course=course,
                batch_id=batch_id,  # works for both batch & new batch
                date=scheduled_date,
                status=status_val,
                marked_by_admin=True
            )

            return Response({
                "success": True,
                "message": f"Admin marked attendance as {status_val}",
                "data": TrainerAttendanceSerializer(attendance).data,
            }, status=201)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=200)
    
class AdminLogViewSet(LoggingMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def list(self, request):
        try:
            user = request.user
            user_type = getattr(user, "user_type", "").lower()
            ist = pytz.timezone('Asia/Kolkata')
            logs = []

            # Determine super admin's admins
            user_created_id = getattr(user, "trainer_id", None)
            if user_type == "super_admin":
                user_created_id = getattr(user, "user_id", None)

            admin_ids = []
            if user_type == "super_admin" and user_created_id:
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_created_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

            # Base attendance querysets
            student_attendance = Attendance.objects.select_related('student', 'course', 'batch')
            trainer_attendance = TrainerAttendance.objects.select_related('trainer', 'course', 'batch')

            # Filter attendance based on user type
            if user_type == "admin" and user_created_id:
                student_attendance = student_attendance.filter(student__created_by=user_created_id)
                trainer_attendance = trainer_attendance.filter(trainer__created_by=user_created_id)
            elif user_type == "super_admin" and user_created_id:
                student_attendance = student_attendance.filter(
                    Q(student__created_by_type='super_admin', student__created_by=user_created_id) |
                    Q(student__created_by_type='admin', student__created_by__in=admin_ids)
                )
                trainer_attendance = trainer_attendance.filter(
                    Q(trainer__created_by_type='super_admin', trainer__created_by=user_created_id) |
                    Q(trainer__created_by_type='admin', trainer__created_by__in=admin_ids)
                )
            else:
                # Non-admin/non-super_admin see nothing
                return Response({"success": True, "logs": []}, status=200)

            # --- Student logs ---
            for att in student_attendance:
                date_ist = att.date.astimezone(ist) if att.date.tzinfo else pytz.utc.localize(att.date).astimezone(ist)

                # Determine batch info
                if att.batch:  # Old batch
                    batch_id = att.batch.batch_id
                    batch_name = att.batch.batch_name
                    title = att.batch.title
                elif att.new_batch:  # New batch
                    batch_id = att.new_batch.batch_id
                    batch_name = att.new_batch.title
                    title = att.new_batch.title
                else:
                    batch_id = None
                    batch_name = None
                    title = None

                logs.append({
                    "name": f"{att.student.first_name} {att.student.last_name}",
                    "course": att.course.course_name if att.course else None,
                    "user_type": "student",
                    "batch": batch_name,
                    "title": title,
                    "batch_id": batch_id,
                    "course_id": att.course.course_id if att.course else None,
                    "status": att.status,
                    "ip": att.ip_address,
                    "date_time": date_ist.strftime("%Y-%m-%d %I:%M:%S %p"),
                    "total_hours": None
                })


            # --- Trainer logs ---
            trainer_logs = []
            for tatt in trainer_attendance:
                date_ist = tatt.date.astimezone(ist) if tatt.date.tzinfo else pytz.utc.localize(tatt.date).astimezone(ist)

                # Determine batch info
                if tatt.batch:  # Old batch
                    batch_id = tatt.batch.batch_id
                    batch_name = tatt.batch.batch_name
                    title = tatt.batch.title
                elif tatt.new_batch:  # New batch
                    batch_id = tatt.new_batch.batch_id
                    batch_name = tatt.new_batch.title
                    title = tatt.new_batch.title
                else:
                    batch_id = None
                    batch_name = None
                    title = None

                trainer_logs.append({
                    "trainer_id": tatt.trainer.trainer_id,
                    "name": tatt.trainer.full_name,
                    "user_type": "trainer",
                    "batch": batch_name,
                    "batch_id": batch_id,
                    "title": title,
                    "course_id": tatt.course.course_id if tatt.course else None,
                    "course": tatt.course.course_name if tatt.course else None,
                    "topic": tatt.topic,
                    "status": tatt.status,
                    "sub_topic": tatt.sub_topic,
                    "date_time": date_ist.strftime("%Y-%m-%d %I:%M:%S %p")
                })

            # --- Group trainer logs by trainer/day for total_hours ---
            grouped = defaultdict(list)
            for log in trainer_logs:
                log_date = log["date_time"].split(" ")[0]
                key = (log["trainer_id"], log_date)
                grouped[key].append(log)

            final_trainer_logs = []
            for (t_id, log_date), day_logs in grouped.items():
                total_seconds = 0
                work_start = None
                break_start = None
                break_seconds = 0

                day_logs = sorted(day_logs, key=lambda x: x['date_time'])
                for log in day_logs:
                    status_val = log['status'].lower()
                    log_time = datetime.strptime(log['date_time'], "%Y-%m-%d %I:%M:%S %p")

                    if status_val == 'login':
                        work_start = log_time
                    elif status_val == 'logout' and work_start:
                        total_seconds += max(0, (log_time - work_start).total_seconds() - break_seconds)
                        work_start = None
                        break_seconds = 0
                    elif status_val == 'break out' and work_start:
                        break_start = log_time
                    elif status_val == 'break in' and break_start:
                        break_seconds += (log_time - break_start).total_seconds()
                        break_start = None

                total_time = str(timedelta(seconds=int(total_seconds)))
                for log in day_logs:
                    log["total_hours"] = total_time
                    final_trainer_logs.append(log)

            # --- Merge logs ---
            logs.extend(final_trainer_logs)
            logs_sorted = sorted(
                logs,
                key=lambda x: datetime.strptime(x['date_time'], "%Y-%m-%d %I:%M:%S %p"),
                reverse=True
            )

            # --- Courses ---
            courses_qs = Course.objects.filter(is_archived=False)
            if user_type == "super_admin":
                courses_qs = courses_qs.filter(
                    Q(created_by_type='super_admin', created_by=user_created_id) |
                    Q(created_by_type='admin', created_by__in=admin_ids)
                )
            elif user_type == "admin":
                courses_qs = courses_qs.filter(created_by=user_created_id)

            # --- Old Batches ---
            batches_old_qs = Batch.objects.filter(is_archived=False)
            batches_old_qs = batches_old_qs.filter(batchcoursetrainer__course__in=courses_qs).distinct()

            # --- New Batches ---
            batches_new_qs = NewBatch.objects.filter(is_archived=False, status=True)
            if user_type == "super_admin":
                batches_new_qs = batches_new_qs.filter(
                    Q(created_by_type='super_admin', created_by=user_created_id) |
                    Q(created_by_type='admin', created_by__in=admin_ids),
                    course__in=courses_qs
                )
            elif user_type == "admin":
                batches_new_qs = batches_new_qs.filter(
                    created_by=user_created_id,
                    course__in=courses_qs
                )

            # --- Merge old + new batches ---
            batches_merge = []

            for b in batches_old_qs:
                batches_merge.append({
                    "batch_id": b.batch_id,
                    "batch_name": b.batch_name,
                    "title": b.title
                })

            for nb in batches_new_qs:
                batches_merge.append({
                    "batch_id": nb.batch_id,
                    "batch_name": nb.title,
                    "title": nb.title
                })

            # Remove duplicates by batch_id
            batches_merge = list({b["batch_id"]: b for b in batches_merge}.values())

            return Response({
                "success": True,
                "logs": logs_sorted,
                "course": list(courses_qs.values("course_id", "course_name")),
                "batch": batches_merge
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

def get_ist_now():
    ist = pytz.timezone('Asia/Kolkata')
    return timezone.now().astimezone(ist)

class PublicHolidaysView(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def list(self, request):
        """
        Fetch public holidays dynamically for a given country and subdivision (state).
        Example: /api/holidays?country=IN&subdiv=TN&year=2025
        """
        year = int(request.GET.get('year', datetime.now().year))
        country = request.GET.get('country', 'IN')
        subdiv = request.GET.get('subdiv', None)

        try:
            if subdiv:
                selected_holidays = holidays.country_holidays(country, subdiv=subdiv, years=year)
            else:
                selected_holidays = holidays.country_holidays(country, years=year)
        except Exception as e:
            return Response({'success': False, 'message': str(e)}, status=status.HTTP_200_OK)

        holiday_list = [{"date": str(date), "name": name} for date, name in sorted(selected_holidays.items())]

        return Response({
            "success": True,
            "country": country,
            "subdivision": subdiv,
            "year": year,
            "holidays": holiday_list
        }, status=status.HTTP_200_OK)

class AnnouncementViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = Announcement.objects.all()
    serializer_class = AnnouncementSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'id'
    
    def get_queryset(self):
        user = self.request.user
        qs = Announcement.objects.filter(is_archived=False)

        # -------- SUPER ADMIN --------
        if user.user_type == "super_admin":
            super_admin_id = str(user.user_id)

            admin_ids = Trainer.objects.filter(
                created_by=super_admin_id,
                created_by_type="super_admin",
                is_archived=False
            ).values_list("trainer_id", flat=True)

            allowed_creators = list(admin_ids) + [super_admin_id]

            return qs.filter(created_by__in=allowed_creators).order_by("-created_at")

        # -------- ADMIN --------
        if user.user_type == "admin" and getattr(user, "trainer_id", None):
            admin_trainer_id = str(user.trainer_id)

            super_admin_id = Trainer.objects.filter(
                trainer_id=admin_trainer_id,
                created_by_type="super_admin",
                is_archived=False
            ).values_list("created_by", flat=True).first()

            allowed_creators = [admin_trainer_id]
            if super_admin_id:
                allowed_creators.append(str(super_admin_id))

            return qs.filter(created_by__in=allowed_creators).order_by("-created_at")

        return qs.none()

    def list(self, request, *args, **kwargs):
        user = request.user

        queryset = self.get_queryset()

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                "success": True,
                "count": queryset.count(),
                "data": serializer.data
            }
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            first_error = next(iter(serializer.errors.values()))[0]
            return Response({
                "success": False,
                "message": first_error
            }, status=status.HTTP_200_OK)

        announcement = serializer.save()
        return Response({
            "success": True,
            "message": "Announcement created successfully.",
            "data": self.get_serializer(announcement).data
        }, status=status.HTTP_201_CREATED)
        
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        if not serializer.is_valid():
            first_error = next(iter(serializer.errors.values()))[0]
            return Response({
                "success": False,
                "message": first_error
            }, status=status.HTTP_200_OK)

        announcement = serializer.save()
        return Response({
            "success": True,
            "message": "Announcement updated successfully.",
            "data": self.get_serializer(announcement).data
        }, status=status.HTTP_201_CREATED)
        
    def is_archived(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            instance.is_archived = True
            instance.save()
            return Response({ 'success': True ,'message': 'Announcement deleted successfully.'}, status=status.HTTP_200_OK)
        except Announcement.DoesNotExist:
            return Response({ 'success': False,'message': 'Announcement not found.'}, status=status.HTTP_200_OK)

class FeedbackViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = Feedback.objects.all()
    serializer_class = FeedbackSerializer
    
class LeaveRequestViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = LeaveRequest.objects.all()
    serializer_class = LeaveRequestSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        return LeaveRequest.objects.none()

    def perform_create(self, serializer):
        # Attach the current user as the requester
        serializer.save(user=self.request.user, status='pending')

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        leave_request = self.get_object()
        user = request.user
        if hasattr(user, 'user_type') and user.user_type == 'admin':
            leave_request.status = 'approved'
            leave_request.save()
            return Response({'success': True, 'message': 'Leave request approved.'}, status=200)
        return Response({'success': False, 'message': 'Permission denied.'}, status=200)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        leave_request = self.get_object()
        user = request.user
        if hasattr(user, 'user_type') and user.user_type == 'admin':
            leave_request.status = 'rejected'
            leave_request.save()
            return Response({'success': True, 'message': 'Leave request rejected.'}, status=200)
        return Response({'success': False, 'message': 'Permission denied.'}, status=200)
    
class ClassScheduleView(LoggingMixin, viewsets.ModelViewSet, NotesMixin):
    serializer_class = ClassScheduleSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'schedule_id'

    def get_queryset(self):
        user = self.request.user
        qs = ClassSchedule.objects.filter(is_archived=False)

        # ---------------- SUPER ADMIN ----------------
        if user.user_type == "super_admin":
            super_admin_id = str(user.user_id)

            admin_ids = list(
                Trainer.objects.filter(
                    created_by=super_admin_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )
            admin_ids = [str(a) for a in admin_ids]

            trainer_ids = list(
                Trainer.objects.filter(
                    created_by__in=admin_ids,
                    created_by_type="admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )
            trainer_ids = [str(t) for t in trainer_ids]

            allowed_creators = admin_ids + trainer_ids + [super_admin_id]

            qs = qs.filter(
                Q(created_by__in=allowed_creators) |
                Q(trainer__trainer_id__in=trainer_ids)
            )

        # ---------------- ADMIN ----------------
        elif user.user_type == "admin" and getattr(user, "trainer_id", None):
            admin_trainer_id = str(user.trainer_id)

            trainer_ids = list(
                Trainer.objects.filter(
                    created_by=admin_trainer_id,
                    created_by_type="admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )
            trainer_ids = [str(t) for t in trainer_ids]

            qs = qs.filter(
                Q(created_by=admin_trainer_id) |
                Q(trainer__trainer_id__in=trainer_ids)
            )

        # ---------------- TRAINER ----------------
        elif user.user_type in ["tutor", "trainer"]:
            trainer_id = str(user.trainer_id)
            qs = qs.filter(trainer__trainer_id=trainer_id)

        return qs.select_related('batch', 'course', 'trainer').order_by('-scheduled_date')

    def list(self, request, *args, **kwargs):
        try:
            user = request.user
            user_type = user.user_type.lower()
            user_id = str(user.user_id)
            trainer_id = str(getattr(user, "trainer_id", None))
            allowed_types = ["super_admin", "admin"]
            if user_type not in allowed_types:
                return Response({
                    "success": False,
                    "message": "You are not authorized to access this API"
                }, status=200)
            
            now = timezone.now()

            schedule_qs = (
                self.get_queryset()
                .select_related("batch", "new_batch", "trainer", "course", "course__course_category")
                .prefetch_related(
                    Prefetch(
                        "batch__batchcoursetrainer",
                        queryset=BatchCourseTrainer.objects.select_related(
                            "course", "trainer", "student"
                        ),
                        to_attr="old_assignments"
                    ),
                    Prefetch(
                        "new_batch__students",
                        queryset=Student.objects.only("registration_id", "first_name", "last_name"),
                        to_attr="new_students"
                    )
                )
            )

            # ---------------- MONTH & YEAR FILTER ----------------
            month = request.query_params.get("month")
            year = request.query_params.get("year")

            if month and year:
                try:
                    month = int(month)
                    year = int(year)

                    schedule_qs = schedule_qs.filter(
                        scheduled_date__year=year,
                        scheduled_date__month=month
                    )
                except ValueError:
                    return Response({
                        "success": False,
                        "message": "Invalid month or year"
                    }, status=400)

            schedule_data = []

            for sched in schedule_qs:
                start_time = sched.start_time or time(9, 0)
                class_start = timezone.make_aware(datetime.combine(sched.scheduled_date, start_time))
                class_end = class_start + (sched.duration or timedelta(hours=1))

                if sched.end_time:
                    class_end = timezone.make_aware(datetime.combine(sched.scheduled_date, sched.end_time))

                if sched.is_class_cancelled:
                    status_info = "cancelled"
                elif now < class_start:
                    status_info = "upcoming"
                elif class_start <= now <= class_end:
                    status_info = "ongoing"
                else:
                    status_info = "completed"

                assignments_list = []

                # OLD ASSIGNMENTS (prefetched)
                for a in getattr(sched.batch, "old_assignments", []):
                    assignments_list.append({
                        "course_id": a.course.course_id,
                        "course_name": a.course.course_name,
                        "trainer_employee_id": a.trainer.employee_id,
                        "trainer_name": a.trainer.full_name,
                        "registration_id": a.student.registration_id,
                        "student_name": f"{a.student.first_name} {a.student.last_name}".strip(),
                        "batch_type": "old",
                    })

                # NEW BATCH ASSIGNMENTS (prefetched)
                if sched.new_batch:
                    for ns in sched.new_batch.new_students:
                        assignments_list.append({
                            "course_id": sched.new_batch.course.course_id if sched.new_batch.course else None,
                            "course_name": sched.new_batch.course.course_name if sched.new_batch.course else None,
                            "trainer_employee_id": sched.new_batch.trainer.employee_id if sched.new_batch.trainer else None,
                            "trainer_name": sched.new_batch.trainer.full_name if sched.new_batch.trainer else None,
                            "registration_id": ns.registration_id,
                            "student_name": f"{ns.first_name} {ns.last_name}".strip(),
                            "batch_type": "new",
                        })

                schedule_data.append({
                    "schedule_id": sched.schedule_id,
                    "course_id": sched.course.course_id if sched.course else None,
                    "course_name": sched.course.course_name if sched.course else None,
                    "category_name": sched.course.course_category.category_name
                        if sched.course and sched.course.course_category else None,

                    "batch_type": "old" if sched.batch else "new" if sched.new_batch else None,
                    "batch_id": sched.batch.batch_id if sched.batch else (
                        sched.new_batch.batch_id if sched.new_batch else None),
                    "batch_name": sched.batch.batch_name if sched.batch else None,
                    "title": (
                        sched.new_batch.title if sched.new_batch
                        else sched.batch.title if sched.batch
                        else None
                    ),
                    "start_date": sched.new_batch.start_date if sched.new_batch else None,
                    "end_date": sched.new_batch.end_date if sched.new_batch else None,

                    "trainer_employee_id": sched.trainer.employee_id if sched.trainer else None,
                    "trainer_name": sched.trainer.full_name if sched.trainer else None,

                    "scheduled_date": sched.scheduled_date,
                    "start_time": sched.start_time,
                    "end_time": sched.end_time,

                    "is_class_cancelled": sched.is_class_cancelled,
                    "is_online_class": sched.is_online_class,
                    "class_link": sched.class_link,

                    "course_trainer_assignments": assignments_list,
                    "status_info": status_info,
                    'is_archived': sched.is_archived,
                })

            # ------------------ Hierarchy-based Active Data ------------------
            batch_filter = Q(is_archived=False, status=True)
            course_filter = Q(is_archived=False, status__iexact="Active")
            category_filter = Q(is_archived=False)

            if user_type == "super_admin":
                user_id_str = str(user_id)

                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_id_str,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

                admin_ids_str = [str(i) for i in admin_ids]

                ownership_q = (
                    Q(created_by=user_id_str, created_by_type="super_admin") |
                    Q(created_by__in=admin_ids_str, created_by_type="admin")
                )

                batch_filter &= ownership_q
                course_filter &= ownership_q
                category_filter &= ownership_q


            elif user_type == "admin":
                trainer_id_str = str(trainer_id)

                super_admin_id = Trainer.objects.filter(
                    trainer_id=trainer_id
                ).values_list("created_by", flat=True).first()

                super_admin_id_str = str(super_admin_id) if super_admin_id else None

                ownership_q = (
                    Q(created_by=trainer_id_str, created_by_type="admin") |
                    Q(created_by=super_admin_id_str, created_by_type="super_admin")
                )

                batch_filter &= ownership_q
                course_filter &= ownership_q
                category_filter &= ownership_q


            # ------------------- Fetch batches -------------------
            batch_qs = NewBatch.objects.filter(batch_filter).select_related(
                "course", "course__course_category", "trainer"
            )

            print("Batch QS Count:", batch_qs.count())

            batch_data = [
                {
                    "batch_id": b.batch_id,
                    "title": b.title,
                    "start_date": b.start_date,
                    "end_date": b.end_date,
                    "start_time": b.start_time,
                    "end_time": b.end_time,
                    "employee_id": b.trainer.employee_id if b.trainer else None,
                    "trainer_name": b.trainer.full_name if b.trainer else None,
                    "trainer_id": b.trainer.trainer_id if b.trainer else None,
                    "course_id": b.course.course_id if b.course else None,
                    "course_name": b.course.course_name if b.course else None,
                }
                for b in batch_qs
            ]


            # ------------------- Fetch courses with batches -------------------
            course_qs = Course.objects.filter(course_filter).select_related("course_category")
            course_data = [
                {
                    "course_id": c.course_id,
                    "course_name": c.course_name,
                    "category_id": c.course_category.category_id if c.course_category else None,
                    "category_name": c.course_category.category_name if c.course_category else None,
                } for c in course_qs
            ]

            # ------------------- Fetch trainers -------------------
            trainer_qs = Trainer.objects.filter(is_archived=False, status__iexact="Active", user_type='tutor')
            if user_type == "super_admin":
                trainer_qs = trainer_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user_type == "admin":
                trainer_qs = trainer_qs.filter(created_by=trainer_id)

            trainer_data = [
                {
                    "trainer_id": t.trainer_id,
                    "employee_id": t.employee_id,
                    "full_name": t.full_name,
                } for t in trainer_qs
            ]

            # ------------------- Categories -------------------
            category_qs = CourseCategory.objects.filter(category_filter).order_by("category_name")
            category_data = [
                {
                    "category_id": cat.category_id,
                    "category_name": cat.category_name,
                } for cat in category_qs
            ]

            # ------------------- Return response -------------------
            return Response({
                "success": True,
                "message": "Class schedule retrieved successfully",
                "Class_Schedule": schedule_data,
                "Batches": batch_data,          # Flat list
                "Courses": course_data,         # Courses with batches inside
                "Trainers": trainer_data,
                "Categories": category_data,
            })

        except Exception as e:
            return Response({"success": False, "message": str(e)})

    @cache_api(prefix="retrive_schedules", timeout=300)
    def retrieve(self, request, *args, **kwargs):
        try:
            sched = self.get_object()
            serializer = self.get_serializer(sched)
            return Response({
                "success": True,
                "message": "Schedule retrieved successfully.",
                "data": serializer.data
            }, status=200)
        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=200)
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
        # Collect all errors
            errors = []
            for field, msgs in serializer.errors.items():
                for msg in msgs:
                    if field == "non_field_errors":
                        errors.append(msg)
                    else:
                        errors.append(f"{field}: {msg}")

            return Response({
                "success": False,
                "message": " | ".join(errors)  # shows all missing/invalid fields
            }, status=status.HTTP_200_OK)

        class_schedule = serializer.save()
        return Response({
            "success": True,
            "message": "Class schedule created successfully.",
            "data": self.get_serializer(class_schedule).data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        try:
            partial = kwargs.pop('partial', False)
            sched = self.get_object()
            serializer = self.get_serializer(sched, data=request.data, partial=partial, context={'request': request})
            serializer.is_valid(raise_exception=True)
            serializer.save()

            # Save notes if provided in request
            notes_text = request.data.get("notes")
            if notes_text:
                mixin = NotesMixin()
                mixin.save_notes(sched, notes_text, request=request)

            return Response({
                "success": True,
                "message": "Schedule updated successfully",
                "data": serializer.data
            })
        except Exception as e:
            return Response({"success": False, "message": str(e)})

    def archive(self, request, schedule_id=None):
        try:
            class_schedule = ClassSchedule.objects.get(schedule_id=schedule_id)
            class_schedule.is_archived = True
            class_schedule.save()
            delete_cache_pattern("schedules*")
            print(f'schedule arch: {class_schedule.is_archived}, id {class_schedule.schedule_id}')
            return Response({'success': True, 'message': 'Class schedule deleted successfully.'}, status=200)
        except ClassSchedule.DoesNotExist:
            return Response({'success': False, 'message': 'Class schedule not found, but no error raised.'}, status=200)

    @cache_api(prefix="trainer_schedules", timeout=300)
    @action(detail=False, methods=['get'], url_path='schedules')
    def schedules(self, request, employee_id=None):
        from datetime import datetime, timedelta, time as dtime
        try:
            user = self.request.user
            now = timezone.now()

            # ------------------ BASE QUERYSET ------------------
            qs = ClassSchedule.objects.filter(
                trainer__employee_id=employee_id,
                is_archived=False
            ).all().select_related(
                "batch",
                "new_batch",
                "course",
                "trainer"
            ).order_by(
                "-scheduled_date",
                "-start_time"
            )

            # ------------------ MONTH & YEAR FILTER ------------------
            month = request.query_params.get("month")
            year = request.query_params.get("year")
            if month and year:
                try:
                    month_i = int(month)
                    year_i = int(year)
                    qs = qs.filter(
                        scheduled_date__year=year_i,
                        scheduled_date__month=month_i
                    )
                except ValueError:
                    return Response({
                        "success": False,
                        "message": "Invalid month or year"
                    }, status=400)

            # Materialize schedules to list to avoid re-evaluating queryset
            schedules = list(qs)

            # If no schedules return quickly (but still return batches/courses/trainers below)
            if not schedules:
                # compute batches/courses/trainer lists below from trainer id
                pass

            # For each schedule we will check attendance within [start-5min, end+5min]
            window_starts = []
            window_ends = []
            for sched in schedules:
                start_time = getattr(sched, "start_time", None) or dtime(9, 0)
                # class start dt
                class_start_dt = timezone.make_aware(
                    datetime.combine(sched.scheduled_date, start_time),
                    timezone.get_current_timezone()
                )

                # compute class end
                class_end_dt = class_start_dt + timedelta(hours=1)
                try:
                    if getattr(sched, "end_time", None):
                        class_end_dt = timezone.make_aware(
                            datetime.combine(sched.scheduled_date, sched.end_time),
                            timezone.get_current_timezone()
                        )
                    elif getattr(sched, "duration", None):
                        class_end_dt = class_start_dt + sched.duration
                except Exception:
                    class_end_dt = class_start_dt + timedelta(hours=1)

                buffer = timedelta(minutes=5)
                window_starts.append(class_start_dt - buffer)
                window_ends.append(class_end_dt + buffer)

            if window_starts and window_ends:
                global_start = min(window_starts)
                global_end = max(window_ends)
            else:
                # no schedules: fallback to today window
                global_start = timezone.now() - timedelta(days=1)
                global_end = timezone.now() + timedelta(days=1)

            # ------------------ BULK FETCH ATTENDANCE for all relevant trainers/batches/courses ------------------
            trainer_obj = None
            if schedules:
                trainer_obj = schedules[0].trainer  # all schedules are for same trainer.employee_id

            attendance_map = defaultdict(list)  # key => list of attendance rows
            if trainer_obj:
                attendance_qs = TrainerAttendance.objects.filter(
                    trainer=trainer_obj,
                    date__gte=global_start,
                    date__lte=global_end,
                    status__in=["Login", "Logout", "Present"]
                ).select_related("batch", "course", "trainer").order_by("-date")

                # Group attendance by (batch_id, course_id)
                for att in attendance_qs:
                    key = (getattr(att.batch, "batch_id", None), getattr(att.course, "course_id", None))
                    attendance_map[key].append(att)

            # ------------------ PRELOAD OLD-BATCH ASSIGNMENTS (BatchCourseTrainer) ------------------
            old_batch_ids = [sched.batch.batch_id for sched in schedules if getattr(sched, "batch", None)]
            old_batch_ids = list(set(old_batch_ids))

            bct_map = defaultdict(list)
            if old_batch_ids:
                bct_qs = BatchCourseTrainer.objects.filter(
                    batch__batch_id__in=old_batch_ids,
                    trainer__employee_id=employee_id
                ).select_related("course", "trainer", "student")

                for bct in bct_qs:
                    bid = getattr(bct.batch, "batch_id", None)
                    bct_map[bid].append(bct)

            # ------------------ PRELOAD NEW-BATCH STUDENTS ------------------
            new_batch_ids = [sched.new_batch.batch_id for sched in schedules if getattr(sched, "new_batch", None)]
            new_batch_ids = list(set(new_batch_ids))

            newbatch_students_map = {}
            if new_batch_ids:
                nb_qs = NewBatch.objects.filter(batch_id__in=new_batch_ids).prefetch_related("students")
                for nb in nb_qs:
                    newbatch_students_map[nb.batch_id] = list(nb.students.all().values("registration_id", "first_name", "last_name"))

            # ------------------ BUILD schedule_data (single loop, no DB hits inside) ------------------
            schedule_data = []
            current_time = timezone.now()

            for sched in schedules:
                start_time = getattr(sched, 'start_time', None) or dtime(9, 0)
                class_start_dt = timezone.make_aware(
                    datetime.combine(sched.scheduled_date, start_time),
                    timezone.get_current_timezone()
                )

                # compute class end as above
                class_end_dt = class_start_dt + timedelta(hours=1)
                try:
                    if getattr(sched, 'end_time', None):
                        class_end_dt = timezone.make_aware(
                            datetime.combine(sched.scheduled_date, sched.end_time),
                            timezone.get_current_timezone()
                        )
                    elif getattr(sched, 'duration', None):
                        class_end_dt = class_start_dt + sched.duration
                except Exception:
                    class_end_dt = class_start_dt + timedelta(hours=1)

                buffer = timedelta(minutes=5)
                window_start = class_start_dt - buffer
                window_end = class_end_dt + buffer

                key = (getattr(sched.batch, "batch_id", None), getattr(sched.course, "course_id", None))
                attendance_for_key = attendance_map.get(key, [])

                # Determine status_info
                if sched.is_class_cancelled:
                    status_info = 'cancelled'
                elif current_time < class_start_dt:
                    status_info = "upcoming"
                elif class_start_dt <= current_time <= class_end_dt:
                    status_info = "ongoing"
                else:
                    # completed if any attendance exists in window, else missed
                    # attendance_for_key already contains attendances in global window; filter by schedule window
                    exists_in_window = any((a.date >= window_start and a.date <= window_end) for a in attendance_for_key)
                    status_info = "completed" if exists_in_window else "missed"

                old_batch = getattr(sched, "batch", None)
                new_batch = getattr(sched, "new_batch", None)
                batch_obj = old_batch if old_batch else new_batch
                batch_name = old_batch.batch_name if old_batch else (new_batch.title if new_batch else None)

                # ------------------ ASSIGNMENTS: old_batch -> from bct_map, new_batch -> from newbatch_students_map
                if old_batch:
                    assignments_list = []
                    bct_list = bct_map.get(old_batch.batch_id, [])
                    for a in bct_list:
                        student = a.student
                        assignments_list.append({
                            "course_id": a.course.course_id if a.course else None,
                            "course_name": a.course.course_name if a.course else None,
                            "employee_id": a.trainer.employee_id if a.trainer else None,
                            "trainer_name": a.trainer.full_name if a.trainer else None,
                            "registration_id": student.registration_id if student else None,
                            "student_name": f"{getattr(student,'first_name','')} {getattr(student,'last_name','')}".strip()
                        })
                elif new_batch:
                    assignments_list = []
                    students_vals = newbatch_students_map.get(new_batch.batch_id, [])
                    for s in students_vals:
                        assignments_list.append({
                            "course_id": getattr(sched.course, "course_id", None),
                            "course_name": getattr(sched.course, "course_name", None),
                            "employee_id": sched.trainer.employee_id if sched.trainer else None,
                            "trainer_name": sched.trainer.full_name if sched.trainer else None,
                            "registration_id": s.get("registration_id"),
                            "student_name": f"{s.get('first_name','')} {s.get('last_name','')}".strip()
                        })
                else:
                    assignments_list = []

                # latest_log and attendance_status
                # filter attendance_for_key to schedule window and pick latest by date
                in_window_att = [a for a in attendance_for_key if a.date >= window_start and a.date <= window_end]
                in_window_att.sort(key=lambda x: x.date, reverse=True)
                latest_log = in_window_att[0] if in_window_att else None
                attendance_status = latest_log.status if latest_log else None

                schedule_data.append({
                    "schedule_id": getattr(sched, "schedule_id", None),
                    "course_id": getattr(sched.course, "course_id", None),
                    "course_name": getattr(sched.course, "course_name", None),
                    "batch_id": getattr(batch_obj, "batch_id", None),
                    "batch_name": batch_name,
                    "title": getattr(batch_obj, "title", None),
                    "trainer_id": sched.trainer.employee_id if sched.trainer else None,
                    "trainer_name": sched.trainer.full_name if sched.trainer else None,
                    "scheduled_date": getattr(sched, "scheduled_date", None),
                    "class_link": getattr(sched, "class_link", None),
                    "course_trainer_assignments": assignments_list,
                    "start_time": sched.start_time,
                    "end_time": sched.end_time,
                    "is_class_cancelled": sched.is_class_cancelled,
                    "attendance_status": attendance_status,
                    "status_info": status_info,
                })

            # ------------------ HIERARCHY FILTERED BATCHES ------------------
            # New system batches for this trainer only
            new_batch_qs = NewBatch.objects.filter(
                trainer__employee_id=employee_id,
                is_archived=False,
                status=True
            ).select_related("trainer", "course").order_by("batch_id")

            # Old batches where trainer is linked via BatchCourseTrainer
            old_batch_ids_for_trainer = BatchCourseTrainer.objects.filter(
                trainer__employee_id=employee_id
            ).values_list("batch__batch_id", flat=True).distinct()

            old_batch_qs = Batch.objects.filter(
                batch_id__in=old_batch_ids_for_trainer,
                is_archived=False
            )


            # Combine: ensure same structure as before
            batch_data = []
            for b in new_batch_qs:
                batch_data.append({
                    "batch_id": b.batch_id,
                    "title": b.title,
                    "start_date": b.start_date,
                    "end_date": b.end_date,
                    "start_time": b.start_time,
                    "end_time": b.end_time,
                    "employee_id": b.trainer.employee_id if b.trainer else None,
                    "trainer_name": b.trainer.full_name if b.trainer else None,
                    "trainer_id": b.trainer.trainer_id if b.trainer else None,
                    "course_id": b.course.course_id if b.course else None,
                    "course_name": b.course.course_name if b.course else None,
                })

            for b in old_batch_qs:

                # get the course used by old batch
                bct_course = BatchCourseTrainer.objects.filter(batch=b).select_related("course").first()
                course_obj = bct_course.course if bct_course else None

                # get trainer (through batchcoursetrainer)
                bct_trainer = BatchCourseTrainer.objects.filter(batch=b).select_related("trainer").first()
                trainer_obj = bct_trainer.trainer if bct_trainer else None

                # time comes only from schedules, not from batch table
                sched = ClassSchedule.objects.filter(batch=b).order_by("start_time").first()

                batch_data.append({
                    "batch_id": b.batch_id,
                    "title": b.title,
                    "start_date": b.scheduled_date,
                    "end_date": b.end_date,

                    # old batch does NOT have time → take from schedule if exists
                    "start_time": sched.start_time if sched else None,
                    "end_time": sched.end_time if sched else None,

                    "employee_id": trainer_obj.employee_id if trainer_obj else None,
                    "trainer_name": trainer_obj.full_name if trainer_obj else None,
                    "trainer_id": trainer_obj.trainer_id if trainer_obj else None,

                    "course_id": course_obj.course_id if course_obj else None,
                    "course_name": course_obj.course_name if course_obj else None,
                })

            # ------------------ COURSES ------------------
            old_course_ids = BatchCourseTrainer.objects.filter(
                trainer__employee_id=employee_id
            ).values_list('course_id', flat=True)

            new_course_ids = NewBatch.objects.filter(
                trainer__employee_id=employee_id,
                is_archived=False
            ).values_list('course_id', flat=True)

            course_ids = list(set(list(old_course_ids) + list(new_course_ids)))

            course_data = Course.objects.filter(
                course_id__in=course_ids,
                is_archived=False,
                status__iexact='Active'
            ).order_by('course_id').values('course_id', 'course_name', "course_category")

            # ------------------ HIERARCHY FILTERED TRAINERS ------------------
            user_type = user.user_type.lower() if getattr(user, "user_type", None) else ""
            user_id = str(getattr(user, "user_id", ""))  # safe fallback
            trainer_id = str(getattr(user, "trainer_id", ""))

            batch_for_hierarchy = NewBatch.objects.filter(is_archived=False, status=True)
            trainer_queryset = Trainer.objects.filter(is_archived=False, status__iexact='Active')

            if user_type == "super_admin":
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )
                trainer_ids = list(
                    Trainer.objects.filter(
                        created_by__in=admin_ids,
                        created_by_type="admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )
                allowed_creators = [user_id] + admin_ids

                batch_for_hierarchy = batch_for_hierarchy.filter(
                    created_by__in=allowed_creators,
                    created_by_type__in=["super_admin", "admin"]
                )
                
                trainer_queryset = trainer_queryset.filter(
                    trainer_id__in=trainer_ids + admin_ids
                )

            elif user_type == "admin" and trainer_id:
                super_admin_id = Trainer.objects.filter(
                    trainer_id=trainer_id
                ).values_list("created_by", flat=True).first()

                trainer_ids = list(
                    Trainer.objects.filter(
                        created_by=trainer_id,
                        created_by_type="admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

                batch_for_hierarchy = batch_for_hierarchy.filter(
                    Q(created_by=trainer_id, created_by_type="admin") |
                    Q(created_by=super_admin_id, created_by_type="super_admin")
                )
                
                trainer_queryset = trainer_queryset.filter(trainer_id__in=trainer_ids)

            trainer_data = list(trainer_queryset.order_by('employee_id').values(
                'employee_id', 'full_name', 'trainer_id'
            ))

            # ------------------ FINAL RESPONSE ------------------
            return Response({
                "success": True,
                "message": f"Class schedules for employee {employee_id}" if employee_id else "Class schedules",
                "Class_Schedule": schedule_data,
                "Batches": list(batch_data),
                "Trainers": trainer_data,
                "Courses": list(course_data),
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "success": False,
                "message": f"{str(e)}"
            }, status=status.HTTP_200_OK)


class RecurringScheduleView(viewsets.ModelViewSet, LoggingMixin):
    queryset = RecurringSchedule.objects.all().order_by('-recurring_id')
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    serializer_class = RecurringScheduleSerializer
    
    def create(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            recurring_schedule = serializer.save()
            return Response({
                "success": True,
                "message": "Recurring schedule created successfully.",
                "data": self.get_serializer(recurring_schedule).data
            }, status=201)

        except ValidationError as ve:
            # Extract first error string from dict
            detail = ve.detail
            message = ""
            if isinstance(detail, dict):
                # Get first key's first error message
                first_key = list(detail.keys())[0]
                first_error = detail[first_key]
                if isinstance(first_error, list):
                    message = first_error[0]
                else:
                    message = str(first_error)
            elif isinstance(detail, list):
                message = detail[0]
            else:
                message = str(detail)

            return Response({
                "success": False,
                "message": message
            }, status=200)

        except Exception as e:
            return Response({
                "success": False,
                "message": f"Something went wrong: {str(e)}"
            }, status=200)

class BatchViewSet(LoggingMixin, viewsets.ModelViewSet, NotesMixin):
    queryset = Batch.objects.all()
    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'batch_id'

    def get_queryset(self):
        user = self.request.user
        qs = Batch.objects.filter(is_archived=False).prefetch_related("schedules__course", "schedules__trainer")

        if user.user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id, 
                    created_by_type="super_admin", 
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )
            courses = Course.objects.filter(is_archived=False)  # remove status__iexact="Active"
            courses = courses.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )
            qs = qs.filter(batchcoursetrainer__course__in=courses).distinct()

        elif user.user_type == "admin" and getattr(user, "trainer_id", None):
            trainer_id = user.trainer_id
            courses = Course.objects.filter(is_archived=False, created_by=trainer_id)  # remove status__iexact="Active"
            qs = qs.filter(batchcoursetrainer__course__in=courses).distinct()

        return qs.order_by('-batch_id')

    def list(self, request, *args, **kwargs):
        user = request.user
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        try:
            user_created_id = getattr(user, "trainer_id", None)  # For admin
            if user.user_type == "super_admin":
                user_created_id = getattr(user, "user_id", None)

            # Get admin IDs for super_admin
            admin_ids = []
            if user.user_type == "super_admin" and user_created_id:
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_created_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

            # --- Students ---
            student_qs = Student.objects.filter(is_archived=False, status=True)
            if user.user_type == "super_admin":
                student_qs = student_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                student_qs = student_qs.filter(created_by=user_created_id)

            student_list = [
                {
                    "registration_id": s.registration_id,
                    "student_id": s.student_id,
                    "full_name": f"{s.first_name} {s.last_name}"
                }
                for s in student_qs
            ]

            # --- Trainers ---
            trainer_qs = Trainer.objects.filter(is_archived=False, status__iexact="Active", user_type='tutor')
            if user.user_type == "super_admin":
                trainer_qs = trainer_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                trainer_qs = trainer_qs.filter(created_by=user_created_id)

            # --- Courses ---
            course_qs = Course.objects.filter(is_archived=False, status__iexact="Active")
            if user.user_type == "super_admin":
                course_qs = course_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                course_qs = course_qs.filter(created_by=user_created_id)

            # --- Categories ---
            category_qs = CourseCategory.objects.filter(is_archived=False, status=True)
            if user.user_type == "super_admin":
                category_qs = category_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                category_qs = category_qs.filter(created_by=user_created_id)

            return Response({
                "success": True,
                "message": "Active Batch list",
                "count": queryset.count(),
                "data": serializer.data,
                "active_category": list(category_qs.values("category_id", "category_name")),
                "active_student": student_list,
                "active_trainer": list(trainer_qs.values("employee_id", "full_name")),
                "active_course": list(course_qs.values("course_id", "course_name", "course_category_id")),
            })

        except Exception as e:
            return Response({
                "success": False,
                "message": f"Something went wrong: {str(e)}"
            }, status=200)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        user = request.user

        # Ensure module_id points to Batch
        batch_module = ModulePermission.objects.filter(module__iexact="Batch").first()
        if not batch_module:
            return Response({"success": False, "message": "Batch module not found"}, status=200)

        if not has_permission(user, module_id=batch_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)
        
        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "success": False,
                "message": error_message
            }, status=status.HTTP_200_OK)
        
        batch = serializer.save()
        return Response({
            "success": True,
            "message": "Batch created successfully.",
            "data": self.get_serializer(batch).data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        user = request.user

        batch_module = ModulePermission.objects.filter(module__iexact="Batch").first()
        if not batch_module:
            return Response({"success": False, "message": "Batch module not found"}, status=200)

        if not has_permission(user, module_id=batch_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)

        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)

        # Save notes if provided in request
        notes_text = request.data.get("notes")
        if notes_text:
            mixin = NotesMixin()
            mixin.save_notes(instance, notes_text, request=request)

        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "success": False,
                "message": error_message
            }, status=status.HTTP_200_OK)
        
        linked_courses = Course.objects.filter(
            batchcoursetrainer__batch=instance,
            is_archived=False
        ).distinct()

        for course in linked_courses:
            if course.status.lower() != "active":
                return Response({
                    "success": False,
                    "message": f"Cannot activate batch because course '{course.course_name}' is inactive."
                }, status=200)

            if course.course_category and not course.course_category.status:
                return Response({
                    "success": False,
                    "message": f"Cannot activate batch because category '{course.course_category.category_name}' is inactive."
                }, status=200)
        
        batch = serializer.save()

        # Save notes again after successful update (optional)
        if notes_text:
            self.save_notes(batch, notes_text, request=request)

        return Response({
            "success": True,
            "message": "Batch updated successfully.",
            "data": self.get_serializer(batch).data
        })

    def is_archived(self, request, *args, **kwargs):
        try:
            batch = self.get_object()
            batch.is_archived = True  # Soft delete by archiving
            batch.save()
            return Response({
                "success": True,
                "message": "Batch deleted successfully."
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                "success": False,
                "message": f"Failed to delete batch: {str(e)}"
            }, status=status.HTTP_200_OK)

class NewBatchViewSet(LoggingMixin, viewsets.ViewSet, NotesMixin):
    lookup_field = 'batch_id'
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    queryset = NewBatch.objects.filter(is_archived=False)
    serializer_class = NewBatchSerializer

    def get_serializer(self, *args, **kwargs):
        kwargs.setdefault("context", {"request": self.request})
        return self.serializer_class(*args, **kwargs)

    # FIXED: Don't return Response here
    def get_object(self):
        pk = self.kwargs.get('pk')
        try:
            return NewBatch.objects.get(batch_id=pk, is_archived=False)
        except NewBatch.DoesNotExist:
            return Response({"success": False, "message": "Batch not found"}, status=status.HTTP_200_OK)
    from django.contrib.contenttypes.models import ContentType
    def list(self, request):
        try:
            user = request.user
            user_type = str(getattr(user, "user_type", "")).lower()
            user_id = str(getattr(user, "user_id", None))
            trainer_id = str(getattr(user, "trainer_id", None))

            # ------------------ Hierarchy Filters ------------------
            batch_filter = Q(is_archived=False)
            course_filter = Q(is_archived=False)
            category_filter = Q(is_archived=False)

            if user_type == "super_admin":
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

                batch_filter &= Q(created_by=user_id, created_by_type="super_admin") | Q(created_by__in=admin_ids, created_by_type="admin")
                course_filter &= Q(created_by=user_id, created_by_type="super_admin") | Q(created_by__in=admin_ids, created_by_type="admin")
                category_filter &= Q(created_by=user_id, created_by_type="super_admin") | Q(created_by__in=admin_ids, created_by_type="admin")

            elif user_type == "admin" and trainer_id:
                super_admin_id = Trainer.objects.filter(trainer_id=trainer_id).values_list("created_by", flat=True).first()
                batch_filter &= Q(created_by=trainer_id, created_by_type="admin") | Q(created_by=super_admin_id, created_by_type="super_admin")
                course_filter &= Q(created_by=trainer_id, created_by_type="admin") | Q(created_by=super_admin_id, created_by_type="super_admin")
                category_filter &= Q(created_by=trainer_id, created_by_type="admin") | Q(created_by=super_admin_id, created_by_type="super_admin")

            elif user_type in ["trainer", "tutor"] and trainer_id:
                assigned_batches = BatchCourseTrainer.objects.filter(trainer__trainer_id=trainer_id).values_list("batch_id", flat=True)
                batch_filter &= Q(batch_id__in=assigned_batches)
                assigned_courses = BatchCourseTrainer.objects.filter(trainer__trainer_id=trainer_id).values_list("course_id", flat=True)
                course_filter &= Q(course_id__in=assigned_courses)

            # ------------------ Fetch Old + New Batches ------------------
            old_batches = Batch.objects.filter(batch_filter).order_by("-created_at")
            new_batches = NewBatch.objects.filter(is_archived=False).order_by("-created_at")

            unified_batches = []

            # -------- OLD BATCHES --------
            for b in old_batches:
                assignments = BatchCourseTrainer.objects.filter(batch=b)

                students_data = []
                trainer_data = None
                course_data = None

                if assignments.exists():
                    first_assignment = assignments.first()
                    course_data = {
                        "course_id": first_assignment.course.course_id if first_assignment.course else None,
                        "course_name": first_assignment.course.course_name if first_assignment.course else None
                    }
                    trainer_data = {
                        "trainer_id": first_assignment.trainer.trainer_id if first_assignment.trainer else None,
                        "trainer_name": first_assignment.trainer.full_name if first_assignment.trainer else None
                    }

                    for a in assignments:
                        if a.student:
                            students_data.append({
                                "student_id": a.student.student_id,
                                "full_name": f"{a.student.first_name} {a.student.last_name}".strip(),
                                "registration_id": a.student.registration_id
                            })

                schedules = ClassSchedule.objects.filter(batch=b).values(
                    "schedule_id",
                    "course_id",
                    "course__course_name",
                    "trainer_id",
                    "trainer__full_name",
                    "scheduled_date",
                    "start_time",
                    "end_time",
                )

                # Get notes for old batch
                note_ct = ContentType.objects.get_for_model(Batch)
                notes_qs = Note.objects.filter(
                    object_id=b.batch_id,
                    content_type=note_ct
                ).order_by("-created_at")

                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": getattr(n.created_by, "username", "") if n.created_by else "",
                        "created_at": n.created_at.strftime("%Y-%m-%d %I:%M:%S %p")
                    } for n in notes_qs
                ]

                unified_batches.append({
                    "id": b.batch_id,
                    "title": b.title,
                    "course": course_data.get("course_id") if course_data else None,
                    "course_name": course_data.get("course_name") if course_data else None,
                    "trainer_id": trainer_data.get("trainer_id") if trainer_data else None,
                    "trainer_name": trainer_data.get("trainer_name") if trainer_data else None,
                    "start_date": getattr(b, "start_date", None),
                    "end_date": getattr(b, "end_date", None),
                    "start_time": getattr(b, "start_time", None),
                    "end_time": getattr(b, "end_time", None),
                    "slots": getattr(b, "slots", None),
                    "created_at": b.created_at,
                    "status": b.status,
                    "created_by": getattr(b, "created_by", None),
                    "created_by_type": getattr(b, "created_by_type", None),
                    "is_archived": b.is_archived,
                    "available_slots": getattr(b, "available_slots", None),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "status": b.status,
                    "schedules": list(schedules),
                    "source": "old"
                })

            # -------- NEW BATCHES --------
            for nb in new_batches:
                students_data = [
                    {
                        "student_id": s.student_id,
                        "full_name": f"{s.first_name} {s.last_name}".strip(),
                        "registration_id": s.registration_id
                    }
                    for s in nb.students.all()
                ]

                # Get notes for old batch
                note_ct = ContentType.objects.get_for_model(Batch)

                notes_qs = Note.objects.filter(
                    object_id=nb.pk,
                    content_type=note_ct
                ).order_by("-created_at")


                def convert_status(value):

                    if isinstance(value, str):
                        if value.lower() == "true":
                            return True
                        if value.lower() == "false":
                            return False
                    return value

                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": n.created_by if n.created_by else "",
                        "created_by_type": n.created_by_type,
                        "status": convert_status(n.status),                         # ← status included
                        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M"),
                    }
                    for n in notes_qs
                ]

                schedules = ClassSchedule.objects.filter(
                    new_batch=nb,
                    is_archived=False
                ).annotate(
                    course_name=F("course__course_name"),
                    trainer_name=F("trainer__full_name")
                ).values(
                    "schedule_id",
                    "course_id",
                    "course__course_name",
                    "trainer_id",
                    "trainer__full_name",
                    "scheduled_date",
                    "start_time",
                    "end_time",
                )

                unified_batches.append({
                    "id": nb.batch_id,
                    "title": nb.title,
                    "course": nb.course.course_id if nb.course else None,
                    "course_name": nb.course.course_name if nb.course else None,
                    "category": nb.course.course_category.category_id if nb.course and nb.course.course_category else None,
                    "trainer_id": nb.trainer.trainer_id if nb.trainer else None,
                    "trainer_name": nb.trainer.full_name if nb.trainer else None,
                    "start_date": nb.start_date,
                    "end_date": nb.end_date,
                    "start_time": nb.start_time,
                    "end_time": nb.end_time,
                    "slots": nb.slots,
                    "created_at": nb.created_at,
                    "created_by": nb.created_by,
                    "created_by_type": nb.created_by_type,
                    "is_archived": nb.is_archived,
                    "status": nb.status,
                    "available_slots": nb.available_slots(),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "schedules": list(schedules),
                    "source": "new"
                })
            
            unified_batches = sorted(unified_batches, key=lambda x: x['created_at'], reverse=True)

            # ------------------ Hierarchy-based Active Data ------------------
            user_created_id = getattr(user, "trainer_id", None)  # For admin
            if user.user_type == "super_admin":
                user_created_id = getattr(user, "user_id", None)
                
            allowed_types = ["super_admin", "admin"]
            if user_type not in allowed_types:
                return Response({
                    "success": False,
                    "message": "You are not authorized to access this API"
                }, status=200)
                
            # --- Students ---
            
            student_qs = Student.objects.filter(is_archived=False, status=True)
            if user.user_type == "super_admin":
                student_qs = student_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                student_qs = student_qs.filter(created_by=user_created_id)

            student_list = [
                {
                    "registration_id": s.registration_id,
                    "student_id": s.student_id,
                    "full_name": f"{s.first_name} {s.last_name}"
                }
                for s in student_qs
            ]

            # --- Trainers ---
            trainer_qs = Trainer.objects.filter(is_archived=False, status__iexact="Active", user_type='tutor')
            if user.user_type == "super_admin":
                trainer_qs = trainer_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                trainer_qs = trainer_qs.filter(created_by=user_created_id)
                
            category_qs = CourseCategory.objects.filter(category_filter).order_by("category_name")
            course_qs = Course.objects.filter(course_filter).order_by("course_name")

            active_category = list(category_qs.values("category_id", "category_name"))
            active_course = list(course_qs.values("course_id", "course_name", "course_category_id"))

            return Response({
                "success": True,
                "message": "Unified batch list retrieved successfully.",
                "batches": unified_batches,
                "active_student": student_list,
                "active_trainer": list(trainer_qs.values("employee_id", "full_name", 'trainer_id')),
                "active_category": active_category,
                "active_course": active_course
            }, status=200)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=200)
            
    def retrieve(self, request, batch_id=None):
        
        batch = NewBatch.objects.filter(batch_id=batch_id, is_archived=False).first()
        batch_type = "new" if batch else "old"

        if not batch:
            batch = Batch.objects.filter(batch_id=batch_id, is_archived=False).first()
            if not batch:
                return Response({"success": False, "message": "Batch not found"}, status=200)
            batch_type = "old"

        serializer = NewBatchSerializer(batch, context={"request": request}) if batch_type == "new" else BatchSerializer(batch, context={"request": request})
        return Response({"success": True, "data": serializer.data}, status=200)
    
    @action(detail=False, methods=['get'], url_path='trainer/(?P<trainer_id>[^/.]+)')
    def trainer_batches(self, request, trainer_id):
        try:
            trainer_id = str(trainer_id)

            unified_batches = []

            # ----------------------------
            # OLD BATCHES
            # ----------------------------
            assigned_old_batch_ids = BatchCourseTrainer.objects.filter(
                trainer__trainer_id=trainer_id
            ).values_list("batch_id", flat=True)

            old_batches = Batch.objects.filter(
                batch_id__in=assigned_old_batch_ids,
                is_archived=False
            ).order_by("-created_at")

            for b in old_batches:
                assignments = BatchCourseTrainer.objects.filter(batch=b)

                # students
                students_data = []
                for a in assignments:
                    if a.student:
                        students_data.append({
                            "student_id": a.student.student_id,
                            "registration_id": a.student.registration_id,
                            "full_name": f"{a.student.first_name} {a.student.last_name}".strip()
                        })

                # trainer + course
                trainer_data = None
                course_data = None
                if assignments.exists():
                    first = assignments.first()
                    trainer_data = {
                        "trainer_id": first.trainer.trainer_id if first.trainer else None,
                        "trainer_name": first.trainer.full_name if first.trainer else None
                    }
                    course_data = {
                        "course_id": first.course.course_id if first.course else None,
                        "course_name": first.course.course_name if first.course else None
                    }

                # schedules
                schedules = ClassSchedule.objects.filter(batch=b).values(
                    "schedule_id",
                    "course_id",
                    "course__course_name",
                    "trainer_id",
                    "trainer__full_name",
                    "scheduled_date",
                    "start_time",
                    "end_time",
                )

                # notes
                note_ct = ContentType.objects.get_for_model(Batch)
                old_notes = Note.objects.filter(
                    object_id=b.batch_id,
                    content_type=note_ct
                ).order_by("-created_at")

                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": getattr(n.created_by, "username", ""),
                        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M")
                    }
                    for n in old_notes
                ]

                unified_batches.append({
                    "id": b.batch_id,
                    "title": b.title,
                    "course": course_data.get("course_id") if course_data else None,
                    "course_name": course_data.get("course_name") if course_data else None,
                    "category": None,
                    "trainer": trainer_data.get("trainer_id") if trainer_data else None,
                    "trainer_name": trainer_data.get("full_name") if trainer_data else None,
                    "start_date": b.scheduled_date,
                    "end_date": b.end_date,
                    "start_time": b.start_time if hasattr(b, "start_time") else None,
                    "end_time": b.end_time if hasattr(b, "end_time") else None,
                    "slots": b.slots if hasattr(b, "slots") else None,
                    "created_at": b.created_at,
                    "created_by": b.created_by,
                    "created_by_type": b.created_by_type,
                    "status": b.status,
                    "is_archived": b.is_archived,
                    "available_slots": getattr(b, "available_slots", None),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "schedules": list(schedules),
                    "source": "old"
                })

            new_batches = NewBatch.objects.filter(
                trainer__trainer_id=trainer_id,
                is_archived=False
            ).order_by("-created_at")

            for nb in new_batches:

                # students
                students_data = [
                    {
                        "student_id": s.student_id,
                        "registration_id": s.registration_id,
                        "full_name": f"{s.first_name} {s.last_name}".strip()
                    }
                    for s in nb.students.all()
                ]

                # schedules
                schedules = ClassSchedule.objects.filter(
                    batch__batch_id=nb.batch_id
                ).annotate(
                    course_name=F("course__course_name"),
                    trainer_name=F("trainer__full_name")
                ).values(
                    "schedule_id",
                    "course_id",
                    "course__course_name",
                    "trainer_id",
                    "trainer__full_name",
                    "scheduled_date",
                    "start_time",
                    "end_time",
                )

                # notes
                note_ct = ContentType.objects.get_for_model(NewBatch)
                new_notes = Note.objects.filter(
                    object_id=nb.pk,
                    content_type=note_ct
                ).order_by("-created_at")

                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": n.created_by,
                        "created_by_type": n.created_by_type,
                        "status": n.status,
                        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M"),
                    }
                    for n in new_notes
                ]

                unified_batches.append({
                    "id": nb.batch_id,
                    "title": nb.title,
                    "course": nb.course.course_id if nb.course else None,
                    "category": nb.course.course_category.category_id if nb.course and nb.course.course_category else None,
                    "course_name": nb.course.course_name if nb.course else None,
                    "trainer": nb.trainer.trainer_id if nb.trainer else None,
                    "trainer_name": nb.trainer.full_name if nb.trainer else None,
                    "start_date": nb.start_date,
                    "end_date": nb.end_date,
                    "start_time": nb.start_time,
                    "end_time": nb.end_time,
                    "slots": nb.slots,
                    "status": nb.status,
                    "created_at": nb.created_at,
                    "created_by": nb.created_by,
                    "created_by_type": nb.created_by_type,
                    "is_archived": nb.is_archived,
                    "available_slots": nb.available_slots(),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "schedules": list(schedules),
                    "source": "new"
                })

            trainer_id = trainer_id
            # Get all courses assigned to this trainer via NewBatch
            assigned_course_ids = NewBatch.objects.filter(
                trainer__trainer_id=trainer_id,
                is_archived=False,
                status=True
            ).values_list("course_id", flat=True).distinct()
            
            course_queryset = Course.objects.filter(
                course_id__in=assigned_course_ids,
                is_archived=False,
                status__iexact='Active'
            )
            
            course_data = course_queryset.annotate(
                category_id=F('course_category__category_id')).values('course_id', 'course_name', 'category_id')
            
            category_ids = course_queryset.values_list('course_category__category_id', flat=True).distinct()
            
            categories = CourseCategory.objects.filter(category_id__in=category_ids).values(
                'category_id', 'category_name'
            )
            
            # From NEW batches (NewBatch -> students M2M)
            new_batches = NewBatch.objects.filter(
                trainer__trainer_id=trainer_id,
                is_archived=False
            ).order_by("-created_at")

            for nb in new_batches:

                # students
                students_data = [
                    {
                        "student_id": s.student_id,
                        "registration_id": s.registration_id,
                        "full_name": f"{s.first_name} {s.last_name}".strip()
                    }
                    for s in nb.students.all()
                ]

            return Response({
                "success": True,
                "message": "Trainer filtered batches retrieved successfully.",
                "batches": unified_batches,
                "active_course": course_data,
                "assigned_students": students_data,
                'active_category': categories
            })

        except Exception as e:
            return Response({"success": False, "message": str(e)})
        
    @action(detail=False, methods=['get'], url_path='student/(?P<student_id>[^/.]+)')
    def student_batches(self, request, student_id):
        try:
            student_id = str(student_id)
            unified_batches = []

            # ---------------- OLD BATCHES ----------------
            assigned_old_batch_ids = BatchCourseTrainer.objects.filter(
                student__student_id=student_id
            ).values_list("batch_id", flat=True)

            old_batches = Batch.objects.filter(
                batch_id__in=assigned_old_batch_ids,
                is_archived=False
            ).order_by("-created_at")

            for b in old_batches:
                assignments = BatchCourseTrainer.objects.filter(batch=b, student__student_id=student_id)

                students_data = [
                    {
                        "student_id": a.student.student_id,
                        "full_name": f"{a.student.first_name} {a.student.last_name}".strip(),
                        "trainer_id": a.trainer.trainer_id if a.trainer else None,
                        "trainer_name": a.trainer.full_name if a.trainer else None,
                        "course_id": a.course.course_id if a.course else None
                    }
                    for a in assignments
                ]

                # Notes
                note_ct = ContentType.objects.get_for_model(Batch)
                notes_qs = Note.objects.filter(object_id=b.batch_id, content_type=note_ct).order_by("-created_at")
                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": getattr(n.created_by, "username", ""),
                        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M")
                    } for n in notes_qs
                ]

                # Schedules
                schedules = ClassSchedule.objects.filter(batch=b).values(
                    "schedule_id",
                    "course_id",
                    "course__course_name",
                    "trainer_id",
                    "trainer__full_name",
                    "scheduled_date",
                    "start_time",
                    "end_time",
                )

                unified_batches.append({
                    "id": b.batch_id,
                    "title": b.title,
                    "course": assignments.first().course.course_id if assignments.exists() else None,
                    "category": assignments.first().course.course_category.category_id if assignments.exists() and assignments.first().course.course_category else None,
                    "course_name": assignments.first().course.course_name if assignments.exists() else None,
                    "trainer": assignments.first().trainer.trainer_id if assignments.exists() else None,
                    "trainer_name": assignments.first().trainer.full_name if assignments.exists() else None,
                    "start_date": getattr(b, "start_date", None),
                    "end_date": getattr(b, "end_date", None),
                    "start_time": getattr(b, "start_time", None),
                    "end_time": getattr(b, "end_time", None),
                    "slots": getattr(b, "slots", None),
                    "created_at": b.created_at,
                    "created_by": b.created_by,
                    "created_by_type": b.created_by_type,
                    "is_archived": b.is_archived,
                    "available_slots": getattr(b, "available_slots", None),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "schedules": list(schedules),
                    "source": "old"
                })

            # ---------------- NEW BATCHES ----------------
            new_batches = NewBatch.objects.filter(
                students__student_id=student_id,
                is_archived=False
            ).order_by("-created_at")

            for nb in new_batches:
                students_data = [
                    {
                        "student_id": s.student_id,
                        "registration_id": s.registration_id,
                        "full_name": f"{s.first_name} {s.last_name}".strip()
                    } for s in nb.students.all()
                ]

                # Notes
                note_ct = ContentType.objects.get_for_model(NewBatch)
                notes_qs = Note.objects.filter(object_id=nb.pk, content_type=note_ct).order_by("-created_at")

                def convert_status(value):
                    if isinstance(value, str):
                        if value.lower() == "true":
                            return True
                        if value.lower() == "false":
                            return False
                    return value

                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": n.created_by,
                        "created_by_type": getattr(n, "created_by_type", None),
                        "status": convert_status(getattr(n, "status", None)),
                        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M"),
                    }
                    for n in notes_qs
                ]

                # Schedules
                schedules = ClassSchedule.objects.filter(batch__batch_id=nb.batch_id).annotate(
                    course_name=F("course__course_name"),
                    trainer_name=F("trainer__full_name")
                ).values(
                    "schedule_id",
                    "course_id",
                    "course__course_name",
                    "trainer_id",
                    "trainer__full_name",
                    "scheduled_date",
                    "start_time",
                    "end_time",
                )

                unified_batches.append({
                    "id": nb.batch_id,
                    "title": nb.title,
                    "course": nb.course.course_id if nb.course else None,
                    "category": nb.course.course_category.category_id if nb.course and nb.course.course_category else None,
                    "course_name": nb.course.course_name if nb.course else None,
                    "trainer": nb.trainer.trainer_id if nb.trainer else None,
                    "trainer_name": nb.trainer.full_name if nb.trainer else None,
                    "start_date": nb.start_date,
                    "end_date": nb.end_date,
                    "start_time": nb.start_time,
                    "end_time": nb.end_time,
                    "slots": nb.slots,
                    "created_at": nb.created_at,
                    "created_by": nb.created_by,
                    "created_by_type": nb.created_by_type,
                    "is_archived": nb.is_archived,
                    "available_slots": nb.available_slots(),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "schedules": list(schedules),
                    "source": "new"
                })
            
            

            new_batches = NewBatch.objects.filter(
                students__student_id=student_id,
                is_archived=False
            ).order_by("-created_at")
            
            trainer_data = [
                {
                    "trainer_id": nb.trainer.trainer_id,
                    "employee_id": nb.trainer.employee_id if nb.trainer.employee_id else None,
                    "trainer_name": nb.trainer.full_name,
                }
                for nb in new_batches
                if nb.trainer
            ]

            student_id = str(student_id)
            # ------------------ ALL ACTIVE COURSES ------------------
            course_queryset = Course.objects.filter(is_archived=False, status__iexact='Active')

            # ------------------ STUDENT ASSIGNED COURSE IDS ------------------
            old_course_ids = BatchCourseTrainer.objects.filter(
                student__student_id=student_id
            ).values_list('course_id', flat=True)

            new_course_ids = NewBatch.objects.filter(
                students__student_id=student_id,
                is_archived=False
            ).values_list('course_id', flat=True)

            assigned_course_ids = set(list(old_course_ids) + list(new_course_ids))

            # ------------------ FILTER COURSES BASED ON STUDENT ------------------
            course_queryset = course_queryset.filter(course_id__in=assigned_course_ids)

            # ------------------ GET COURSE DATA ------------------
            course_data = course_queryset.annotate(
                category_id=F('course_category__category_id')).values('course_id', 'course_name', 'category_id')

            # ------------------ GET UNIQUE CATEGORIES ------------------
            category_ids = course_queryset.values_list('course_category__category_id', flat=True).distinct()
            categories = CourseCategory.objects.filter(category_id__in=category_ids).values(
                'category_id', 'category_name'
            )

            return Response({
                "success": True,
                "message": f"All batches for student {student_id} retrieved successfully.",
                "batches": unified_batches,
                "trainer": trainer_data,
                'active_courses': list(course_data),
                'categories': list(categories),
            })

        except Exception as e:
            return Response({"success": False, "message": str(e)})

    def create(self, request, *args, **kwargs):
        try:
            data = request.data.copy()

            # ----------------- Validate slots -----------------
            slots = int(data.get("slots", 0))
            if slots <= 0:
                return Response(
                    {"success": False, "message": "Slots must be greater than 0"},
                    status=200
                )

            # ----------------- Validate students -----------------
            student_ids = data.get("students", [])

            if student_ids:
                if not isinstance(student_ids, list):
                    return Response(
                        {"success": False, "message": "Students must be a list"},
                        status=200
                    )

                if len(student_ids) > slots:
                    return Response(
                        {
                            "success": False,
                            "message": f"Only {slots} slots available but {len(student_ids)} students given"
                        },
                        status=200
                    )

                valid_students = Student.objects.filter(
                    pk__in=student_ids, is_archived=False
                )

                if valid_students.count() != len(student_ids):
                    return Response(
                        {
                            "success": False,
                            "message": "Some students are invalid or archived"
                        },
                        status=200
                    )

            # ----------------- Validate Course -----------------
            course_id = data.get("course")
            if course_id:
                if not Course.objects.filter(pk=course_id).exists():
                    return Response(
                        {"success": False, "message": "Invalid course"},
                        status=200
                    )

            # ----------------- Validate Trainer -----------------
            trainer_id = data.get("trainer")
            if trainer_id:
                if not Trainer.objects.filter(pk=trainer_id).exists():
                    return Response(
                        {"success": False, "message": "Invalid trainer"},
                        status=200
                    )

            # ----------------- Create Batch -----------------
            serializer = NewBatchSerializer(data=data, context={'request': request})
            serializer.is_valid(raise_exception=True)

            batch = serializer.save()

            return Response(
                {
                    "success": True,
                    "message": "Batch created successfully",
                    "data": NewBatchSerializer(batch, context={"request": request}).data
                },
                status=200
            )

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    def update(self, request, batch_id=None):
        try:
            batch = NewBatch.objects.filter(batch_id=batch_id, is_archived=False).first()
            if not batch:
                return Response({"success": False, "message": "Batch not found"}, status=200)

            data = request.data

            # ---------- Update Course ----------
            course_id = data.get("course")
            if course_id:
                course = Course.objects.filter(pk=course_id).first()
                if not course:
                    return Response({"success": False, "message": "Invalid course"}, status=200)
                batch.course = course

            # ---------- Update Trainer ----------
            trainer_id = data.get("trainer")
            if trainer_id:
                trainer = Trainer.objects.filter(pk=trainer_id).first()
                if not trainer:
                    return Response({"success": False, "message": "Invalid trainer"}, status=200)
                batch.trainer = trainer

            # ---------- Update normal fields ----------
            for key, value in data.items():
                if key in ["course", "trainer", "students"]:
                    continue
                if hasattr(batch, key):
                    setattr(batch, key, value)

            # ---------- Update Students (M2M) ----------
            student_ids = data.get("students")

            # If students key is missing → keep existing students
            if student_ids is None:
                student_ids = list(batch.students.values_list("pk", flat=True))

            # Ensure list type
            if not isinstance(student_ids, list):
                return Response({"success": False, "message": "Students must be a list"}, status=200)

            # Validate slots
            slots = int(data.get("slots", batch.slots))
            if slots <= 0:
                return Response({"success": False, "message": "Slots must be greater than 0"}, status=200)

            if len(student_ids) > slots:
                return Response({
                    "success": False,
                    "message": f"Only {slots} slots available but {len(student_ids)} given"
                }, status=200)

            # Validate students exist
            valid_students = Student.objects.filter(pk__in=student_ids, is_archived=False)
            if len(valid_students) != len(student_ids):
                return Response({
                    "success": False,
                    "message": "Some students are invalid or archived"
                }, status=200)

            # Apply M2M update
            batch.students.set(valid_students)

            batch.save()

            serializer = NewBatchSerializer(batch, context={"request": request})

            return Response({
                "success": True,
                "message": "Batch updated successfully",
                "data": serializer.data
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    def is_archived(self, request, batch_id=None, *args, **kwargs):
        try:
            pk = int(batch_id)
            batch = NewBatch.objects.filter(batch_id=pk, is_archived=False).first()
            batch_type = "new" if batch else "old"

            if not batch:
                from .models import Batch  # old batch model
                batch = Batch.objects.filter(batch_id=pk, is_archived=False).first()
                if not batch:
                    return Response({
                        "success": False,
                        "message": "Batch not found"
                    }, status=status.HTTP_200_OK)
                batch_type = "old"

            batch.is_archived = True
            batch.save()

            return Response({
                "success": True,
                "message": f"{'New' if batch_type=='new' else 'Old'} batch archived successfully",
            }, status=status.HTTP_200_OK)

        except ValueError:
            return Response({
                "success": False,
                "message": "Invalid batch ID"
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

class AssignmentViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = Assignment.objects.all()
    serializer_class = AssignmentSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        course_id = self.request.query_params.get('course_id')
        queryset = Assignment.objects.filter(is_archived=False)
        if course_id:
            queryset = queryset.filter(course__course_id=course_id)
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset().filter(is_archived=False).order_by("id")
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "success": True,
            "message": "Excerise retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    
    def list_by_course(self, request, course_id=None):
        try:
            course = Course.objects.get(course_id=course_id)
        except Course.DoesNotExist:
            return Response({
                "success": False,
                "message": "Course not found"
            }, status=status.HTTP_200_OK)

        assignments = Assignment.objects.filter(course=course, is_archived=False).order_by("id")

        # Pass request in context so the serializer can decode JWT
        serializer = self.get_serializer(assignments, many=True, context={'request': request})

        return Response({
            "success": True,
            "message": "Exercises retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        try:
            course_id = request.data.get('course')
            
            user = request.user
            
            # Ensure module_id points to Assignment
            assignment_module = ModulePermission.objects.filter(module__iexact="Exercise").first()
            if not assignment_module:
                return Response({"success": False, "message": "Assignment module not found"}, status=200)

            if not has_permission(user, module_id=assignment_module.module_id, actions=["create"]):
                return Response({"success": False, "message": "You do not have permission"}, status=200)
            
            try:
                course = Course.objects.get(course_id=course_id, is_archived=False)
            except Course.DoesNotExist:
                return Response({
                    "success": False,
                    "message": "Course not found or deleted."
                }, status=status.HTTP_200_OK)

            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(course=course)
            return Response({
                "success": True,
                "message": "Excerise created successfully",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
        except ValidationError as ve:
            error = ve.detail
            if isinstance(error, dict):
                field = next(iter(error.keys()))
                error_message = next(iter(error.values()))[0].replace('this',field)
                
            return Response({
                "success": False,
                "message": error_message
            }, status=status.HTTP_200_OK)
            
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        user = request.user
        
        # Ensure module_id points to Assignment
        assignment_module = ModulePermission.objects.filter(module__iexact="Exercise").first()
        if not assignment_module:
            return Response({"success": False, "message": "Assignment module not found"}, status=200)

        if not has_permission(user, module_id=assignment_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            first_error = next(iter(serializer.errors.values()))[0]
            return Response({
                "success": False,
                "message": first_error
            }, status=status.HTTP_200_OK)

        assignment = serializer.save()
        return Response({
            "success": True,
            "message": "Excerise updated successfully.",
            "data": self.get_serializer(assignment).data
        }, status=status.HTTP_200_OK)
     
    @action(detail=True, methods=['patch'], url_path='archive')   
    def is_archived(self, request, *args, **kwargs):
        assignment = self.get_object()
        assignment.is_archived = True
        assignment.save()
        return Response({
            "success": True,
            "message": "Excerise deleted successfully.",
            "data": AssignmentSerializer(assignment, context={'request': request}).data
        }, status=status.HTTP_200_OK)

class SubmissionViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = Submission.objects.all()
    serializer_class = SubmissionSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def get_queryset(self):
        user = self.request.user

        if not getattr(user, "is_authenticated", False):
            return Submission.objects.filter(is_archived=False).order_by('-id')

        # Try to resolve the real user_id from JWT
        user_id = getattr(user, "id", None) or getattr(user, "user_id", None)
        username = getattr(user, "username", None)

        # --- Student ---
        if user_id:
            try:
                student = Student.objects.get(user_id=user_id)
                return Submission.objects.filter(student=student, is_archived=False)
            except Student.DoesNotExist:
                pass

        # --- Trainer ---
        if username:
            try:
                trainer = Trainer.objects.get(username=username)

                assigned_old = Student.objects.filter(
                    batchcoursetrainer__trainer=trainer
                )

                assigned_new = Student.objects.filter(
                    new_batches__trainer=trainer,
                    new_batches__status=True,
                    new_batches__is_archived=False
                )

                assigned_students = (assigned_old | assigned_new).distinct()

                return Submission.objects.filter(student__in=assigned_students, is_archived=False)

            except Trainer.DoesNotExist:
                pass

        # --- Default fallback ---
        return Submission.objects.filter(is_archived=False).order_by('-date')


    def create(self, request, *args, **kwargs):
        registration_id = request.data.get("registration_id")
        assignment_id = request.data.get("assignment")

        # Validate student
        try:
            student = Student.objects.get(registration_id=registration_id, is_archived=False)
        except Student.DoesNotExist:
            return Response({"success": False, "message": "Invalid registration ID"}, status=status.HTTP_200_OK)

        # Validate assignment
        try:
            assignment = Assignment.objects.get(id=assignment_id)
        except Assignment.DoesNotExist:
            return Response({"success": False, "message": "Invalid assignment ID"}, status=status.HTTP_200_OK)

        # Serialize and save submission
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(student=student, assignment=assignment)
            # Async virus scan triggered via signal
            return Response({
                "success": True,
                "message": "Submission created successfully. File will be scanned for viruses.",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
            
        # Convert serializer.errors to a single message string
        error_messages = []
        for field_errors in serializer.errors.values():
            if isinstance(field_errors, list):
                error_messages.extend(field_errors)
            elif isinstance(field_errors, dict):
                # nested serializer errors
                for sub_errors in field_errors.values():
                    error_messages.extend(sub_errors)

        return Response({
            "success": False,
            "message": error_messages[0] if error_messages else "Validation error"
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='<registration_id>')
    def by_student(self, request, registration_id=None):
        try:
            student = Student.objects.get(registration_id=registration_id, is_archived=False)
        except Student.DoesNotExist:
            return Response({
                "success": False,
                "message": "Student not found"
            }, status=status.HTTP_200_OK)

        submissions = Submission.objects.filter(student=student).order_by('-date')
        serializer = self.get_serializer(submissions, many=True)
        return Response({
            "success": True,
            "message": "Submissions retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['patch'], url_path='archive')
    def is_archived(self, request, *args, **kwargs):
        try:
            submission = self.get_object()
            submission.is_archived = True
            submission.save()
            return Response({
                "success": True,
                "message": f"Submission {submission.id} deleted successfully."
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=status.HTTP_200_OK)

class SubmissionReplyViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = SubmissionReplySerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        submission_id = self.kwargs.get('submission_id')
        return SubmissionReply.objects.filter(submission_id=submission_id)

    def create(self, request, *args, **kwargs):
        submission_id = self.kwargs.get('submission_id')
        employee_id = request.data.get("employee_id")

        if not submission_id:
            return Response({
                "success": False,
                "message": "submission_id is required in URL."
            }, status=status.HTTP_200_OK)

        if not employee_id:
            return Response({
                "success": False,
                "message": "employee_id is required in data."
            }, status=status.HTTP_200_OK)

        try:
            submission = Submission.objects.get(id=submission_id)
        except Submission.DoesNotExist:
            return Response({
                "success": False,
                "message": "Invalid submission ID."
            }, status=status.HTTP_200_OK)

        try:
            trainer = Trainer.objects.get(employee_id=employee_id)
        except Trainer.DoesNotExist:
            return Response({
                "success": False,
                "message": "Invalid trainer ID."
            }, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(submission=submission, trainer=trainer)
            return Response({
                "success": True,
                "message": "Reply created successfully.",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
        else:
            return Response({
                "success": False,
                "message": serializer.errors
            }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='archive')
    def is_archived(self, request, *args, **kwargs):
        reply = self.get_object()
        reply.is_archived = True
        reply.save()
        return Response({
            "success": True,
            "message": f"Reply {reply.id} deleted successfully."
        }, status=status.HTTP_200_OK)
        
class TestViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = TestSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    queryset = Test.objects.all()
    
    def get_queryset(self):
        user = self.request.user
        user_type = getattr(user, "user_type", "").lower()
        admin_trainer_id = getattr(user, "trainer_id", None)
        user_created_id = getattr(user, "user_id", None) if user_type == "super_admin" else admin_trainer_id

        # Super admin: get all admin IDs created by this super admin
        admin_ids = []
        if user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

        # Base queryset
        qs = Test.objects.filter(is_archived=False)

        # Apply filtering
        if user_type == "admin" and admin_trainer_id:
            qs = qs.filter(created_by=admin_trainer_id)
        elif user_type == "super_admin":
            qs = qs.filter(
                Q(created_by=user_created_id, created_by_type="super_admin") |
                Q(created_by__in=admin_ids, created_by_type="admin")
            )

        return qs.order_by('-test_id')

    def list(self, request, *args, **kwargs):
        try:
            # Annotate each test with the count of non-archived questions
            queryset = self.get_queryset().annotate(
                question_count=Count('test_questions', filter=Q(test_questions__is_archived=False))
            )

            serializer = self.get_serializer(queryset, many=True)

            user = self.request.user
            user_type = getattr(user, "user_type", "").lower()
            admin_trainer_id = getattr(user, "trainer_id", None)
            user_created_id = getattr(user, "user_id", None) if user_type == "super_admin" else admin_trainer_id

            # ---------------- Courses Filtering ----------------
            all_courses = Course.objects.filter(is_archived=False, status__iexact='Active')

            if user_type == "admin" and admin_trainer_id:
                all_courses = all_courses.filter(created_by=admin_trainer_id)
            elif user_type == "super_admin" and user_created_id:
                # Get all admin IDs created by this super admin
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_created_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )
                all_courses = all_courses.filter(
                    Q(created_by=user_created_id, created_by_type="super_admin") |
                    Q(created_by__in=admin_ids, created_by_type="admin")
                )
            elif user_type == "trainer":
                    # Trainer belongs to an admin
                trainer_id = getattr(user, "trainer_id", None)
                if trainer_id:
                    # Find the admin who created this trainer
                    trainer_obj = Trainer.objects.filter(trainer_id=trainer_id).first()
                    if trainer_obj and trainer_obj.created_by_type == "admin":
                        admin_id = trainer_obj.created_by
                        courses = courses.filter(created_by=admin_id, created_by_type="admin")
                    elif trainer_obj and trainer_obj.created_by_type == "super_admin":
                        super_admin_id = trainer_obj.created_by
                        courses = courses.filter(created_by=super_admin_id, created_by_type="super_admin")

            elif user_type == "student":
                student_id = getattr(user, "student_id", None)
                if student_id:
                    # Get the admin/super_admin who created their batch/trainer
                    batch_trainer_qs = NewBatch.objects.filter(students=student_id)
                    # get all unique admins
                    admin_ids = set()
                    for bt in batch_trainer_qs:
                        if bt.trainer.created_by_type == "admin":
                            admin_ids.add(bt.trainer.created_by)
                        elif bt.trainer.created_by_type == "super_admin":
                            admin_ids.add(bt.trainer.created_by)

                    courses = courses.filter(Q(created_by__in=admin_ids))


            all_courses = all_courses.values('course_id', 'course_name')

            if queryset.exists():
                # Add question_count to each serialized test
                data_with_question_count = []
                for item, test in zip(serializer.data, queryset):
                    item['question_count'] = test.question_count
                    data_with_question_count.append(item)

                return Response({
                    "success": True,
                    'message': "Data retrieved successfully.",
                    "data": data_with_question_count,
                    "courses": list(all_courses)
                }, status=200)

            return Response({
                "success": False,
                "message": "No data found.",
                "courses": list(all_courses)
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        user = request.user
        
        # Ensure module_id points to Test
        test_module = ModulePermission.objects.filter(module__iexact="Assessment").first()
        if not test_module:
            return Response({"success": False, "message": "Test module not found in permissions"}, status=200)

        if not has_permission(user, module_id=test_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)

        if not serializer.is_valid():
            # Extract the first error message
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."

            return Response({
                "message": error_message,
                "success": False
            }, status=status.HTTP_200_OK)

        test = serializer.save()
        return Response({
            "success": True,
            "message": "Test created successfully.",
            "data": self.get_serializer(test).data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        
        user = request.user
        
        # Ensure module_id points to Test
        test_module = ModulePermission.objects.filter(module__iexact="Assessment").first()
        if not test_module:
            return Response({"success": False, "message": "Test module not found"}, status=200)

        if not has_permission(user, module_id=test_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)
        
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            # Extract the first error message
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."

            return Response({
                "message": error_message,
                "success": False
            }, status=status.HTTP_200_OK)

        test = serializer.save()
        return Response({
            "success": True,
            "message": "Test updated successfully.",
            "data": self.get_serializer(test).data
        })

    @action(detail=True, methods=['patch'], url_path='questions')
    def test_questions(self, request, *args, **kwargs):
        try:
            test = self.get_object()  # get the Test instance
        except Test.DoesNotExist:
            return Response({"success": False, "message": "Test not found"}, status=200)

        # Use the correct related_name
        questions = test.test_questions.all().filter(is_archived=False)

        serializer = TestQuestionsSerializer(questions, many=True)
        return Response({"success": True, "questions": serializer.data}, status=200)

    @action(detail=False, methods=['get'], url_path=r'(?P<test_id>\d+)/student/(?P<student_id>[^/.]+)/result')
    def student_test_result(self, request, test_id=None, student_id=None):
        try:
            student = Student.objects.filter(student_id=student_id).first()
            if not student:
                return Response({"success": False, "message": "Student not found"}, status=200)

            test = Test.objects.filter(test_id=test_id, is_archived=False).first()
            if not test:
                return Response({"success": False, "message": "Test not found"}, status=200)

            # Fetch answers for this student & test
            answers = StudentAnswers.objects.filter(student_id=student, test_id=test)

            # Fetch finalized score
            test_result = TestResult.objects.filter(student_id=student, test_id=test).first()

            # Build response
            questions_data = []
            for ans in answers.select_related("question_id"):
                question = ans.question_id
                question_type = question.type  # or 'type' depending on your field

                # Determine correct answer and student answer based on type
                if question_type == "mcq":
                    correct_answer = question.mcq_correct_option
                    student_answer = ans.selected_option
                    options = question.options
                    written_answer = None
                elif question_type == "written":
                    correct_answer = question.written_answer
                    student_answer = ans.written_answer
                    options = None
                    written_answer = question.written_answer

                questions_data.append({
                    "question_id": question.question_id,
                    "question": question.question,
                    "type": question_type,
                    "options": options,
                    "correct_answer": correct_answer,
                    "student_answer": student_answer,
                    "is_correct": ans.is_correct,
                    "marks": question.marks,
                })

            return Response({
                "success": True,
                "student_id": student.student_id,
                "registration_id": student.registration_id,
                "test_id": test.test_id,
                "test_name": test.test_name,
                "total_marks": test.total_marks,
                "score": test_result.score if test_result else None,
                "questions": questions_data
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    @action(detail=False, methods=['get'], url_path=r'course/(?P<course_id>[^/.]+)')
    def tests_by_course(self, request, course_id=None):
        try:
            # -------------------------
            # Validate Course
            # -------------------------
            course = Course.objects.filter(course_id=course_id, is_archived=False).first()
            if not course:
                return Response({"success": False, "message": "Course not found"}, status=200)

            user_type = getattr(request.user, "user_type", None)
            employee_id = getattr(request.user, "employee_id", None)
            employer_id = getattr(request.user, "employer_id", None)
            trainer_id = getattr(request.user, "trainer_id", None)
            student_id = getattr(request.user, "student_id", None)

            # -------------------------
            # Base Tests
            # -------------------------
            tests = Test.objects.filter(
                course_id=course,
                is_archived=False
            ).prefetch_related(
                Prefetch(
                    'test_questions',
                    queryset=TestQuestions.objects.filter(is_archived=False),
                    to_attr='active_questions'
                )
            )

            data = []  # final list

            # ============================================================
            # CASE 1 : STUDENT
            # ============================================================
            if user_type == "student":
                student = Student.objects.filter(student_id=student_id).first()
                if not student:
                    return Response({"success": False, "message": "Student not found"}, status=200)

                for test in tests:
                    answers_qs = StudentAnswers.objects.filter(
                        student_id=student.student_id,
                        test_id=test.test_id
                    )

                    attempted = answers_qs.exists()
                    correction_done = TestResult.objects.filter(
                        student_id=student,
                        test_id=test.test_id
                    ).exists() if attempted else False

                    # Get question snapshot
                    if attempted:
                        questions_data = [
                            {
                                "question_id": ans.question_id.question_id if ans.question_id else None,
                                "question": ans.question_text,
                                "type": ans.question_id.type if ans.question_id else None,
                                "options": ans.options_snapshot,
                                "correct_answer": ans.correct_answer_snapshot
                            }
                            for ans in answers_qs.select_related("question_id")
                        ]
                    else:
                        questions_data = TestQuestionsSerializer(test.active_questions, many=True).data

                    data.append({
                        "test_id": test.test_id,
                        "test_name": test.test_name,
                        "description": test.description,
                        "course_name": test.course_id.course_name,
                        "course_id": test.course_id.course_id,
                        "duration": test.duration,
                        "total_marks": test.total_marks,
                        "question_count": len(test.active_questions),
                        "questions": questions_data,
                        "test_completion": attempted,
                        "correction_done": correction_done
                    })

            # ============================================================
            # CASE 2 : TUTOR
            # ============================================================

            elif user_type == "tutor":

                # Fetch students ONLY from NewBatch
                assigned_students = Student.objects.filter(
                    new_batches__trainer__employee_id=employee_id,
                    new_batches__course_id=course_id,
                    new_batches__status=True,
                    new_batches__is_archived=False,
                    is_archived=False
                ).distinct()

                for test in tests:
                    students_data = []

                    for student in assigned_students:
                        answers_qs = StudentAnswers.objects.filter(student_id=student, test_id=test.test_id)
                        if not answers_qs.exists():
                            continue

                        correction_done = TestResult.objects.filter(
                            student_id=student,
                            test_id=test.test_id
                        ).exists()

                        students_data.append({
                            "registration_id": student.registration_id,
                            "student_id": student.student_id,
                            "student_name": f"{student.first_name} {student.last_name}",
                            "attempted": True,
                            "answers": StudentAnswersSerializer(answers_qs, many=True).data,
                            "correction_done": correction_done
                        })

                    if students_data:
                        data.append({
                            "test_id": test.test_id,
                            "test_name": test.test_name,
                            "description": test.description,
                            "course_name": test.course_id.course_name,
                            "course_id": test.course_id.course_id,
                            "duration": test.duration,
                            "total_marks": test.total_marks,
                            "question_count": len(test.active_questions),
                            "students": students_data
                        })


            # ============================================================
            # CASE 3 : EMPLOYER
            # ============================================================
            elif user_type == "employer":

                students = Student.objects.filter(
                    new_batches__course_id=course_id,
                    new_batches__status=True,
                    new_batches__is_archived=False,
                    employer_id=employer_id,
                    is_archived=False
                ).distinct()

                for test in tests:
                    students_data = []

                    for student in students:
                        answers_qs = StudentAnswers.objects.filter(student_id=student, test_id=test.test_id)
                        if not answers_qs.exists():
                            continue

                        answers_data = []
                        questions_data = []

                        for ans in answers_qs.select_related("question_id"):
                            answers_data.append({
                                "answer_id": ans.answer_id,
                                "question_id": ans.question_id.question_id if ans.question_id else None,
                                "answer_text": ans.written_answer or ans.selected_option,
                                "submitted_at": ans.submitted_at.strftime('%Y-%m-%d %H:%M:%S')
                            })
                            questions_data.append({
                                "question_id": ans.question_id.question_id if ans.question_id else None,
                                "question": ans.question_text,
                                "type": ans.question_id.type if ans.question_id else None,
                                "options": ans.options_snapshot,
                                "correct_answer": ans.correct_answer_snapshot
                            })

                        correction_done = TestResult.objects.filter(
                            student_id=student,
                            test_id=test.test_id
                        ).exists()

                        students_data.append({
                            "registration_id": student.registration_id,
                            "student_id": student.student_id,
                            "student_name": f"{student.first_name} {student.last_name}",
                            "attempted": True,
                            "answers": answers_data,
                            "questions": questions_data,
                            "correction_done": correction_done
                        })

                    if students_data:
                        data.append({
                            "test_id": test.test_id,
                            "test_name": test.test_name,
                            "description": test.description,
                            "course_name": test.course_id.course_name,
                            "course_id": test.course_id.course_id,
                            "duration": test.duration,
                            "total_marks": test.total_marks,
                            "question_count": len(test.active_questions),
                            "students": students_data
                        })


            # ============================================================
            # CASE 4 : ADMIN + SUPER ADMIN
            # ============================================================
            elif user_type in ["admin", "super_admin"]:
                
                if user_type == "super_admin":
                    admin_tests = tests

                    admin_students = Student.objects.filter(
                        new_batches__course_id=course_id,
                        new_batches__status=True,
                        new_batches__is_archived=False,
                        is_archived=False
                    ).distinct()

                else:
                    admin_tests = tests.filter(created_by=trainer_id)

                    admin_students = Student.objects.filter(
                        new_batches__trainer__trainer_id=trainer_id,
                        new_batches__course_id=course_id,
                        new_batches__status=True,
                        new_batches__is_archived=False,
                        is_archived=False
                    ).distinct()

                for test in admin_tests:
                    students_data = []

                    for student in admin_students:
                        answers_qs = StudentAnswers.objects.filter(student_id=student, test_id=test.test_id)
                        if not answers_qs.exists():
                            continue

                        answers_data = []
                        questions_data = []

                        for ans in answers_qs.select_related("question_id"):
                            answers_data.append({
                                "answer_id": ans.answer_id,
                                "question_id": ans.question_id.question_id if ans.question_id else None,
                                "answer_text": ans.written_answer or ans.selected_option,
                                "submitted_at": ans.submitted_at.strftime('%Y-%m-%d %H:%M:%S')
                            })
                            questions_data.append({
                                "question_id": ans.question_id.question_id if ans.question_id else None,
                                "question": ans.question_text,
                                "type": ans.question_id.type if ans.question_id else None,
                                "options": ans.options_snapshot,
                                "correct_answer": ans.correct_answer_snapshot
                            })

                        correction_done = TestResult.objects.filter(
                            student_id=student,
                            test_id=test.test_id
                        ).exists()

                        students_data.append({
                            "registration_id": student.registration_id,
                            "student_id": student.student_id,
                            "student_name": f"{student.first_name} {student.last_name}",
                            "attempted": True,
                            "answers": answers_data,
                            "questions": questions_data,
                            "correction_done": correction_done
                        })

                    if students_data:
                        data.append({
                            "test_id": test.test_id,
                            "test_name": test.test_name,
                            "description": test.description,
                            "course_name": test.course_id.course_name,
                            "course_id": test.course_id.course_id,
                            "duration": test.duration,
                            "total_marks": test.total_marks,
                            "question_count": len(test.active_questions),
                            "students": students_data
                        })

            else:
                return Response({"success": False, "message": "Role not supported"}, status=200)

            return Response({"success": True, "tests": data}, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)
        
    @action(detail=False, methods=['get'], url_path='<int:course_id>/<str:student_id>')
    def test_by_students(self, request, course_id=None, student_id=None):
        try:
            # 1. Validate course
            try:
                course = Course.objects.get(course_id=course_id, is_archived=False)
            except Course.DoesNotExist:
                return Response({"success": False, "message": "Course not found"}, status=200)

            # 2. Validate student
            try:
                student = Student.objects.get(student_id=student_id, is_archived=False)
            except Student.DoesNotExist:
                return Response({"success": False, "message": "Student not found"}, status=200)

            # 3. Fetch tests only for this course
            tests = Test.objects.filter(course_id=course, is_archived=False).prefetch_related(
                Prefetch(
                    "test_questions",
                    queryset=TestQuestions.objects.filter(is_archived=False),
                    to_attr="active_questions"
                )
            ).order_by("-test_id")

            data = []
            for test in tests:
                # answers for this student & test
                answers_qs = StudentAnswers.objects.filter(
                    student_id=student.student_id,
                    test_id=test.test_id
                )

                attempted = answers_qs.exists()

                correction_done = False
                                
                # Determine questions to show based on whether the student already attempted
                if attempted:
                    # Use snapshot from StudentAnswers
                    questions_data = []
                    for ans in answers_qs.select_related('question_id'):
                        questions_data.append({
                            "question_id": ans.question_id.question_id if ans.question_id else None,
                            "question": ans.question_text,
                            "type": ans.question_id.type if ans.question_id else None,
                            "options": ans.options_snapshot,
                            "correct_answer": ans.correct_answer_snapshot
                        })
                else:
                    # Student not attempted yet, show current questions
                    questions_data = TestQuestionsSerializer(test.active_questions, many=True).data
                    
                result = TestResult.objects.filter(student_id=student, test_id=test).first()
                correction_done = bool(result)
                trainer_name = None
                trainer_employee_id = None
                if result and result.evaluated_by:
                    trainer_name = result.evaluated_by.full_name
                    trainer_employee_id = result.evaluated_by.employee_id
                evaluated_at = result.evaluated_at if result else None

                # Keep all other fields as-is
                data.append({
                    "test_id": test.test_id,
                    "test_name": test.test_name,
                    "course_name": test.course_id.course_name,
                    'course_id': test.course_id.course_id,
                    "description": test.description,
                    "duration": test.duration,
                    "total_marks": test.total_marks,
                    "submitted_at": answers_qs.first().submitted_at.strftime('%Y-%m-%d %H:%M:%S') if attempted else None,
                    "evaluated_by": {
                        "employee_id": trainer_employee_id,
                        "full_name": trainer_name
                    },
                    "evaluated_at": evaluated_at.strftime('%Y-%m-%d %H:%M:%S') if evaluated_at else evaluated_at,
                    "question_count": len(test.active_questions),
                    "questions": questions_data,
                    "answers": StudentAnswersSerializer(answers_qs, many=True).data if attempted else [],
                    "test_completion": attempted,
                    "correction_done": correction_done
                })

            return Response({
                "success": True,
                "message": "Tests retrieved successfully",
                "registration_id": student.registration_id,
                "student_name": f"{student.first_name} {student.last_name}".strip(),
                "tests": data
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    @action(
        detail=False,
        methods=['get'],
        url_path=r'<test_id>/student/<student_id>/answers'
    )
    def student_test_answers(self, request, test_id=None, student_id=None):
        """
        Get all questions of a test with student's submitted answers (snapshot).
        """
        # Get student
        student = Student.objects.filter(student_id=student_id).first()
        if not student:
            return Response({"success": False, "message": "Student not found"}, status=200)

        # Get test
        test = Test.objects.filter(pk=test_id, is_archived=False).first()
        if not test:
            return Response({"success": False, "message": "Test not found"}, status=200)

        # Get student's answers for this test
        answers = StudentAnswers.objects.filter(test_id=test, student_id=student).select_related('question_id')
        answers_map = {a.question_id_id: a for a in answers}

        # Build response using snapshot
        data = []
        for ans in answers:
            q_snapshot = {
                "question_id": ans.question_id.question_id if ans.question_id else None,
                "question": ans.question_text,               # snapshot of question text
                "type": ans.question_id.type if ans.question_id else None,
                "options": ans.options_snapshot,             # snapshot of options
                "marks": ans.marks_snapshot,
                "mcq_correct_answer": ans.correct_answer_snapshot,  # snapshot of correct answer
            }

            submitted_answer = {
                "answer_id": ans.answer_id,
                "selected_option": ans.selected_option,
                "written_answer": ans.written_answer,
                "is_correct": ans.is_correct,
            }

            data.append({
                "question": q_snapshot,
                "submitted_answer": submitted_answer
            })

        return Response({
            "success": True,
            "message": "Questions and answers retrieved successfully",
            "student": {
                "registration_id": student.registration_id,
                "student_id": student.student_id,
                "name": f"{student.first_name} {student.last_name}"
            },
            "test": {
                "test_id": test.test_id,
                "test_name": test.test_name,
            },
            "data": data
        }, status=200)

    def is_archived(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_archived = True
        instance.save()
        if instance.is_archived:
            return Response({ 'success': True ,'message': 'Test deleted successfully.'}, status=status.HTTP_200_OK)
        return Response({ 'success': False ,'message': 'Failed to delete test.'}, status=status.HTTP_200_OK)

class TestQuestionViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = TestQuestionsSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    queryset = TestQuestions.objects.all()

    def get_queryset(self):
        return super().get_queryset().filter(is_archived=False).order_by('question_id')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        if queryset.exists():
            return Response({"success": True, "message": "Data retrieved successfully.", "data": serializer.data}, status=200)
        return Response({"success": False, "message": "No data found."}, status=200)

    def create(self, request, *args, **kwargs):
        """
        Accepts either a single question or a list of questions.
        Each question can be MCQ or Written.
        """
        data = request.data
        is_list = isinstance(data, list)
        if not is_list:
            data = [data]

        created_questions = []

        for q_data in data:
            serializer = self.get_serializer(data=q_data)
            if serializer.is_valid():
                question = serializer.save()
                created_questions.append(serializer.data)
            else:
                # Use global flatten_errors function
                error_messages = flatten_errors(serializer.errors)
                error_message = ". ".join(error_messages) + "."

                return Response({
                    "success": False,
                    "message": error_message
                }, status=status.HTTP_200_OK)

        return Response({
            "success": True,
            "message": "Questions created successfully.",
            "data": created_questions
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "success": False,
                "message": error_message
            }, status=status.HTTP_200_OK)
        
        serializer.save()
        return Response({
            "success": True,
            "message": "Question updated successfully.",
            "data": self.get_serializer(instance).data
        }, status=status.HTTP_200_OK)

    def is_archived(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_archived = True
        instance.save()
        return Response({'success': True, 'message': 'Question archived successfully.'}, status=200)
    
class StudentAnswerViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = StudentAnswersSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    queryset = StudentAnswers.objects.all()

    def get_queryset(self):
        return super().get_queryset().order_by('answer_id')

    def create(self, request, *args, **kwargs):
        try:
            student_stu_id = getattr(request.user, "student_id", None)
            if not student_stu_id:
                return Response({"success": False, "message": "student_id missing in token"}, status=200)

            student = Student.objects.filter(student_id=student_stu_id).first()
            if not student:
                return Response({"success": False, "message": f"Student {student_stu_id} not found"}, status=200)

            data = request.data
            is_list = isinstance(data, list)
            if not is_list:
                data = [data]

            created_answers = []
            for ans_data in data:
                ans_data = ans_data.copy()
                ans_data['student_id'] = student.student_id
                ans_data['is_correct'] = False  # always false initially

                serializer = self.get_serializer(data=ans_data)
                try:
                    serializer.is_valid(raise_exception=True)
                except serializers.ValidationError as ve:
                    # Grab the first error message (clean version)
                    error_msg = " ".join([str(err) for errs in ve.detail.values() for err in errs])
                    return Response({"success": False, "message": error_msg}, status=400)

                answer = serializer.save()
                created_answers.append(self.get_serializer(answer).data)

            return Response({
                "success": True,
                "message": f"{len(created_answers)} Answer(s) submitted successfully.",
                "data": created_answers
            }, status=201)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)
        
class TestResultViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = TestResultSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = TestResult.objects.all()

    def get_queryset(self):
        return super().get_queryset().order_by('-result_id')

    def list(self, request, registration_id=None, *args, **kwargs):
        queryset = self.get_queryset().filter(student_id__registration_id=registration_id)
        serializer = self.get_serializer(queryset, many=True)
        if queryset.exists():
            return Response({"success": True, "message": "Data retrieved successfully.", "data": serializer.data}, status=200)
        return Response({"success": False, "message": f"No results found for student {registration_id}"}, status=200)

    @action(detail=False, methods=['post'], url_path='finalize/(?P<test_id>[^/.]+)/mark_and_finalize')
    def mark_and_finalize(self, request, test_id=None):
        try:
            data = request.data
            student_id = data.get("student_id")
            answers = data.get("answers", [])
            score = data.get("score")

            # 1. Update StudentAnswers correctness
            for ans in answers:
                answer_id = ans.get("answer_id")
                is_correct = ans.get("is_correct", False)
                StudentAnswers.objects.filter(
                    answer_id=answer_id,
                    test_id=test_id,
                    student_id__student_id=student_id
                ).update(is_correct=is_correct)

            # 2. Create/Update TestResult
            trainer = Trainer.objects.get(employee_id=request.user.employee_id)

            test_result, _ = TestResult.objects.update_or_create(
                student_id=Student.objects.get(student_id=student_id),
                test_id=Test.objects.get(test_id=test_id),
                defaults={
                    "score": score,
                    "evaluated_by": trainer,
                    "evaluated_at": timezone.now()
                }
            )

            return Response({
                "success": True,
                "message": "Result finalized successfully",
                "test_result_id": test_result.result_id,
                "score": test_result.score
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=status.HTTP_200_OK)

class NotificationListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        token = self._get_token_from_header(request)
        if not token:
            return Response({"success": False, "message": "Authorization token missing."}, status=200)

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return Response({"success": False, "message": "Token expired."}, status=200)
        except jwt.InvalidTokenError:
            return Response({"success": False, "message": "Invalid token."}, status=200)

        user_type = payload.get("user_type")
        if not user_type:
            return Response({"success": False, "message": "User type missing in token."}, status=200)

        try:
            if user_type == "student":
                return self._get_student_notifications(payload)

            elif user_type == "tutor":
                return self._get_trainer_notifications(payload)

            elif user_type == "employer":
                return self._get_sub_admin_notifications(payload)
            elif user_type == "admin":
                return self._get_admin_notifications(payload)

            elif user_type == "super_admin":
                return self._get_super_admin_notifications(payload)


            else:
                return Response({"success": False, "message": "Unknown user type."}, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    def _get_token_from_header(self, request):
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header.split(" ")[1]
        return None

    # -------------------------------------------------------------
    # STUDENT NOTIFICATIONS + UNREAD MESSAGE COUNT
    # -------------------------------------------------------------
    def _get_student_notifications(self, payload):
        registration_id = payload.get("registration_id")
        if not registration_id:
            return Response({"success": False, "message": "Student ID missing."}, status=200)

        notifications = Notification.objects.filter(
            student__registration_id=registration_id,
            is_read=False
        ).filter(
            Q(message__icontains='reviewed your submission') |
            Q(message__icontains='Your new class') |
            Q(message__startswith='test_result:') |
            Q(message__icontains='ticket:reply:by Admin') 
        ).order_by("-created_at")

        # NEW → unread message count
        unread_message_count = self._get_unread_message_count_student(registration_id)

        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "success": True,
            "notifications": serializer.data,
            "count": notifications.count(),
            "unread_messages": unread_message_count
        }, status=200)

    # -------------------------------------------------------------
    # TRAINER NOTIFICATIONS + UNREAD MESSAGE COUNT
    # -------------------------------------------------------------
    def _get_trainer_notifications(self, payload):
        employee_id = payload.get("employee_id")
        if not employee_id:
            return Response({"success": False, "message": "Trainer ID missing."}, status=200)

        notifications = Notification.objects.filter(
            trainer__employee_id=employee_id,
            is_read=False
        ).filter(
            Q(message__startswith='submission:') |
            Q(message__icontains='submitted assignment') |
            Q(message__startswith='topic:') |
            Q(message__icontains='updated their topic') |
            Q(message__startswith='class:') |
            Q(message__icontains='class is scheduled') |
            Q(message__startswith='test_submission:')
        ).order_by("-created_at")

        # NEW → unread message count
        unread_message_count = self._get_unread_message_count_trainer(employee_id)

        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "success": True,
            "notifications": serializer.data,
            "count": notifications.count(),
            "unread_messages": unread_message_count
        }, status=200)

    # -------------------------------------------------------------
    # SUB ADMIN NOTIFICATIONS (NO MESSAGE COUNT)
    # -------------------------------------------------------------
    def _get_sub_admin_notifications(self, payload):
        employer_id = payload.get("employer_id")
        if not employer_id:
            return Response({"success": False, "message": "Employer ID missing."}, status=200)

        notifications = Notification.objects.filter(
            sub_admin__employer_id=employer_id,
            is_read=False
        ).filter(
            Q(message__startswith='submission:') |
            Q(message__startswith='submission_reply:') |
            Q(message__startswith='topic:') |
            Q(message__icontains='updated their topic') |
            Q(message__startswith='class:')
        ).order_by("-created_at")

        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "success": True,
            "notifications": serializer.data,
            "count": notifications.count(),
            "unread_messages": 0
        }, status=200)
    
    def _get_admin_notifications(self, payload):
        """
        Admin (Trainer with user_type='admin') notification list.
        We will use the trainer__employee_id field from JWT.
        """
        employee_id = payload.get("employee_id")
        if not employee_id:
            return Response({"success": False, "message": "Admin employee_id missing."}, status=200)

        notifications = Notification.objects.filter(
            trainer__employee_id=employee_id,
            is_read=False
        ).filter(
            # Ticket-specific notifications for admin
            Q(message__startswith='ticket:new:') |
            Q(message__startswith='ticket:reply:')
        ).order_by("-created_at")

        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "success": True,
            "notifications": serializer.data,
            "count": notifications.count(),
            "unread_messages": 0  # If you later want admin chat unread, you can add similar to trainer
        }, status=200)
    
    def _get_super_admin_notifications(self, payload):
        """
        Super admin (User with user_type='super_admin') notification list.
        """
        super_admin_id = payload.get("user_id")
        if not super_admin_id:
            return Response({"success": False, "message": "Super admin ID missing."}, status=200)

        notifications = Notification.objects.filter(
            super_admin_id=super_admin_id,
            is_read=False
        ).filter(
            # Ticket-specific notifications for super admin
            Q(message__startswith='ticket:new:') |
            Q(message__startswith='ticket:reply:')
        ).order_by("-created_at")

        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "success": True,
            "notifications": serializer.data,
            "count": notifications.count(),
            "unread_messages": 0
        }, status=200)

    def _get_unread_message_count_student(self, registration_id):
        return Message.objects.filter(
            room__student__registration_id=registration_id,
            is_read=False
        ).count()

    def _get_unread_message_count_trainer(self, employee_id):
        return Message.objects.filter(
            room__trainer__employee_id=employee_id,
            is_read=False
        ).count()

class AdminChatLogViewSet(viewsets.ViewSet):
    
    @action(detail=False, methods=["get"], url_path="chat-logs")
    def admin_chat_logs(self, request):
        try:
            user_type = getattr(request.user, "user_type", None)

            # Allow admin + super_admin only
            if user_type not in ["admin", "super_admin"]:
                return Response({
                    "success": False,
                    "message": "Only admins & super admins can view chat logs"
                }, status=200)

            # Fetch all chat rooms
            chat_rooms = ChatRoom.objects.all().select_related("student", "trainer")

            final_data = []

            for room in chat_rooms:
                messages = room.messages.filter(is_deleted=False).order_by("created_at")
                messages_data = MessageSerializer(messages, many=True).data

                # Latest message
                last_msg = room.messages.filter(is_deleted=False).order_by("-created_at").first()
                last_message_data = MessageSerializer(last_msg).data if last_msg else None

                final_data.append({
                    "room_id": room.id,
                    "student": {
                        "id": room.student.registration_id,
                        "student_name": f"{room.student.first_name} {room.student.last_name}",
                        "profile_pic": (
                            request.build_absolute_uri(room.student.profile_pic.url)
                            if room.student.profile_pic else None
                        )
                    },
                    "trainer": {
                        "id": room.trainer.employee_id,
                        "trainer_name": (
                            room.trainer.full_name
                            if hasattr(room.trainer, "full_name")
                            else f"{room.trainer.first_name} {room.trainer.last_name}"
                        ),
                        "profile_pic": (
                            request.build_absolute_uri(room.trainer.profile_pic.url)
                            if room.trainer.profile_pic else None
                        )
                    },
                    "created_at": room.created_at,
                    "last_message": last_message_data,
                    "messages": messages_data
                })

            return Response({
                "success": True,
                "total_rooms": len(final_data),
                "chat_logs": final_data
            }, status=200)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=200)

@api_view(["POST"])
def mark_notification_read(request):
    notif_id = request.data.get("id")
    try:
        notif = Notification.objects.get(id=notif_id)
        notif.is_read = True
        notif.save()
        return Response({"success": True, "message": "Notification marked as read"})
    except Notification.DoesNotExist:
        return Response({"success": False, "message": "Notification not found"}, status=status.HTTP_200_OK)
    
class ChatRoomViewSet(viewsets.ModelViewSet):
    queryset = ChatRoom.objects.all()
    serializer_class = ChatRoomSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def list(self, request, *args, **kwargs):
        try:
            user_type = getattr(request.user, "user_type", None)

            # --- CASE 1: Student ---
            if user_type == "student":
                registration_id = getattr(request.user, "registration_id", None)
                student = Student.objects.filter(registration_id=registration_id).first()

                if not student:
                    return Response({"success": False, "message": "Student not found"}, status=200)

                chat_rooms = (
                    ChatRoom.objects.filter(student=student)
                    .annotate(last_msg_time=Max("messages__created_at"))
                    .order_by("-last_msg_time", "-created_at")
                )

                chat_data = self.get_serializer(chat_rooms, many=True).data

                # Inject last_message + unread_count
                enriched_chat_data = []
                for chatroom, serialized in zip(chat_rooms, chat_data):
                    last_message = chatroom.messages.filter(is_deleted=False).order_by("-created_at").first()
                    serialized["last_message"] = {
                        "id": last_message.id,
                        "content": last_message.content,
                        "sender_type": last_message.sender_type,
                        "sender_id": last_message.sender_id,
                        "created_at": last_message.created_at,
                    } if last_message else None

                    serialized["unread_count"] = chatroom.messages.filter(
                        is_read=False,
                        is_deleted=False,
                        sender_type="trainer"
                    ).count()

                    enriched_chat_data.append(serialized)

                assigned_trainers = (
                    NewBatch.objects.filter(students=student)
                    .select_related("trainer", "course")
                )

                trainer_map = {}
                for bct in assigned_trainers:
                    trainer = bct.trainer
                    if trainer.employee_id not in trainer_map:
                        trainer_map[trainer.employee_id] = {
                            "trainer": TrainerSimpleSerializer(trainer).data,

                        }

                return Response({
                    "success": True,
                    "message": "Chat rooms and assigned trainers fetched successfully",
                    "chat_rooms": chat_data,
                    "assigned_trainers": list(trainer_map.values()),
                    "last_message": enriched_chat_data
                }, status=200)

            # --- CASE 2: Trainer ---
            elif user_type == "tutor":
                employee_id = getattr(request.user, "employee_id", None)
                trainer = Trainer.objects.filter(employee_id=employee_id).first()

                if not trainer:
                    return Response({"success": False, "message": "Trainer not found"}, status=200)
                
                chat_rooms = (
                    ChatRoom.objects.filter(trainer=trainer)
                    .annotate(last_msg_time=Max("messages__created_at"))
                    .order_by("-last_msg_time", "-created_at")
                )

                chat_data = self.get_serializer(chat_rooms, many=True).data

                # 🔹 Inject last_message + unread_count
                enriched_chat_data = []
                for chatroom, serialized in zip(chat_rooms, chat_data):
                    last_message = chatroom.messages.filter(is_deleted=False).order_by("-created_at").first()
                    serialized["last_message"] = {
                        "id": last_message.id,
                        "content": last_message.content,
                        "sender_type": last_message.sender_type,
                        "sender_id": last_message.sender_id,
                        "created_at": last_message.created_at,
                    } if last_message else None

                    serialized["unread_count"] = chatroom.messages.filter(
                        is_read=False,
                        is_deleted=False,
                        sender_type="student"
                    ).count()

                    enriched_chat_data.append(serialized)

                assigned_batches = (
                    NewBatch.objects.filter(trainer=trainer)
                    .select_related("trainer", "course")
                )

                student_map = {}

                for batch in assigned_batches:
                    for student in batch.students.all():
                        if student.registration_id not in student_map:
                            serialized_student = SubmissionStudentSerializer(student).data
                            student_map[student.registration_id] = {
                                "student_id": student.registration_id,
                                "student_name": f"{student.first_name} {student.last_name}",
                                "profile_pic": serialized_student["profile_pic"],
                            }
 
                return Response({
                    "success": True,
                    "message": "Assigned students fetched successfully",
                    "chat_rooms": chat_data,
                    "assigned_students": list(student_map.values()),
                    "last_message": enriched_chat_data
                }, status=200)

            # --- CASE 3: Others ---
            return Response({"success": False, "message": "Only students and trainers can access this"}, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    def create(self, request, *args, **kwargs):
        try:
            student_id = request.data.get("student_id")
            trainer_id = request.data.get("trainer_id")

            if not student_id or not trainer_id:
                return Response(
                    {"success": False, "message": "student_id and trainer_id are required"},
                    status=status.HTTP_200_OK
                )

            student = Student.objects.filter(registration_id=student_id).first()
            trainer = Trainer.objects.filter(employee_id=trainer_id).first()

            if not student:
                return Response(
                    {"success": False, "message": "Student not found"},
                    status=status.HTTP_200_OK
                )

            if not trainer:
                return Response(
                    {"success": False, "message": "Trainer not found"},
                    status=status.HTTP_200_OK
                )

            room, created = ChatRoom.objects.get_or_create(student=student, trainer=trainer)
            serializer = self.get_serializer(room)

            return Response(
                {"success": True, "message": "Chat room created", "data": serializer.data},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_200_OK
            )

    @action(detail=False, methods=["get"], url_path=r'(?P<student_id>[^/.]+)/eduthuko')
    def student_chat_logs(self, request, student_id=None):
        try:
            user_type = getattr(request.user, "user_type", None)
            if user_type != "admin":
                return Response(
                    {"success": False, "message": "Only admins can view chat logs"},
                    status=status.HTTP_200_OK
                )

            # Get student
            student = Student.objects.filter(student_id=student_id).first()
            if not student:
                return Response(
                    {"success": False, "message": "Student not found"},
                    status=status.HTTP_200_OK
                )

            # Fetch all chatrooms for this student
            chat_rooms = ChatRoom.objects.filter(student=student).select_related("trainer")
            data = []

            for room in chat_rooms:
                trainer_data = TrainerSimpleSerializer(room.trainer).data if room.trainer else None
                messages = Message.objects.filter(room=room, is_deleted=False).order_by("created_at")
                messages_data = MessageSerializer(messages, many=True).data

                data.append({
                    "room_id": room.id,
                    "trainer": trainer_data,
                    "messages": messages_data
                })

            return Response({
                "success": True,
                "student": SubmissionStudentSerializer(student).data,
                "chat_rooms": data
            }, status=200)

        except Exception as e:
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_200_OK
            )

class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.all().order_by("created_at")
    serializer_class = MessageSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def list(self, request, room_id=None):
        try:
            messages = Message.objects.filter(room_id=room_id).order_by("created_at")
            serializer = self.get_serializer(messages, many=True)
            return Response({"success": True, "message": "Messages fetched successfully", "data": serializer.data}, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)
        
    def create(self, request, room_id=None):
        try:
            # Pass request.data and request.FILES
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(room_id=room_id)

            return Response({
                "success": True,
                "message": "Message sent successfully",
                "data": serializer.data
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    def unread_messages(self, request, room_id=None):
        messages = Message.objects.filter(room_id=room_id, is_read=False, is_deleted=False)
        return Response({"unread_count": messages.count()})

    def mark_as_read(self, request, room_id=None):
        reader_type = request.data.get("reader_type")
        reader_id = request.data.get("reader_id")

        if not reader_type or not reader_id:
            return Response({"success": False, "message": "reader_type and reader_id required"}, status=200)

        # Mark only messages in this room that are not read
        Message.objects.filter(room_id=room_id, is_read=False).update(is_read=True)

        return Response({"success": True, "message": f"All messages in room {room_id} marked as read"}, status=200)

    @action(detail=True, methods=["put"], url_path="edit")
    def edit_message(self, request, pk=None):
        """ Allow only sender to edit their own message """
        message = self.get_object()
        sender_type = request.data.get("sender_type")
        sender_id = request.data.get("sender_id")

        if message.sender_type != sender_type or message.sender_id != sender_id:
            return Response({ "success": False, "message": "You can only edit your own message"}, status=status.HTTP_200_OK)

        message.content = request.data.get("content", message.content)
        message.save()
        return Response(MessageSerializer(message).data)

    @action(detail=True, methods=["delete"], url_path="delete")
    def delete_message(self, request, pk=None):
        """ Soft delete: mark message as deleted """
        message = self.get_object()
        sender_type = request.data.get("sender_type")
        sender_id = request.data.get("sender_id")

        if message.sender_type != sender_type or message.sender_id != sender_id:
            return Response({ "success": False, "message": "You can only delete your own message"}, status=status.HTTP_200_OK)

        message.is_deleted = True
        message.content = "This message was deleted"
        message.save()
        return Response({ "success": True, "status": "message deleted"}, status=status.HTTP_200_OK)

class UserPresenceViewSet(viewsets.ModelViewSet):
    queryset = UserPresence.objects.all()
    serializer_class = UserPresenceSerializer

    @action(detail=False, methods=["post"])
    def update_status(self, request):
        user_type = request.data.get("user_type")
        user_id = request.data.get("user_id")
        is_online = request.data.get("is_online", False)

        presence, _ = UserPresence.objects.update_or_create(
            user_type=user_type, user_id=user_id,
            defaults={"is_online": is_online}
        )
        return Response(UserPresenceSerializer(presence).data)

class AdminfullLogViewSet(ReadOnlyModelViewSet):
    authentication_classes = [CustomJWTAuthentication]  # <- This is required
    queryset = UserActivityLog.objects.all().order_by('-timestamp')
    serializer_class = UserActivityLogSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['user_type', 'user_id', 'username', 'action']
    ordering_fields = ['timestamp']

    def list(self, request, *args, **kwargs):
        user = getattr(request, 'user_data', None)
        if not user or user.get('user_type') != 'admin':
            return Response({'error': 'Unauthorized'}, status=status.HTTP_200_OK)
        return super().list(request, *args, **kwargs)

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
class LeadViewSet(viewsets.ModelViewSet, NotesMixin):
    queryset = Lead.objects.filter(is_archived=False).order_by('-created_at')
    serializer_class = LeadSerializer
    permission_classes = [IsAuthenticated]

    # ---------------- CREATE ----------------
    def create(self, request, *args, **kwargs):
        phone = request.data.get("phone")

        # Check for duplicate lead
        if Lead.objects.filter(phone=phone, is_archived=False).exists():
            return Response(
                {"message": "Lead already exists"},
                status=status.HTTP_200_OK
            )

        # Proceed with normal creation
        response = super().create(request, *args, **kwargs)
        return Response(
            {
                "success": True,
                "message": "Lead created successfully",
                "data": response.data
            },
            status=status.HTTP_201_CREATED
        )

    # ---------------- LIST ----------------
    def list(self, request, *args, **kwargs):
        queryset = self.queryset
        serializer = self.get_serializer(queryset, many=True)
        return Response({"success": True, "leads": serializer.data}, status=status.HTTP_200_OK)

    # ---------------- RETRIEVE ----------------
    def retrieve(self, request, *args, **kwargs):
        lead_id = self.kwargs.get('pk')
        lead = Lead.objects.filter(pk=lead_id, is_archived=False).first()
        if not lead:
            return Response({"success": False, "message": "Lead not found"}, status=status.HTTP_200_OK)
        serializer = self.get_serializer(lead)
        return Response({"success": True, "lead": serializer.data}, status=status.HTTP_200_OK)

    # ---------------- UPDATE (Full + Partial + Notes) ----------------
    def update(self, request, *args, **kwargs):
        lead_id = self.kwargs.get('pk')
        partial = kwargs.pop('partial', False)
        lead = Lead.objects.filter(pk=lead_id, is_archived=False).first()

        if not lead:
            return Response(
                {"success": False, "message": "Lead not found"},
                status=status.HTTP_200_OK
            )

        serializer = self.get_serializer(lead, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        notes_text = request.data.get("notes")
        if notes_text:
            self.save_notes(lead, notes_text, request=request)

        notes_data = self.get_notes_reasons(lead, request=request)

        return Response(
            {
                "success": True,
                "message": "Lead updated successfully",
                "lead": serializer.data,
                "notes": notes_data
            },
            status=status.HTTP_200_OK
        )

    # ---------------- SOFT DELETE ----------------
    def is_archived(self, request, *args, **kwargs):
        lead_id = self.kwargs.get('pk')
        lead = Lead.objects.filter(pk=lead_id, is_archived=False).first()
        if not lead:
            return Response({"success": False, "message": "Lead not found"}, status=status.HTTP_200_OK)
        lead.is_archived = True
        lead.save()
        return Response({"success": True, "message": "Lead archived successfully"}, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'], url_path='call/(?P<call_id>[^/.]+)/notes')
    def add_call_notes(self, request, pk=None, call_id=None):

        lead = Lead.objects.filter(pk=pk, is_archived=False).first()
        if not lead:
            return Response(
                {"success": False, "message": "Lead not found"},
                status=status.HTTP_200_OK
            )

        call_log = LeadCallLog.objects.filter(id=call_id, lead=lead).first()
        if not call_log:
            return Response(
                {"success": False, "message": "Call log not found"},
                status=status.HTTP_200_OK
            )

        notes_text = request.data.get("notes")
        if not notes_text:
            return Response(
                {"success": False, "message": "Note text required"},
                status=status.HTTP_200_OK
            )

        # Use NotesMixin to save notes
        self.save_notes(instance=call_log, notes_text=notes_text, request=request)

        return Response({
            "success": True,
            "message": "Note added successfully",
            "data": {
                "call_log_id": call_log.id,
                "lead_id": lead.id,
                "note": notes_text,
                "added_by": request.user.username,
                "created_at": timezone.now()
            }
        }, status=status.HTTP_201_CREATED)

    # ---------------- TWILIO CALL ----------------
    
    @action(detail=True, methods=['post'], url_path='call')
    def call(self, request, pk=None):

        lead = Lead.objects.filter(pk=pk, is_archived=False).first()
        if not lead:
            return Response({"success": False, "message": "Lead not found"}, status=200)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.filter(id=request.user.user_id).first()

        # The sales user’s phone number (must include country code)
        # sales_person_phone = "+918838264338"  # TODO: Replace with logged-in user's number or profile field
        sales_person_phone = "+919677377316"

        lead_number = lead.phone
        if not lead_number.startswith('+'):
            lead_number = f"+91{lead_number}"  # Verified lead number

        client = Client(settings.TWILIO_SID, settings.TWILIO_AUTH_TOKEN)

        try:
            # First call: sales person
            call = client.calls.create(
                to=sales_person_phone,
                from_=settings.TWILIO_PHONE_NUMBER,  # Verified Twilio number
                url=f"https://portal.aryuacademy.com/api/twilio/connect_customer?lead_phone={lead_number}"
            )

            # Log the call
            log = LeadCallLog.objects.create(
                lead=lead,
                called_by=user,
                call_status="initiated"
            )

            serializer = LeadCallLogSerializer(log)
            return Response({
                "success": True,
                "message": "Call initiated",
                "call_sid": call.sid,
                "log": serializer.data
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    # ---------------- CALL LOGS ----------------
    @action(detail=True, methods=['get'], url_path='call-logs')
    def call_logs(self, request, pk=None):
        lead = Lead.objects.filter(pk=pk, is_archived=False).first()
        if not lead:
            return Response({"success": False, "message": "Lead not found"}, status=status.HTTP_200_OK)
        logs = lead.call_logs.all().order_by('-call_time')
        serializer = LeadCallLogSerializer(logs, many=True)
        return Response({"success": True, "call_logs": serializer.data})

@api_view(['GET'])
@permission_classes([AllowAny])
def connect_customer(request):

    print("Twilio hit /connect_customer endpoint")  # Debug
    lead_phone = request.GET.get('lead_phone')
    print(f"Lead phone: {lead_phone}")

    if not lead_phone:
        print("Missing lead_phone parameter")
        return Response({'success': False, "message": "Missing lead_phone parameter"}, status=200)

    try:
        response = VoiceResponse()
        dial = Dial(callerId=settings.TWILIO_PHONE_NUMBER)
        dial.number(lead_phone)
        response.append(dial)

        print("TwiML response generated successfully")
        return Response({'success': True, 'message': str(response)}, content_type='text/xml', status=200)

    except Exception as e:
        print(f"Error in connect_customer: {e}")
        return Response({'success': False, "message": str(e)}, status=200)



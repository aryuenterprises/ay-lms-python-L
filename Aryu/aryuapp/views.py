import requests
from rest_framework.views import APIView
from .models import *
from .serializer import *
from rest_framework.viewsets import ReadOnlyModelViewSet, ViewSet
from rest_framework.exceptions import ValidationError, NotFound, AuthenticationFailed,PermissionDenied
from .auth import CustomJWTAuthentication
from rest_framework.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from announcements.models import Announcement
from announcements.serializers import AnnouncementSerializer
from chats.models import ChatRoom, Message
from django.views.decorators.csrf import csrf_exempt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated , AllowAny, BasePermission
from tests.models import Test, TestResult, StudentAnswers
from django.utils.dateparse import parse_datetime
from django.core.validators import EmailValidator
from collections import defaultdict
from datetime import datetime, time, timedelta, date
from rest_framework.decorators import action, api_view, permission_classes
from twilio.twiml.voice_response import VoiceResponse, Dial
from django.db.models.functions import TruncDate, Cast, TruncMonth, TruncDay
from django.db import IntegrityError, transaction
import time
from datetime import datetime, timedelta, time
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
import jwt
from django.db import IntegrityError
from django.utils.timezone import localtime
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.hashers import *
from django.db.models import Q, Count, F, Max, ExpressionWrapper, Prefetch, DateField, Case, When,  IntegerField, Sum, Avg, Value, CharField,Subquery, Window
import holidays
from core.permissions import IsSelfOrAdmin, IsAdminOrTrainer
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from django.db.models.functions import Concat,Lag, JSONObject, Coalesce
from django.contrib.postgres.aggregates import JSONBAgg
from .utils import *
from .mixins import *
from webinar.models import Webinar, WebinarRegistration, WebinarAttendanceSummary, WebinarFeedback
from .services.dashboard.student_dashboard_service import StudentDashboardService
from courses.models import Course, CourseCategory
from batches.models import NewBatch, ClassSchedule, Batch, BatchCourseTrainer
from payments.models import PaymentTransaction
from ebook.models import EbookRegistration
from django.core.cache import cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.hashers import make_password
import traceback
from batches.models import BatchRecording
from batches.serializers import BatchRecordingSerializer
class IsAdminOrSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, "user_type", "") in ["admin", "super_admin"]
    
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
    permission_classes = [IsAuthenticated, IsAdminOrSuperAdmin]
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
        user = request.user

        allowed_types = ["super_admin", "admin"]

        if user.user_type not in allowed_types:
            return Response({
                "success": False,
                "message": "You are not authorized to access this resource."
            }, status=403)
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

class CustomRefreshToken(RefreshToken):

    @classmethod
    def for_user(cls, user, role_permissions=None, system_settings=None):
        token = super().for_user(user)

        role = getattr(user, "role", None)

        token["user_id"] = user.id
        token["username"] = user.username
        token["name"] = user.full_name
        token["user_type"] = user.user_type
        token["attendance_type"] = (
            system_settings.attendance_options
            if system_settings else None
        )

        token["role_id"] = role.role_id if role else None
        token["role_name"] = role.name if role else None
        token["permissions"] = role_permissions or []

        token["created_at"] = (
            user.created_at.isoformat()
            if getattr(user, "created_at", None)
            else None
        )

        return token
    
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
                    role_modules = RoleModulePermission.objects.filter(
                        role=role
                    ).exclude(allowed_actions=[]).select_related("module_permission")

                    for rm in role_modules:
                        role_permissions.append({
                            "module_id": rm.module_permission.module_id,
                            "module_name": rm.module_permission.module,
                            "allowed_actions": rm.allowed_actions
                        })

                refresh = CustomRefreshToken.for_user(
                    user,
                    role_permissions=role_permissions,
                    system_settings=system_settings
                )

                access_token = str(refresh.access_token)
                refresh_token = str(refresh)

                response = Response(
                    {
                        "success": True,
                        "message": "Login successful",
                        "token": access_token,
                        "refresh_token":refresh_token,
                        "user": {
                            "user_id": user.id,
                            "username": user.username,
                            "created_at": user.created_at,
                            "name": user.full_name,
                            "user_type": user.user_type,
                            "attendance_type": system_settings.attendance_options if system_settings else None,
                            "role_id": role.role_id if role else None,
                            "role_name": role.name if role else None,
                            "permissions": role_permissions,
                        }
                    },
                    status=status.HTTP_200_OK
                )

                origin = request.headers.get("Origin", "")

                LOCAL_ORIGINS = {
                    "http://localhost:3000",
                    "http://localhost:8000",
                    "http://127.0.0.1:8000",
                }

                if origin in LOCAL_ORIGINS:
                    cookie_domain = None
                    cookie_secure = False
                    cookie_samesite = "Lax"
                else:
                    cookie_domain = ".aryuprojects.com"
                    cookie_secure = True
                    cookie_samesite = "Lax"

                
                response.set_cookie(
                    key="refresh_token",
                    value=refresh_token,
                    httponly=True,
                    secure=cookie_secure,
                    samesite=cookie_samesite,
                    domain=cookie_domain,
                    path="/",
                    max_age=30 * 24 * 60 * 60,
                )

                return response
            
            # For Student
            student = Student.objects.filter(
                Q(username=username_or_email) | Q(email__iexact=username_or_email),
                is_archived=False
            ).first()

            if student:
                if student.status == False:
                    return Response({'success': False, 'message': 'Your account is inactive. Please contact admin.'}, status=200)

            if student and check_password(password, student.password):
                role = getattr(student, "role", None)
                role_permissions = []

                if role:
                    role_modules = (
                        RoleModulePermission.objects
                        .filter(role=role)
                        .exclude(allowed_actions=[])
                        .select_related("module_permission")
                    )

                    for rm in role_modules:
                        role_permissions.append({
                            "module_id": rm.module_permission.module_id,
                            "module_name": rm.module_permission.module,
                            "allowed_actions": rm.allowed_actions
                        })

                payload = {
                    'registration_id': student.registration_id,
                    'student_id': student.student_id,
                    'username': student.username,
                    "name": student.first_name,
                    'user_type': 'student',
                    "attendance_type": system_settings .attendance_options if system_settings  else None,
                    'student_type': student.student_type,
                    "role_id": role.role_id if role else None,
                    "role_name": role.name if role else None,
                    "permissions": role_permissions,
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
                        "role_id": role.role_id if role else None,
                        "role_name": role.name if role else None,
                        "permissions": role_permissions,
                    },
                    "exp": int((timezone.now() + timedelta(minutes=30)).timestamp()),
                }, status=200)

            # For EbookRegistration login
            ebook_user = EbookRegistration.objects.filter(
                email__iexact=username_or_email
            ).first()

            if ebook_user:

                if not ebook_user.is_paid:
                    return Response({
                        "success": False,
                        "message": "Please complete payment to login"
                    }, status=200)

                if check_password(password, ebook_user.password) or password == ebook_user.password:

                    # 🔥 convert old password to hashed
                    if password == ebook_user.password:
                        
                        ebook_user.password = make_password(password)
                        ebook_user.save()

                    payload = {
                        "registration_id": ebook_user.id,
                        "name": ebook_user.name,
                        "email": ebook_user.email,
                        "user_type": "ebookuser",
                        "role_id": 50,
                        "role_name": "ebook user",
                        "exp": int((timezone.now() + timedelta(minutes=30)).timestamp()),
                        "phone":ebook_user.phone,
                    }

                    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

                    return Response({
                        "success": True,
                        "message": "Login successful",
                        "token": token,
                        "user": {
                            "registration_id": ebook_user.id,
                            "name": ebook_user.name,
                            "email": ebook_user.email,
                            "user_type": "ebookuser",
                            "role_id": 50,
                            "role_name": "ebook user",
                            "phone":ebook_user.phone
                        },
                        "exp": payload["exp"]
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
                        role_modules = RoleModulePermission.objects.filter(
                            role=role
                        ).exclude(allowed_actions=[]).select_related("module_permission")

                        for rm in role_modules:
                            if rm.allowed_actions:
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


class CustomTokenRefreshView(APIView):
    permission_classes = [AllowAny]
    serializer_class = CustomTokenRefreshSerializer

    def post(self, request):
        refresh_token = request.COOKIES.get("refresh_token")

        serializer = self.serializer_class(
            data={"refresh": refresh_token}
        )

        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data

        response = Response(
            {
                "access_token": validated_data["access_token"]
            },
            status=200
        )

        # Save NEW rotated refresh token - USE SAME SETTINGS AS LOGIN
        if validated_data.get("refresh_token_obj"):
            # Determine cookie settings based on origin (same as login)
            origin = request.headers.get("Origin", "")
            
            LOCAL_ORIGINS = {
                "http://localhost:3000",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
            }

            if origin in LOCAL_ORIGINS:
                cookie_domain = None
                cookie_secure = False
                cookie_samesite = "Lax"
            else:
                cookie_domain = ".aryuprojects.com"
                cookie_secure = True
                cookie_samesite = "Lax"  # ✅ Changed from "None" to "Lax"

            response.set_cookie(
                key="refresh_token",
                value=validated_data["refresh_token_obj"],
                httponly=True,
                secure=cookie_secure,
                samesite=cookie_samesite,  # ✅ Match login
                domain=cookie_domain,       # ✅ Match login
                max_age=30 * 24 * 60 * 60,
                path="/",                   # ✅ Changed from "api/refresh/token/" to "/"
                expires=None
            )
        return response
    
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
    

    def status_update(self,request,pk=None):
        try:
            role = Role.objects.get(role_id=pk)
            role.status=not role.status
            role.save()
            return Response({"success": True, "message": "Role deleted successfully"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)



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
                    'is_archived': role.is_archived,
                    'status':role.status
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
            elif user_type == "ebookuser":
                return self._get_ebook_dashboard(payload,request)
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
            return Response({"success": False, "message": "Student ID missing"}, status=200)

        dashboard_service = StudentDashboardService(student_id)

        data = dashboard_service.get_dashboard()

        return Response({
            "success": True,
            "user_type": "student",
            "data": data
        })
    def _get_ebook_dashboard(self, payload, request):
        from ebook.models import EbookRegistration

        email = payload.get("email")

        if not email:
            return Response({
                "success": False,
                "message": "Email missing in token"
            }, status=200)

        # ✅ Get purchased ebooks
        registrations = EbookRegistration.objects.filter(
            email__iexact=email,
            is_paid=True
        ).select_related("ebook")

        ebooks = []

        for reg in registrations:
            ebook = reg.ebook

            ebooks.append({
                "ebook_id": ebook.id,
                "title": ebook.title,
                "description": ebook.description,
                "price": ebook.price,
                "pdf": f"{settings.MEDIA_BASE_URL}{ebook.pdf.url}" if ebook.pdf else None,
                "image": f"{settings.MEDIA_BASE_URL}{ebook.ebook_image.url}" if ebook.ebook_image else None
            })

        return Response({
            "success": True,
            "user_type": "ebookuser",
            "ebooks": ebooks
        }, status=200)

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
                trainers=trainer,
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

        creator_filter = (
            Q(created_by_type="super_admin", created_by__in=allowed_ids) |
            Q(created_by_type="admin", created_by__in=allowed_ids)
        )

        # -----------------------------
        # STUDENTS (1 query)
        # -----------------------------

        student_stats = Student.objects.filter(
            is_archived=False
        ).filter(creator_filter).aggregate(
            total_students=Count("student_id"),
            active_students=Count("student_id", filter=Q(status=True))
        )

        total_students = student_stats["total_students"]
        active_students = student_stats["active_students"]

        # -----------------------------
        # TRAINERS (1 query)
        # -----------------------------

        trainer_stats = Trainer.objects.filter(
            is_archived=False,
            user_type="tutor"
        ).filter(creator_filter).aggregate(
            total_trainers=Count("trainer_id"),
            active_trainers=Count("trainer_id", filter=Q(status__iexact="Active"))
        )

        # -----------------------------
        # COURSES (1 query)
        # -----------------------------

        course_stats = Course.objects.filter(
            is_archived=False
        ).filter(creator_filter).aggregate(
            total_courses=Count("course_id"),
            active_courses=Count("course_id", filter=Q(status="Active"))
        )

        # -----------------------------
        # BATCHES (1 query)
        # -----------------------------

        batch_stats = NewBatch.objects.filter(
            is_archived=False
        ).filter(creator_filter).aggregate(
            total_batches=Count("batch_id"),
            active_batches=Count("batch_id", filter=Q(status=True))
        )

        # -----------------------------
        # BATCHWISE STUDENTS
        # -----------------------------

        batchwise_student_count = (
            NewBatch.objects
            .filter(is_archived=False, status=True, created_by__in=allowed_ids)
            .annotate(student_count=Count("students", distinct=True))
            .values("title", "batch_id", "student_count")
            .order_by("title")
        )

        # -----------------------------
        # WEBINAR BASE QUERY
        # -----------------------------

        webinar_qs = Webinar.objects.filter(
            creator_filter,
            is_deleted=False
        )

        webinar_ids = Subquery(
            webinar_qs.values("uuid")
        )

        webinar_ids_str = webinar_qs.values_list("uuid", flat=True)

        webinar_ids_str = [str(i) for i in webinar_ids_str]

        # -----------------------------
        # WEBINAR OVERVIEW
        # -----------------------------

        webinar_overview = webinar_qs.aggregate(
            total_webinars=Count("uuid"),
            completed_webinars=Count("uuid", filter=Q(is_completed=True)),
            active_webinars=Count(
                "uuid",
                filter=Q(webinar_status=True, is_registration_open=True)
            )
        )

        # -----------------------------
        # REGISTRATIONS
        # -----------------------------

        total_registrations = WebinarRegistration.objects.filter(
            webinar__in=webinar_qs
        ).count()

        # -----------------------------
        # TOTAL REVENUE (JSONB FIX)
        # -----------------------------

        total_revenue = PaymentTransaction.objects.filter(
            metadata__webinar_id__in=webinar_ids_str,
            payment_status="done"
        ).aggregate(
            total=Sum("amount")
        )["total"] or 0

        # -----------------------------
        # WEBINAR PERFORMANCE
        # -----------------------------

        webinar_performance = webinar_qs.annotate(
            participants=Count("registrations", distinct=True),
            attended=Count(
                "registrations",
                filter=Q(registrations__attended=True),
                distinct=True
            ),
            feedback_count=Count("feedbacks", distinct=True),
            avg_rating=Avg("feedbacks__overall_rating")
        ).values(
            "title",
            "uuid",
            "participants",
            "attended",
            "feedback_count",
            "avg_rating"
        ).order_by("-participants")

        # -----------------------------
        # REVENUE MAP
        # -----------------------------

        revenue_map = {
            r["metadata__webinar_id"]: r["total"]
            for r in PaymentTransaction.objects.filter(
                metadata__webinar_id__in=webinar_ids_str,
                payment_status="done"
            ).values("metadata__webinar_id").annotate(
                total=Sum("amount")
            )
        }

        webinar_analytics = []

        for w in webinar_performance:

            webinar_analytics.append({

                "title": w["title"],
                "participants": w["participants"],
                "attended": w["attended"],

                "attendance_rate": (
                    round((w["attended"] / w["participants"]) * 100, 2)
                    if w["participants"] else 0
                ),

                "revenue": float(
                    revenue_map.get(str(w["uuid"]), 0)
                ),

                "avg_rating": round(w["avg_rating"] or 0, 2)

            })

        now = timezone.now()

        start_of_month = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        # -----------------------------
        # DAILY REVENUE
        # -----------------------------

        daily_revenue = PaymentTransaction.objects.filter(
            metadata__webinar_id__in=webinar_ids_str,
            payment_status="done",
            created_at__gte=start_of_month
        ).annotate(
            day=TruncDay("created_at")
        ).values("day").annotate(
            total=Sum("amount")
        ).order_by("day")

        # -----------------------------
        # DAILY REGISTRATIONS
        # -----------------------------

        daily_registrations = WebinarRegistration.objects.filter(
            webinar__in=webinar_qs,
            registered_at__gte=start_of_month
        ).annotate(
            day=TruncDay("registered_at")
        ).values("day").annotate(
            total=Count("id")
        ).order_by("day")

        # -----------------------------
        # MONTHLY REVENUE
        # -----------------------------

        monthly_revenue = PaymentTransaction.objects.filter(
            metadata__webinar_id__in=webinar_ids_str,
            payment_status="done"
        ).annotate(
            month=TruncMonth("created_at")
        ).values("month").annotate(
            total=Sum("amount")
        ).order_by("month")

        # -----------------------------
        # MONTHLY REGISTRATIONS
        # -----------------------------

        monthly_registrations = WebinarRegistration.objects.filter(
            webinar__in=webinar_qs
        ).annotate(
            month=TruncMonth("registered_at")
        ).values("month").annotate(
            total=Count("id")
        ).order_by("month")

        # -----------------------------
        # ATTENDANCE SUMMARY
        # -----------------------------

        attendance_summary = WebinarAttendanceSummary.objects.filter(
            registration__webinar__in=webinar_qs
        ).aggregate(
            avg_duration=Avg("total_duration_seconds"),
            total_joins=Sum("join_count")
        )

        # -----------------------------
        # FEEDBACK STATS
        # -----------------------------

        feedback_stats = WebinarFeedback.objects.filter(
            webinar__in=webinar_qs
        ).aggregate(
            avg_rating=Avg("overall_rating"),
            recommend_rate=Avg(
                Case(
                    When(would_recommend=True, then=1),
                    default=0,
                    output_field=IntegerField()
                )
            )
        )

        return Response({

            "success": True,
            "user_type": "super_admin",

            "data": {

                "total_trainers": trainer_stats["total_trainers"],
                "active_trainers": trainer_stats["active_trainers"],

                "total_students": total_students,
                "active_students": active_students,

                "total_courses": course_stats["total_courses"],
                "active_courses": course_stats["active_courses"],

                "total_batches": batch_stats["total_batches"],
                "active_batches": batch_stats["active_batches"],

                "batchwise_student_count": list(batchwise_student_count),

                "overall_monthly_revenue": list(monthly_revenue),

                "webinar_analytics": {

                    "overview": {

                        "total_webinars": webinar_overview["total_webinars"],
                        "completed_webinars": webinar_overview["completed_webinars"],
                        "active_webinars": webinar_overview["active_webinars"],
                        "total_registrations": total_registrations,
                        "total_revenue": float(total_revenue)

                    },

                    "daily_revenue": list(daily_revenue),
                    "daily_registrations": list(daily_registrations),
                    "webinar_performance": webinar_analytics,
                    "monthly_revenue": list(monthly_revenue),
                    "monthly_registrations": list(monthly_registrations),
                    "attendance_summary": attendance_summary,
                    "feedback_stats": feedback_stats

                }

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
                    new_batch__students=student,
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
            new_batch__students__in=students_qs,
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
    

import logging     
logger = logging.getLogger(__name__)  
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
        setting=Settings.objects.values('payment_method')

        return Response({
            "success": True,
            "message": "Reports",
            "organizations_list": organization,
            "students_list": student_list,
            "trainers_list": trainer,
            "setting":setting
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
                schedule_qs = ClassSchedule.objects.filter(
                    new_batch__students__in=students_qs,
                    is_archived=False,
                    scheduled_date__lte=date.today()
                ).select_related("course", "batch").order_by("scheduled_date").distinct()
                
                total_classes = schedule_qs.count()
                attended_classes = 0
                class_cancelled = 0

                for sched in schedule_qs:
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
                new_batch__students__in=students_qs,
                is_archived=False,
                scheduled_date__lte=date.today()
            ).select_related("course", "batch").distinct()

            # Group by (date, course, batch)
            for sched in schedule_qs:
                class_date = sched.scheduled_date
                course = sched.course
                batch = sched.new_batch

                # Students enrolled in this batch & course
                enrolled_students = Student.objects.filter(
                    new_batches=batch,
                    new_batches__course=course,
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
                    "title": batch.title,
                    "present_count": present_count,
                    "absent_count": absent_count,
                    "absent_names": absent_names,
                    "class_cancelled": cancelled_classes,
                })
            student = students_qs.first() if students_qs.exists() else None
            # Get all courses the student is enrolled in
            student_courses = Course.objects.filter(new_batches__students=student).distinct()

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
                student_courses = Course.objects.filter(new_batches__students=student)

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
            student_courses = Course.objects.filter(new_batches__student=student).distinct()

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
            courses = Course.objects.filter(new_batches__students__in=students_qs).distinct()
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
                students__in=students_qs
            ).values_list(
                "batch_id",
                "course_id",
                "trainer_id",
                "students__student_id"
            )

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
                        # "order_id": txn.order_id,
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
            logger.error("ADMIN REPORT ERROR")
            logger.error(str(e))
            logger.error(traceback.format_exc())   # ← FULL STACK TRACE
            return Response({
                "success": False,
                "message": str(e)
            })

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
        companies = Employer.objects.filter(is_archived=False, status=True).order_by('-created_at')
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
            full_key = f"{parent_key}.{field}" if parent_key else field
            error_messages.extend(flatten_errors(value, full_key))

    elif isinstance(errors, list):
        for msg in errors:
            msg_str = str(msg).lower()

            # Convert field_name → "Field name"
            field_name = parent_key.split('.')[-1].replace("_", " ").capitalize()

            if "required" in msg_str:
                error_messages.append(f"{field_name} is required")

            elif "valid" in msg_str:
                error_messages.append(f"{field_name} is invalid")

            elif "exists" in msg_str:
                error_messages.append(f"{field_name} already exists")

            else:
                error_messages.append(f"{field_name} {msg_str}")

    else:
        field_name = parent_key.replace("_", " ").capitalize()
        error_messages.append(f"{field_name} {str(errors).lower()}")

    return error_messages

class StudentRegistration(viewsets.ModelViewSet):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def perform_create(self, serializer):
        # DRF calls this automatically when you use self.perform_create()
        user = self.request.user
        admin_trainer_id = getattr(user, "trainer_id", None)
        serializer.save(created_by=admin_trainer_id)

    def create(self, request, *args, **kwargs):
        user = request.user
        
        # 1. Permission checks
        student_module = ModulePermission.objects.filter(module__iexact="Students").first()
        if not student_module:
            return Response({"success": False, "message": "Students module not found"}, status=status.HTTP_404_NOT_FOUND)

        if not has_permission(user, module_id=student_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission"}, status=status.HTTP_403_FORBIDDEN)
        
        # 2. Initialize serializer
        serializer = self.get_serializer(data=request.data)
        
        # 3. Validate and catch errors properly
        if not serializer.is_valid():
            return Response({
                "success": False,
                "message": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)  # Use 400 so frontend knows it failed

        # 4. Trigger the standard save sequence (which fires perform_create internally)
        self.perform_create(serializer)
        student = serializer.instance
        
        headers = self.get_success_headers(serializer.data)

        return Response({
            "success": True,
            "message": "Student registered successfully.",
            "registration_id": student.registration_id
        }, status=status.HTTP_201_CREATED, headers=headers)
    
class StudentListAPIView(viewsets.ViewSet):

    def get(self, request):
        try:
            user = request.user
            user_type = user.user_type

            creator_id = None
            super_admin_id = None
            admin_ids = []

            if user_type == "super_admin":
                creator_id = user.user_id
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=creator_id,
                        created_by_type="super_admin",
                        user_type="admin"
                    ).values_list("trainer_id", flat=True)
                )

            elif user_type == "admin":
                creator_id = user.trainer_id
                admin_obj = Trainer.objects.filter(trainer_id=creator_id).only(
                    "created_by", "created_by_type"
                ).first()
                if admin_obj and admin_obj.created_by_type == "super_admin":
                    super_admin_id = admin_obj.created_by

            elif user_type == "student":
                creator_id = user.student_id

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

            elif user_type == "student":
                students_qs = students_qs.filter(student_id=creator_id)

            else:
                students_qs = Student.objects.none()

            students_qs = students_qs.select_related(
                "school_student",
                "college_student",
                "jobseeker",
                "employee"
            ).prefetch_related(
                Prefetch(
                    "notes",
                    queryset=Note.objects.all().order_by("-created_at"),
                    to_attr="prefetched_notes"
                ),
                Prefetch(
                    "batchcoursetrainer_set",
                    queryset=BatchCourseTrainer.objects.select_related(
                        "batch", "course__course_category"
                    ),
                    to_attr="old_batches"
                ),
                Prefetch(
                    "new_batches",
                    queryset=NewBatch.objects.select_related(
                        "course__course_category"
                    ),
                    to_attr="prefetched_new_batches"
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

                company_id = None
                if getattr(s, "employee", None) and s.employee.company_id:
                    company_id = s.employee.company_id.company_id
                elif getattr(s, "jobseeker", None) and s.jobseeker.company_id:
                    company_id = s.jobseeker.company_id.company_id
                elif getattr(s, "college_student", None) and s.college_student.company_id:
                    company_id = s.college_student.company_id.company_id
                elif getattr(s, "school_student", None) and s.school_student.company_id:
                    company_id = s.school_student.company_id.company_id

                batch_id_list = []
                title_list = []
                course_id_list = []
                course_name_list = []
                category_id_list = []
                category_name_list = []

                for b in getattr(s, "old_batches", []):
                    batch = b.batch
                    course = b.course
                    category = course.course_category if course else None

                    batch_id_list.append(batch.batch_id)
                    title_list.append(batch.title or batch.batch_name)
                    course_id_list.append(course.course_id if course else None)
                    course_name_list.append(course.course_name if course else None)
                    category_id_list.append(category.category_id if category else None)
                    category_name_list.append(category.category_name if category else None)

                for nb in getattr(s, "prefetched_new_batches", []):
                    course = nb.course
                    category = course.course_category if course else None

                    batch_id_list.append(nb.batch_id)
                    title_list.append(nb.title)
                    course_id_list.append(course.course_id if course else None)
                    course_name_list.append(course.course_name if course else None)
                    category_id_list.append(category.category_id if category else None)
                    category_name_list.append(category.category_name if category else None)

                def unique(values):
                    return list(dict.fromkeys(v for v in values if v is not None))

                response_data.append({
                    "registration_id": s.registration_id,
                    "student_id": s.student_id,
                    "first_name": s.first_name,
                    "last_name": s.last_name,
                    "username": s.username,
                    "dob": s.dob,
                    "email": s.email,
                    "converter":s.converter,
                    "contact_no": s.contact_no,
                    "gender": s.gender,
                    "current_address": s.current_address,
                    "permanent_address": s.permanent_address,
                    "city": s.city,
                    "company_id": company_id,
                    "parent_guardian_name": s.parent_guardian_name,
                    "parent_guardian_phone": s.parent_guardian_phone,
                    "parent_guardian_occupation": s.parent_guardian_occupation,
                    "reference_number": s.reference_number,
                    "reference_name":s.reference_name,
                    "alternate_mobile_no":s.alternate_mobile_no,
                    "state": s.state,
                    "student_type": s.student_type,
                    "student_sub_type":s.student_sub_type,
                    "country": s.country,
                    "status": s.status,
                    "internship_required": s.internship_required,
                    "internship": s.internship,
                    "source_type": s.source_type,
                    "source_name":s.source_name,
                    "notes": notes,
                    "joining_date": s.joining_date,
                    "created_by": s.created_by,
                    "created_by_type": s.created_by_type,
                    "created_at": s.created_at,
                    "batch_id": unique(batch_id_list),
                    "batch_title": unique(title_list),
                    "course_id": unique(course_id_list),
                    "course_name": unique(course_name_list),
                    "category_id": unique(category_id_list),
                    "category_name": unique(category_name_list),
                    "profile_pic": (
                        f"https://portal.aryuacademy.com/api{s.profile_pic.url}"
                        if s.profile_pic else None
                    ),
                    "school_student": School_StudentSerializer(s.school_student).data if getattr(s, "school_student", None) else None,
                    "college_student": College_StudentSerializer(s.college_student).data if getattr(s, "college_student", None) else None,
                    "jobseeker": JobSeekerSerializer(s.jobseeker).data if getattr(s, "jobseeker", None) else None,
                    "employee": EmployeeSerializer(s.employee).data if getattr(s, "employee", None) else None,
                })

            role_filter = Q(created_by=-1)

            if user_type == "super_admin":
                role_filter = Q(created_by=creator_id, created_by_type="super_admin") | Q(
                    created_by__in=admin_ids, created_by_type="admin"
                )

            elif user_type == "admin":
                role_filter = Q(created_by=creator_id, created_by_type="admin") | Q(
                    created_by=super_admin_id, created_by_type="super_admin"
                )

            courses = list(
                Course.objects.filter(is_archived=False)
                .filter(role_filter)
                .values(
                    "course_id",
                    "course_name",
                    "fee",
                    category_id=F("course_category_id"),
                    category_name=F("course_category__category_name"),
                )
            )

            categories = list(
                CourseCategory.objects.filter(is_archived=False)
                .filter(role_filter)
                .values("category_id", "category_name")
            )

            companies = list(
                Employer.objects.filter(is_archived=False, status=True)
                .filter(role_filter)
                .values("company_id", "company_name")
            )

            return Response({
                "success": True,
                "students": response_data,
                "courses": courses,
                "categories": categories,
                "batches": [],
                "companies": companies
            })

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            })


class StudentTicketViewSet(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    # Optimized base queryset with prefetch
    def get_queryset(self):
        return (
            StudentTicket.objects
            .select_related(
                "student",
                "webinar_participant",
                "handled_by_trainer",
                "handled_by_superadmin"
            )
            .prefetch_related(
                "attachments",
                Prefetch(
                    "replies",
                    queryset=TicketReply.objects.select_related(
                        "student",
                        "trainer",
                        "super_admin"
                    ).order_by("created_at")
                )
            )
            .annotate(
                replies_count=Count("replies", distinct=True)
            )
        )

    # GET: List or Detail
    def get(self, request):
        user = request.user
        user_type = getattr(user, "user_type", None)

        queryset = self.get_queryset()

        # ---------------- STUDENT VIEW ----------------
        if request.query_params.get("type") == "iron_man":
            if user_type != "student":
                return Response({"success": False, "message": "Access denied"}, status=403)

            queryset = queryset.filter(student__student_id=user.student_id)

        # ---------------- ADMIN / SUPER ADMIN VIEW ----------------
        elif request.query_params.get("type") == "wonder_women":
            if user_type not in ("admin", "super_admin"):
                return Response({"success": False, "message": "Access denied"}, status=403)

            scope = self.get_admin_scope(user)
            queryset = queryset.filter(scope)

        # ---------------- DETAIL VIEW ----------------
        elif request.query_params.get("natasha"):
            try:
                ticket_id = int(request.query_params["natasha"])
            except ValueError:
                return Response({"success": False, "message": "Invalid ticket_id"}, status=400)

            ticket = queryset.filter(ticket_id=ticket_id).first()
            if not ticket:
                return Response({"success": False, "message": "Ticket not found"}, status=404)

            return Response({
                "success": True,
                "data": TicketDetailSerializer(ticket, context={'request': request}).data
            })

        else:
            return Response({"success": False, "message": "Invalid request"}, status=400)

        # ----------- STATUS COUNTS (Single Aggregation) -----------
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
            "tickets": StudentTicketSerializer(
                tickets,
                many=True,
                context={'request': request}
            ).data
        })

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

        admin_user = None
        trainer = None

        created_by = student.created_by
        created_type = student.created_by_type

        if created_by and created_type:

            # -------- SUPER ADMIN --------
            if created_type == "super_admin":
                admin_user = User.objects.filter(
                    id=int(created_by)
                ).first()

            # -------- ADMIN (TRAINER) --------
            elif created_type == "admin":
                trainer = Trainer.objects.filter(
                    trainer_id=created_by
                ).first()

                # OPTIONAL: also assign its parent super admin
                if trainer and trainer.created_by:
                    admin_user = User.objects.filter(
                        id=int(trainer.created_by)
                    ).first()

        ticket = StudentTicket.objects.create(
            student=student,
            subject=subject,
            message=message,
            priority=priority,
            status="new",
            updated_by=real_user,
            handled_by_superadmin=admin_user,
            handled_by_trainer=trainer
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

        # Convert JWTUser → Real DB User
        real_user = self.get_real_user(user)
        if not real_user:
            return Response({"success": False, "message": "User not found"}, status=status.HTTP_400_BAD_REQUEST)

        # Permission check for student
        if ut == "student":
            if not ticket.student or ticket.student.student_id != getattr(user, "student_id", None):
                return Response({"success": False, "message": "You can only reply to your own tickets"}, status=status.HTTP_403_FORBIDDEN)

        reply_data = {
            "ticket": ticket,
            "message": message
        }

        # ---------------- STUDENT ----------------
        if ut == "student":
            reply_data["student"] = ticket.student

        # ---------------- ADMIN ----------------
        elif ut == "admin":
            trainer = Trainer.objects.filter(username=real_user.username).first()
            if not trainer:
                return Response({"success": False, "message": "Trainer profile not found"}, status=status.HTTP_400_BAD_REQUEST)

            reply_data["trainer"] = trainer
            ticket.handled_by_trainer = trainer

        # ---------------- SUPER ADMIN ----------------
        elif ut == "super_admin":
            reply_data["super_admin"] = real_user
            ticket.handled_by_superadmin = real_user

        else:
            return Response({"success": False, "message": "Invalid user type"}, status=status.HTTP_403_FORBIDDEN)

        # Create reply
        reply = TicketReply.objects.create(**reply_data)

        # Update ticket
        ticket.status = "in_progress"
        ticket.updated_by = real_user
        ticket.save(update_fields=[
            "status",
            "handled_by_trainer",
            "handled_by_superadmin",
        ])

        return Response({
            "success": True,
            "message": "Reply added successfully",
            "reply": TicketReplySerializer(reply, context={'request': request}).data
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
    from .utils import get_real_user
    def get_admin_scope(self, user):
        user_type = getattr(user, "user_type", None)
        real_user = self.get_real_user(user)

        if not real_user:
            return Q(pk__isnull=True)

        # -------- SUPER ADMIN --------
        if user_type == "super_admin":

            # Get all admins under this super admin
            trainers = Trainer.objects.filter(
                created_by=str(real_user.id)   # adjust field name if different
            ).values_list("trainer_id", flat=True)

            return (
                # assigned tickets
                Q(handled_by_superadmin=real_user) |

                # tickets of students directly created by super admin
                Q(
                    student__created_by=str(real_user.id),
                    student__created_by_type="super_admin"
                ) |

                # KEY FIX: students created by admins under this super admin
                Q(
                    student__created_by__in=[str(t) for t in trainers],
                    student__created_by_type="admin"
                ) |

                # webinar
                Q(webinar_participant__isnull=False)
            )

        # -------- ADMIN --------
        if user_type == "admin":
            trainer = Trainer.objects.filter(username=real_user.username).first()

            if not trainer:
                return Q(pk__isnull=True)

            return (
                Q(handled_by_trainer=trainer) |
                Q(student__created_by=str(trainer.trainer_id), student__created_by_type="admin") |
                Q(webinar_participant__isnull=False)
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
        status_value = request.data.get('status', '').strip()

        if not status_value:
            return Response({
                'success': False,
                'message': 'Status is required.'
            }, status=200)

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
            # Prevent duplicate SAME STATUS only

            already_exists = Attendance.objects.filter(
                student=student,
                new_batch=new_batch,
                course=course,
                status=status_val,
                date__date=scheduled_date.date()
            ).exists()

            if already_exists:

                return Response({
                    "success": False,
                    "message": f"{status_val} already marked."
                }, status=200)
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

    @action(detail=False, methods=['get'], permission_classes = [IsAuthenticated],authentication_classes = [CustomJWTAuthentication],url_path='full_logs/(?P<student_id>[^/.]+)')
    def full_logs(self, request, student_id=None):
        # permission_classes = [IsAuthenticated]
        # authentication_classes = [CustomJWTAuthentication]
        try:
            if not student_id:
                return Response({
                    'success': False,
                    'message': 'student_id is required'
                }, status=200)

            month = request.query_params.get('month')
            year = request.query_params.get('year')

            queryset = Attendance.objects.filter(
                student__student_id=student_id
            ).order_by('date')

            if month:
                queryset = queryset.filter(
                    date__month=int(month)
                )

            if year:
                queryset = queryset.filter(
                    date__year=int(year)
                )

            ist = pytz.timezone("Asia/Kolkata")

            grouped = {}

            # ======================================================
            # GROUP ATTENDANCE
            # ======================================================

            for att in queryset:

                serializer_data = AttendanceSerializer(att).data

                local_dt = datetime.strptime(
                    serializer_data['date'],
                    '%Y-%m-%d %I:%M:%S %p'
                )

                local_dt = ist.localize(local_dt)

                # ----------------------------------------
                # BATCH
                # ----------------------------------------

                batch_id = None
                batch_title = None

                if att.new_batch_id:

                    batch_id = att.new_batch.batch_id

                    batch_title = att.new_batch.title

                # ----------------------------------------
                # GROUP KEY
                # ----------------------------------------

                key = (
                    att.student.student_id,
                    att.course.course_id,
                    batch_id,
                    local_dt.date()
                )

                # ----------------------------------------
                # INITIALIZE
                # ----------------------------------------

                if key not in grouped:

                    grouped[key] = {

                        'attendance_id': att.id,

                        'student_id': att.student.student_id,

                        'student_name': (
                            f"{att.student.first_name} "
                           
                        ),

                        'batch_id': batch_id,

                        'title': batch_title,

                        'course_id': att.course.course_id,

                        'course_name': att.course.course_name,

                        'date': local_dt.strftime('%d-%m-%Y'),

                        'status': 'Absent',

                        'login_time': None,

                        'logout_time': None,

                        'break_in': None,

                        'break_out': None,

                        'time_spend': '-',

                        'break_duration': '-',

                        'net_time_spend': '-',

                        # TEMP FIELDS

                        'login_dt': None,

                        'logout_dt': None,

                        'break_sessions': [],

                        'current_break_in': None,
                    }

                current = grouped[key]

                status_lower = att.status.lower()

                # ----------------------------------------
                # LOGIN
                # ----------------------------------------

                if status_lower in ['login', 'present']:

                    current['login_time'] = (
                        local_dt.strftime('%I:%M %p')
                    )

                    current['login_dt'] = local_dt

                    current['status'] = 'Present'

                # ----------------------------------------
                # LOGOUT
                # ----------------------------------------

                elif status_lower == 'logout':

                    current['logout_time'] = (
                        local_dt.strftime('%I:%M %p')
                    )

                    current['logout_dt'] = local_dt

                    current['status'] = 'Present'

                # ----------------------------------------
                # BREAK IN
                # ----------------------------------------

                elif status_lower in ['breakin', 'break in']:

                    current['break_in'] = local_dt.strftime('%I:%M %p')
                    current['current_break_in'] = local_dt

                elif status_lower in ['breakout', 'break out']:

                    current['break_out'] = local_dt.strftime('%I:%M %p')

                    if current['current_break_in']:
                        current['break_sessions'].append({
                            'break_in': current['current_break_in'],
                            'break_out': local_dt
                        })

                        current['current_break_in'] = None
            logs = list(grouped.values())

            # ======================================================
            # CALCULATIONS
            # ======================================================

            for item in logs:

                # ----------------------------------------
                # CHECK CLASS SCHEDULE
                # ----------------------------------------

                schedule_exists = ClassSchedule.objects.filter(

                    new_batch_id=item['batch_id'],

                    course_id=item['course_id'],

                    scheduled_date=datetime.strptime(
                        item['date'],
                        '%d-%m-%Y'
                    ).date(),

                    is_archived=False

                ).exists()

                # ----------------------------------------
                # HOLIDAY
                # ----------------------------------------

                if (
                    not schedule_exists
                    and not item['login_dt']
                ):

                    item['status'] = 'Holiday'

                # ----------------------------------------
                # AUTO LOGOUT
                # ----------------------------------------

                if item['login_dt'] and not item['logout_dt']:

                    now_ist = timezone.now().astimezone(ist)

                    # SAME DATE CHECK

                    if now_ist.date() != item['login_dt'].date():

                        now_ist = item['login_dt']

                    # NEGATIVE TIME CHECK

                    if now_ist < item['login_dt']:

                        now_ist = item['login_dt']

                    item['logout_dt'] = now_ist

                    item['logout_time'] = (
                        now_ist.strftime('%I:%M %p')
                    )

                # ----------------------------------------
                # TOTAL TIME
                # ----------------------------------------

                if item['login_dt'] and item['logout_dt']:

                    time_diff = (
                        item['logout_dt']
                        - item['login_dt']
                    ).total_seconds()

                    # PREVENT NEGATIVE TIME

                    if time_diff < 0:

                        time_diff = 0

                        item['logout_dt'] = (
                            item['login_dt']
                        )

                        item['logout_time'] = (
                            item['login_time']
                        )

                    total_seconds = int(time_diff)

                    # ----------------------------------------
                    # TOTAL BREAK
                    # ----------------------------------------

                    total_break_seconds = 0

                    for session in item['break_sessions']:

                        break_diff = (
                            session['break_out']
                            - session['break_in']
                        ).total_seconds()

                        if break_diff < 0:

                            break_diff = 0

                        total_break_seconds += int(
                            break_diff
                        )

                    # ----------------------------------------
                    # NET WORKING TIME
                    # ----------------------------------------

                    net_seconds = max(
                        total_seconds - total_break_seconds,
                        0
                    )

                    # ----------------------------------------
                    # TOTAL TIME FORMAT
                    # ----------------------------------------

                    total_hours = (
                        total_seconds // 3600
                    )

                    total_minutes = (
                        total_seconds % 3600
                    ) // 60

                    item['time_spend'] = (
                        f"{total_hours:02}:{total_minutes:02} Hrs"
                    )

                    # ----------------------------------------
                    # BREAK FORMAT
                    # ----------------------------------------

                    break_hours = (
                        total_break_seconds // 3600
                    )

                    break_minutes = (
                        total_break_seconds % 3600
                    ) // 60

                    item['break_duration'] = (
                        f"{break_hours:02}:{break_minutes:02} Hrs"
                    )

                    # ----------------------------------------
                    # NET TIME FORMAT
                    # ----------------------------------------

                    net_hours = (
                        net_seconds // 3600
                    )

                    net_minutes = (
                        net_seconds % 3600
                    ) // 60

                    item['net_time_spend'] = (
                        f"{net_hours:02}:{net_minutes:02} Hrs"
                    )

                # ----------------------------------------
                # REMOVE TEMP FIELDS
                # ----------------------------------------

                item.pop('login_dt', None)

                item.pop('logout_dt', None)

                item.pop('current_break_in', None)

                item.pop('break_sessions', None)

            return Response({

                'success': True,

                'message': (
                    f'Full attendance logs for student '
                    f'{student_id}'
                ),

                'data': logs

            }, status=200)
        except Exception as e:
            print(traceback.format_exc())
            return Response(
                {
                    "success": False,
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                },
                status=500,
            )
    
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
            "student": f"{student.first_name or ''} {student.last_name or ''}".strip(),
            "total_classes": total_classes,
            "attended": attended_count,
            "not_attended": not_attended_count,
            "attendance_percentage": round(attendance_percentage, 2),
            "classes": class_statuses
        }, status=status.HTTP_200_OK)
    
    @action(detail=False,methods=['get'],url_path='attendance-logs')
    def attendance_logs(self, request):

        student_id = request.GET.get("student_id")
        course_id = request.GET.get("course_id")
        batch_id = request.GET.get("batch_id")
        date = request.GET.get("date")

        queryset = Attendance.objects.all()

        if student_id:
            queryset = queryset.filter(student__student_id=student_id)

        if course_id:
            queryset = queryset.filter(course_id=course_id)

        if batch_id:
            queryset = queryset.filter(new_batch_id=batch_id)

        if date:
            queryset = queryset.filter(date__date=date)

        queryset = queryset.order_by("date")

        data = []

        for obj in queryset:

            dt = obj.date

            if timezone.is_naive(dt):
                dt = timezone.make_aware(
                    dt,
                    timezone.get_current_timezone()
                )

            dt = timezone.localtime(dt)

            data.append({
                "id": obj.id,
                "status": obj.status,
                "datetime": dt.strftime(
                    "%Y-%m-%d %I:%M %p"
                )
            })

        return Response({
            "success": True,
            "data": data
        })
    
    @action(detail=False,methods=['put'],url_path='update-attendance-log')
    def update_attendance_log(self, request, student_id=None):

        attendance_id = (
            request.data.get("attendance_id")
            or request.data.get("id")
        )

        datetime_value = request.data.get("datetime")
        status_value = request.data.get("status")

        if not attendance_id:
            return Response({
                "success": False,
                "message": "attendance_id is required"
            })

        try:
            attendance = Attendance.objects.get(
                id=attendance_id
            )

        except Attendance.DoesNotExist:

            return Response({
                "success": False,
                "message": f"Attendance {attendance_id} not found"
            })

        if datetime_value:

            naive_dt = datetime.strptime(
                datetime_value,
                "%Y-%m-%d %I:%M %p"
            )

            attendance.date = timezone.make_aware(
                naive_dt,
                timezone.get_current_timezone()
            )

        if status_value:
            attendance.status = status_value

        attendance.save()

        return Response({
            "success": True,
            "message": "Attendance updated successfully"
        })

class StudentProfileViewSet(LoggingMixin, NotesMixin, viewsets.ModelViewSet):

    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    http_method_names = ['get', 'patch', 'put']
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    lookup_field = 'student_id'    
    lookup_url_kwarg = 'student_id'

    def get_queryset(self):
        user = self.request.user
        user_type = getattr(user, 'user_type', None)

        # BASE QUERY (optimized)
        base_qs = (
            Student.objects.filter(is_archived=False)
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
                "new_batches__course",
                "new_batches__trainers",
                "batchcoursetrainer_set__course",
                "batchcoursetrainer_set__trainer",
                Prefetch(
                    "attendance_set",
                    queryset=Attendance.objects.select_related("course"),
                ),
            )
        )

        # STUDENT → only own record
        if user_type == 'student':
            return base_qs.filter(student_id=user.student_id)

        # TRAINER → students in their batches (optimized with distinct)
        if user_type in ['tutor', 'trainer']:
            trainer_student_ids = (
                NewBatch.objects.filter(
                    trainer__trainer_id=user.trainer_id,
                    is_archived=False
                )
                .values_list('students__student_id', flat=True)
                .distinct()
            )
            return base_qs.filter(student_id__in=trainer_student_ids)

        # ADMIN → scoped students
        if user_type == 'admin':
            return base_qs.filter(
                created_by=str(user.trainer_id),
                created_by_type='admin'
            )

        # SUPER ADMIN → include admins + own created students
        if user_type == 'super_admin':
            admin_ids = (
                Trainer.objects.filter(
                    created_by=user.user_id,
                    created_by_type='super_admin',
                    is_archived=False
                )
                .values_list('trainer_id', flat=True)
            )

            return base_qs.filter(
                Q(created_by=str(user.user_id), created_by_type='super_admin') |
                Q(created_by__in=[str(i) for i in admin_ids], created_by_type='admin')
            )

        return Student.objects.none()

    @cache_api(prefix="student_profile", timeout=300)
    def retrieve(self, request, student_id=None):
        user = request.user
        user_type = getattr(user, 'user_type', None)
        print("USER:", user)
        print("USER TYPE:", user_type)
        print("USER STUDENT ID:", getattr(user, "student_id", None))
        print("REQUESTED STUDENT ID:", student_id)
        try:
            student = self.get_queryset().get(student_id=int(student_id))
        except Student.DoesNotExist:
            return Response(
                {"success": False, "message": "Not found or access denied."},
                status=404
            )

        
        if user_type == "student" and str(student.student_id) != str(user.student_id):
            return Response(
                {"success": False, "message": "You are not allowed to access this resource."},
                status=403
            )

        

        try:
            serializer = StudentProfileSerializer(
                student,
                context={"request": request}
            )
            return Response({
                "success": True,
                "data": serializer.data
            })
        except Exception:
            traceback.print_exc()
            raise

    @transaction.atomic
    def partial_update(self, request, student_id=None):
        try:
            # Fetches based on user role security restrictions defined in your get_queryset
            student = self.get_queryset().get(student_id=student_id)
        except Student.DoesNotExist:
            return Response(
                {"success": False, "message": "Not found or access denied."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 1. Update the base student information
        serializer = StudentUpdateSerializer(student, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({"success": False, "message": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        
        student = serializer.save()

        # 2. Extract and dynamically write sub-table data
        student_type = request.data.get('student_type', student.student_type)
        
        sub_profile_mappings = {
            'college_student': ('college_student', College_Student),
            'school_student': ('school_student', School_Student),
            'job_seeker': ('jobseeker', JobSeeker),
            'employee': ('employee', Employee),
        }

        if student_type in sub_profile_mappings:
            payload_key, model_class = sub_profile_mappings[student_type]
            sub_data = request.data.get(payload_key)

            # If sent via FormData stringified, convert to native dictionary
            if isinstance(sub_data, str):
                import json
                try:
                    sub_data = json.loads(sub_data)
                except json.JSONDecodeError:
                    sub_data = None

            if sub_data and isinstance(sub_data, dict):
                # Pull file uploads (like resumes) safely from request structures
                file_fields = ['resume']
                for field in file_fields:
                    file_key = f"{payload_key}.{field}"
                    if file_key in request.FILES:
                        sub_data[field] = request.FILES[file_key]
                    elif field in request.FILES:
                        sub_data[field] = request.FILES[field]

                # Update or automatically create if it doesn't exist yet
                model_class.objects.update_or_create(
                    student=student,
                    defaults=sub_data
                )

        return Response({"success": True, "message": "Updated successfully."})
    
    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return StudentUpdateSerializer
        return StudentProfileSerializer  # Read-only profile view
    
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
    def change_password(self, request, student_id=None):
        try:
            student = Student.objects.get(student_id=student_id)
        except Student.DoesNotExist:
            return Response({"success": False, "message": "Student not found"}, status=status.HTTP_404_NOT_FOUND)

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

        if not hasattr(user, 'user_type') or user.user_type.lower() not in ['admin', 'super_admin']:
            return Response(
                {
                    "success": False,
                    "message": "Only admin or super admin users can reset student passwords."
                },
                status=200
            )

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


class StudentCourseViewSet(LoggingMixin, NotesMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    http_method_names = ['get', 'post',"patch", 'delete']
    parser_classes = [JSONParser]

    # ----------------------------------
    # Helper: Get student (optimized)
    # ----------------------------------
    def _get_student(self, student_id):
        return (
            Student.objects
            .only("student_id", "first_name", "last_name", "discount")
            .filter(student_id=student_id, is_archived=False)
            .first()
        )

    # ----------------------------------
    # GET: List courses (optimized query)
    # ----------------------------------
    def list_courses(self, request, student_id=None):
        from courses.models import Topic
        student = self._get_student(student_id)
        if not student:
            return Response(
                {"success": False, "message": "Student not found"},
                status=404
            )

        MEDIA_BASE_URL = "https://portal.aryuacademy.com/api/media/"

        # ----------------------------------
        # 1. STUDENT-SPECIFIC BATCHES
        # ----------------------------------
        student_batches = (
            NewBatch.objects
            .filter(students=student, is_archived=False)
            .select_related("course")
            .only(
                "batch_id", "title",
                "course__course_id",
                "course__course_name",
                "course__duration",
                "course__fee",
                "course__course_pic"
            )
        )

        # ----------------------------------
        # 2. GET COURSE IDS (for progress)
        # ----------------------------------
        course_ids = list(
            student_batches.values_list("course_id", flat=True)
        )

        # ----------------------------------
        # 3. PROGRESS CALCULATION (OPTIMIZED)
        # ----------------------------------
        progress_qs = (
            Topic.objects
            .filter(course_id__in=course_ids, is_archived=False)
            .values("course_id")
            .annotate(
                total_topics=Count("topic_id"),
                completed_topics=Count(
                    "topic_id",
                    filter=Q(
                        student_statuses__student=student,
                        student_statuses__status=True
                    )
                )
            )
        )

        # Convert to dict → {course_id: progress%}
        progress_map = {}
        for p in progress_qs:
            total = p["total_topics"] or 0
            completed = p["completed_topics"] or 0
            progress = int((completed / total) * 100) if total > 0 else 0
            progress_map[p["course_id"]] = progress

        # ----------------------------------
        # 4. BUILD RESPONSE DATA
        # ----------------------------------
        result = {}

        for b in student_batches:
            course = b.course
            cid = course.course_id

            course_pic_url = (
                f"{MEDIA_BASE_URL}{course.course_pic}"
                if course.course_pic else None
            )

            if cid not in result:
                result[cid] = {
                    "course_id": cid,
                    "course_name": course.course_name,
                    "duration": course.duration,
                    "fee": course.fee,
                    "course_pic": course_pic_url,
                    "discount": student.discount,
                    "progress": progress_map.get(cid, 0),
                    "batches": []
                }

            result[cid]["batches"].append({
                "batch_id": b.batch_id,
                "batch_title": b.title
            })

        # ----------------------------------
        # 5. ALL COURSES (GLOBAL)
        # ----------------------------------
        all_courses = list(
            Course.objects
            .filter(is_archived=False, status="Active")
            .values(
                "course_id",
                "course_name",
                "duration",
                "fee",
            )
        )

        # ----------------------------------
        # 6. ALL BATCHES (GLOBAL)
        # ----------------------------------
        all_batches = list(
            NewBatch.objects
            .filter(is_archived=False, status=True)
            .values(
                "batch_id",
                "title",
                "course__course_id",
                "course__course_name",
            )
        )

        # ----------------------------------
        # FINAL RESPONSE
        # ----------------------------------
        return Response({
            "success": True,
            # STUDENT-SPECIFIC DATA
            "data": list(result.values()),
            # GLOBAL DATA
            "courses": all_courses,
            "batches": all_batches,

            
        })
    
    
    # ----------------------------------
    # POST: Assign course (optimized)
    # ----------------------------------
    def assign_course(self, request, student_id=None):
        student = self._get_student(student_id)
        if not student:
            return Response({"success": False, "message": "Student not found"}, status=404)

        batch_id = request.data.get("batch")
        discount = request.data.get("discount")

        if not batch_id:
            return Response({"success": False, "message": "Batch is required"}, status=400)

        batch = (
            NewBatch.objects
            .only("batch_id", "course_id")
            .filter(batch_id=batch_id, is_archived=False)
            .first()
        )

        if not batch:
            return Response({"success": False, "message": "Batch not found"}, status=404)

        # prevent duplicate (single query)
        if NewBatch.objects.filter(
            batch_id=batch_id,
            students__student_id=student.student_id
        ).exists():
            return Response({
                "success": False,
                "message": "Student already assigned to this batch"
            })

        # assign (no extra query)
        batch.students.add(student)

        # update discount only if provided
        if discount is not None:
            Student.objects.filter(student_id=student.student_id).update(discount=discount)

        return Response({
            "success": True,
            "message": "Course assigned successfully"
        })

    # ----------------------------------
    # GET: Single course detail
    # ----------------------------------
    def retrieve_course(self, request, student_id=None, course_id=None):
        student = self._get_student(student_id)
        if not student:
            return Response({"success": False, "message": "Student not found"}, status=404)

        # Get batch + course in one query
        batch = (
            NewBatch.objects
            .filter(
                students=student,
                course__course_id=course_id,
                is_archived=False
            )
            .select_related("course", "trainer", "course__course_category")
            .first()
        )

        if not batch:
            return Response({
                "success": False,
                "message": "Course not assigned"
            })

        course = batch.course

        # Serialize full course details
        serializer = CourseSerializer(
            course,
            context={"request": request, "student": student}
        )

        return Response({
            "success": True,
            "discount": student.discount,
            "data": {
                "course": serializer.data,   # full course data
                "batch": {
                    "batch_id": batch.batch_id,
                    "batch_title": batch.title,
                    "trainer": getattr(batch.trainer, "full_name", None)
                }
            }
        })

    @action(detail=True, methods=['put', 'patch'], url_path='edit-course')
    def edit_course(self, request, student_id=None):
        student = self._get_student(student_id)
        if not student:
            return Response(
                {"success": False, "message": "Student not found"},
                status=404
            )

        old_batch_id = request.data.get("old_batch")
        new_batch_id = request.data.get("new_batch")
        discount = request.data.get("discount")

        if not any([new_batch_id, discount is not None]):
            return Response({
                "success": False,
                "message": "Nothing to update"
            }, status=400)

        with transaction.atomic():

            # ----------------------------------
            # 1. Handle batch change (ONLY if changed)
            # ----------------------------------
            if new_batch_id and old_batch_id and new_batch_id != old_batch_id:

                old_batch = (
                    NewBatch.objects
                    .filter(
                        batch_id=old_batch_id,
                        students__student_id=student.student_id
                    )
                    .only("batch_id")
                    .first()
                )

                if not old_batch:
                    return Response({
                        "success": False,
                        "message": "Student not assigned to old batch"
                    }, status=404)

                new_batch = (
                    NewBatch.objects
                    .filter(batch_id=new_batch_id, is_archived=False)
                    .only("batch_id")
                    .first()
                )

                if not new_batch:
                    return Response({
                        "success": False,
                        "message": "New batch not found"
                    }, status=404)

                # prevent duplicate
                if NewBatch.objects.filter(
                    batch_id=new_batch_id,
                    students__student_id=student.student_id
                ).exists():
                    return Response({
                        "success": False,
                        "message": "Student already in new batch"
                    })

                # Update batch
                old_batch.students.remove(student)
                new_batch.students.add(student)

            # ----------------------------------
            # 2. Handle invalid batch case
            # ----------------------------------
            elif new_batch_id and old_batch_id and new_batch_id == old_batch_id:
                # only error if NO discount update
                if discount is None:
                    return Response({
                        "success": False,
                        "message": "Both batches are same"
                    })

            # ----------------------------------
            # 3. Update discount (always allowed)
            # ----------------------------------
            if discount is not None:
                Student.objects.filter(
                    student_id=student.student_id
                ).update(discount=discount)

        return Response({
            "success": True,
            "message": "Course updated successfully"
        })

    # ----------------------------------
    # DELETE: Remove course (optimized)
    # ----------------------------------
    def remove_course(self, request, student_id=None, batch_id=None):
        student = self._get_student(student_id)
        if not student:
            return Response({"success": False, "message": "Student not found"}, status=404)

        batch = NewBatch.objects.filter(batch_id=batch_id).only("batch_id").first()

        if not batch:
            return Response({"success": False, "message": "Batch not found"}, status=404)

        # remove in single query
        if not NewBatch.objects.filter(
            batch_id=batch_id,
            students__student_id=student.student_id
        ).exists():
            return Response({"success": False, "message": "Student not in batch"})

        batch.students.remove(student)

        return Response({
            "success": True,
            "message": "Course removed successfully"
        })

class StudentusertypeViewSet(viewsets.ViewSet):
    def get(self, request):
        student_id = request.GET.get('student_id')

        queryset = Studentusertype.objects.filter(is_active=True)

        if student_id:
            queryset = queryset.filter(student_id=student_id)

        serializer =StudentusertypeSerializer(queryset, many=True)

        return Response({
            "success": True,
            "data": serializer.data
        })

    def post(self, request):
        serializer = StudentusertypeSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "User type created successfully",
                "data": serializer.data
            })

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, student_id=None):
        try:
            obj = Studentusertype.objects.get(id=student_id)
        except Studentusertype.DoesNotExist:
            return Response({
                "success": False,
                "message": "Record not found"
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = StudentusertypeSerializer(
            obj,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "Updated successfully",
                "data": serializer.data
            })

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request, *args, **kwargs):
        obj_id = kwargs.get('pk') or kwargs.get('student_id')

        try:
            obj = Studentusertype.objects.get(id=obj_id)
            obj.delete()

            return Response({
                "success": True,
                "message": "Deleted successfully"
            })

        except Studentusertype.DoesNotExist:
            return Response({
                "success": False,
                "message": "Record not found"
            }, status=status.HTTP_404_NOT_FOUND)
        
class StudentsubusertypeViewset(viewsets.ViewSet):
    def get(self, request):
        student_id = request.GET.get('student_id')
        user_type = request.GET.get('user_type')

        queryset = Studentsubusertype.objects.filter(is_active=True)

        if student_id:
            queryset = queryset.filter(student_id=student_id)

        if user_type:
            queryset = queryset.filter(user_type=user_type)

        serializer = StudentsubusertypeSerializer(queryset, many=True)

        return Response({
            "success": True,
            "data": serializer.data
        })

    def post(self, request):
        serializer = StudentsubusertypeSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "User type created successfully",
                "data": serializer.data
            })

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, student_id=None):
        try:
            obj = Studentsubusertype.objects.get(id=student_id)
        except Studentsubusertype.DoesNotExist:
            return Response({
                "success": False,
                "message": "Record not found"
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = StudentsubusertypeSerializer(
            obj,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "Updated successfully",
                "data": serializer.data
            })

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, *args, **kwargs):
        obj_id = kwargs.get('pk') or kwargs.get('student_id')

        try:
            obj = Studentsubusertype.objects.get(id=obj_id)
            obj.delete()

            return Response({
                "success": True,
                "message": "Deleted successfully"
            })

        except Studentsubusertype.DoesNotExist:
            return Response({
                "success": False,
                "message": "Record not found"
            }, status=status.HTTP_404_NOT_FOUND)

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
    
    def create(self, request, *args, **kwargs):
        """
        POST /api/certificates/
        Creates a certificate record and triggers the image/PDF generation.
        """
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            print("--- VALIDATION ERRORS ---")
            print(serializer.errors)  # This will print {'field_name': ['This field is required.']}
            print("------------------------")
            
        serializer.is_valid(raise_exception=True)
        
        # 1. Save the instance to the database
        certificate = serializer.save()
        from .certificate_filler import generate_and_send_certificate_pdf

        # 2. Trigger the PDF generation
        # If generate_and_send_certificate_pdf is decorated with @shared_task, use:
        # generate_and_send_certificate_pdf.delay(certificate.id)
        # Otherwise, run it synchronously:
        try:
            generate_and_send_certificate_pdf(certificate.id)
            # Refresh from DB to get the newly updated file path if needed
            certificate.refresh_from_db()
        except Exception as e:
            logger.error("Failed to generate certificate file: %s", str(e))
            # Optional: You can choose to fail the request or return success 
            # with a warning that the file is generating.

        # 3. Return response with serialized data
        return Response({
            "success": True,
            "message": "Certificate created and file generation triggered successfully.",
            "data": self.get_serializer(certificate).data
        }, status=status.HTTP_201_CREATED)
    
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


class RegisterThrottle(AnonRateThrottle):
    rate = "5/hour"

class PublicTrainerRegisterAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []          # 🔥 no auth
    throttle_classes = [RegisterThrottle]

    def post(self, request):
        serializer = PublicTrainerRegisterSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "message": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                trainer = serializer.save()

        except IntegrityError:
            return Response(
                {
                    "success": False,
                    "message": "Registration failed. Try again."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "Registration successful. Await admin approval.",
                "trainer_id": trainer.trainer_id
            },
            status=status.HTTP_201_CREATED
        )

    def _trainer_prefetches():
        """
        Returns a list of Prefetch objects that eliminate every N+1 query
        present in the serializer (notes, attendance, batches + their students).
        """
        return [
            # Attendance  →  prefetched_attendance
            Prefetch(
                "trainerattendance_set",
                queryset=TrainerAttendance.objects.order_by("-date"),
                to_attr="prefetched_attendance",
            ),
            # New-system batches  →  prefetched_batches
            # course is select_related (1 JOIN), students is a further prefetch
            Prefetch(
                "new_batches",
                queryset=(
                    NewBatch.objects
                    .filter(is_archived=False)
                    .select_related("course")
                    .prefetch_related(
                        Prefetch(
                            "students",
                            queryset=Student.objects.only(
                                "student_id", "first_name", "last_name", "registration_id"
                            ),
                        )
                    )
                ),
                to_attr="prefetched_batches",
            ),
            # Notes (GenericRelation)  →  prefetched_notes
            Prefetch(
                "notes",
                queryset=Note.objects.order_by("-created_at"),
                to_attr="prefetched_notes",
            ),
        ]
    
 
class TrainerViewSet(NotesMixin, LoggingMixin, viewsets.ModelViewSet):
    serializer_class        = TrainerSerializer
    parser_classes          = [JSONParser, MultiPartParser, FormParser]
    permission_classes      = [IsAuthenticated, IsAdminOrSuperAdmin]
    authentication_classes  = [CustomJWTAuthentication]
    lookup_field            = "employee_id"
 
    # ── Base queryset — used by list, retrieve, update, destroy ──────────
 
    def get_queryset(self):
        queryset = (
            Trainer.objects
            .filter(is_archived=False)
            .select_related("role")              # eliminates role N+1
            # .prefetch_related(*_trainer_prefetches())
        )
 
        employee_id = self.request.query_params.get("employee_id")
        user_type   = self.request.query_params.get("user_type")
 
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        if user_type:
            queryset = queryset.filter(user_type=user_type)
 
        return queryset.order_by("employee_id")
  
    def retrieve(self, request, *args, **kwargs):
        try:
            trainer = self.get_object()   # uses optimised get_queryset above
        except Trainer.DoesNotExist:
            return Response(
                {"success": False, "message": "Trainer not found."},
                status=status.HTTP_200_OK,
            )
 
        # ── Old-batch data (kept for backward compatibility) ──────────────
        # Two queries, both use covering indexes — no further optimisation needed
        courses = (
            Course.objects
            .filter(
                batchcoursetrainer__trainer=trainer,
                is_archived=False,
                status__iexact="Active",
            )
            .distinct()
            .values("course_id", "course_name")      # only 2 cols — fast
        )
 
        old_batches = (
            Batch.objects
            .filter(
                batchcoursetrainer__trainer=trainer,
                is_archived=False,
                status=True,
            )
            .distinct()
            .values("batch_id", "batch_name", "title")  # only needed cols
        )
 
        serializer = self.get_serializer(trainer)
        return Response(
            {
                "success": True,
                "message": "Trainer profile retrieved successfully.",
                "data":    serializer.data,
                "course":  list(courses),
                "batch":   list(old_batches),
            },
            status=status.HTTP_200_OK,
        )
 
    # ── Create ───────────────────────────────────────────────────────────
 
    def create(self, request, *args, **kwargs):

        tutors_module = (
            ModulePermission.objects
            .filter(module__iexact="Tutors")
            .values("module_id")
            .first()
        )
        if not tutors_module:
            return Response(
                {"success": False, "message": "Tutors module not found"},
                status=status.HTTP_200_OK,
            )
 
        if not has_permission(request.user, module_id=tutors_module["module_id"], actions=["create"]):
            return Response(
                {"success": False, "message": "You do not have permission"},
                status=status.HTTP_200_OK,
            )
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "message": serializer.errors,
                },
                status=status.HTTP_200_OK,
            )
 
        try:
            trainer = serializer.save()
        except IntegrityError as e:
            message = (
                "Email already exists"
                if "email" in str(e)
                else "Something went wrong while creating the trainer"
            )
            return Response(
                {"success": False, "message": message},
                status=status.HTTP_200_OK,
            )
 
        # Auto-set created_by when not provided
        if not trainer.created_by:
            trainer.created_by = str(trainer.trainer_id)
            trainer.save(update_fields=["created_by"])
 
        return Response(
            {
                "success": True,
                "message": "Trainer created successfully.",
                "user_type": getattr(trainer, "user_type", None),
            },
            status=status.HTTP_201_CREATED,
            headers=self.get_success_headers(serializer.data),
        )
 
    # ── Update ───────────────────────────────────────────────────────────
 
    def update(self, request, *args, **kwargs):
        try:
            tutors_module = (
                ModulePermission.objects
                .filter(module__iexact="Tutors")
                .values("module_id")
                .first()
            )

            if not tutors_module:
                return Response(
                    {"success": False, "message": "Tutors module not found"},
                    status=status.HTTP_200_OK,
                )

            if not has_permission(
                request.user,
                module_id=tutors_module["module_id"],
                actions=["update"]
            ):
                return Response(
                    {"success": False, "message": "You do not have permission"},
                    status=status.HTTP_200_OK,
                )

            instance = self.get_object()

            serializer = self.get_serializer(
                instance,
                data=request.data,
                partial=True
            )

            serializer.is_valid(raise_exception=True)

            self.perform_update(serializer)

            notes_text = request.data.get("notes")

            if notes_text:
                self.save_notes(instance, notes_text, request=request)

            # Reload trainer with latest batches
            instance = (
                Trainer.objects
                .filter(pk=instance.pk)
                .select_related("role")
                .prefetch_related(
                    Prefetch(
                        "new_batches",
                        queryset=NewBatch.objects
                            .select_related("course")
                            .prefetch_related("students"),
                        to_attr="prefetched_batches",
                    ),
                    Prefetch(
                        "notes",
                        queryset=Note.objects.order_by("-created_at"),
                        to_attr="prefetched_notes",
                    ),
                )
                .first()
            )

            serializer = self.get_serializer(instance)

            return Response(
                {
                    "success": True,
                    "message": "Trainer Profile updated successfully",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()

            return Response(
                {
                    "success": False,
                    "message": str(e),
                },
                status=status.HTTP_200_OK,
            )  
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
            trainers=trainer,
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
                    "new_batches__trainers",
                )
                .first())

        if not student:
            return Response({"success": False, "message": "Student not found"}, status=200)

        # courses assigned to trainer
        trainer_courses = (NewBatch.objects
                        .filter(trainers=trainer, students=student)
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
    
class TutorSignupView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    # throttle_classes = [RegisterThrottle]

    def post(self, request):

        # generate employee id
        last_trainer = Trainer.objects.aggregate(Max('trainer_id'))
        next_id = (last_trainer['trainer_id__max'] or 0) + 1
        employee_id = f"TR{str(next_id).zfill(4)}"

        data = request.data.copy()
        data['employee_id'] = employee_id
        data['user_type'] = "tutor"

        serializer = TrainerSerializer(data=data)

        if serializer.is_valid():
            trainer = serializer.save(status="pending",created_by = "self__signup",created_by_type ="public")

            return Response({
                "success": True,
                "message": "Application submitted successfully",
                "data": serializer.data
            }, status=201)

        return Response({
            "success": False,
            "errors": serializer.errors
        }, status=400)
        
BASE_MEDIA_URL = "https://portal.aryuacademy.com/api/media/"
  
class TrainerListAPIView(LoggingMixin, NotesMixin, APIView):

    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get(self, request):

        try:

            user = request.user
            user_created_id = getattr(user, "trainer_id", None)
            super_admin_id = None
            admin_ids = []

            # ---------------- USER ACCESS ----------------

            if user.user_type == "super_admin":

                user_created_id = getattr(user, "user_id", None)
                super_admin_id = user_created_id

                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_created_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

            elif user.user_type == "admin" and user_created_id:

                super_admin_id = Trainer.objects.filter(
                    trainer_id=user_created_id
                ).values_list("created_by", flat=True).first()

            # ---------------- TRAINERS ----------------

            trainers_qs = Trainer.objects.filter(
                user_type="tutor",
                is_archived=False
            )

            if user.user_type == "super_admin":

                trainers_qs = trainers_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)|
                    Q(created_by_type = "public")
                )

            elif user.user_type == "admin":

                filters = Q(created_by=user_created_id, created_by_type="admin")

                if super_admin_id:
                    filters |= Q(created_by=super_admin_id, created_by_type="super_admin")

                trainers_qs = trainers_qs.filter(filters)

            trainers_qs = trainers_qs.select_related("role").prefetch_related(
                Prefetch(
                    "notes",
                    queryset=Note.objects.all().order_by("-created_at"),
                    to_attr="prefetched_notes"
                )
            ).order_by("-trainer_id")

            # ---------------- PRELOAD BATCH DATA ----------------

            old_batch_map = defaultdict(list)
            new_batch_map = defaultdict(list)

            old_batches = BatchCourseTrainer.objects.filter(
                batch__is_archived=False
            ).select_related(
                "trainer",
                "batch",
                "course__course_category"
            )

            for obj in old_batches:
                old_batch_map[obj.trainer_id].append(obj)

            new_batches = (
                NewBatch.objects.filter(is_archived=False)
                .select_related("course__course_category")
                .prefetch_related("trainers")
            )
            for nb in new_batches:
                for trainer in nb.trainers.all():
                    new_batch_map[trainer.trainer_id].append(nb)

            trainer_data = []

            # ---------------- TRAINER LOOP ----------------

            for t in trainers_qs:

                # -------- Notes --------

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

                batch_ids = []
                titles = []
                course_ids = []
                course_names = []
                category_ids = []
                category_names = []

                course_details = []

                # -------- OLD BATCH --------

                for bct in old_batch_map.get(t.trainer_id, []):

                    course = bct.course
                    category = course.course_category if course else None

                    batch_ids.append(bct.batch.batch_id)
                    titles.append(bct.batch.title or bct.batch.batch_name)

                    if course:
                        course_ids.append(course.course_id)
                        course_names.append(course.course_name)

                    if category:
                        category_ids.append(category.category_id)
                        category_names.append(category.category_name)

                    course_details.append({
                        "course_id": course.course_id if course else None,
                        "course_name": course.course_name if course else None,
                        "batch_id": bct.batch.batch_id,
                        "batch_title": bct.batch.title or bct.batch.batch_name
                    })

                # -------- NEW BATCH --------

                for nb in new_batch_map.get(t.trainer_id, []):

                    course = nb.course
                    category = course.course_category if course else None

                    batch_ids.append(nb.batch_id)
                    titles.append(nb.title)

                    if course:
                        course_ids.append(course.course_id)
                        course_names.append(course.course_name)

                    if category:
                        category_ids.append(category.category_id)
                        category_names.append(category.category_name)

                    course_details.append({
                        "course_id": course.course_id if course else None,
                        "course_name": course.course_name if course else None,
                        "batch_id": nb.batch_id,
                        "batch_title": nb.title
                    })

                batch_ids = list(dict.fromkeys(batch_ids))
                titles = list(dict.fromkeys(titles))
                course_ids = list(dict.fromkeys(course_ids))
                course_names = list(dict.fromkeys(course_names))
                category_ids = list(dict.fromkeys(category_ids))
                category_names = list(dict.fromkeys(category_names))

                # -------- TRAINER FIELDS --------

                trainer_fields = {}

                for field in Trainer._meta.fields:

                    name = field.name

                    if name in ["created_at", "created_by"]:
                        continue

                    value = getattr(t, name)

                    if field.get_internal_type() in ["FileField", "ImageField"]:

                        if value:
                            trainer_fields[name] = BASE_MEDIA_URL + str(value)
                        else:
                            trainer_fields[name] = None

                    else:
                        trainer_fields[name] = value

                trainer_data.append({
                    **trainer_fields,
                    "role": t.role.role_id if t.role else None,
                    "notes": notes,

                    "batch_id": batch_ids,
                    "title": titles,

                    "course_id": course_ids,
                    "course_name": course_names,

                    "category_id": category_ids,
                    "category_name": category_names,

                    "course_details": course_details
                })

            # ---------------- COURSES ----------------

            courses = list(
                Course.objects.filter(
                    is_archived=False,
                    status__iexact="Active"
                ).values(
                    "course_id",
                    "course_name",
                    "course_category"
                )
            )

            for c in courses:
                c["category_id"] = c.pop("course_category")

            # ---------------- CATEGORIES ----------------

            categories = list(
                CourseCategory.objects.filter(
                    is_archived=False,
                    status=True
                ).values(
                    "category_id",
                    "category_name"
                )
            )

            # ---------------- BATCHES ----------------

            batches = list(
                Batch.objects.filter(
                    is_archived=False,
                    status=True
                ).values(
                    "batch_id",
                    "batch_name",
                    "title"
                )
            )

            # ---------------- STUDENTS ----------------

            students = list(
                Student.objects.filter(
                    is_archived=False,
                    status=True
                ).values(
                    "student_id",
                    "registration_id",
                    "first_name",
                    "last_name"
                )
            )

            student_list = [
                {
                    "student_id": s["student_id"],
                    "registration_id": s["registration_id"],
                    "full_name": f'{s["first_name"]} {s["last_name"]}'.strip()
                }
                for s in students
            ]

            # ---------------- ROLES ----------------

            roles = list(
                Role.objects.filter(is_archived=False).values(
                    "role_id",
                    "name"
                )
            )

            return Response({

                "success": True,
                "trainer_data": trainer_data,
                "trainers_count": len(trainer_data),
                "courses": courses,
                "categories": categories,
                "batches": batches,
                "students": student_list,
                "roles": roles

            })

        except Exception as e:

            return Response({

                "success": False,
                "message": str(e)

            })


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
            status = request.data.get("status")
            # ---------- Prevent Duplicate Attendance ----------
            if TrainerAttendance.objects.filter(
                trainer=trainer,
                batch_id=batch_id,
                course=course,
                date__date=scheduled_date.date(),
                status=status
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

            user_created_id = getattr(user, "trainer_id", None)
            if user_type == "super_admin":
                user_created_id = getattr(user, "user_id", None)

            # ---------------------------------------------
            # Admin IDs
            # ---------------------------------------------

            admin_ids = Trainer.objects.filter(
                created_by=user_created_id,
                created_by_type="super_admin",
                is_archived=False
            ).annotate(
                trainer_id_str=Cast("trainer_id", CharField())
            ).values("trainer_id_str")

            # ---------------------------------------------
            # STUDENT LOGS
            # ---------------------------------------------

            student_filter = Q()

            if user_type == "admin":
                student_filter = Q(student__created_by=user_created_id)

            elif user_type == "super_admin":
                student_filter = (
                    Q(student__created_by_type="super_admin", student__created_by=user_created_id)
                    |
                    Q(student__created_by_type="admin", student__created_by__in=Subquery(admin_ids))
                )

            student_logs = Attendance.objects.filter(student_filter).annotate(

                student_name=Concat(
                    F("student__first_name"),
                    Value(" "),
                    F("student__last_name")
                )

            ).values().aggregate(

                logs=JSONBAgg(

                    JSONObject(

                        name=F("student_name"),
                        course=F("course__course_name"),
                        user_type=Value("student", output_field=CharField()),
                        batch=F("batch__batch_name"),
                        title=F("batch__title"),
                        batch_id=F("batch__batch_id"),
                        course_id=F("course__course_id"),
                        status=F("status"),
                        ip=F("ip_address"),
                        date_time=Cast(F("date"), CharField())

                    )

                )

            )["logs"] or []

            # ---------------------------------------------
            # TRAINER LOGS
            # ---------------------------------------------

            trainer_filter = Q()

            if user_type == "admin":
                trainer_filter = Q(trainer__created_by=user_created_id)

            elif user_type == "super_admin":
                trainer_filter = (
                    Q(trainer__created_by_type="super_admin", trainer__created_by=user_created_id)
                    |
                    Q(trainer__created_by_type="admin", trainer__created_by__in=Subquery(admin_ids))
                )

            trainer_logs_raw = TrainerAttendance.objects.filter(
                trainer_filter
            ).annotate(

                prev_time=Window(
                    expression=Lag("date"),
                    partition_by=[F("trainer_id")],
                    order_by=F("date").asc()
                ),

                trainer_name=F("trainer__full_name")

            ).values(

                "trainer_id",
                "trainer_name",
                "course__course_id",
                "course__course_name",
                "topic",
                "sub_topic",
                "status",
                "batch__batch_id",
                "batch__batch_name",
                "batch__title",
                "new_batch__batch_id",
                "new_batch__title",
                date_time=Cast(F("date"), CharField())

            )

            trainer_logs = []

            for row in trainer_logs_raw:

                trainer_logs.append({

                    "trainer_id": row["trainer_id"],
                    "name": row["trainer_name"],
                    "user_type": "trainer",

                    "batch": row["batch__batch_name"] or row["new_batch__title"],
                    "batch_id": row["batch__batch_id"] or row["new_batch__batch_id"],
                    "title": row["batch__title"] or row["new_batch__title"],

                    "course_id": row["course__course_id"],
                    "course": row["course__course_name"],

                    "topic": row["topic"],
                    "sub_topic": row["sub_topic"],

                    "status": row["status"],
                    "date_time": row["date_time"],

                    "total_hours": None

                })

            # ---------------------------------------------
            # MERGE LOGS
            # ---------------------------------------------

            logs = student_logs + trainer_logs

            logs_sorted = sorted(
                logs,
                key=lambda x: x["date_time"],
                reverse=True
            )

            # ---------------------------------------------
            # COURSES
            # ---------------------------------------------

            courses_qs = Course.objects.filter(is_archived=False)

            if user_type == "super_admin":
                courses_qs = courses_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id)
                    |
                    Q(created_by_type="admin", created_by__in=Subquery(admin_ids))
                )

            elif user_type == "admin":
                courses_qs = courses_qs.filter(created_by=user_created_id)

            courses = list(
                courses_qs.values("course_id", "course_name")
            )

            # ---------------------------------------------
            # BATCHES
            # ---------------------------------------------

            old_batches = Batch.objects.filter(
                is_archived=False,
                batchcoursetrainer__course__in=Subquery(courses_qs.values("course_id"))
            ).values(
                "batch_id",
                "batch_name",
                "title"
            ).distinct()

            new_batches = NewBatch.objects.filter(
                is_archived=False,
                status=True,
                course__in=Subquery(courses_qs.values("course_id"))
            ).values(
                "batch_id"
            ).annotate(
                batch_name=F("title"),
                title_val=F("title")
            )

            batches = list(old_batches)

            for nb in new_batches:
                batches.append({
                    "batch_id": nb["batch_id"],
                    "batch_name": nb["batch_name"],
                    "title": nb["title_val"]
                })

            batches = list({b["batch_id"]: b for b in batches}.values())

            # ---------------------------------------------
            # RESPONSE
            # ---------------------------------------------

            return Response({

                "success": True,
                "logs": logs_sorted,
                "course": courses,
                "batch": batches

            })

        except Exception as e:

            return Response({

                "success": False,
                "message": str(e)

            })

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
        try:
            registration_id = request.data.get("registration_id")
            assignment_id = request.data.get("assignment")

            try:
                student = Student.objects.get(
                    registration_id=registration_id,
                    is_archived=False
                )
            except Student.DoesNotExist:
                return Response({
                    "success": False,
                    "message": "Invalid registration ID"
                }, status=status.HTTP_200_OK)

            try:
                assignment = Assignment.objects.get(id=assignment_id)
            except Assignment.DoesNotExist:
                return Response({
                    "success": False,
                    "message": "Invalid assignment ID"
                }, status=status.HTTP_200_OK)

            serializer = self.get_serializer(data=request.data)

            if serializer.is_valid():

                serializer.save(
                    student=student,
                    assignment=assignment
                )

                return Response({
                    "success": True,
                    "message": "Submission created successfully.",
                    "data": serializer.data
                }, status=status.HTTP_201_CREATED)

            return Response({
                "success": False,
                "message": serializer.errors
            }, status=status.HTTP_200_OK)

        except Exception as e:
            print(traceback.format_exc())

            return Response({
                "success": False,
                "message": str(e),
                "traceback": traceback.format_exc()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
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

class StudentBatchRecordingView(APIView):
    def get(self, request, student_id):
        student = Student.objects.get(student_id=student_id)

        recordings = BatchRecording.objects.filter(
            batch__students=student,
            status=True
        ).order_by("-created_at")

        serializer = BatchRecordingSerializer(recordings, many=True)

        return Response(serializer.data)
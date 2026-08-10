from rest_framework import status, viewsets, permissions
from rest_framework.response import Response
from payments.models import PaymentTransaction, PaymentGateway
from rest_framework.permissions import  AllowAny
from .models import ResumeRegistration,Contact,Subscription,PaymentHistory, UserSubscription, UserResume, ResumeTemplate
from rest_framework import permissions
from .serializers import *
from core.views import secure_throttle
from django.contrib.auth.hashers import make_password, check_password
from django.conf import settings
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from rest_framework.views import APIView
import razorpay
import hmac
import hashlib
import uuid
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal
from django.utils import timezone
from rest_framework.decorators import action, api_view,permission_classes
from rest_framework_simplejwt.tokens import RefreshToken
from playwright.async_api import async_playwright
from aryuapp.auth import CustomJWTAuthentication
import asyncio
from django.core.mail import EmailMultiAlternatives
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.shortcuts import redirect
from datetime import timedelta
from django.contrib.auth.hashers import (
    make_password,
    check_password
)
import secrets
import string
import re
from io import BytesIO
from django.http import FileResponse
import logging
from rest_framework.exceptions import ValidationError
from weasyprint import HTML, CSS
from django.db.models import Q
from django.utils.timezone import now
# from celery import shared_task
from collections import defaultdict
import time
import os
import requests
from django.conf import settings
from .tasks import send_verification_email_task
from .pdf_generator import PDFGenerationError, PDFGeneratorService, GeneratePDFSerializer
import traceback

logger = logging.getLogger(__name__)


SIGNING_SALT = "resume-email-verification"


# ==============================================================================
# Helper Functions (Must be defined at the top-level before AuthViewSet)
# ==============================================================================

def build_verification_link(token: str, request=None) -> str:
    """
    Generates a unified email verification link based on environment configuration.
    """
    frontend_url = getattr(settings, "FRONTEND_VERIFY_URL", None)
    if frontend_url:
        return f"{frontend_url.rstrip('/')}/verify-email?token={token}"

    domain = (
        request.build_absolute_uri("/")[:-1]
        if request
        else "https://portal.aryuacademy.com"
    )
    return f"{domain}/api/resume/auth/verify-email/?token={token}"


def get_email_verification_html(first_name: str, verification_link: str) -> str:
    """
    Centralized HTML Email Template for Registration & Resend Email Actions.
    """
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Verify Your PassATS Account</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f5f3ff; font-family: Arial, sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f5f3ff; padding: 40px 15px;">
      <tr>
        <td align="center">
          <table width="620" cellpadding="0" cellspacing="0" border="0" style="background: #ffffff; border-radius: 18px; overflow: hidden; box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);">
            <tr>
              <td align="center" style="background: linear-gradient(135deg, #090116 0%, #090116 50%, #7120e7 100%); padding: 45px 5px;">
                <img src="https://portal.aryuacademy.com/api/media/logos/passats.png" alt="Pass ATS" style="width: 200px; max-width: 90%; height: auto; display: block; margin: 0 auto;" />
                <p style="margin-top: 20px; color: #996ae3; font-size: 16px; font-weight: 600;">Secure Account Verification</p>
              </td>
            </tr>
            <tr>
              <td style="padding: 45px 20px;">
                <h2 style="margin: 0 0 20px 0; font-size: 28px; color: #1e1b4b;">Hello {first_name},</h2>
                <p style="margin: 0 0 20px 0; font-size: 16px; line-height: 30px; color: #475569;">
                  Please verify your email address to activate your PassATS account securely.
                </p>
                <table cellpadding="0" cellspacing="0" border="0" align="center">
                  <tr>
                    <td align="center" style="border-radius: 12px; background: linear-gradient(135deg, #5c20e7, #7120e7);">
                      <a href="{verification_link}" target="_blank" style="display: inline-block; padding: 16px 34px; font-size: 16px; font-weight: 700; color: #ffffff; text-decoration: none; border-radius: 12px;">
                        Verify Email Address
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
</body>
</html>
"""


def process_email_verification(token):
    """
    Validates verification tokens, marks user as verified, and invalidates token.
    """
    if not token:
        return False, {"status": False, "error": "Verification token is required"}, status.HTTP_400_BAD_REQUEST, None

    user = ResumeRegistration.objects.filter(
        email_verification_token=token,
        is_deleted=False
    ).first()

    if not user:
        return False, {"status": False, "error": "Invalid or expired verification token"}, status.HTTP_400_BAD_REQUEST, None

    if user.is_verified and not user.email_verification_token:
        return False, {"status": False, "error": "Verification token has already been used"}, status.HTTP_400_BAD_REQUEST, user

    if user.email_verification_token_expiry and timezone.now() > user.email_verification_token_expiry:
        return False, {"status": False, "error": "Verification token has expired"}, status.HTTP_400_BAD_REQUEST, user

    user.is_verified = True
    user.email_verification_token = None
    user.email_verification_token_expiry = None
    user.save(update_fields=["is_verified", "email_verification_token", "email_verification_token_expiry"])

    return True, {"status": True, "message": "Email verified successfully", "user_id": user.id}, status.HTTP_200_OK, user


class AuthViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    @action(detail=False, methods=["post"], url_path="signup")
    @secure_throttle(rate_limit=5, period=60)
    def signup(self, request):
        serializer = SecureSignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        email = validated_data["email"].strip().lower()
        phone = validated_data["phone"].strip()

        existing_user = ResumeRegistration.objects.filter(email=email, is_deleted=False).first()
        if existing_user:
            if existing_user.is_verified:
                return Response({"error": "Email already registered"}, status=status.HTTP_400_BAD_REQUEST)
            existing_user.delete()

        free_plan = Subscription.objects.filter(name__iexact="Free", is_active=True, is_deleted=False).first()
        if not free_plan:
            return Response(
                {"success": False, "message": "Free subscription plan not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        verification_token = str(uuid.uuid4())
        token_expiry = timezone.now() + timedelta(hours=24)

        user = ResumeRegistration.objects.create(
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
            email=email,
            phone=phone,
            password=make_password(validated_data["password"]),
            city=validated_data["city"],
            state=validated_data["state"],
            country=validated_data["country"],
            is_verified=False,
            email_verification_token=verification_token,
            email_verification_token_expiry=token_expiry,
        )

        start_date = timezone.now()
        duration = str(free_plan.duration_days).strip()
        end_date = None if duration.lower() == "lifetime" else start_date + timedelta(days=int(duration.split()[0]))

        user_subscription = UserSubscription.objects.create(
            user=user,
            subscription=free_plan,
            start_date=start_date,
            end_date=end_date,
            status="active"
        )
        user.current_subscription = user_subscription
        user.save(update_fields=["current_subscription"])

        PaymentHistory.objects.create(user=user, plan_name="Free", price=0, payment_status="free")

        verification_link = build_verification_link(verification_token, request=request)
        subject = f"{user.first_name}, verify your PassATS account"
        body = f"Please verify your account: {verification_link}"
        html_message = get_email_verification_html(user.first_name, verification_link)

        def queue_email():
            try:
                send_verification_email_task.delay(
                    subject, body, html_message, user.email
                )
            except Exception as e:
                logger.error(
                    f"Failed to queue email task for {user.email}: {str(e)}"
                )

        transaction.on_commit(queue_email)

        return Response(
            {"message": "Registration successful. Verification email sent."},
            status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["post"], url_path="resend-verification-email")
    @secure_throttle(rate_limit=3, period=60)
    def resend_verification_email(self, request):
        email = str(request.data.get("email", "")).strip().lower()

        # OWASP Generic Response to prevent user account enumeration
        generic_response = Response(
            {"message": "If an account with that email exists, a verification link has been sent."},
            status=status.HTTP_200_OK
        )

        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = ResumeRegistration.objects.get(email=email, is_deleted=False)
        except ResumeRegistration.DoesNotExist:
            return generic_response

        if user.is_verified:
            return generic_response

        # Generate fresh token & extended 24h expiration
        new_token = str(uuid.uuid4())
        new_expiry = timezone.now() + timedelta(hours=24)

        user.email_verification_token = new_token
        user.email_verification_token_expiry = new_expiry
        user.save(update_fields=["email_verification_token", "email_verification_token_expiry"])

        verification_link = build_verification_link(new_token, request=request)
        subject = f"{user.first_name}, verify your PassATS account"
        body = f"Please verify your account: {verification_link}"
        html_message = get_email_verification_html(user.first_name, verification_link)

        def queue_email():
            try:
                send_verification_email_task.delay(
                    subject, body, html_message, user.email
                )
            except Exception as e:
                logger.error(
                    f"Failed to queue email task for {user.email}: {str(e)}"
                )

        transaction.on_commit(queue_email)

        return generic_response

    @action(detail=False, methods=["get", "post"], url_path="verify-email")
    def verify_email(self, request):
        token = request.GET.get("token") or request.data.get("token")
        success, resp_data, status_code, user = process_email_verification(token)

        if success and getattr(request, 'accepted_renderer', None) and request.accepted_renderer.format == 'html':
            return redirect("https://passats.aryuacademy.com/email-verified")

        return Response(resp_data, status=status_code)
class CustomTokenRefreshView(APIView):
    permission_classes = [AllowAny]
    serializer_class = CustomTokenRefreshSerializer

    def post(self, request, *args, **kwargs):
        # 1. Extract the token directly from the HTTP secure cookie container
        refresh_token = request.COOKIES.get("refresh_token")

        # 2. Hand it off to the serializer mapping dictionary explicitly
        serializer = self.serializer_class(data={"refresh": refresh_token})
        serializer.is_valid(raise_exception=True)
        
        validated_data = serializer.validated_data
        new_refresh_obj = validated_data.get("refresh_token_obj")

        # 3. Create clean baseline response containing ONLY the access token in the body
        response = Response(
            {
                "access_token": validated_data["access_token"]
            },
            status=status.HTTP_200_OK
        )

        origin = request.headers.get("Origin", "")

        LOCAL_ORIGINS = {
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://192.168.0.139:8081",
        }

        if origin in LOCAL_ORIGINS:
            cookie_domain = None
            cookie_secure = False
            cookie_samesite = "None"

        else:
            cookie_domain = ".aryuacademy.com"
            cookie_samesite = "Lax"  # Matches your custom API CNAME architecture setup
            cookie_secure = True

        # 5. Bake the newly rotated refresh token back into the user's browser cookie storage
        if new_refresh_obj:
            response.set_cookie(
                key="refresh_token",
                value=str(new_refresh_obj),
                max_age=30 * 24 * 60 * 60,  # 30 Days
                expires=None,
                path="/api/token/refresh/",
                domain=cookie_domain,
                secure=cookie_secure,
                httponly=True,              # Keeps XSS defense completely locked down
                samesite=cookie_samesite,
            )

        return response



class ResumeRegistrationViewset(viewsets.ModelViewSet):

    serializer_class = ResumeRegistrationSerializers
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [AllowAny]

    def get_queryset(self):
        return ResumeRegistration.objects.filter(
            is_verified=True,
            is_deleted=False
        ).order_by("-id")

    @action(detail=False, methods=["get", "post"], url_path="verify-email")
    def verify_email(self, request):
        """
        Endpoint: /api/resume-registration/verify-email/?token=<TOKEN>
        """
        token = request.GET.get("token") or request.data.get("token")
        if not token:
            return Response(
                {"status": False, "message": "Verification token is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        success, resp_data, status_code, user = process_email_verification(token)
        return Response(resp_data, status=status_code)

    def verify_turnstile_token(self, token: str, client_ip: str = None) -> dict:
        secret_key = getattr(settings, 'TURNSTILE_SECRET_KEY', None)
        if not secret_key:
            return {"success": True, "score": 1.0, "hostname": "localhost"}

        verification_data = {
            "secret": secret_key,
            "response": token,
        }

        try:
            verify_start = time.perf_counter()
            response = requests.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data=verification_data,
                timeout=10
            )
            logger.info(
                f"Cloudflare API call took {time.perf_counter() - verify_start:.4f} seconds"
            )
            return response.json()
        except requests.exceptions.Timeout:
            return {"success": False, "error": "Verification timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @secure_throttle(rate_limit=5, period=60)
    def create(self, request, *args, **kwargs):
        start = time.perf_counter()

        # STEP 1: TURNSTILE VERIFICATION
        client_ip = self.get_client_ip(request)

        if settings.DEBUG or request.data.get("turnstileToken") == "test_pass":
            logger.info("Turnstile verification skipped (DEBUG=True or test_pass token)")
            verification_result = {"success": True, "score": 1.0, "hostname": "localhost"}
        else:
            turnstile_token = request.data.get("turnstileToken")

            if not turnstile_token:
                return Response(
                    {"status": False, "message": "Security verification required."},
                    status=status.HTTP_403_FORBIDDEN
                )

            verification_result = self.verify_turnstile_token(turnstile_token, client_ip)

            if not verification_result.get("success"):
                return Response(
                    {"status": False, "message": "Security check failed. Refresh and try again."},
                    status=status.HTTP_403_FORBIDDEN
                )

            score = verification_result.get("score", 0)
            if score < 0.7:
                return Response(
                    {"status": False, "message": "Suspicious activity detected."},
                    status=status.HTTP_403_FORBIDDEN
                )

            expected_hostnames = ["portal.aryuacademy.com", "localhost", "yourdomain.com"]
            if verification_result.get("hostname") not in expected_hostnames:
                return Response(
                    {"status": False, "message": "Invalid request source."},
                    status=status.HTTP_403_FORBIDDEN
                )

        # STEP 2: REGISTRATION & USER CREATION
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        verification_token = str(uuid.uuid4())
        token_expiry = timezone.now() + timedelta(hours=24)

        registration = serializer.save(
            is_verified=False,
            email_verification_token=verification_token,
            email_verification_token_expiry=token_expiry
        )

        PaymentHistory.objects.create(
            user=registration,
            plan_name="Free",
            price=0,
            payment_status="free"
        )

        # =========================================================
        # FIX 1: DYNAMIC/CORRECT VERIFICATION LINK CONSTRUCTION
        # =========================================================
        # If your frontend handles verification (recommended):
        # verification_link = f"https://portal.aryuacademy.com/verify-email?token={verification_token}"
        
        # If API direct link is used:
        domain = request.build_absolute_uri('/')[:-1] if request else "https://portal.aryuacademy.com"
        verification_link = f"{domain}/api/resume-registration/verify-email/?token={verification_token}"

        subject = f"{registration.first_name}, verify your PassATS account"
        body = f"Please verify your account using this link: {verification_link}"

        html_message = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Verify Your Account</title></head>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    <h2>Hello {registration.first_name},</h2>
    <p>Please click the button below to verify your email address:</p>
    <a href="{verification_link}" style="background-color: #7120e7; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Verify Email Address</a>
    <p>Or copy this link into your browser: <br><a href="{verification_link}">{verification_link}</a></p>
</body>
</html>
"""

        # =========================================================
        # FIX 2: SAFE EMAIL DISPATCH
        # =========================================================
        try:
            if settings.DEBUG:
                # Call task logic directly in debug mode
                send_verification_email(
                    subject, body, html_message, registration.email
                )
            else:
                # Queue through Celery in production
                send_verification_email.delay(
                    subject, body, html_message, registration.email
                )
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")

        logger.info(f"TOTAL API TIME: {time.perf_counter() - start:.4f}s")

        return Response(
            {
                "status": True,
                "message": "Registration successful. Please check your email to verify your account.",
                "data": serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        return x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
    
    
class UserDashboardView(APIView):

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):

        user_id = request.user.id

        try:
            user = ResumeRegistration.objects.select_related(
                'current_subscription__subscription'
            ).get(
                id=user_id,
                is_deleted=False
            )

        except ResumeRegistration.DoesNotExist:

            return Response(
                {"error": "User account not found."},
                status=status.HTTP_404_NOT_FOUND
            )


        # --------------------------------------------
        # GET CURRENT ACTIVE PLAN
        # --------------------------------------------

        current_subscription = UserSubscription.objects.select_related(
            "subscription"
        ).filter(
            user=user,
            status="active"
        ).filter(
            Q(end_date__gt=now()) |
            Q(end_date__isnull=True)
        ).order_by(
            "-id"
        ).first()

        # --------------------------------------------
        # GET LATEST SUBSCRIPTION (ACTIVE OR EXPIRED)
        # --------------------------------------------

        latest_subscription = UserSubscription.objects.select_related(
            "subscription"
        ).filter(
            user=user
        ).order_by(
            "-id"
        ).first()

        # --------------------------------------------
        # PREPARE SUBSCRIPTION DATA
        # --------------------------------------------

        if current_subscription:

            subscription_data = {
                "current_plan": current_subscription.subscription.name,
                "plan_details": DashboardSubscriptionSerializer(
                    current_subscription
                ).data,
                "message": None,
                "is_expired": False
            }

        elif latest_subscription:

            plan_details = DashboardSubscriptionSerializer(
                latest_subscription
            ).data

            plan_details["days_remaining"] = 0

            subscription_data = {
                "current_plan": "",  # Empty because no active plan
                "plan_details": plan_details,  # Last plan details
                "message": "Your subscription has expired. Subscribe to a new plan to continue.",
                "is_expired": True
            }

        else:

            subscription_data = {
                "current_plan": "",
                "plan_details": {},
                "message": "No active subscription found. Please subscribe to a plan.",
                "is_expired": True
            }

        # --------------------------------------------
        # RESUMES
        # --------------------------------------------

        resumes = UserResume.objects.filter(
            user_id=user_id,
            is_deleted=False
        ).select_related(
            'template'
        ).order_by(
            '-updated_at'
        )

        resume_data = DashboardResumeSerializer(
            resumes,
            many=True
        ).data

        resume_count = resumes.count()

        # --------------------------------------------
        # TRANSACTIONS
        # --------------------------------------------

        transactions = UserSubscription.objects.select_related(
            "subscription",
            "payment_transaction"
        ).filter(
            user=user
        ).order_by(
            "subscription__name",
            "-created_at"
        ).distinct(
            "subscription__name"
            )   

        transaction_data = DashboardSubscriptionHistorySerializer(
            transactions,
            many=True
        ).data

        # --------------------------------------------
        # TEMPLATE COUNT
        # --------------------------------------------

        available_templates_count = ResumeTemplate.objects.filter(
            is_active=True,
            is_deleted=False
        ).count()

        # --------------------------------------------
        # RESPONSE
        # --------------------------------------------

        return Response({

            "profile": {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "phone": user.phone,
                "country": user.country,
                "city": user.city,
                "state": user.state
            },

            "subscription": subscription_data,

            "statistics": {
                "total_resumes_created": resume_count,
                "total_transactions": transactions.count(),
                "currently_available_templates": available_templates_count
            },

            "resumes": resume_data,
            "transactions": transaction_data

        }, status=status.HTTP_200_OK)

class ResumePaymentViewSet(viewsets.ViewSet):

    authentication_classes = [CustomJWTAuthentication]

    permission_classes = [permissions.IsAuthenticated]

    def _has_used_free_plan(self, user, subscription):

        return UserSubscription.objects.filter(
            user=user,
            subscription=subscription
        ).exists()

    # =========================================
    # GET RAZORPAY CLIENT
    # =========================================

    def _get_client(self):

        gateway = PaymentGateway.objects.filter(
            gatway_name__icontains="razorpay",
            is_archived=False
        ).first()

        if not gateway:
            return None, None

        client = razorpay.Client(
            auth=(
                gateway.public_key,
                gateway.secret_key
            )
        )

        return client, gateway

    # =========================================
    # CREATE ORDER
    # =========================================

    @secure_throttle(rate_limit=5, period=60)
    @action(
        detail=False,
        methods=["post"],
        url_path="create-order"
    )
    def create_order(self, request):

        subscription_id = request.data.get(
            "subscription_id"
        )

        if not subscription_id:

            return Response(
                {
                    "success": False,
                    "message": "Subscription required"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ==================================================
        # GET SUBSCRIPTION
        # ==================================================

        subscription = get_object_or_404(

            Subscription.objects.only(
                "id",
                "name",
                "slug",
                "price",
                "discount_price",
                "duration_days",
                "is_active",
                "limit"
            ),

            id=subscription_id,
            is_active=True
        )

        # ==================================================
        # PREVENT REBUY ACTIVE PLAN
        # ==================================================

        active_subscription = UserSubscription.objects.filter(
            user_id=request.user.id,
            subscription=subscription,
            status="active"
        ).exists()

        if active_subscription:

            return Response(
                {
                    "success": False,
                    "message": (
                        "You already have an active subscription."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ==================================================
        # FREE PLAN VALIDATION
        # ==================================================

        if subscription.slug == "free":

            already_used = self._has_used_free_plan(
                request.user,
                subscription
            )

            if already_used:

                return Response(
                    {
                        "success": False,
                        "message": (
                            "Free plan already used. "
                            "Please upgrade to continue."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        # ==================================================
        # NEVER TRUST FRONTEND AMOUNT
        # ==================================================

        final_amount = (
            subscription.discount_price
            if subscription.discount_price
            else subscription.price
        )

        final_amount = Decimal(final_amount)

        if final_amount <= 0:

            return Response(
                {
                    "success": False,
                    "message": "Invalid amount"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ==================================================
        # GET RAZORPAY CLIENT
        # ==================================================

        client, gateway = self._get_client()

        if not client:

            return Response(
                {
                    "success": False,
                    "message": "Payment gateway unavailable"
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # ==================================================
        # EXPIRE OLD PENDING TRANSACTIONS
        # ==================================================

        PaymentTransaction.objects.filter(

            resume_registration_id=request.user.id,

            payment_status__in=[
                "created",
                "pending"
            ]

        ).exclude(

            payment_status="done"

        ).update(

            payment_status="expired"
        )

        # ==================================================
        # UNIQUE RECEIPT
        # ==================================================

        receipt = (
            f"resume_"
            f"{request.user.id}_"
            f"{uuid.uuid4().hex[:12]}"
        )

        # ==================================================
        # ALWAYS CREATE NEW ORDER
        # NEVER REUSE OLD RAZORPAY ORDERS
        # ==================================================

        try:

            razorpay_order = client.order.create({

                "amount": int(final_amount * 100),

                "currency": "INR",

                "receipt": receipt,

                "notes": {

                    "user_id": str(request.user.id),

                    "subscription_id": str(subscription.id),

                    "module": "resume"
                }
            })

        except Exception as e:

            logger.exception(
                f"Razorpay order creation failed: {str(e)}"
            )

            return Response(
                {
                    "success": False,
                    "message": (
                        "Unable to create payment order."
                    )
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # ==================================================
        # CREATE TRANSACTION
        # ==================================================

        txn = PaymentTransaction.objects.create(

            resume_registration_id=request.user.id,

            subscription=subscription,

            gateway=gateway,

            amount=final_amount,

            total_after_discount=final_amount,

            currency="INR",

            payment_status="created",

            order_id=razorpay_order["id"],

            description=(
                f"{subscription.name} "
                f"subscription purchase"
            ),

            metadata={

                "subscription_name": subscription.name,

                "duration_days": (
                    subscription.duration_days
                ),

                "razorpay_order_id": (
                    razorpay_order["id"]
                ),

                "receipt": receipt
            }
        )

        # ==================================================
        # SUCCESS RESPONSE
        # ==================================================

        return Response({

            "success": True,

            "message": "Order created successfully",

            "order_id": razorpay_order["id"],

            "transaction_id": txn.id,

            "key": gateway.public_key,

            "amount": int(final_amount * 100),

            "currency": "INR",

            "subscription": {

                "id": subscription.id,

                "name": subscription.name,

                "slug": subscription.slug
            }
        })


    # =========================================
    # VERIFY PAYMENT
    # =========================================

    @secure_throttle(rate_limit=10, period=60)
    @action(
        detail=False,
        methods=["post"],
        url_path="verify-payment"
    )
    def verify_payment(self, request):

        payment_id = request.data.get(
            "razorpay_payment_id"
        )

        order_id = request.data.get(
            "razorpay_order_id"
        )

        signature = request.data.get(
            "razorpay_signature"
        )

        if not all([
            payment_id,
            order_id,
            signature
        ]):

            return Response(
                {
                    "success": False,
                    "message": "Missing payment fields"
                },
                status=400
            )

        gateway = PaymentGateway.objects.filter(
            gatway_name__icontains="razorpay",
            is_archived=False
        ).first()

        if not gateway:

            return Response(
                {
                    "success": False,
                    "message": "Gateway unavailable"
                },
                status=500
            )

        try:

            client = razorpay.Client(
                auth=(
                    gateway.public_key,
                    gateway.secret_key
                )
            )

            client.utility.verify_payment_signature({

                "razorpay_order_id": order_id,

                "razorpay_payment_id": payment_id,

                "razorpay_signature": signature
            })

        except razorpay.errors.SignatureVerificationError:

            return Response(
                {
                    "success": False,
                    "message": "Invalid signature"
                },
                status=400
            )

        # =========================================
        # GET TRANSACTION
        # =========================================

        txn = PaymentTransaction.objects.filter(
            order_id=order_id
        ).select_related(
            "subscription"
        ).first()

        if not txn:

            return Response(
                {
                    "success": False,
                    "message": "Transaction not found"
                },
                status=404
            )

        # =========================================
        # GET ACTUAL USER MODEL
        # =========================================

        user = ResumeRegistration.objects.filter(
            id=request.user.id
        ).first()

        if not user:

            return Response(
                {
                    "success": False,
                    "message": "User not found"
                },
                status=404
            )

        # =========================================
        # UPDATE TRANSACTION
        # =========================================

        txn.payment_status = "done"

        # only if field exists
        # txn.payment_id = payment_id

        txn.save()
        PaymentHistory.objects.create(
            user=user,
            plan_name=txn.subscription.name,  # adjust field name
            price=txn.amount,
            payment_status="done"
        )

        # =========================================
        # EXPIRE OLD ACTIVE SUBSCRIPTIONS
        # =========================================

        UserSubscription.objects.filter(
            user=user,
            status="active"
        ).update(
            status="expired"
        )

        # =========================================
        # CALCULATE END DATE
        # =========================================

        duration_value = str(txn.subscription.duration_days).strip()

        if duration_value.lower() in ["lifetime", "life time"]:
            end_date = None
        else:
            duration = int(
                duration_value
                .replace("Days", "")
                .replace("Day", "")
                .strip()
            )

            end_date = timezone.now() + timedelta(days=duration)

        # =========================================
        # CREATE NEW ACTIVE SUBSCRIPTION
        # =========================================

        new_subscription = UserSubscription.objects.create(
            user=user,
            subscription=txn.subscription,
            payment_transaction=txn,
            status="active",
            start_date=timezone.now(),
            end_date=end_date
        )

        # =========================================
        # UPDATE USER CURRENT PLAN
        # =========================================

        user.current_subscription = new_subscription

        user.save(
            update_fields=["current_subscription"]
        )

        return Response(
            {
                "success": True,
                "message": "Subscription activated successfully",
                "subscription_id": new_subscription.id
            }
        )
    
@csrf_exempt
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def resume_razorpay_webhook(request):

    payload = request.body

    received_signature = request.headers.get(
        "X-Razorpay-Signature"
    )

    if not received_signature:
        return HttpResponse(status=400)

    gateway = PaymentGateway.objects.filter(
        gatway_name__icontains="razorpay",
        is_archived=False
    ).first()

    if not gateway:
        return HttpResponse(status=400)

    expected_signature = hmac.new(

        gateway.webhook_secret.encode(),

        payload,

        hashlib.sha256

    ).hexdigest()

    # =========================================
    # VERIFY WEBHOOK SIGNATURE
    # =========================================

    if not hmac.compare_digest(
        expected_signature,
        received_signature
    ):
        return HttpResponse(status=400)

    data = request.data

    event = data.get("event")

    # =========================================
    # PAYMENT CAPTURED
    # =========================================

    if event == "payment.captured":

        entity = data["payload"]["payment"]["entity"]

        order_id = entity.get("order_id")

        payment_id = entity.get("id")

        amount = (
            Decimal(entity.get("amount")) / 100
        )

        with transaction.atomic():

            txn = PaymentTransaction.objects.select_for_update().filter(
                order_id=order_id
            ).first()

            if not txn:
                return HttpResponse(status=200)

            # =================================
            # PREVENT DUPLICATE PROCESSING
            # =================================

            if txn.payment_status == "done":
                return HttpResponse(status=200)

            # =================================
            # VERIFY AMOUNT
            # =================================

            if amount != txn.amount:

                txn.payment_status = "amount_tampered"

                txn.save(
                    update_fields=["payment_status"]
                )

                return HttpResponse(status=200)

            # =================================
            # SUCCESS
            # =================================

            txn.payment_status = "done"

            txn.transaction_id = payment_id

            txn.payment_mode = "razorpay"

            txn.save()

            # =================================
            # PREVENT DUPLICATE SUBSCRIPTION
            # =================================

            already_exists = UserSubscription.objects.filter(
                payment_transaction=txn
            ).exists()

            if not already_exists:

                start_date = timezone.now()

                end_date = None

                if not txn.subscription.is_lifetime:

                    end_date = (
                        start_date +
                        timedelta(
                            days=txn.subscription.duration_days
                        )
                    )

                user_subscription = UserSubscription.objects.create(

                    user=txn.resume_registration,

                    subscription=txn.subscription,

                    payment_transaction=txn,

                    start_date=start_date,

                    end_date=end_date,

                    is_lifetime=txn.subscription.is_lifetime,

                    status="active"
                )

                txn.resume_registration.current_subscription = (
                    user_subscription
                )

                txn.resume_registration.save(
                    update_fields=["current_subscription"]
                )

    # =========================================
    # PAYMENT FAILED
    # =========================================

    elif event == "payment.failed":

        entity = data["payload"]["payment"]["entity"]

        order_id = entity.get("order_id")

        PaymentTransaction.objects.filter(
            order_id=order_id
        ).exclude(
            payment_status="done"
        ).update(
            payment_status="failed"
        )

    return HttpResponse(status=200)

class SubscriptionService:

    @staticmethod
    def can_parse_resume(user):

        db_user = ResumeRegistration.objects.select_related(
            "current_subscription",
            "current_subscription__subscription",
        ).get(id=user.id)

        subscription = db_user.current_subscription

        if not subscription:
            return False, "No subscription"

        if subscription.end_date and subscription.end_date < timezone.now():
            return False, "Subscription expired"

        limit = subscription.subscription.resume_parse_limit

        if subscription.parse_used >= limit:
            return False, "Resume parsing limit exceeded"

        return True, subscription


    @staticmethod
    def can_run_ats(user):

        db_user = ResumeRegistration.objects.select_related(
            "current_subscription",
            "current_subscription__subscription",
        ).get(id=user.id)
        print(db_user)
        subscription = db_user.current_subscription

        if not subscription:
            return False, "No subscription"

        if subscription.end_date and subscription.end_date < timezone.now():
            return False, "Subscription expired"

        limit = subscription.subscription.ats_scan_limit

        if subscription.ats_used >= limit:
            return False, "ATS Scan limit exceeded"

        return True, subscription


    @staticmethod
    def increase_parse_count(subscription):
        subscription.parse_used += 1
        subscription.save(update_fields=["parse_used"])


    @staticmethod
    def increase_ats_count(subscription):
        subscription.ats_used += 1
        subscription.save(update_fields=["ats_used"])


class SubscriptionViewSet(viewsets.ViewSet):

    permission_classes = [permissions.IsAuthenticated]

    authentication_classes = [CustomJWTAuthentication]

    @secure_throttle(rate_limit=20, period=60)
    @action(detail=False,methods=["get"],url_path="plans")
    def plans(self, request):

        subscriptions = Subscription.objects.filter(
            is_active=True
        ).order_by("order")

        serializer = SubscriptionSerializer(
            subscriptions,
            many=True
        )

        return Response(
            {
                "success": True,
                "plans": serializer.data
            },
            status=status.HTTP_200_OK
        )


    @secure_throttle(rate_limit=20, period=60)
    @action(detail=False,methods=["get"],url_path="my-subscription")
    def my_subscription(self, request):

        if not request.user.is_authenticated:

            return Response(
                {
                    "success": False,
                    "message": "Authentication required"
                },
                status=status.HTTP_401_UNAUTHORIZED
            )

        current_subscription = UserSubscription.objects.select_related(
            "subscription"
        ).filter(
            user_id=request.user.id,
            status="active"
        ).order_by("-id").first()

        if not current_subscription:

            return Response(
                {
                    "success": True,
                    "subscription": None
                },
                status=status.HTTP_200_OK
            )

        if (
            current_subscription.end_date
            and timezone.now() >
            current_subscription.end_date
        ):

            current_subscription.status = "expired"

            current_subscription.save(
                update_fields=["status"]
            )

            current_subscription.user.current_subscription = None

            current_subscription.user.save(
                update_fields=["current_subscription"]
            )

            return Response(
                {
                    "success": True,
                    "subscription": None,
                    "message": "Subscription expired"
                },
                status=status.HTTP_200_OK
            )

        serializer = UserSubscriptionSerializer(
            current_subscription
        )

        return Response(
            {
                "success": True,
                "subscription": serializer.data
            },
            status=status.HTTP_200_OK
        )

    @secure_throttle(rate_limit=20, period=60)
    @action(detail=False,methods=["get"],url_path="subscription-history")
    def subscription_history(self, request):

        if not request.user.is_authenticated:

            return Response(
                {
                    "success": False,
                    "message": "Authentication required"
                },
                status=status.HTTP_401_UNAUTHORIZED
            )

        subscriptions = UserSubscription.objects.select_related(
            "subscription"
        ).filter(
            user_id=request.user.id
        ).order_by("-id")

        serializer = UserSubscriptionSerializer(
            subscriptions,
            many=True
        )

        return Response(
            {
                "success": True,
                "subscriptions": serializer.data
            },
            status=status.HTTP_200_OK
        ) 
    
    def _is_admin(self, request):

        return request.user.user_type in [
            "admin",
            "super_admin"
        ]

    @secure_throttle(rate_limit=10, period=60)
    @action(detail=False,methods=["post"],url_path="create-plan")
    def create_plan(self, request):
        if not self._is_admin(request):

            return Response(
                {
                    "success": False,
                    "message": "Permission denied"
                },
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = SubscriptionSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        validated_data = serializer.validated_data

        if (
            validated_data.get("price", 0) < 0
        ):

            return Response(
                {
                    "success": False,
                    "message": "Invalid price"
                },
                status=400
            )

        if (
            validated_data.get(
                "discount_price"
            )
            and
            validated_data["discount_price"]
            >
            validated_data["price"]
        ):

            return Response(
                {
                    "success": False,
                    "message":
                    "Discount price cannot exceed price"
                },
                status=400
            )

        subscription = Subscription.objects.create(
            name=validated_data["name"],
            slug=validated_data["slug"],
            description=validated_data.get("description"),
            price=validated_data["price"],
            discount_price=validated_data.get("discount_price"),
            billing_type=validated_data["billing_type"],
            duration_days=validated_data["duration_days"],
            limit=validated_data.get("limit", "free"),
            order=validated_data.get("order", 0),
            is_active=validated_data.get("is_active", True),
        )

        if not validated_data.get("order"):
            subscription.order = subscription.id
            subscription.save(update_fields=["order"])

        response_serializer = SubscriptionSerializer(
            subscription
        )

        return Response(
            {
                "success": True,
                "message":
                "Subscription plan created successfully",
                "plan": response_serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    @secure_throttle(rate_limit=10, period=60)
    @action(detail=False,methods=["patch"],url_path="update-plan/(?P<plan_id>[^/.]+)")
    def update_plan(self, request, plan_id=None):

        if not self._is_admin(request):

            return Response(
                {
                    "success": False,
                    "message": "Permission denied"
                },
                status=status.HTTP_403_FORBIDDEN
            )

        subscription = get_object_or_404(
            Subscription,
            id=plan_id
        )

        serializer = SubscriptionSerializer(
            subscription,
            data=request.data,
            partial=True
        )

        serializer.is_valid(
            raise_exception=True
        )

        validated_data = serializer.validated_data

        new_price = validated_data.get(
            "price",
            subscription.price
        )

        new_discount_price = validated_data.get(
            "discount_price",
            subscription.discount_price
        )

        if new_price < 0:

            return Response(
                {
                    "success": False,
                    "message": "Invalid price"
                },
                status=400
            )

        if (
            new_discount_price
            and
            new_discount_price > new_price
        ):

            return Response(
                {
                    "success": False,
                    "message":
                    "Discount price cannot exceed price"
                },
                status=400
            )

        allowed_fields = [

            "name",

            "slug",

            "description",

            "price",

            "discount_price",

            "billing_type",

            "duration_days",

            "limit",

            "order",

            "is_active"
        ]

        for field in allowed_fields:

            if field in validated_data:

                setattr(
                    subscription,
                    field,
                    validated_data[field]
                )

        subscription.save()

        response_serializer = SubscriptionSerializer(
            subscription
        )

        return Response(
            {
                "success": True,
                "message":
                "Subscription updated successfully",
                "plan": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @secure_throttle(rate_limit=10, period=60)
    @action(detail=False,methods=["patch"],url_path="delete-plan/(?P<plan_id>[^/.]+)")
    def delete_plan(self, request, plan_id=None):

        if not self._is_admin(request):

            return Response(
                {
                    "success": False,
                    "message": "Permission denied"
                },
                status=status.HTTP_403_FORBIDDEN
            )

        subscription = get_object_or_404(
            Subscription,
            id=plan_id
        )

        # =====================================
        # SOFT DELETE
        # =====================================

        subscription.is_active = False

        subscription.save(
            update_fields=["is_active"]
        )

        return Response(
            {
                "success": True,
                "message":
                "Subscription deleted successfully"
            },
            status=status.HTTP_200_OK
        )

import requests

class ResumeGateway(APIView):

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):

        allowed, subscription = SubscriptionService.can_parse_resume(
            request.user
        )

        if not allowed:
            return Response(
                {
                    "success": False,
                    "message": subscription
                },
                status=403
            )

        file = request.FILES["file"]

        files = {
            "file": (
                file.name,
                file.file,
                file.content_type
            )
        }

        data = {}

        for key, value in request.data.items():
            if key != "file":
                data[key] = value

        response = requests.post(
            f"{settings.FASTAPI_URL}/api/v1/resume/parse-resume",
            files=files,
            data=data,
            timeout=120
        )
        print("response",response)

        if response.ok:
            SubscriptionService.increment_parse(subscription)

        return HttpResponse(
            response.content,
            status=response.status_code,
            content_type=response.headers.get(
                "Content-Type",
                "application/json"
            )
        )
    
class ATSGateway(APIView):

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):

        allowed, subscription = SubscriptionService.can_run_ats(
            request.user
        )
        print('allowed', allowed)

        if not allowed:
            return Response(
                {
                    "success": False,
                    "message": subscription
                },
                status=status.HTTP_403_FORBIDDEN
            )

        if "file" not in request.FILES:
            return Response(
                {
                    "success": False,
                    "message": "File is required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        uploaded_file = request.FILES["file"]

        files = {
            "file": (
                uploaded_file.name,
                uploaded_file.file,
                uploaded_file.content_type,
            )
        }

        data = {}

        for key, value in request.data.items():
            if key != "file":
                data[key] = value

        try:
            logger.info(f'data: {data}')

            url = f"{settings.FASTAPI_URL}/api/v1/ats/scan-file"

            logger.info(f'url: {url}')

            response = requests.post(
                url,
                files=files,
                data=data,
                timeout=180,
            )
            logger.info(response.status_code)
            logger.info(response.text)

            if response.ok:
                SubscriptionService.increase_ats_count(
                    subscription
                )

            return HttpResponse(
                response.content,
                status=response.status_code,
                content_type=response.headers.get(
                    "Content-Type",
                    "application/json",
                ),
            )

        except requests.Timeout:
            return Response(
                {
                    "success": False,
                    "message": "ATS service timeout."
                },
                status=status.HTTP_504_GATEWAY_TIMEOUT
            )

        except requests.RequestException:
            return Response(
                {
                    "success": False,
                    "message": "ATS service unavailable."
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
    

class PublicSubscriptionPlansViewSet(viewsets.ViewSet):

    permission_classes = [AllowAny]
    authentication_classes = []

    # LIST
    @secure_throttle(rate_limit=20, period=60)
    def list(self, request):

        subscriptions = Subscription.objects.filter(
            is_active=True
        ).order_by("order")

        serializer = SubscriptionSerializer(
            subscriptions,
            many=True
        )

        return Response(
            {
                "success": True,
                "plans": serializer.data
            },
            status=status.HTTP_200_OK
        )

    # CREATE
    @secure_throttle(rate_limit=10, period=60)
    def create(self, request):

        serializer = SubscriptionSerializer(
            data=request.data
        )

        if serializer.is_valid():

            serializer.save()

            return Response(
                {
                    "success": True,
                    "message": "Subscription created successfully",
                    "plan": serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        return Response(
            {
                "success": False,
                "errors": serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # UPDATE
    @secure_throttle(rate_limit=10, period=60)
    def update(self, request, pk=None):

            subscription = get_object_or_404(
                Subscription,
                id=pk
            )

            serializer = SubscriptionSerializer(
                subscription,
                data=request.data,
                partial=True
            )

            if serializer.is_valid():
                serializer.save()

                return Response(
                    {
                        "success": True,
                        "message": "Subscription updated successfully",
                        "plan": serializer.data
                    },
                    status=status.HTTP_200_OK
                )

            return Response(
                {
                    "success": False,
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )
    # DELETE
    @secure_throttle(rate_limit=10, period=60)
    def destroy(self, request, pk=None):

        subscription = get_object_or_404(
            Subscription,
            id=pk
        )

        subscription.delete()

        return Response(
            {
                "success": True,
                "message": "Subscription deleted successfully"
            },
            status=status.HTTP_200_OK
        )


class ResumeTransactionViewSet(viewsets.ViewSet):

    def list(self, request):

        user = request.user

        allowed_types = ["super_admin", "admin"]

        if user.user_type not in allowed_types:
            return Response({
                "success": False,
                "message": "Unable to process request."
            }, status=status.HTTP_403_FORBIDDEN)

        queryset = (
            PaymentTransaction.objects
            .filter(
                resume_registration__isnull=False,
                is_archived=False
            )
            .select_related(
                "resume_registration",
                "subscription"
            )
            .only(
                "transaction_id",
                "amount",
                "payment_status",
                "created_at",

                "resume_registration__first_name",
                "resume_registration__last_name",
                "resume_registration__email",

                "subscription__name",
            )
            .order_by("-created_at")
        )

        data = [
            {
                "first_name": obj.resume_registration.first_name,
                "last_name": obj.resume_registration.last_name,
                "email": obj.resume_registration.email,

                "transaction_id": obj.transaction_id,

                "plan": (
                    obj.subscription.name
                    if obj.subscription
                    else None
                ),

                "status": obj.payment_status,

                "amount": obj.amount,

                "date": obj.created_at,
            }
            for obj in queryset
        ]

        return Response(
            {
                "count": queryset.count(),
                "results": data
            },
            status=status.HTTP_200_OK
        )

class ResumeTemplateViewSet(viewsets.ViewSet):
    """
    Secure, read-only blueprint distribution hub optimized for performance 
    and engineered to meet core OWASP secure access guidelines.
    """
    # Enforce global authentication barrier to prevent API enumeration scanning
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = CustomJWTAuthentication
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        """
        Enforces defensive data isolation. Soft-deleted and inactive blueprints 
        are stripped entirely at the database level before any processing.
        """
        return ResumeTemplate.objects.filter(is_active=True, is_deleted=False)
    
    def get_permissions(self):
        """
        OWASP Security Boundary Enforcement:
        - Safe read actions are open to any Authenticated user.
        - Destructive/Write actions (including create) are locked strictly to Staff.
        """
        if self.action in ['list', 'retrieve', 'verify_access']:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]

    def create(self, request):
        """
        POST /api/templates
        Allows Staff/Admin users to provision a new resume template blueprint.
        """
        # We use the detailed serializer because creating a template requires 
        # specifying its layout 'structure' and 'html_markup'.
        serializer = ResumeTemplateDetailSerializer(data=request.data)
        
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "message": "Resume template created successfully.",
                    "data": serializer.data
                }, 
                status=status.HTTP_201_CREATED
            )
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def list(self, request):
        """
        GET /api/templates
        Returns lightweight representations of active layouts optimized for gallery discovery.
        """
        # Context optimization: Apply optional query parameters for tier sorting if needed
        tier_filter = request.query_params.get('tier')
        queryset = self.get_queryset()
        
        if tier_filter:
            queryset = queryset.filter(tier=tier_filter)

        # Uses the lightweight listing serializer
        serializer = ResumeTemplateListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def retrieve(self, request, pk=None):
        """
        GET /api/templates/{id}
        Returns the deep metadata structures and markup of a layout.
        """
        # Safe lookup preventing arbitrary database probing
        template = get_object_or_404(self.get_queryset(), pk=pk)
        
        # Security Boundary: Validate eligibility before exposing proprietary layout structures
        is_accessible, current_tier = self._verify_tier_access(request.user, template)
        
        if not is_accessible:
            return Response(
                {
                    "error": "Access Denied",
                    "message": f"This premium asset requires a '{template.tier}' subscription. Your account is on '{current_tier}'."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # Uses the detail serializer containing heavy layout payloads
        serializer = ResumeTemplateDetailSerializer(template)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def update(self, request, pk=None):
        """
        PUT/PATCH /api/templates/{id}
        Handles both full overrides (PUT) and partial tweaks (PATCH).
        Locked to Staff/Admin users only.
        """
        # Admins can modify even inactive/soft-deleted templates if needed, 
        # so we bypass the standard filtered queryset for updates.
        template = get_object_or_404(ResumeTemplate.objects.all(), pk=pk)
        
        # Determine if this is a partial update (PATCH) or full update (PUT)
        partial = request.method == 'PATCH'
        
        serializer = ResumeTemplateDetailSerializer(template, data=request.data, partial=partial)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):

        template = get_object_or_404(ResumeTemplate.objects.all(), pk=pk)
        
        if template.is_deleted:
            return Response(
                {"message": "Template has already been deleted."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Perform soft-delete and make it inactive
        template.is_deleted = True
        template.is_active = False
        template.save(update_fields=['is_deleted', 'is_active'])
        
        return Response(
            {"message": "Template successfully soft-deleted and removed from active listings."}, 
            status=status.HTTP_204_NO_CONTENT
        )

    @action(detail=True, methods=['get'], url_path='verify-access')
    def verify_access(self, request, pk=None):
        """
        GET /api/templates/{id}/verify-access
        Lightweight gateway check enabling frontends to preemptively toggle 'Unlock' interfaces
        without running resource-intensive full detail payloads.
        """
        template = get_object_or_404(self.get_queryset(), pk=pk)
        is_accessible, current_tier = self._verify_tier_access(request.user, template)
        
        return Response({
            "template_id": template.id,
            "has_access": is_accessible,
            "user_current_tier": current_tier,
            "required_tier": template.tier
        }, status=status.HTTP_200_OK)

    def _verify_tier_access(self, user, template) -> tuple[bool, str]:
        """
        Private core authorization engine enforcing server-side gatekeeping.
        Safeguards against parameter tampering across subscription boundary layers.
        """
        # Safely fall back to free tier metrics if relationship queries resolve empty
        user_subscription = getattr(user, 'current_subscription', None)
        
        # A user's tier is only valid if active
        if user_subscription and user_subscription.status == 'active':
            user_tier = user_subscription.subscription.limit.lower()
        else:
            user_tier = 'free'

        # Relative access level weight system 
        tier_authority = {'free': 1, 'pro': 2, 'premium': 3}
        
        user_weight = tier_authority.get(user_tier, 1)
        template_weight = tier_authority.get(template.tier.lower(), 1)

        return user_weight >= template_weight, user_tier

class UserResumeViewSet(viewsets.ViewSet):
    """
    Highly optimized ViewSet for creating and incrementally updating 
    single-row JSON document resumes.
    """
    # Restrict endpoint strictly to authenticated users
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Optimized queryset leveraging select_related to avoid N+1 queries 
        when fetching template and user details.
        """
        return UserResume.objects.filter(user_id=self.request.user.id).select_related(
            'template', 
            'user__current_subscription__subscription'
        ).order_by("-created_at")

    def list(self, request):
        """
        GET /api/resumes/
        List all resumes for the authenticated user.
        """
        queryset = self.get_queryset()
        serializer = UserResumeSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def retrieve(self, request, pk=None):
        """
        GET /api/resumes/{id}/
        Retrieve a specific resume document.
        """
        resume = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = UserResumeSerializer(resume)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request):
        """
        POST /api/resumes/
        Step 1: First-time initialization (e.g., Personal Details step).
        Creates the single permanent database row for this resume.
        """
        # 1. Enforce Subscription Tier Restrictions Securely
        template_id = request.data.get('template')
        if template_id:
            template = get_object_or_404(ResumeTemplate, id=template_id, is_active=True)
            
            # Extract user's active limits
            user_sub = UserSubscription.objects.filter(
                user_id=request.user.id,
                status="active"
            ).select_related("subscription").first()
            user_tier = user_sub.subscription.limit if (user_sub and user_sub.status == 'active') else 'free'
            
            # Simple fallback validation logic hierarchy
            tier_weights = {'free': 1, 'pro': 2, 'premium': 3}
            if tier_weights.get(template.tier, 1) > tier_weights.get(user_tier, 1):
                return Response(
                    {"error": f"This template requires a {template.tier} subscription tier."},
                    status=status.HTTP_403_FORBIDDEN
                )

        # 2. Extract context data for validation
        serializer = UserResumeSerializer(data=request.data)
        if serializer.is_valid():

            resume_user = get_object_or_404(
                ResumeRegistration,
                id=request.user.id
            )

            serializer.save(user=resume_user)

            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['patch'], url_path='update-section')
    def update_section(self, request, pk=None):
        """
        PATCH /api/resumes/{id}/update-section/
        Step 2+: Incremental structural update to add or modify a specific section
        without touching or rewriting other keys inside the JSONField.
        """
        resume = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = IncrementalSectionUpdateSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        section_name = serializer.validated_data['section_name']
        section_payload = serializer.validated_data['section_payload']
        is_completed_flag = serializer.validated_data.get('is_completed', False)

        # Concurrency Protection: Wrap in database atomic transaction block
        with transaction.atomic():
            # Lock the target database row for the duration of this specific patch operation
            resume = UserResume.objects.select_for_update().get(pk=resume.pk)
            
            # Efficient internal initialization/mutation mapping
            if not isinstance(resume.resume_data, dict):
                resume.resume_data = {}

            # Append, insert, or overwrite just this explicit section element payload
            resume.resume_data[section_name] = section_payload
            
            # Update general management state metadata
            resume.last_completed_section = section_name
            resume.is_completed = is_completed_flag
            
            # Save strictly targeted fields to avoid broad table write overhead locks
            resume.save(update_fields=['resume_data', 'last_completed_section', 'is_completed', 'updated_at'])

        # Return full updated representation payload 
        return Response(UserResumeSerializer(resume).data, status=status.HTTP_200_OK)

    def update(self, request, pk=None):
        """
        PUT /api/resumes/{id}/
        Complete override update structure backup interface.
        """
        resume = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = UserResumeSerializer(resume, data=request.data, partial=False)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        """
        DELETE /api/resumes/{id}/
        Standard deletion cycle cleanup handling.
        """
        resume = get_object_or_404(self.get_queryset(), pk=pk)
        resume.is_deleted = True
        resume.save(update_fields=['is_deleted'])
        return Response({"message": "Resume permanently deleted successfully."}, status=status.HTTP_204_NO_CONTENT)

class ContactViewset(viewsets.ModelViewSet):

    queryset = Contact.objects.all().order_by("-id")
    serializer_class = ContactSerializers
    permission_classes = [AllowAny]
    authentication_classes = []
    #List
    def list(self, request, *args, **kwargs):
        user = request.user

        allowed_types = ["super_admin", "admin"]

        if user.user_type not in allowed_types:
            return Response({
                "success": False,
                "message": "Unable to process request."
            }, status=status.HTTP_403_FORBIDDEN)

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        return Response(
            {
                "status": True,
                "message": "Contact list",
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )
  
    # CREATE
    def create(self, request, *args, **kwargs):
        user = request.user

        allowed_types = ["super_admin", "admin"]

        if user.user_type not in allowed_types:
            return Response({
                "success": False,
                "message": "Unable to process request."
            }, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)

        if serializer.is_valid():
            serializer.save()

            return Response(
                {
                    "status": True,
                    "message": "Subscription created successfully",
                    "data": serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        return Response(
            {
                "status": False,
                "message": "Validation error",
                "errors": serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    # DELETE
    def destroy(self, request, *args, **kwargs):
        user = request.user

        allowed_types = ["super_admin", "admin"]

        if user.user_type not in allowed_types:
            return Response({
                "success": False,
                "message": "Unable to process request."
            }, status=status.HTTP_403_FORBIDDEN)

        instance = self.get_object()
        instance.delete()

        return Response(
            {
                "status": True,
                "message": "Contact deleted successfully"
            },
            status=status.HTTP_200_OK
        )
    
class PaymentHistoryViewset(viewsets.ModelViewSet):
    queryset = PaymentHistory.objects.select_related(
        "user"
    ).order_by("-id")

    serializer_class = PaymentHistorySerializers

   

    def list(self, request, *args, **kwargs):

        user = request.user

        allowed_types = ["super_admin", "admin"]

        if user.user_type not in allowed_types:
            return Response(
                {
                    "success": False,
                    "message": "Unable to process request."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        queryset = self.get_queryset()

        grouped_data = defaultdict(list)

        for item in queryset:

            grouped_data[item.user.id].append({
                "id": item.id,
                "plan_name": item.plan_name,
                "price": str(item.price),
                "payment_status": item.payment_status,
                "created_at": item.created_at
            })

        response_data = []

        for user_id, transactions in grouped_data.items():

            user_obj = ResumeRegistration.objects.get(id=user_id)

            response_data.append({
                "user_id": user_id,
                "user_name": f"{user_obj.first_name} {user_obj.last_name}",
                "transactions": transactions
            })

        return Response(
            {
                "status": True,
                "message": "Payment history list",
                "data": response_data
            },
            status=status.HTTP_200_OK
        )
    
class GenerateResumePDFView(APIView):
 
    parser_classes = [JSONParser]
    permission_classes = [permissions.IsAuthenticated]
 
    def post(self, request) -> HttpResponse:
        serializer = GeneratePDFSerializer(data=request.data)
        if not serializer.is_valid():
            return HttpResponse(
                content=serializer.errors,
                content_type="application/json",
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        html_content: str = serializer.validated_data["html"]
 
        t_start = time.perf_counter()
        try:
            service = PDFGeneratorService()
            pdf_bytes = service.generate_pdf(html_content)
        except PDFGenerationError as exc:
            logger.error(
                "PDF generation error for user %s: %s",
                getattr(request.user, "pk", "anonymous"),
                exc,
            )
            return HttpResponse(
                content={"detail": str(exc)},
                content_type="application/json",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.exception(
                "Unexpected PDF generation failure for user %s",
                getattr(request.user, "pk", "anonymous"),
            )
            return HttpResponse(
                content={"detail": "An unexpected error occurred while generating the PDF."},
                content_type="application/json",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        finally:
            elapsed = time.perf_counter() - t_start
            logger.info(
                "PDF generation completed in %.2fs for user %s",
                elapsed,
                getattr(request.user, "pk", "anonymous"),
            )
 
        response = HttpResponse(
            content=pdf_bytes,
            content_type="application/pdf",
            status=status.HTTP_200_OK,
        )
        response["Content-Disposition"] = 'attachment; filename="resume.pdf"'
        response["Content-Length"] = len(pdf_bytes)
        # Prevent CDN/proxy caching of personal resumes
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["X-Content-Type-Options"] = "nosniff"
        return response
        

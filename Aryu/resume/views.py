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
import io
import logging
from rest_framework.exceptions import ValidationError
from weasyprint import HTML, CSS

logger = logging.getLogger(__name__)


SIGNING_SALT = "resume-email-verification"


class AuthViewSet(viewsets.ViewSet):

    permission_classes = [AllowAny]

    # =========================
    # VALIDATORS
    # =========================

    def validate_password(self, password):

        if len(password) < 8:
            return "Password must be minimum 8 characters"

        if not re.search(r"[A-Z]", password):
            return "Password must contain one uppercase letter"

        if not re.search(r"[a-z]", password):
            return "Password must contain one lowercase letter"

        if not re.search(r"[0-9]", password):
            return "Password must contain one number"

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return "Password must contain one special character"

        return None

    # =========================
    # SIGNUP
    # =========================

    @transaction.atomic
    @action(detail=False, methods=["post"], url_path="signup")
    @secure_throttle(rate_limit=5, period=60)
    def signup(self, request):

        data = request.data

        email = str(data.get("email", "")).strip().lower()
        phone = str(data.get("phone", "")).strip()

        if not email:
            return Response(
                {"error": "Email is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not data.get("password"):
            return Response(
                {"error": "Password is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        password_error = self.validate_password(data["password"])

        if password_error:
            return Response(
                {"error": password_error},
                status=status.HTTP_400_BAD_REQUEST
            )

        # prevent duplicate account
        if ResumeRegistration.objects.filter(email=email).exists():
            return Response(
                {"error": "Email already registered"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # hash password
        hashed_password = make_password(data["password"])

        user = ResumeRegistration.objects.create(
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            email=email,
            phone=phone,
            password=hashed_password,
            city=data.get("city"),
            state=data.get("state"),
            country=data.get("country"),
            is_verified=False,
        )
        free_plan = Subscription.objects.get(
            name="free",
            is_active=True,
            is_deleted=False
        )

        start_date = timezone.now()

        duration = str(free_plan.duration_days).strip()

        if duration.lower() == "lifetime":
            end_date = None
        else:
            days = int(duration.split()[0])
            end_date = start_date + timedelta(days=days)

        user_subscription = UserSubscription.objects.create(

            user=user,

            subscription=free_plan,

            start_date=start_date,

            end_date=end_date,

            status="active"
        )

        user_subscription = UserSubscription.objects.create(

            user=user,

            subscription=free_plan,

            start_date=start_date,

            end_date=end_date,

            status="active"
        )

        user.current_subscription = user_subscription

        user.save(update_fields=["current_subscription"])

        token = signing.dumps(
            {
                "user_id": user.id,
                "email": user.email
            },
            salt=SIGNING_SALT
        )

        verification_link = (
            "https://aylms.aryuprojects.com"
            f"/api/resume/auth/verify-email/?token={token}"
        )

        html_message = f"""
<!DOCTYPE html>
<html lang="en">

<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Verify Your Pass ATS Account</title>
</head>

<body
    style="
      margin: 0;
      padding: 0;
      background-color: #f5f3ff;
      font-family: Arial, sans-serif;
    ">
    <table
      width="100%"
      cellpadding="0"
      cellspacing="0"
      border="0"
      style="background-color: #f5f3ff; padding: 40px 15px">
      <tr>
        <td align="center">
          <table
            width="620"
            cellpadding="0"
            cellspacing="0"
            border="0"
            style="
              background: #ffffff;
              border-radius: 18px;
              overflow: hidden;
              box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
            ">
            <!-- HEADER -->
            <tr>
              <td
                align="center"
                style="
                  background: linear-gradient(
                    135deg,
                    #090116 0%,
                    #090116 50%,
                    #7120e7 100%
                  );
                  padding: 45px 5px;
                ">
                <img
                  src="https://aylms.aryuprojects.com/api/media/logos/passats.png"
                  alt="Pass ATS"
                  style="
                    width: 200px;
                    max-width: 90%;
                    height: auto;
                    display: block;
                    margin: 0 auto;
                  " />

                <p
                  style="
                    margin-top: 20px;
                    color: #996ae3;
                    font-size: 16px;
                    line-height: 26px;
                    font-weight: 600;
                  ">
                  Secure Account Verification
                </p>
              </td>
            </tr>

            <!-- CONTENT -->
            <tr>
              <td style="padding: 45px 20px">
                <h2
                  style="
                    margin: 0 0 20px 0;
                    font-size: 28px;
                    color: #1e1b4b;
                    font-weight: 700;
                  ">
                  Hello {user.first_name},
                </h2>

                <p
                  style="
                    margin: 0 0 20px 0;
                    font-size: 16px;
                    line-height: 30px;
                    color: #475569;
                  ">
                  Thank you for creating your Pass ATS account. Please verify
                  your email address to activate your account securely.
                </p>

                <p
                  style="
                    margin: 0 0 35px 0;
                    font-size: 16px;
                    line-height: 30px;
                    color: #475569;
                  ">
                  This verification link is secure and expires automatically.
                </p>

                <!-- BUTTON -->
                <table
                  cellpadding="0"
                  cellspacing="0"
                  border="0"
                  align="center">
                  <tr>
                    <td
                      align="center"
                      style="
                        border-radius: 12px;
                        background: linear-gradient(135deg, #5c20e7, #7120e7);
                      ">
                      <a
                        href="{verification_link}"
                        target="_blank"
                        style="
                          display: inline-block;
                          padding: 16px 34px;
                          font-size: 16px;
                          font-weight: 700;
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 12px;
                        ">
                        Verify Email Address
                      </a>
                    </td>
                  </tr>
                </table>

                <!-- NOTICE -->
                <table
                  width="100%"
                  cellpadding="0"
                  cellspacing="0"
                  border="0"
                  style="
                    margin-top: 40px;
                    background: #f5f3ff;
                    border-left: 4px solid #7c3aed;
                    border-radius: 10px;
                  ">
                  <tr>
                    <td style="padding: 18px 22px">
                      <p
                        style="
                          margin: 0;
                          font-size: 14px;
                          line-height: 24px;
                          color: #5b21b6;
                        ">
                        If you did not create this account, you can safely
                        ignore this email.
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- FOOTER -->
            <tr>
              <td
                align="center"
                style="
                  background: #fafafa;
                  padding: 30px;
                  border-top: 1px solid #e5e7eb;
                ">
                <p style="margin: 0 0 10px 0; font-size: 14px; color: #475569">
                  Product of
                  <a
                    href="https://aryuacademy.com"
                    style="
                      color: #005aef;
                      text-decoration: none;
                      font-weight: 600;
                    ">
                    Aryu Academy Pvt Ltd.
                  </a>
                </p>

                <p
                  style="
                    margin: 0;
                    font-size: 13px;
                    color: #64748b;
                    line-height: 24px;
                  ">
                  <a
                    href="https://passats.aryuacademy.com/privacy-policy"
                    style="color: #005aef; text-decoration: none">
                    Privacy Policy
                  </a>

                  &nbsp; | &nbsp;

                  <a
                    href="https://passats.aryuacademy.com/terms-conditions"
                    style="color: #005aef; text-decoration: none">
                    Terms & Conditions
                  </a>
                </p>

                <p
                  style="
                    margin-top: 18px;
                    font-size: 12px;
                    line-height: 22px;
                    color: #9ca3af;
                  ">
                  © 2026 Aryu Academy Private Limited. All rights reserved.
                </p>

                <p
                  style="
                    margin-top: 8px;
                    font-size: 12px;
                    line-height: 22px;
                    color: #9ca3af;
                  ">
                  This is an automated security email. Please do not reply.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

        # =========================================
        # EMAIL SEND
        # =========================================

        email_message = EmailMultiAlternatives(

            subject=f"{user.first_name}, complete your Pass ATS registration",

            body=f"""
Hello {user.first_name},

Please verify your Pass ATS account:

{verification_link}

Website:
https://aryuacademy.com
""",

            from_email=settings.DEFAULT_FROM_EMAIL,

            to=[user.email],
        )

        email_message.attach_alternative(
            html_message,
            "text/html"
        )

        email_message.extra_headers = {
            "Reply-To": "support@aryuacademy.com",
            "X-Auto-Response-Suppress": "OOF, AutoReply"
        }
        
        # send email
        email_message = EmailMultiAlternatives(

        subject=f"{user.first_name}, verify your Pass Ats account",

        body=f"""
        Hello {user.first_name},

        Please verify your Pass Ats account:

        {verification_link}

        Website:
        https://aryuacademy.com
        """,

            from_email=settings.DEFAULT_FROM_EMAIL,

            to=[user.email],
        )

        email_message.attach_alternative(
            html_message,
            "text/html"
        )

        email_message.send(fail_silently=False)

        return Response(
            {
                "message": "Registration successful. Verification email sent."
            },
            status=status.HTTP_201_CREATED
        )

    # =========================================
    # RESEND VERIFICATION EMAIL
    # =========================================

    @action(detail=False, methods=["post"], url_path="resend-verification-email")
    def resend_verification_email(self, request):

        email = str(
            request.data.get("email", "")
        ).strip().lower()

        if not email:

            return Response(
                {
                    "error": "Email is required"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:

            user = ResumeRegistration.objects.only(
                "id",
                "email",
                "first_name",
                "is_verified"
            ).get(email=email)

        except ResumeRegistration.DoesNotExist:

            return Response(
                {
                    "error": "Account not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )

        # already verified
        if user.is_verified:

            return Response(
                {
                    "message": "Account already verified"
                },
                status=status.HTTP_200_OK
            )

        # =========================================
        # TOKEN
        # =========================================

        token = signing.dumps(
            {
                "user_id": user.id,
                "email": user.email
            },
            salt=SIGNING_SALT
        )

        verification_link = (
            "https://aylms.aryuprojects.com"
            f"/api/resume/auth/verify-email/?token={token}"
        )

        # =========================================
        # EMAIL TEMPLATE
        # =========================================

        html_message = f"""
<!DOCTYPE html>
<html lang="en">

<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Verify Your Pass ATS Account</title>
</head>

<body
    style="
      margin: 0;
      padding: 0;
      background-color: #f5f3ff;
      font-family: Arial, sans-serif;
    ">
    <table
      width="100%"
      cellpadding="0"
      cellspacing="0"
      border="0"
      style="background-color: #f5f3ff; padding: 40px 15px">
      <tr>
        <td align="center">
          <table
            width="620"
            cellpadding="0"
            cellspacing="0"
            border="0"
            style="
              background: #ffffff;
              border-radius: 18px;
              overflow: hidden;
              box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
            ">
            <!-- HEADER -->
            <tr>
              <td
                align="center"
                style="
                  background: linear-gradient(
                    135deg,
                    #090116 0%,
                    #090116 50%,
                    #7120e7 100%
                  );
                  padding: 45px 5px;
                ">
                <img
                  src="https://aylms.aryuprojects.com/api/media/logos/passats.png"
                  alt="Pass ATS"
                  style="
                    width: 200px;
                    max-width: 90%;
                    height: auto;
                    display: block;
                    margin: 0 auto;
                  " />

                <p
                  style="
                    margin-top: 20px;
                    color: #996ae3;
                    font-size: 16px;
                    line-height: 26px;
                    font-weight: 600;
                  ">
                  Secure Account Verification
                </p>
              </td>
            </tr>

            <!-- CONTENT -->
            <tr>
              <td style="padding: 45px 20px">
                <h2
                  style="
                    margin: 0 0 20px 0;
                    font-size: 28px;
                    color: #1e1b4b;
                    font-weight: 700;
                  ">
                  Hello {user.first_name},
                </h2>

                <p
                  style="
                    margin: 0 0 20px 0;
                    font-size: 16px;
                    line-height: 30px;
                    color: #475569;
                  ">
                  Thank you for creating your Pass ATS account. Please verify
                  your email address to activate your account securely.
                </p>

                <p
                  style="
                    margin: 0 0 35px 0;
                    font-size: 16px;
                    line-height: 30px;
                    color: #475569;
                  ">
                  This verification link is secure and expires automatically.
                </p>

                <!-- BUTTON -->
                <table
                  cellpadding="0"
                  cellspacing="0"
                  border="0"
                  align="center">
                  <tr>
                    <td
                      align="center"
                      style="
                        border-radius: 12px;
                        background: linear-gradient(135deg, #5c20e7, #7120e7);
                      ">
                      <a
                        href="{verification_link}"
                        target="_blank"
                        style="
                          display: inline-block;
                          padding: 16px 34px;
                          font-size: 16px;
                          font-weight: 700;
                          color: #ffffff;
                          text-decoration: none;
                          border-radius: 12px;
                        ">
                        Verify Email Address
                      </a>
                    </td>
                  </tr>
                </table>

                <!-- NOTICE -->
                <table
                  width="100%"
                  cellpadding="0"
                  cellspacing="0"
                  border="0"
                  style="
                    margin-top: 40px;
                    background: #f5f3ff;
                    border-left: 4px solid #7c3aed;
                    border-radius: 10px;
                  ">
                  <tr>
                    <td style="padding: 18px 22px">
                      <p
                        style="
                          margin: 0;
                          font-size: 14px;
                          line-height: 24px;
                          color: #5b21b6;
                        ">
                        If you did not create this account, you can safely
                        ignore this email.
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- FOOTER -->
            <tr>
              <td
                align="center"
                style="
                  background: #fafafa;
                  padding: 30px;
                  border-top: 1px solid #e5e7eb;
                ">
                <p style="margin: 0 0 10px 0; font-size: 14px; color: #475569">
                  Product of
                  <a
                    href="https://aryuacademy.com"
                    style="
                      color: #005aef;
                      text-decoration: none;
                      font-weight: 600;
                    ">
                    Aryu Academy Pvt Ltd.
                  </a>
                </p>

                <p
                  style="
                    margin: 0;
                    font-size: 13px;
                    color: #64748b;
                    line-height: 24px;
                  ">
                  <a
                    href="https://passats.aryuacademy.com/privacy-policy"
                    style="color: #005aef; text-decoration: none">
                    Privacy Policy
                  </a>

                  &nbsp; | &nbsp;

                  <a
                    href="https://passats.aryuacademy.com/terms-conditions"
                    style="color: #005aef; text-decoration: none">
                    Terms & Conditions
                  </a>
                </p>

                <p
                  style="
                    margin-top: 18px;
                    font-size: 12px;
                    line-height: 22px;
                    color: #9ca3af;
                  ">
                  © 2026 Aryu Academy Private Limited. All rights reserved.
                </p>

                <p
                  style="
                    margin-top: 8px;
                    font-size: 12px;
                    line-height: 22px;
                    color: #9ca3af;
                  ">
                  This is an automated security email. Please do not reply.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

        # =========================================
        # SEND EMAIL
        # =========================================

        email_message = EmailMultiAlternatives(

            subject=f"{user.first_name}, complete your Pass ATS registration",

            body=f"""
    Hello {user.first_name},

    Please verify your Pass ATS account:

    {verification_link}

    Website:
    https://aryuacademy.com
    """,

            from_email=settings.DEFAULT_FROM_EMAIL,

            to=[user.email],
        )

        email_message.attach_alternative(
            html_message,
            "text/html"
        )

        email_message.extra_headers = {
            "Reply-To": "support@aryuacademy.com",
            "X-Auto-Response-Suppress": "OOF, AutoReply"
        }

        try:

            email_message.send(fail_silently=False)

        except Exception:

            return Response(
                {
                    "error": "Unable to send verification email"
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "message": "Verification email sent successfully"
            },
            status=status.HTTP_200_OK
        )

    # =========================
    # VERIFY EMAIL
    # =========================

    @action(detail=False, methods=["get"], url_path="verify-email")
    def verify_email(self, request):

        token = request.GET.get("token")

        if not token:
            return Response(
                {"error": "Invalid verification link"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:

            data = signing.loads(
                token,
                salt=SIGNING_SALT,
                max_age=60 * 60 * 24
            )

            user = ResumeRegistration.objects.only(
                "id",
                "email",
                "is_verified"
            ).get(
                id=data["user_id"],
                email=data["email"]
            )

        except SignatureExpired:

            return Response(
                {"error": "Verification link expired"},
                status=status.HTTP_400_BAD_REQUEST
            )

        except (BadSignature, ResumeRegistration.DoesNotExist):

            return Response(
                {"error": "Invalid verification link"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if user.is_verified:

            return redirect(
            "https://passats.aryuacademy.com/login"
        )

        user.is_verified = True

        user.save(update_fields=["is_verified"])

        return redirect(
            "https://passats.aryuacademy.com/login"
        )

    # =========================
    # LOGIN
    # =========================

    @action(detail=False, methods=["post"], url_path="login")
    @secure_throttle(rate_limit=5, period=60)
    def login(self, request):

        email = str(request.data.get("email", "")).strip().lower()
        password = request.data.get("password")

        if not email or not password:
            return Response(
                {"error": "Email and password required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:

            user = ResumeRegistration.objects.select_related(
                "current_subscription"
            ).only(
                "id",
                "email",
                "password",
                "is_verified",
                "first_name",
                "last_name",
                "current_subscription",
            ).get(email=email)

        except ResumeRegistration.DoesNotExist:

            # Prevent timing attack
            check_password(password, make_password("dummy_password"))

            return Response(
                {"error": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Password check
        if not check_password(password, user.password):
            return Response(
                {"error": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Email verification
        if not user.is_verified:
            return Response(
                {"error": "Please verify your email first"},
                status=status.HTTP_403_FORBIDDEN
            )

        # CREATE REFRESH TOKEN MANUALLY
        refresh = RefreshToken()

        refresh["user_id"] = user.id
        refresh["id"] = user.id

        refresh["email"] = user.email
        refresh["user_type"] = "resume_user"

        refresh["first_name"] = user.first_name
        refresh["last_name"] = user.last_name

        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        return Response(
            {
                "message": "Login successful",

                "access_token": access_token,
                "refresh_token": refresh_token,

                "user": {
                    "id": user.id,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "user": "resume_user",
                }
            },
            status=status.HTTP_200_OK
        )

    @staticmethod
    def generate_secure_otp(length=6):

        characters = (
            string.ascii_uppercase +
            string.ascii_lowercase +
            string.digits +
            "!@#$%^&*"
        )

        while True:

            otp = "".join(
                secrets.choice(characters)
                for _ in range(length)
            )

            if (
                re.search(r"[A-Z]", otp)
                and re.search(r"[a-z]", otp)
                and re.search(r"[0-9]", otp)
                and re.search(r"[!@#$%^&*]", otp)
            ):
                return otp
            
    @action(detail=False, methods=["post"], url_path="forgot-password")
    @secure_throttle(rate_limit=5, period=60)
    def forgot_password(self, request):

        email = str(
            request.data.get("email", "")
        ).strip().lower()

        # generic response
        generic_response = {
            "message": (
                "If the account exists, "
                "a password reset OTP has been sent."
            )
        }

        if not email:

            return Response(
                generic_response,
                status=status.HTTP_200_OK
            )

        try:

            user = ResumeRegistration.objects.get(
                email=email
            )

        except ResumeRegistration.DoesNotExist:

            return Response(
                generic_response,
                status=status.HTTP_200_OK
            )

        # generate secure OTP
        otp = self.generate_secure_otp()

        # store hashed OTP
        user.reset_otp_hash = make_password(otp)

        # expiry
        user.reset_otp_expiry = (
            timezone.now() + timedelta(minutes=5)
        )

        # reset attempts
        user.reset_otp_attempts = 0

        # reset verification
        user.reset_verified = False

        user.save(
            update_fields=[
                "reset_otp_hash",
                "reset_otp_expiry",
                "reset_otp_attempts",
                "reset_verified"
            ]
        )

        # email template
        html_message = f"""
<!DOCTYPE html>
<html lang="en">

<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Reset Your Pass ATS Password</title>
</head>

<body
    style="
      margin: 0;
      padding: 0;
      background-color: #f5f3ff;
      font-family: Arial, sans-serif;
    ">

    <table
      width="100%"
      cellpadding="0"
      cellspacing="0"
      border="0"
      style="background-color: #f5f3ff; padding: 40px 15px">

      <tr>
        <td align="center">

          <table
            width="620"
            cellpadding="0"
            cellspacing="0"
            border="0"
            style="
              background: #ffffff;
              border-radius: 18px;
              overflow: hidden;
              box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
            ">

            <!-- HEADER -->
            <tr>
              <td
                align="center"
                style="
                  background: linear-gradient(
                    135deg,
                    #090116 0%,
                    #090116 50%,
                    #7120e7 100%
                  );
                  padding: 45px 5px;
                ">

                <img
                  src="https://aylms.aryuprojects.com/api/media/logos/passats.png"
                  alt="Pass ATS"
                  style="
                    width: 200px;
                    max-width: 90%;
                    height: auto;
                    display: block;
                    margin: 0 auto;
                  " />

                <p
                  style="
                    margin-top: 20px;
                    color: #996ae3;
                    font-size: 16px;
                    line-height: 26px;
                    font-weight: 600;
                  ">
                  Secure Password Reset
                </p>

              </td>
            </tr>

            <!-- CONTENT -->
            <tr>
              <td style="padding: 45px 20px">

                <h2
                  style="
                    margin: 0 0 20px 0;
                    font-size: 28px;
                    color: #1e1b4b;
                    font-weight: 700;
                  ">
                  Hello {user.first_name},
                </h2>

                <p
                  style="
                    margin: 0 0 20px 0;
                    font-size: 16px;
                    line-height: 30px;
                    color: #475569;
                  ">
                  We received a request to reset your Pass ATS account password.
                </p>

                <p
                  style="
                    margin: 0 0 25px 0;
                    font-size: 16px;
                    line-height: 30px;
                    color: #475569;
                  ">
                  Use the secure OTP below to continue your password reset process.
                </p>

                <!-- OTP BOX -->
                <table
                  width="100%"
                  cellpadding="0"
                  cellspacing="0"
                  border="0"
                  style="margin: 30px 0">

                  <tr>
                    <td align="center">

                      <div
                        style="
                          display: inline-block;
                          background: linear-gradient(
                            135deg,
                            #5c20e7,
                            #7120e7
                          );
                          padding: 18px 40px;
                          border-radius: 14px;
                          color: #ffffff;
                          font-size: 34px;
                          font-weight: 800;
                          letter-spacing: 8px;
                          box-shadow: 0 4px 12px rgba(113, 32, 231, 0.35);
                        ">
                        {otp}
                      </div>

                    </td>
                  </tr>

                </table>

                <p
                  style="
                    margin: 25px 0 0 0;
                    font-size: 15px;
                    line-height: 28px;
                    color: #475569;
                  ">
                  This OTP is valid for
                  <strong>5 minutes</strong>.
                </p>

                <!-- NOTICE -->
                <table
                  width="100%"
                  cellpadding="0"
                  cellspacing="0"
                  border="0"
                  style="
                    margin-top: 40px;
                    background: #fef2f2;
                    border-left: 4px solid #dc2626;
                    border-radius: 10px;
                  ">

                  <tr>
                    <td style="padding: 18px 22px">

                      <p
                        style="
                          margin: 0;
                          font-size: 14px;
                          line-height: 24px;
                          color: #991b1b;
                        ">

                        If you did not request this password reset,
                        please ignore this email immediately.
                        Your account remains secure.

                      </p>

                    </td>
                  </tr>

                </table>

              </td>
            </tr>

            <!-- FOOTER -->
            <tr>
              <td
                align="center"
                style="
                  background: #fafafa;
                  padding: 30px;
                  border-top: 1px solid #e5e7eb;
                ">

                <p
                  style="
                    margin: 0 0 10px 0;
                    font-size: 14px;
                    color: #475569;
                  ">

                  Product of

                  <a
                    href="https://aryuacademy.com"
                    style="
                      color: #005aef;
                      text-decoration: none;
                      font-weight: 600;
                    ">

                    Aryu Academy Pvt Ltd.

                  </a>

                </p>

                <p
                  style="
                    margin: 0;
                    font-size: 13px;
                    color: #64748b;
                    line-height: 24px;
                  ">

                  <a
                    href="https://passats.aryuacademy.com/privacy-policy"
                    style="
                      color: #005aef;
                      text-decoration: none;
                    ">

                    Privacy Policy

                  </a>

                  &nbsp; | &nbsp;

                  <a
                    href="https://passats.aryuacademy.com/terms-conditions"
                    style="
                      color: #005aef;
                      text-decoration: none;
                    ">

                    Terms & Conditions

                  </a>

                </p>

                <p
                  style="
                    margin-top: 18px;
                    font-size: 12px;
                    line-height: 22px;
                    color: #9ca3af;
                  ">

                  © 2026 Aryu Academy Private Limited.
                  All rights reserved.

                </p>

                <p
                  style="
                    margin-top: 8px;
                    font-size: 12px;
                    line-height: 22px;
                    color: #9ca3af;
                  ">

                  This is an automated security email.
                  Please do not reply.

                </p>

              </td>
            </tr>

          </table>

        </td>
      </tr>

    </table>

  </body>
</html>
"""

        email_message = EmailMultiAlternatives(

            subject="Secure Password Reset OTP",

            body=f"""
    Hello {user.first_name},

    Your OTP is:

    {otp}

    This OTP expires in 5 minutes.
            """,

            from_email=settings.DEFAULT_FROM_EMAIL,

            to=[user.email],
        )

        email_message.attach_alternative(
            html_message,
            "text/html"
        )

        email_message.send(
            fail_silently=True
        )

        return Response(
            generic_response,
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=["post"], url_path="verify-reset-otp")
    def verify_reset_otp(self, request):

        email = str(
            request.data.get("email", "")
        ).strip().lower()

        otp = str(
            request.data.get("otp", "")
        ).strip()

        if not email or not otp:

            return Response(
                {
                    "error": "Email and OTP required"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:

            user = ResumeRegistration.objects.get(
                email=email
            )

        except ResumeRegistration.DoesNotExist:

            return Response(
                {
                    "error": "Invalid OTP"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # expiry check
        if (
            not user.reset_otp_expiry
            or timezone.now() > user.reset_otp_expiry
        ):

            return Response(
                {
                    "error": "OTP expired"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # attempt limit
        if user.reset_otp_attempts >= 5:

            return Response(
                {
                    "error": "Too many attempts"
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        # increment attempts
        user.reset_otp_attempts += 1
        user.save(update_fields=["reset_otp_attempts"])

        # verify OTP
        if not check_password(
            otp,
            user.reset_otp_hash
        ):

            return Response(
                {
                    "error": "Invalid OTP"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # verified
        user.reset_verified = True

        user.save(update_fields=["reset_verified"])

        # create reset token
        reset_token = signing.dumps(
            {
                "user_id": user.id,
                "email": user.email,
                "purpose": "password_reset"
            },
            salt="password-reset"
        )

        return Response(
            {
                "message": "OTP verified",
                "reset_token": reset_token
            },
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=["post"], url_path="reset-password")
    def reset_password(self, request):

        token = request.data.get("reset_token")

        new_password = request.data.get(
            "new_password"
        )

        if not token or not new_password:

            return Response(
                {
                    "error": (
                        "Token and password required"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # validate password
        password_error = self.validate_password(
            new_password
        )

        if password_error:

            return Response(
                {
                    "error": password_error
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:

            data = signing.loads(
                token,
                salt="password-reset",
                max_age=300
            )

            user = ResumeRegistration.objects.get(
                id=data["user_id"],
                email=data["email"]
            )

        except SignatureExpired:

            return Response(
                {
                    "error": "Reset session expired"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        except (
            BadSignature,
            ResumeRegistration.DoesNotExist
        ):

            return Response(
                {
                    "error": "Invalid reset token"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ensure OTP verified
        if not user.reset_verified:

            return Response(
                {
                    "error": "OTP verification required"
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # update password
        user.password = make_password(
            new_password
        )

        # clear reset data
        user.reset_otp_hash = None
        user.reset_otp_expiry = None
        user.reset_otp_attempts = 0
        user.reset_verified = False

        user.save(
            update_fields=[
                "password",
                "reset_otp_hash",
                "reset_otp_expiry",
                "reset_otp_attempts",
                "reset_verified"
            ]
        )

        return Response(
            {
                "message": (
                    "Password reset successful"
                )
            },
            status=status.HTTP_200_OK
        )

class CustomTokenRefreshView(APIView):

    permission_classes = [AllowAny]
    serializer_class = CustomTokenRefreshSerializer

    def post(self, request, *args, **kwargs):

        serializer = self.serializer_class(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        return Response(
            serializer.validated_data,
            status=status.HTTP_200_OK
        )

class ResumeRegistrationViewset(viewsets.ModelViewSet):

    queryset = ResumeRegistration.objects.all().order_by("-id")
    serializer_class = ResumeRegistrationSerializers
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [AllowAny]


    # CREATE
    @secure_throttle(rate_limit=5, period=60)
    def create(self, request, *args, **kwargs):

        serializer = self.get_serializer(data=request.data)

        if serializer.is_valid():
            serializer.save()

            return Response(
                {
                    "status": True,
                    "message": "Resume registration created successfully",
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


    # LIST
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
                "message": "Resume registration list",
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )
    


    # PATCH / UPDATE
    def partial_update(self, request, *args, **kwargs):

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save()

            return Response(
                {
                    "status": True,
                    "message": "Resume registration updated successfully",
                    "data": serializer.data
                },
                status=status.HTTP_200_OK
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
    @secure_throttle(rate_limit=5, period=60)
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
                "message": "Resume registration deleted successfully"
            },
            status=status.HTTP_200_OK
        )

class UserDashboardView(APIView):

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):

        user_id = request.user.id

        try:
            user = ResumeRegistration.objects.select_related(
                'current_subscription__subscription'
            ).only(
                'id',
                'first_name',
                'last_name',
                'email',
                'phone',
                'current_subscription'
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
        # GET CURRENT PLAN
        # --------------------------------------------

        current_subscription = UserSubscription.objects.select_related(
            "subscription"
        ).filter(
            user=user,
            status="active"
        ).order_by("-id").first()

        current_plan_name = (
            current_subscription.subscription.name
        )

        plan_details = DashboardSubscriptionSerializer(
            current_subscription
        ).data

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

        transactions = UserSubscription.objects.select_related(
            "subscription",
            "payment_transaction"
        ).filter(
            user=user
        ).order_by(
            "-created_at"
        )

        transaction_data = DashboardSubscriptionHistorySerializer(
            transactions,
            many=True
        ).data

        available_templates_count = ResumeTemplate.objects.filter(
            is_active=True,
            is_deleted=False
        ).count()

        return Response({

            "profile": {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "phone": user.phone,
                "country":user.country,
                "city":user.city,
                "state":user.state
            },

            "subscription": {
                "current_plan": current_plan_name,
                "plan_details": plan_details
            },

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

        return Response({

            "success": True,

            "message": (
                "Payment verification success. "
                "Webhook processing pending."
            )
        })

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

class SubscriptionViewSet(viewsets.ViewSet):

    authentication_classes = [CustomJWTAuthentication]

    permission_classes = [permissions.IsAuthenticated]

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

            description=validated_data.get(
                "description"
            ),

            price=validated_data["price"],

            discount_price=validated_data.get(
                "discount_price"
            ),

            billing_type=validated_data[
                "billing_type"
            ],

            duration_days=validated_data[
                "duration_days"
            ],

            limit=validated_data.get(
                "limit",
                "free"
            ),

            order=validated_data.get(
                "order",
                0
            ),

            is_active=validated_data.get(
                "is_active",
                True
            )
        )

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
    queryset = PaymentHistory.objects.all().order_by("-id")
    serializer_class = PaymentHistorySerializers
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


class GeneratePDFView(APIView):

    permission_classes = [permissions.IsAuthenticated]

    MAX_HTML_SIZE = 2 * 1024 * 1024  # 2MB

    async def generate_pdf_async(self, html_content):

        async with async_playwright() as p:

            browser = await p.chromium.launch(

                headless=True,

                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ]
            )

            page = await browser.new_page(

                viewport={
                    "width": 794,
                    "height": 1123
                }
            )

            # IMPORTANT
            # wait_until networkidle gives proper rendering

            await page.set_content(
                html_content,
                wait_until="networkidle"
            )

            # FORCE A4 PRINT
            await page.emulate_media(media="print")

            pdf_bytes = await page.pdf(

                format="A4",

                print_background=True,

                margin={
                    "top": "0mm",
                    "right": "0mm",
                    "bottom": "0mm",
                    "left": "0mm",
                },

                prefer_css_page_size=True
            )

            await browser.close()

            return pdf_bytes

    def post(self, request, *args, **kwargs):

        html_content = request.data.get("html")

        if not html_content:

            raise ValidationError({
                "detail": "HTML content is required."
            })

        if len(html_content) > self.MAX_HTML_SIZE:

            raise ValidationError({
                "detail": (
                    "HTML payload too large. "
                    "Maximum size is 2MB."
                )
            })

        try:

            pdf_bytes = asyncio.run(
                self.generate_pdf_async(html_content)
            )

            response = HttpResponse(
                pdf_bytes,
                content_type="application/pdf"
            )

            response[
                "Content-Disposition"
            ] = 'attachment; filename="resume.pdf"'

            return response

        except Exception as e:

            logger.exception(
                f"PDF generation failed: {str(e)}"
            )

            return Response(
                {
                    "detail": (
                        "Failed to generate PDF."
                    )
                },
                status=500
            )
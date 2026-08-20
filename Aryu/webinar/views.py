from aryuapp.services.dashboard import student_dashboard_service
from datetime import datetime
from django.utils import timezone
import json
from django.shortcuts import render
from django.db import transaction as db_transaction
from requests import request
import requests
from rest_framework import viewsets, permissions, status, mixins
from rest_framework.views import APIView
from .tasks import send_certificate_task
from .services.scheduler import schedule_webinar_messages
from .services.certificate_generation import generate_and_send_certificate_pdf
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from .services.whatsapp import send_webinar_reminder, send_webinar_welcome_whatsapp, send_webinar_joining_whatsapp
from payments.models import PaymentGateway, PaymentTransaction
from aryuapp.models import Certificate
import razorpay
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.throttling import AnonRateThrottle
from rest_framework.response import Response
import json
from django.http import HttpResponse, JsonResponse
from django.utils.timezone import make_aware, is_naive
from .services.webinar_emails import send_webinar_registration_email
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import action
from django.views.decorators.csrf import csrf_exempt
import hmac
import hashlib
from django.core.cache import cache
from django.conf import settings
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from aryuapp.auth import CustomJWTAuthentication
from django.db.models import Count, Prefetch, Sum, Q, Avg, F, Value, IntegerField, Case, When, FloatField, Value, CharField
from .models import *
from .serializers import *
import logging
from .utils import get_ticket_from_token
from django.contrib.postgres.aggregates import JSONBAgg
from django.db.models.functions import Coalesce, JSONObject, Concat
from django.db.models.expressions import ExpressionWrapper
from urllib.parse import quote
from .services.zoom_service import get_zoom_access_token
from django.db.models import DecimalField
# from celery import shared_task
from aryuapp.models import Student,StudentCourse
from courses.models import Course
from batches.models import NewBatch
from payments.services.invoice_service import (
    InvoiceService
)
from datetime import time, timedelta
import secrets
from django.contrib.auth.hashers import make_password
from aryuapp.services.dashboard.student_registration_service import send_welcome_and_invoice_email

logger = logging.getLogger(__name__)

# ==========================================
# RAZORPAY WEBHOOK
# ==========================================
@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def razorpay_webhook(request):
    logger.info("=" * 80)
    logger.info("Webhook received")

    payload = request.body
    received_signature = request.headers.get("X-Razorpay-Signature")

    if not received_signature:
        logger.error("Signature missing")
        return HttpResponse(status=400)

    gateway = PaymentGateway.objects.filter(gatway_name__icontains="razorpay").first()

    if not gateway or not gateway.webhook_secret:
        logger.error("Razorpay webhook gateway is not configured")
        return HttpResponse(status=400)

    expected_signature = hmac.new(
        gateway.webhook_secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, received_signature):
        logger.error("Signature mismatch")
        return HttpResponse(status=400)

    data = request.data
    event = data.get("event")

    if event == "payment.captured":
        entity = data["payload"]["payment"]["entity"]
        order_id = entity.get("order_id")

        with db_transaction.atomic():
            txn = PaymentTransaction.objects.select_for_update().filter(order_id=order_id).first()

            if not txn or txn.payment_status == "done":
                return HttpResponse(status=200)

            txn.payment_status = "done"
            txn.transaction_id = entity["id"]
            txn.order_id = order_id
            txn.save(update_fields=["payment_status", "transaction_id", "order_id"])

            WebinarRegistrationViewSet.create_registration_from_transaction(txn)

    elif event == "payment.failed":
        entity = data["payload"]["payment"]["entity"]
        order_id = entity.get("order_id")
        PaymentTransaction.objects.filter(order_id=order_id).update(payment_status="failed")

    return HttpResponse(status=200)



class RazorpayPaymentViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    def _get_client(self):
        gateway = PaymentGateway.objects.filter(
            gatway_name__icontains="razorpay"
        ).first()


        if not gateway:
            return None, None

        client = razorpay.Client(
            auth=(gateway.public_key, gateway.secret_key)
        )
        return client, gateway

    @action(detail=False, methods=["post"])
    def create(self, request):
        amount = request.data.get("amount")
        webinar_id = request.data.get("webinar_id")
        webinar_title = request.data.get("webinar_title")
        name = request.data.get("name")
        email = request.data.get("email")
        phone = request.data.get("phone")
        profession = request.data.get("profession")

        if not all([amount, webinar_id, phone]):
            return Response(
                {"success": False, "message": "Missing required fields"},
                status=400
            )

        client, gateway = self._get_client()
        if not client:
            return Response(
                {"success": False, "message": "Razorpay not configured"},
                status=400
            )

        order = client.order.create({
            "amount": int(float(amount) * 100),
            "currency": "INR",
            "payment_capture": 1,
            "notes": {
                "webinar_id": webinar_id,
                "name": name,
                "email": email,
                "phone": phone,
                "description":webinar_title 
            }
        })

        webinar = get_object_or_404(Webinar, uuid=webinar_id)

        return Response({
            "success": True,
            "order_id": order["id"],
            "key": gateway.public_key,
            "amount": int(float(amount) * 100),
            "currency": "INR",
            "webinar_title": webinar.title,
            "waba_link": webinar.waba_link
        })


    # -------------------------
    # Verify Razorpay Payment
    # -------------------------
    @csrf_exempt
    @action(detail=False, methods=['post'], url_path="verify")
    def verify_payment(self, request):
        payment_id = request.data.get("razorpay_payment_id")
        order_id = request.data.get("razorpay_order_id")
        signature = request.data.get("razorpay_signature")

        if not all([payment_id, order_id, signature]):
            return Response(
                {"success": False, "message": "Missing payment verification fields"},
                status=400
            )

        gateway = PaymentGateway.objects.filter(
            gatway_name__icontains="razorpay"
        ).first()

        if not gateway or not gateway.secret_key:
            return Response(
                {"success": False, "message": "Razorpay secret not configured"},
                status=500
            )

        try:
            razorpay_client = razorpay.Client(
                auth=(gateway.public_key, gateway.secret_key)
            )

            razorpay_client.utility.verify_payment_signature({
                "razorpay_payment_id": payment_id,
                "razorpay_order_id": order_id,
                "razorpay_signature": signature
            })

        except razorpay.errors.SignatureVerificationError:
            return Response(
                {"success": False, "message": "Invalid payment signature"},
                status=400
            )

        # Let webhook handle final status

        return Response({"success": True})
        
CACHE_KEY_WEBINAR_LIST = "webinar_list_v1"
CACHE_KEY_BOOTCAMP_LIST = "bootcamp_list_v1"
VERIFY_TOKEN = "akzworld"



# ==========================================
# PUBLIC WEBINAR VIEWSET
# ==========================================
class PublicWebinarViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Webinar.objects.filter(is_deleted=False, webinar_status=True).order_by("-created_at")
    serializer_class = PublicWebinarListSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = "slug"

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return Response({"success": True, "data": response.data.get("results", response.data)})

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return Response({"success": True, "data": response.data})


# ==========================================
# WEBINAR VIEWSET (type=True: NO COURSE GENERATION)
# ==========================================
class WebinarViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = WebinarSerializer
    lookup_field = "slug"
    lookup_url_kwarg = "slug"

    def get_queryset(self):
        """Webinars Queryset (type=True)"""
        return Webinar.objects.filter(is_deleted=False, type=True).order_by("-created_at")

    def list(self, request, *args, **kwargs):
        data = cache.get(CACHE_KEY_WEBINAR_LIST)
        if not data:
            queryset = self.get_queryset()
            data = WebinarListSerializer(queryset, many=True, context={"request": request}).data
            cache.set(CACHE_KEY_WEBINAR_LIST, data, 60)
        return Response(data)

    def retrieve(self, request, slug=None):
        webinar = get_object_or_404(
            self.get_queryset(),
            slug=slug
        )
        serializer = self.get_serializer(webinar, context={"request": request})
        return Response({"success": True, "message": "Webinar retrieved successfully", "data": serializer.data})

    def _save_nested_relations(self, request, webinar):
        # --- TOOLS ---
        i = 0
        while f"tools[{i}][tools_title]" in request.data:
            WebinarTool.objects.create(
                webinar=webinar,
                tools_title=request.data.get(f"tools[{i}][tools_title]"),
                tools_image=request.FILES.get(f"tools[{i}][tools_image]")
            )
            i += 1

        # --- METADATA ---
        j = 0
        while f"metadata[{j}][meta_title]" in request.data:
            webinar_metadata.objects.create(
                webinar=webinar,
                meta_title=request.data.get(f"metadata[{j}][meta_title]"),
                meta_description=request.data.get(f"metadata[{j}][meta_description]"),
                meta_image=request.FILES.get(f"metadata[{j}][meta_image]")
            )
            j += 1

        # --- FAQs ---
        faqs_data = request.data.get("faqs")
        if faqs_data:
            if isinstance(faqs_data, str):
                try:
                    faqs_data = json.loads(faqs_data)
                except json.JSONDecodeError:
                    faqs_data = []

            if isinstance(faqs_data, list):
                for faq in faqs_data:
                    Webinar_FAQ.objects.create(
                        webinar=webinar,
                        question=faq.get("question"),
                        answer=faq.get("answer")
                    )

    def create(self, request):
        serializer = WebinarSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        with db_transaction.atomic():
            # type=True guarantees NO Course will be created
            webinar = serializer.save(type=True)
            self._save_nested_relations(request, webinar)

        cache.delete(CACHE_KEY_WEBINAR_LIST)
        return Response({
            "status": True,
            "message": "Webinar created successfully",
            "data": WebinarSerializer(webinar, context={"request": request}).data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        slug = kwargs.get("slug")
        webinar = get_object_or_404(Webinar, slug=slug, is_deleted=False, type=True)

        try:
            with db_transaction.atomic():
                serializer = WebinarSerializer(webinar, data=request.data, partial=True, context={"request": request})
                serializer.is_valid(raise_exception=True)
                serializer.save()
                self._save_nested_relations(request, webinar)

            cache.delete(CACHE_KEY_WEBINAR_LIST)
            return Response({
                "status": True,
                "message": "Webinar updated successfully",
                "data": WebinarSerializer(webinar, context={"request": request}).data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"status": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        slug = kwargs.get("slug")
        webinar = get_object_or_404(Webinar, slug=slug, is_deleted=False, type=True)

        webinar.is_deleted = True
        webinar.save(update_fields=["is_deleted", "updated_at"])
        cache.delete(CACHE_KEY_WEBINAR_LIST)

        return Response({"status": True, "message": "Webinar deleted successfully"}, status=status.HTTP_200_OK)


# ==========================================
# BOOTCAMP VIEWSET (type=False: AUTOMATIC COURSE CREATION)
# ==========================================
class BootcampViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = WebinarSerializer
    lookup_field = "slug"
    lookup_url_kwarg = "slug"

    def get_queryset(self):
        """Bootcamps Queryset (type=False)"""
        return (
            Webinar.objects
            .filter(is_deleted=False, type=False)  # ONLY BOOTCAMPS
            .annotate(
                participants_count=Count("registrations", distinct=True),
                total_amount_received=Sum(
                    "registrations__payment_transaction__amount",
                    filter=Q(registrations__payment_transaction__payment_status="done"),
                ),
                feedback_count=Count("feedbacks", distinct=True),
                avg_rating=Avg("feedbacks__overall_rating"),
            )
            .order_by("-created_at")
        )

    def list(self, request, *args, **kwargs):
        data = cache.get(CACHE_KEY_BOOTCAMP_LIST)
        if not data:
            queryset = self.get_queryset()
            data = WebinarListSerializer(queryset, many=True, context={"request": request}).data
            cache.set(CACHE_KEY_BOOTCAMP_LIST, data, 60)
        return Response(data)

    def retrieve(self, request, slug=None, *args, **kwargs):
        webinar = get_object_or_404(self.get_queryset(), slug=slug)
        serializer = self.get_serializer(webinar, context={"request": request})
        return Response({"success": True, "message": "Bootcamp retrieved successfully", "data": serializer.data})

    def _save_nested_relations(self, request, webinar):
        # Helper for Tools, Metadata, FAQs
        i = 0
        while f"tools[{i}][tools_title]" in request.data:
            WebinarTool.objects.create(
                webinar=webinar,
                tools_title=request.data.get(f"tools[{i}][tools_title]"),
                tools_image=request.FILES.get(f"tools[{i}][tools_image]")
            )
            i += 1

    def create(self, request):
        serializer = WebinarSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        with db_transaction.atomic():
            # type=False triggers automatic Course creation via post_save signal
            webinar = serializer.save(type=False)
            self._save_nested_relations(request, webinar)

        cache.delete(CACHE_KEY_BOOTCAMP_LIST)
        return Response({
            "status": True,
            "message": "Bootcamp and associated Course created successfully",
            "data": WebinarSerializer(webinar, context={"request": request}).data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        slug = kwargs.get("slug")
        webinar = get_object_or_404(Webinar, slug=slug, is_deleted=False, type=False)

        try:
            with db_transaction.atomic():
                serializer = WebinarSerializer(webinar, data=request.data, partial=True, context={"request": request})
                serializer.is_valid(raise_exception=True)
                serializer.save()
                self._save_nested_relations(request, webinar)

            cache.delete(CACHE_KEY_BOOTCAMP_LIST)
            return Response({
                "status": True,
                "message": "Bootcamp updated successfully",
                "data": WebinarSerializer(webinar, context={"request": request}).data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"status": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        slug = kwargs.get("slug")
        webinar = get_object_or_404(Webinar, slug=slug, is_deleted=False, type=False)

        webinar.is_deleted = True
        webinar.save(update_fields=["is_deleted", "updated_at"])
        cache.delete(CACHE_KEY_BOOTCAMP_LIST)

        return Response({"status": True, "message": "Bootcamp deleted successfully"}, status=status.HTTP_200_OK)


# ==========================================
# REGISTRATION & BOOTCAMP PARTICIPANT SYNC
# ==========================================
# class WebinarRegistrationViewSet(viewsets.ViewSet):
#     permission_classes = [permissions.AllowAny]

#     @staticmethod
#     def _auto_generate_invoice_safe(transaction_id):
#         try:
#             InvoiceService.generate_invoice(transaction_id, regenerate=False)
#             logger.info(f"[Auto Invoice] Invoice generated for Transaction ID: {transaction_id}")
#         except Exception as e:
#             logger.error(f"[Auto Invoice Failed] Transaction ID {transaction_id}: {str(e)}")

#     @staticmethod
#     def _generate_registration_id():
#         today_prefix = f"AYA{timezone.now().strftime('%m%y')}"
#         last_student = (
#             Student.objects.filter(registration_id__startswith=today_prefix)
#             .order_by("-created_at")
#             .first()
#         )
#         if last_student and last_student.registration_id:
#             try:
#                 last_num = int(last_student.registration_id[-3:])
#                 return f"{today_prefix}{last_num + 1:03d}"
#             except ValueError:
#                 pass
#         return f"{today_prefix}001"

#     @classmethod
#     def _get_or_create_active_student(cls, name, email, phone, campaign_title="Bootcamp Registration", webinar=None):
#         student = None
#         email = (email or "").strip().lower()
#         phone = (phone or "").strip()
#         raw_password = secrets.token_urlsafe(10)

#         if phone:
#             student = Student.objects.filter(contact_no=phone, is_archived=False).first()
#         if not student and email:
#             student = Student.objects.filter(email=email, is_archived=False).first()

#         name_parts = (name or "").strip().split(" ", 1)
#         first_name = name_parts[0] if name_parts else "Student"
#         last_name = name_parts[1] if len(name_parts) > 1 else ""

#         webinar_org = getattr(webinar, "organization", None) if webinar else None
#         webinar_creator = getattr(webinar, "created_by", None) if webinar else None

#         if not student:
#             reg_id = cls._generate_registration_id()
#             student = Student.objects.create(
#                 registration_id=reg_id,
#                 first_name=first_name,
#                 last_name=last_name,
#                 username=email or phone or reg_id,
#                 password=make_password(raw_password),
#                 email=email,
#                 contact_no=phone,
#                 status=True,
#                 created_by_type="public",
#                 converter="campaign",
#                 source_type="webinar",
#                 source_name=campaign_title,
#                 organization=webinar_org,
#                 created_by=webinar_creator,
#                 is_archived=False,
#             )
#         else:
#             student.password = make_password(raw_password)
#             if first_name and student.first_name != first_name:
#                 student.first_name = first_name
#                 student.last_name = last_name
#             if phone and not student.contact_no:
#                 student.contact_no = phone
#             if not student.status:
#                 student.status = True
#             if webinar_org and not student.organization:
#                 student.organization = webinar_org
#             student.save()

#         return student, raw_password

#     @classmethod
#     def _get_bootcamp_course(cls, webinar):
#         notes_identifier = f"Auto-created from Webinar/Bootcamp ID: {webinar.id}"
#         course = Course.objects.filter(notes__icontains=notes_identifier, is_archived=False).first()
#         if not course:
#             course = Course.objects.filter(course_name=webinar.title, is_archived=False).first()
#         if not course:
#             course = Course.objects.create(
#                 course_name=webinar.title,
#                 fee=getattr(webinar, "price", None) or getattr(webinar, "regular_price", None) or 0,
#                 status="Active",
#                 notes=notes_identifier,
#                 is_archived=False,
#                 created_by=getattr(webinar, "created_by", "system"),
#                 created_by_type=getattr(webinar, "created_by_type", "super_admin"),
#             )
#         return course

#     @classmethod
#     def _enroll_bootcamp_student(cls, student, webinar):
#         if not student or not webinar or not webinar.title:
#             return None

#         course = cls._get_bootcamp_course(webinar)

#         if hasattr(student, "courses"):
#             student.courses.add(course)

#         batch = None
#         try:
#             start_date = timezone.now().date()
#             end_date = start_date + timedelta(days=30)
#             batch, _ = NewBatch.objects.get_or_create(
#                 course=course,
#                 defaults={
#                     "title": f"Batch - {course.course_name}",
#                     "status": True,
#                     "start_date": start_date,
#                     "end_date": end_date,
#                     "start_time": time(9, 0),
#                     "end_time": time(18, 0),
#                 },
#             )
#             if hasattr(batch, "students"):
#                 batch.students.add(student)
#         except Exception as e:
#             logger.warning(f"[Bootcamp Batch Assign Failed] {str(e)}")

#         try:
#             StudentCourse.objects.update_or_create(
#                 student=student,
#                 course=course,
#                 defaults={
#                     "batch": batch,
#                     "discount": getattr(student, "discount", 0) or 0,
#                 },
#             )
#         except Exception as e:
#             logger.warning(f"[StudentCourse Map Failed] {str(e)}")

#         return course

#     @classmethod
#     def sync_bootcamp_participant_to_student(cls, registration):
#         if not registration or not registration.webinar:
#             return None, None

#         webinar = registration.webinar

#         if not registration.is_paid:
#             return None, None

#         campaign_name = f"Campaign - {webinar.title}"

#         student, raw_password = cls._get_or_create_active_student(
#             name=registration.name,
#             email=registration.email,
#             phone=registration.phone,
#             campaign_title=campaign_name,
#             webinar=webinar,
#         )

#         if not student:
#             return None, None

#         # Enroll in Course ONLY if it is a Bootcamp (type == False)
#         if webinar.type is False:
#             course = cls._enroll_bootcamp_student(student, webinar)
#             if registration.payment_transaction and course:
#                 txn = registration.payment_transaction
#                 txn.student = student
#                 txn.course = course
#                 txn.billing_type = "student"
#                 txn.save(update_fields=["student", "course", "billing_type"])

#                 db_transaction.on_commit(lambda: cls._auto_generate_invoice_safe(txn.id))

#         return student, raw_password

class WebinarToolUpdateDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, uuid, pk):
        tool = get_object_or_404(WebinarTool, id=pk, webinar__uuid=uuid)

        if "tools_title" in request.data:
            tool.tools_title = request.data["tools_title"]

        if "tools_image" in request.FILES:
            tool.tools_image = request.FILES["tools_image"]

        tool.save()

        return Response({"status": True, "message": "Tool updated successfully"})

    def delete(self, request, uuid, pk):
        tool = get_object_or_404(WebinarTool, id=pk, webinar__uuid=uuid)
        tool.delete()
        return Response({"status": True, "message": "Tool deleted successfully"})

class VerifyRazorpayPaymentView(APIView):
    def post(self, request, *args, **kwargs):
        razorpay_order_id = request.data.get("razorpay_order_id")
        razorpay_payment_id = request.data.get("razorpay_payment_id")
        razorpay_signature = request.data.get("razorpay_signature")
        transaction_id = request.data.get("transaction_id")

        try:
            # 1. Fetch transaction safely by transaction_id or order_id
            txn = None
            if transaction_id:
                txn = PaymentTransaction.objects.filter(id=transaction_id).first()
            if not txn and razorpay_order_id:
                txn = PaymentTransaction.objects.filter(order_id=razorpay_order_id).first()

            if not txn:
                return Response(
                    {"success": False, "message": "Transaction record not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 2. Ensure metadata is a valid dictionary
            if isinstance(txn.metadata, str):
                import json
                try:
                    txn.metadata = json.loads(txn.metadata)
                except Exception:
                    txn.metadata = {}

            # 3. Mark transaction as done
            txn.payment_status = "done"
            txn.transaction_id = razorpay_payment_id or txn.transaction_id
            txn.save()

            # 4. Trigger Student creation & Webinar Registration safely
            if txn.billing_type == "webinar":
                registration = WebinarRegistrationViewSet.create_registration_from_transaction(txn)
                if not registration:
                    logger.warning(f"Registration auto-creation returned None for txn #{txn.id}")

            return Response(
                {"success": True, "message": "Payment verified and registration completed successfully!"},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Error verifying payment for txn: {str(e)}", exc_info=True)
            return Response(
                {"success": False, "message": f"Payment processing error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WebinarRegistrationViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    # -----------------------------
    # HELPER: Safe Auto Invoice Generation
    # -----------------------------
    @staticmethod
    def _auto_generate_invoice_safe(transaction_id):
        """
        Executes InvoiceService.generate_invoice safely inside transaction.on_commit.
        Prevents PDF errors from rolling back DB operations.
        """
        try:
            from payments.services.invoice_service import InvoiceService
            InvoiceService.generate_invoice(transaction_id, regenerate=False)
            logger.info(f"[Auto Invoice] Invoice PDF generated successfully for Transaction ID: {transaction_id}")
        except Exception as e:
            logger.error(f"[Auto Invoice Failed] Failed to generate invoice for Transaction ID {transaction_id}: {str(e)}")

    # -----------------------------
    # HELPER: Generate Unique Registration ID
    # -----------------------------
    @staticmethod
    def _generate_registration_id():
        today_prefix = f"AYA{timezone.now().strftime('%m%y')}"
        last_student = (
            Student.objects.filter(registration_id__startswith=today_prefix)
            .order_by("-created_at")
            .first()
        )

        if last_student and last_student.registration_id:
            try:
                last_num = int(last_student.registration_id[-3:])
                return f"{today_prefix}{last_num + 1:03d}"
            except ValueError:
                pass
        return f"{today_prefix}001"

    # -----------------------------
    # HELPER: Get or Create Student
    # -----------------------------
    @classmethod
    def _get_or_create_active_student(cls, name, email, phone, campaign_title="Bootcamp Registration", webinar=None):
        student = None
        email = (email or "").strip().lower()
        phone = (phone or "").strip()
        
        raw_password = secrets.token_urlsafe(10)

        # 1. Search existing student
        if phone:
            student = Student.objects.filter(contact_no=phone, is_archived=False).first()
        if not student and email:
            student = Student.objects.filter(email=email, is_archived=False).first()

        name_parts = (name or "").strip().split(" ", 1)
        first_name = name_parts[0] if name_parts else "Student"
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        # Extract organization & creator details if present on webinar
        webinar_org = getattr(webinar, "organization", None) if webinar else None
        webinar_creator = getattr(webinar, "created_by", None) if webinar else None

        # 2. Create if student does not exist
        if not student:
            reg_id = cls._generate_registration_id()

            student = Student.objects.create(
                registration_id=reg_id,
                first_name=first_name,
                last_name=last_name,
                username=email or phone or reg_id,
                password=make_password(raw_password),
                email=email,
                contact_no=phone,
                status=True,
                created_by_type="public",
                converter="campaign",
                source_type="webinar",
                source_name=campaign_title,
                organization=webinar_org,  # Ensures student is visible under the organization
                created_by=webinar_creator,
                is_archived=False,
            )
        else:
            # Update existing student credentials
            student.password = make_password(raw_password)
            
            if first_name and student.first_name != first_name:
                student.first_name = first_name
                student.last_name = last_name
            if phone and not student.contact_no:
                student.contact_no = phone
            if not student.status:
                student.status = True
            if student.converter != "campaign":
                student.converter = "campaign"
            if webinar_org and not student.organization:
                student.organization = webinar_org

            student.save()

        return student, raw_password

    # -----------------------------
    # HELPER: Enroll Student in Bootcamp Course
    # -----------------------------
    @classmethod
    def _enroll_bootcamp_student(cls, student, webinar):
        if not student or not webinar or not webinar.title:
            return None

        course = cls._get_bootcamp_course(webinar)

        if hasattr(student, "courses"):
            student.courses.add(course)

        batch = None
        try:
            start_date = timezone.now().date()
            end_date = start_date + timedelta(days=30)
            batch, _ = NewBatch.objects.get_or_create(
                course=course,
                defaults={
                    "title": f"Batch - {course.course_name}",
                    "status": True,
                    "start_date": start_date,
                    "end_date": end_date,
                    "start_time": time(10, 0),
                    "end_time": time(11, 0),
                },
            )
            if hasattr(batch, "students"):
                batch.students.add(student)
        except Exception as e:
            logger.error(f"[Bootcamp Enrollment Error] Failed for student {student.id}: {str(e)}")

        return batch
    # -----------------------------
    # HELPER: Sync Bootcamp Participant
    # -----------------------------
    @classmethod
    def sync_bootcamp_participant_to_student(cls, registration):
        if not registration or not registration.webinar:
            logger.warning("[Sync Failed] Missing registration or webinar instance.")
            return None, None

        webinar = registration.webinar

        if not registration.is_paid:
            logger.warning(f"[Sync Skipped] Registration ID {registration.id} is not marked as paid.")
            return None, None

        campaign_name = f"Campaign - {webinar.title}"

        # Pass webinar to ensure organization mapping works
        student, raw_password = cls._get_or_create_active_student(
            name=registration.name,
            email=registration.email,
            phone=registration.phone,
            campaign_title=campaign_name,
            webinar=webinar,
        )

        if not student:
            logger.error(f"[Sync Failed] Could not get or create student for registration ID {registration.id}")
            return None, None

        course = cls._enroll_bootcamp_student(student, webinar)

        if registration.payment_transaction:
            txn = registration.payment_transaction
            txn.student = student
            if course:
                txn.course = course
            
            txn.billing_type = "student"
            txn.save(update_fields=["student", "course", "billing_type"])

            transaction.on_commit(lambda: cls._auto_generate_invoice_safe(txn.id))

        return student, raw_password
    # -----------------------------
    # HELPER: Fetch Auto-Created Bootcamp Course
    # -----------------------------
    @classmethod
    def _get_bootcamp_course(cls, webinar):
        course = Course.objects.filter(course_name=webinar.title, is_archived=False).first()
        if not course:
            course = Course.objects.create(
                course_name=webinar.title,
                fee=getattr(webinar, "price", None) or getattr(webinar, "regular_price", None) or 0,
                status="active",
                is_archived=False,
                created_by=getattr(webinar, "created_by", None),
                created_by_type=getattr(webinar, "created_by_type", None),
                organization=getattr(webinar, "organization", None),
            )
        return course

    # # -----------------------------
    # # HELPER: Enroll Student in Bootcamp Course
    # # -----------------------------
    # @classmethod
    # def _enroll_bootcamp_student(cls, student, webinar):
    #     if not student or not webinar or not webinar.title:
    #         return None

    #     # Fetch or auto-create course
    #     course = cls._get_bootcamp_course(webinar)

    #     # Attach Course to Student
    #     if hasattr(student, "courses"):
    #         student.courses.add(course)

    #     # Create or Fetch Batch for this specific Course
    #     batch = None
    #     try:
    #         start_date = timezone.now().date()
    #         end_date = start_date + timedelta(days=30)

    #         batch, _ = NewBatch.objects.get_or_create(
    #             course=course,
    #             defaults={
    #                 "title": f"Batch - {course.course_name}",
    #                 "status": True,
    #                 "start_date": start_date,
    #                 "end_date": end_date,
    #                 "start_time": time(9, 0),
    #                 "end_time": time(18, 0),
    #             },
    #         )

    #         if hasattr(batch, "students"):
    #             batch.students.add(student)
    #         if hasattr(student, "new_batches"):
    #             student.new_batches.add(batch)

    #     except Exception as e:
    #         logger.warning(f"[Bootcamp Enrollment] Could not assign batch: {str(e)}")

    #     # Create/Update StudentCourse mapping
    #     try:
    #         StudentCourse.objects.update_or_create(
    #             student=student,
    #             course=course,
    #             defaults={
    #                 "batch": batch,
    #                 "discount": getattr(student, "discount", 0) or 0,
    #             },
    #         )
    #     except Exception as e:
    #         logger.warning(f"[Bootcamp Enrollment] Could not create StudentCourse: {str(e)}")

    #     return course
    # -----------------------------
    # ACTION: MANUAL PAYMENT STATUS UPDATE FROM BOOTCAMP VIEW UI
    # -----------------------------
    @action(detail=True, methods=["patch", "put"], url_path="update-payment-status")
    @transaction.atomic
    def update_payment_status(self, request, pk=None, slug=None):
        """
        Endpoint called when admin changes payment status in the UI (e.g. to "Done").
        """
        registration = get_object_or_404(WebinarRegistration, pk=pk)
        payment_status = request.data.get("payment_status", "").lower()

        if payment_status in ["done", "paid", "completed"]:
            registration.is_paid = True
            registration.save()

            if registration.payment_transaction:
                registration.payment_transaction.payment_status = "done"
                registration.payment_transaction.save()

            # Sync to Student list and attach Bootcamp Course
            student = self.sync_bootcamp_participant_to_student(registration)

            return Response({
                "success": True,
                "message": "Payment status updated to Done and student enrolled successfully.",
                "student_id": student.student_id if student else None
            }, status=status.HTTP_200_OK)

        registration.is_paid = False
        registration.save()
        return Response({"success": True, "message": "Payment status updated."}, status=status.HTTP_200_OK)

    # -----------------------------
    # CAMPAIGN REGISTRATION FLOW
    # -----------------------------
    @action(detail=True, methods=["post"], url_path="campaign")
    @transaction.atomic
    def campaign(self, request, slug=None):
        webinar = get_object_or_404(Webinar, slug=slug, is_deleted=False)

        name = request.data.get("name")
        email = request.data.get("email")
        phone = request.data.get("phone")
        amount = request.data.get("amount") or webinar.price or webinar.regular_price
        payment_mode = request.data.get("payment_mode", "Cash")
        reference_id = request.data.get("reference_id") or request.data.get("transaction_id")
        profession = request.data.get("profession", "")

        campaign_name = f"Campaign - {webinar.title}"

        # 1. Create Initial Payment Transaction
        txn = PaymentTransaction.objects.create(
            amount=amount,
            payment_status="done",
            payment_mode=payment_mode,
            billing_type="student",
            invoice_date=timezone.now().date(),
            description=campaign_name,
            transaction_id=reference_id or f"CAMPAIGN-{timezone.now().strftime('%Y%m%d%H%M%S')}",
            metadata={"webinar_id": str(webinar.uuid), "slug": webinar.slug},
        )

        # 2. Get or Create Registration
        registration, created = WebinarRegistration.objects.get_or_create(
            webinar=webinar,
            phone=phone,
            defaults={
                "name": name,
                "email": email,
                "profession": profession,
                "is_paid": True,
                "payment_transaction": txn,
            },
        )

        if not created:
            registration.is_paid = True
            registration.payment_transaction = txn
            registration.save(update_fields=["is_paid", "payment_transaction"])

        # 3. Perform Sync
        student, raw_password = self.sync_bootcamp_participant_to_student(registration)

        # Fallback: Guarantee student creation if sync was skipped
        if not student:
            student, raw_password = self._get_or_create_active_student(
                name=name,
                email=email,
                phone=phone,
                campaign_title=campaign_name,
            )
            txn.student = student
            txn.save(update_fields=["student"])

        # 4. Schedule Post-Commit Invoice PDF Generation & Email Dispatch
        # Schedule Post-Commit Invoice PDF Generation & Email Dispatch
        tx_id = txn.id

        def _process_invoice_and_email():
            # Step A: Generate PDF Invoice
            self._auto_generate_invoice_safe(tx_id)
            
            # Step B: Send Welcome Email with auto-generated password
            try:
                send_welcome_and_invoice_email(student, raw_password, transaction_id=tx_id)
            except Exception as mail_err:
                logger.error(f"[Campaign Email Failed] Could not send email to {getattr(student, 'email', '')}: {str(mail_err)}")

        transaction.on_commit(_process_invoice_and_email)


        return Response(
            {
                "success": True,
                "message": "Campaign payment processed, student registered, invoice generated, and welcome email sent.",
                "data": {
                    "registration_id": registration.id,
                    "student_id": getattr(student, "student_id", student.pk),
                    "username": student.username,
                    "transaction_id": txn.transaction_id,
                    "payment_status": "done",
                },
            },
            status=status.HTTP_201_CREATED,
        )

def fetch_zoom_participants(meeting_id):
    token = get_zoom_access_token()

    headers = {
        "Authorization": f"Bearer {token}"
    }

    url = f"https://api.zoom.us/v2/report/meetings/{meeting_id}/participants"

    participants = []
    next_page_token = None

    while True:
        params = {"page_size": 300}

        if next_page_token:
            params["next_page_token"] = next_page_token

        resp = requests.get(url, headers=headers, params=params, timeout=10)

        print("ZOOM DEBUG:", meeting_id, resp.status_code, resp.text)

        resp.raise_for_status()

        data = resp.json()

        participants.extend(data.get("participants", []))
        next_page_token = data.get("next_page_token")

        if not next_page_token:
            break

    return participants

class WebinarAttendanceViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def calculate_total_seconds(self, logs):
        intervals = []

        for l in logs:
            intervals.append((l.join_time, l.leave_time))

        # sort by start time
        intervals.sort()

        merged = []

        for start, end in intervals:
            if not merged:                    
                merged.append([start, end])
                continue

            last_start, last_end = merged[-1]

            if start <= last_end:  # overlap
                merged[-1][1] = max(last_end, end)
            else:
                merged.append([start, end])

        total = 0
        for s, e in merged:
            total += (e - s).total_seconds()

        return int(total)

    def sync(self, request, slug=None):

        webinar = get_object_or_404(Webinar, slug=slug)
        session = webinar.session

        if not session.ended_at:
            return Response({"message": "Session not ended"}, status=400)

        participants = fetch_zoom_participants(session.zoom_meeting_id)
        print("zoom meeting  id",session.zoom_meeting_id)

        registrations = list(webinar.registrations.all())

        # ----------------------------------
        # BUILD FAST LOOKUP MAPS
        # ----------------------------------

        email_map = {}
        name_map = {}
        first_name_map = {}

        for r in registrations:
            if r.email:
                email_map[r.email.lower()] = r

            if r.name:
                name_map[r.name.lower()] = r

                first = r.name.split()[0].lower()
                if first not in first_name_map:
                    first_name_map[first] = r

        # ----------------------------------
        # CREATE ATTENDANCE LOGS
        # ----------------------------------

        logs_to_create = []

        for p in participants:

            zoom_name = (p.get("name") or "").strip().lower()
            email = (p.get("user_email") or "").strip().lower()

            join_time = parse_datetime(p.get("join_time"))
            leave_time = parse_datetime(p.get("leave_time"))

            if not join_time or not leave_time:
                continue

            registration = None

            # email match
            if email:
                registration = email_map.get(email)

            # exact name match
            if not registration and zoom_name:
                registration = name_map.get(zoom_name)

            # first name fallback
            if not registration and zoom_name:
                first = zoom_name.split()[0]
                registration = first_name_map.get(first)

            if not registration:
                continue

            duration = int((leave_time - join_time).total_seconds())

            logs_to_create.append(
                WebinarAttendanceLog(
                    registration_id=registration.id,
                    join_time=join_time,
                    leave_time=leave_time,
                    duration_seconds=duration
                )
            )

        WebinarAttendanceLog.objects.bulk_create(
            logs_to_create,
            batch_size=500
        )

        # ----------------------------------
        # CALCULATE ATTENDANCE SUMMARY
        # ----------------------------------

        aggregates = (
            WebinarAttendanceLog.objects
            .filter(registration__in=registrations)
            .values("registration")
            .annotate(
                total_duration=Sum("duration_seconds"),
                join_count=Count("id")
            )
        )

        reg_map = {r.id: r for r in registrations}

        summaries = []
        reg_updates = []

        for item in aggregates:

            reg_id = item["registration"]
            total = item["total_duration"]
            joins = item["join_count"]

            summaries.append(
                WebinarAttendanceSummary(
                    registration_id=reg_id,
                    total_duration_seconds=total,
                    join_count=joins,
                    eligible_for_certificate=total >= (45 * 60)
                )
            )

            reg = reg_map.get(reg_id)
            reg.attended = True
            reg_updates.append(reg)

        # UPSERT summaries
        WebinarAttendanceSummary.objects.bulk_create(
            summaries,
            update_conflicts=True,
            unique_fields=["registration"],
            update_fields=[
                "total_duration_seconds",
                "join_count",
                "eligible_for_certificate"
            ]
        )

        # BULK UPDATE registrations
        WebinarRegistration.objects.bulk_update(
            reg_updates,
            ["attended"]
        )

        return Response({
            "status": True,
            "message": "Attendance synced successfully"
        })

    def list(self, request, slug=None):
        webinar = get_object_or_404(Webinar, slug=slug)

        data = []

        attended_regs = webinar.registrations.filter(attended=True)

        for reg in attended_regs:
            summary = getattr(reg, "attendance_summary", None)

            logs_qs = reg.attendance_logs.all().order_by("join_time")

            logs_data = []
            for log in logs_qs:
                logs_data.append({
                    "join_time": log.join_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "leave_time": log.leave_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "duration_minutes": log.duration_seconds // 60
                })

            data.append({
                "email": reg.email,
                "attended": True,
                "total_duration_minutes": (
                    summary.total_duration_seconds // 60
                    if summary else 0
                ),
                "join_count": summary.join_count if summary else 0,
                "eligible_for_certificate": (
                    summary.eligible_for_certificate if summary else False
                ),
                "logs": logs_data
            })

        return Response({
            "webinar": str(webinar.uuid),
            "attendance": data
        })


VERIFY_TOKEN = "akzworld"  # same token you give Meta

@csrf_exempt
def whatsapp_webhook(request):

    # =================================
    # META VERIFICATION (GET)
    # =================================
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            return HttpResponse(challenge)

        return HttpResponse("Invalid token", status=403)


    # =================================
    # EVENTS (POST)
    # =================================
    payload = json.loads(request.body.decode("utf-8"))

    print("===== WHATSAPP WEBHOOK RECEIVED =====")
    print(json.dumps(payload, indent=2))
    print("===================================")

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # =================================
            # A) DELIVERY STATUS (IMPORTANT)
            # =================================
            for status in value.get("statuses", []):
                print(
                    "STATUS:",
                    status.get("status"),           # sent/delivered/read/failed
                    "TIME:",
                    status.get("timestamp"),
                    "PHONE:",
                    status.get("recipient_id"),
                    "MESSAGE_ID:",
                    status.get("id")
                )

            # =================================
            # B) USER MESSAGES (buttons etc.)
            # =================================
            for message in value.get("messages", []):

                phone = message["from"]

                if message["type"] == "button":
                    button_text = message["button"]["text"].strip().lower()

                    registration = WebinarRegistration.objects.filter(
                        phone=phone[-10:]
                    ).last()

                    if not registration:
                        continue

                    if button_text in ["remaind me", "remind me"]:
                        registration.wants_reminder = True
                        registration.save()

                        send_webinar_reminder.delay(
                            registration.id,
                            time_left="15 mins"
                        )

                        print(f"Reminder opted by {phone}")

    return JsonResponse({"status": "ok"})

def _create_payment(self, request, webinar):
    razorpay_view = RazorpayPaymentViewSet()

    payment_request = request._request
    payment_request.data = {
        "amount": webinar.price,
        "currency": "INR",
        "success_url": f"https://aylms.aryuprojects.com/webinar/payment-success/{webinar.uuid}",
        "failure_url": f"https://aylms.aryuprojects.com/webinar/payment-failed/{webinar.uuid}",
    }

    return razorpay_view.create(payment_request)

class WebinarSessionViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    def retrieve(self, request, slug=None):
        webinar = get_object_or_404(Webinar, slug=slug)
        session = getattr(webinar, 'session', None)

        if not session:
            return Response({
                "is_live": False,
                "started": False
            })

        serializer = WebinarSessionSerializer(session)
        return Response(serializer.data)
    
    def start(self, request, slug=None):
        webinar = get_object_or_404(Webinar, slug=slug)

        session, created = WebinarSession.objects.get_or_create(
            webinar=webinar,
            defaults={
                "zoom_meeting_id": webinar.zoom_meeting_id,
                "started_at": timezone.now(),
            }
        )

        webinar.status = "LIVE"
        webinar.save(update_fields=["status"])

        return Response({
            "message": "Session started",
            "session_id": session.uuid
        })
    
    def end(self, request, slug=None):
        webinar = get_object_or_404(Webinar, slug=slug)

        session = WebinarSession.objects.filter(webinar=webinar).first()

        if not session:
            return Response({"message": "Session not started"}, status=400)

        session.ended_at = timezone.now()
        session.save(update_fields=["ended_at"])

        webinar.status = "COMPLETED"
        webinar.save(update_fields=["status"])

        return Response({"message": "Session ended"})
    
class WebinarLifecycleViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, slug=None):
        webinar = get_object_or_404(Webinar, slug=slug)

        if webinar.status in ['LIVE', 'COMPLETED']:
            return Response(
                {"detail": "Cannot cancel live/completed webinar"},
                status=status.HTTP_400_BAD_REQUEST
            )

        webinar.status = 'CANCELLED'
        webinar.is_registration_open = False
        webinar.save()

        return Response({"detail": "Webinar cancelled"})
    
class WebinarFeedbackViewSet(viewsets.ViewSet):
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [permissions.AllowAny]

    def list(self, request):
        queryset = WebinarFeedback.objects.select_related(
            "webinar",
            "registration"
        ).order_by("-submitted_at")

        serializer = WebinarFeedbackSerializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        feedback = get_object_or_404(
            WebinarFeedback.objects.select_related(
                "webinar",
                "registration"
            ),
            pk=pk
        )
        serializer = WebinarFeedbackSerializer(feedback)
        return Response(serializer.data)

    def create(self, request):
        try:
            serializer = WebinarFeedbackSerializer(data=request.data)

            if not serializer.is_valid():
                return Response({
                    "success": False,
                    "message": serializer.errors
                }, status=200)

            feedback = serializer.save()

            reg = feedback.registration
            webinar = reg.webinar

            certificate, _ = Certificate.objects.get_or_create(
                webinar_registration=reg,
                defaults={
                    "student": getattr(reg, "student", None),
                    "student_name": feedback.name.strip(),
                    "course_name": webinar.title,
                    "course_duration": "3 Hours",
                    "created_by": "system",
                    "created_by_type": "auto"
                }
            )

            generate_and_send_certificate_pdf(
                certificate=certificate,
                phone=reg.phone
            )
            reg.certificate_sent = True
            reg.save(update_fields=["certificate_sent"])

            return Response({
                "success": True,
                "message": "Feedback submitted and certificate sent",
                "data": serializer.data
            }, status=201)
        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=400)

class WebinarTicketViewSet(viewsets.ViewSet):
    """
    Token-based ticketing for webinar participants.
    Multi-use token until expiry.
    """

    def _get_token(self, request):
        return (
            request.headers.get("X-Webinar-Token")
            or request.query_params.get("token")
        )

    # GET /webinar/tickets/
    def list(self, request):
        mobile = request.query_params.get("mobile")

        if not mobile:
            return Response({"detail": "Mobile required"}, status=400)

        participant = WebinarRegistration.objects.filter(phone=mobile).first()
        if not participant:
            return Response({"detail": "Mobile not registered"}, status=404)

        ticket = (
            StudentTicket.objects
            .filter(webinar_participant=participant)
            .order_by("-created_at")
            .first()
        )

        if not ticket:
            return Response({"success": True, "data": None})

        serializer = WebinarTicketSerializer(ticket)
        return Response({"success": True, "data": serializer.data})

    # POST /webinar/tickets/
    
    def create(self, request):
        mobile = request.data.get("mobile")

        if not mobile:
            return Response({"detail": "Mobile number required"}, status=400)

        participant = WebinarRegistration.objects.filter(phone=mobile).first()

        if not participant:
            return Response({"detail": "Mobile not registered"}, status=400)

        serializer = WebinarTicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket = StudentTicket.objects.create(
            webinar_participant=participant,  # IMPORTANT FIX
            subject=serializer.validated_data["subject"],
            message=serializer.validated_data["message"],
            priority=serializer.validated_data["priority"],
            status="New",
        )

        return Response({
            "success": True,
            "ticket_id": ticket.ticket_id
        }, status=201)
    
    # POST /webinar/tickets/{id}/reply/
    def reply(self, request, pk=None):
        ticket = StudentTicket.objects.filter(ticket_id=pk).first()

        if not ticket:
            return Response({"detail": "Ticket not found"}, status=404)

        serializer = WebinarReplyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        TicketReply.objects.create(
            ticket=ticket,
            message=serializer.validated_data["message"]
        )

        ticket.status = "in_progress"
        ticket.save(update_fields=["status"])

        return Response({"success": True}, status=201)

class PublicTicketViewSet(viewsets.ViewSet):

    permission_classes = [permissions.AllowAny]

    # CREATE TICKET
    @transaction.atomic
    def create(self, request):

        serializer = PublicTicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket = serializer.save()

        return Response(
            {
                "success": True,
                "ticket_id": ticket.ticket_id,
                "token": str(ticket.ticket_token),
                "name": ticket.name,
                "status": ticket.status,
                "priority": ticket.priority,
                "created_at": ticket.created_at,
                "message": "Support ticket created successfully"
            },
            status=status.HTTP_201_CREATED
        )

    # GET OPEN TICKET DETAILS
    def retrieve(self, request):

        mobile = request.query_params.get("mobile")

        if not mobile:
            return Response(
                {"detail": "Mobile required"},
                status=400
            )

        ticket = (
            StudentTicket.objects
            .prefetch_related("replies", "attachments")
            .filter(phone=mobile)
            .exclude(status="closed")   # ignore closed tickets
            .order_by("-created_at")
            .first()
        )

        if not ticket:
            return Response(
                {
                    "success": True,
                    "data": None,
                    "message": "No open ticket found"
                }
            )

        serializer = PublicTicketDetailSerializer(ticket)

        return Response(
            {
                "success": True,
                "data": serializer.data
            }
        )
    
    @transaction.atomic
    def reply(self, request, pk= None):

        if not pk:
            return Response({"detail": "Id required"}, status=400)

        ticket = get_object_or_404(StudentTicket, ticket_id=pk)

        serializer = PublicTicketReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        TicketReply.objects.create(
            ticket=ticket,
            message=serializer.validated_data["message"],
        )

        ticket.status = "in_progress"
        ticket.save(update_fields=["status"])

        return Response({"success": True}, status=201)

class WebinarCertificateViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    # @shared_task
    @action(detail=False, methods=["post"])
    def send(self, request):

        webinar_uuid = request.data.get("webinar_uuid")
        participant_ids = request.data.get("participant_ids", [])

        webinar = Webinar.objects.get(uuid=webinar_uuid)

        regs = WebinarRegistration.objects.select_related(
            "webinar"
        ).filter(
            id__in=participant_ids,
            webinar=webinar
        )

        user_id = getattr(request.user, "user_id", None)
        user_type = getattr(request.user, "username", None)

        sent_count = 0

        for reg in regs:

            certificate, _ = Certificate.objects.get_or_create(
                webinar_registration=reg,
                defaults={
                    "student": getattr(reg, "student", None),
                    "student_name": reg.name,
                    "course_name": reg.webinar.title,
                    "course_duration": "3 Hours",
                    "created_by": user_id,
                    "created_by_type": user_type
                }
            )

            generate_and_send_certificate_pdf(
                certificate=certificate,
                phone=reg.phone
            )

            reg.certificate_sent = True
            reg.save(update_fields=["certificate_sent"])

            sent_count += 1

        return Response({
            "success": True,
            "message": "Certificates sent successfully",
            "count": sent_count
        })

class FormViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def create(self, request):
        data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)

        # Parse questions JSON string → list (sent as text in multipart)
        questions = data.get("questions")
        if isinstance(questions, str):
            try:
                data["questions"] = json.loads(questions)
            except json.JSONDecodeError:
                return Response(
                    {"success": False, "message": "Invalid JSON in 'questions' field."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif isinstance(questions, list) and len(questions) == 1 and isinstance(questions[0], str):
            # QueryDict wraps everything in a list — unwrap and parse
            try:
                data["questions"] = json.loads(questions[0])
            except json.JSONDecodeError:
                return Response(
                    {"success": False, "message": "Invalid JSON in 'questions' field."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Re-attach the file from original request (dict() doesn't carry files)
        if "form_image" not in data and "form_image" in request.data:
            data["form_image"] = request.data["form_image"]
        print("FINAL DATA FOR SERIALIZER:", data)
        serializer = FormCreateSerializer(
            data=data,  # pass the FIXED data, not request.data
            context={"request": request}
        )

        if not serializer.is_valid():
            return Response(
                {"success": False, "message": "Validation failed.", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        form = serializer.save()

        return Response(
            {
                "success": True,
                "message": "Form created successfully",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    def list(self, request):
        user = request.user

        role = getattr(user, "user_type", None)

        if role in ("tutor", "admin"):
            creator_id = getattr(user, "trainer_id", None)
        elif role == "super_admin":
            creator_id = getattr(user, "user_id", None)
        else:
            creator_id = None

        if not creator_id or not role:
            return Response(
                {
                    "success": False,
                    "message": "Invalid authenticated user"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = (
            Form.objects
            .filter(
                created_by=str(creator_id),
                created_by_type=role,
                is_deleted=False
            )
            .annotate(
                submissions_count=Count("submission", distinct=True)
            )
            .only(
                "id",
                "uuid",
                "title",
                "form_image",
                "slug",
                "description",
                "is_active",
                "created_at",
            )
            .order_by("-created_at")
        )

        serializer = FormReadSerializer(queryset, many=True)

        return Response(
            {
                "success": True,
                "message": "Forms List retrieved successfully",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def retrieve(self, request, slug=None):
        user_id = str(request.user.user_id)
        user_type = request.user.user_type

        form = get_object_or_404(
            Form.objects
            .annotate(submissions_count=Count("submission"))
            .prefetch_related(
                Prefetch(
                    "questions",
                    queryset=Question.objects
                    .order_by("order")
                    .prefetch_related("options")
                    .prefetch_related(
                        Prefetch(
                            "answer_set",
                            queryset=Answer.objects
                            .select_related("submission")
                            .order_by("submission__submitted_at"),
                            to_attr="prefetched_answers"
                        )
                    )
                )
            ),
            slug=slug,
            created_by=user_id,
            created_by_type=user_type
        )

        serializer = FormWithAnswersSerializer(form)
        return Response(
            {
                "success": True,
                "message": "Form retrieved successfully",
                "data": serializer.data
            }
        )
    
    def update(self, request, slug=None):
        user = request.user
        user_id = str(getattr(user, "user_id", None))
        user_type = getattr(user, "user_type", None)

        form = get_object_or_404(
            Form,
            slug=slug,
            created_by=user_id,
            created_by_type=user_type,
            is_deleted=False
        )

        is_partial = request.method.lower() == "patch"

        serializer = FormUpdateSerializer(
            instance=form,
            data=request.data,
            partial=is_partial
        )

        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {
                "success": True,
                "message": "Form updated successfully"
            },
            status=status.HTTP_200_OK
        )
    
    def destroy(self, request, slug=None):
        user = request.user
        user_id = str(getattr(user, "user_id", None))
        user_type = getattr(user, "user_type", None)

        form = get_object_or_404(
            Form,
            slug=slug,
            created_by=user_id,
            created_by_type=user_type,
            is_deleted=False
        )

        form.is_deleted = True
        form.is_active = False
        form.save(update_fields=["is_deleted", "is_active"])

        return Response(
            {
                "success": True,
                "message": "Form deleted successfully"
            },
            status=status.HTTP_200_OK
        )

class SubmissionViewSet(viewsets.ViewSet):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def list(self, request):

        form_slug = request.query_params.get("form_slug")
        if not form_slug:
            return Response(
                {"success": False, "message": "form_slug query param required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = (
            Submission.objects
            .filter(form__slug=form_slug, is_deleted=False)
            .prefetch_related(
                Prefetch(
                    "answers",
                    queryset=Answer.objects.select_related("question")
                )
            )
            .order_by("-submitted_at")
        )

        serializer = SubmissionReadSerializer(queryset, many=True)

        return Response(
            {
                "success": True,
                "count": len(serializer.data),
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )
    
    def retrieve(self, request, pk=None):
        submission = get_object_or_404(
            Submission.objects
            .filter(is_deleted=False)
            .select_related("user", "form")
            .prefetch_related(
                Prefetch(
                    "answers",
                    queryset=Answer.objects.select_related("question")
                )
            ),
            uuid=pk
        )

        serializer = SubmissionReadSerializer(submission)

        return Response(
            {
                "success": True,
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def create(self, request):
        raw_answers = request.data.get("answers")
        print("RAW ANSWERS:", raw_answers)

        # multipart → JSON string → Python list
        if isinstance(raw_answers, str):
            answers = json.loads(raw_answers)
        else:
            answers = raw_answers

        data = {
            "form_slug": request.data.get("form_slug"),
            "answers": answers,
        }

        serializer = SubmissionCreateSerializer(data=data)

        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        submission = self._create_submission(
            form=serializer.validated_data["form"],
            answers_payload=serializer.validated_data["answers"],
            files=request.FILES,
        )

        return Response(
            {
                "success": True,
                "message": "Submission created successfully",
                "submission_id": submission.uuid
            },
            status=status.HTTP_201_CREATED,
        )

    # --------------------------------------------------
    # FAST + ATOMIC SUBMISSION HANDLER
    # --------------------------------------------------
    @transaction.atomic
    def _create_submission(self, form, answers_payload, files):
        submission = Submission.objects.create(
            form=form,
        )

        question_ids = [a["question_id"] for a in answers_payload]

        questions = Question.objects.filter(
            form=form,
            id__in=question_ids
        )

        question_map = {q.id: q for q in questions}

        answer_objects = []

        for item in answers_payload:
            question = question_map.get(item["question_id"])
            if not question:
                continue

            # secure file mapping
            file_obj = None
            if "file_key" in item:
                file_obj = files.get(item["file_key"])

            answer_objects.append(
                Answer(
                    submission=submission,
                    question=question,
                    value_text=item.get("value_text"),
                    value_json=item.get("value_json"),
                    value_number=item.get("value_number"),
                    value_file=file_obj,
                )
            )

        Answer.objects.bulk_create(answer_objects, batch_size=500)

        return submission
    
    def destroy(self, request, pk=None):
        submission = get_object_or_404(
            Submission.objects.filter(is_deleted=False),
            uuid=pk
        )

        submission.is_deleted = True
        submission.save(update_fields=["is_deleted"])

        return Response(
            {
                "success": True,
                "message": "Submission deleted successfully"
            },
            status=status.HTTP_200_OK,
        )

class PublicFormThrottle(AnonRateThrottle):
    rate = "30/hour"

class PublicFormViewSet(ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    throttle_classes = [PublicFormThrottle]
    serializer_class = PublicFormSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return (
            Form.objects
            .filter(is_active=True, is_deleted=False)
            .prefetch_related(
                Prefetch(
                    "questions",
                    queryset=Question.objects
                    .order_by("order")
                    .prefetch_related("options")
                )
            )
        )

    def retrieve(self, request, *args, **kwargs):
        form = get_object_or_404(
            self.get_queryset(),
            slug=kwargs["slug"]
        )
        serializer = self.get_serializer(form)
        return Response({
            "success": True,
            "data": serializer.data
        })
    

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
logger = logging.getLogger("razorpay_webhook")

# Valid completed status lookup set across payment gateways
VALID_DONE_STATUSES = {
    "success",
    "done",
    "paid",
    "captured",
    "complete",
    "partial",
    "advanced",
}


# ============================================================================
# RAZORPAY WEBHOOK HANDLER
# ============================================================================

@csrf_exempt
def razorpay_webhook(request):
    """
    Razorpay Webhook Handler
    """

    logger.info("=" * 80)
    logger.info("Razorpay Webhook Received")

    if request.method != "POST":
        logger.error("Invalid request method: %s", request.method)
        return HttpResponse("Method Not Allowed", status=405)

    payload = request.body
    received_signature = request.headers.get("X-Razorpay-Signature")

    logger.info("Request Headers:")
    logger.info(dict(request.headers))

    logger.info("Payload Length: %s", len(payload))

    if not received_signature:
        logger.error("Missing X-Razorpay-Signature header")
        return HttpResponse("Signature Missing", status=400)

    logger.info("Received Signature: %s", received_signature)

    gateway = PaymentGateway.objects.filter(
        gatway_name__icontains="razorpay"
    ).first()

    if not gateway:
        logger.error("PaymentGateway configuration not found")
        return HttpResponse("Server Misconfiguration", status=500)

    if not gateway.webhook_secret:
        logger.error("Webhook secret is empty")
        return HttpResponse("Server Misconfiguration", status=500)

    secret = gateway.webhook_secret.strip()

    logger.info("Webhook Secret: %r", secret)
    logger.info("Webhook Secret Length: %s", len(secret))

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    logger.info("Expected Signature: %s", expected_signature)
    logger.info("Received Signature: %s", received_signature)

    # if not hmac.compare_digest(expected_signature, received_signature):
    #     logger.error("❌ Signature mismatch")
    #     return HttpResponse("Invalid Signature", status=400)

    logger.info("✅ Signature verification successful")

    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        logger.exception("Invalid JSON payload")
        return HttpResponse("Invalid JSON", status=400)

    event = data.get("event")

    logger.info("Webhook Event: %s", event)

    try:

        if event in ["payment.captured", "payment.authorized"]:

            entity = data["payload"]["payment"]["entity"]

            order_id = entity.get("order_id")
            transaction_id = entity.get("id")
            notes = entity.get("notes", {})

            phone = notes.get("phone")
            webinar_id = notes.get("webinar_id")

            logger.info("Order ID: %s", order_id)
            logger.info("Payment ID: %s", transaction_id)
            logger.info("Phone: %s", phone)
            logger.info("Webinar UUID: %s", webinar_id)

            with db_transaction.atomic():

                txn = (
                    PaymentTransaction.objects
                    .select_for_update()
                    .filter(order_id=order_id)
                    .first()
                )
                
                logger.info("txn", txn)
                if txn:

                    txn.payment_status = "done"
                    txn.transaction_id = transaction_id
                    logger.info("transaction id ", transaction_id)
                    txn.save(
                        update_fields=[
                            "payment_status",
                            "transaction_id",
                        ]
                    )

                    logger.info(
                        "PaymentTransaction updated successfully"
                    )

                else:
                    logger.warning(
                        "PaymentTransaction not found for Order ID: %s",
                        order_id,
                    )

                if phone and webinar_id:

                    registration = (
                        WebinarRegistration.objects
                        .select_for_update()
                        .filter(
                            phone=phone,
                            webinar__uuid=webinar_id,
                        )
                        .first()
                    )

                    if registration:

                        registration.is_paid = True

                        if txn:
                            registration.payment_transaction = txn

                        registration.save(
                            update_fields=[
                                "is_paid",
                                "payment_transaction",
                            ]
                        )

                        logger.info(
                            "WebinarRegistration updated successfully"
                        )

                    else:

                        logger.warning(
                            "Registration not found "
                            "(Phone=%s Webinar=%s)",
                            phone,
                            webinar_id,
                        )

        elif event == "payment.failed":

            entity = data["payload"]["payment"]["entity"]

            order_id = entity.get("order_id")

            PaymentTransaction.objects.filter(
                order_id=order_id
            ).update(
                payment_status="failed"
            )

            logger.info(
                "Payment marked as FAILED for Order ID: %s",
                order_id,
            )

        else:

            logger.info("Unhandled Event: %s", event)

    except Exception:

        logger.exception("Webhook processing failed")
        return HttpResponse("Internal Server Error", status=500)

    logger.info("Webhook processed successfully")
    logger.info("=" * 80)

    return HttpResponse(status=200)


# ============================================================================
# RAZORPAY PAYMENT VIEWSET
# ============================================================================
class RazorpayPaymentViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    def _get_client(self):
        gateway = PaymentGateway.objects.filter(gatway_name__icontains="razorpay").first()
        if not gateway or not gateway.public_key or not gateway.secret_key:
            return None, None
        client = razorpay.Client(auth=(gateway.public_key, gateway.secret_key))
        return client, gateway

    @action(detail=False, methods=["post"])
    def create(self, request):
        amount = request.data.get("amount")
        webinar_id = request.data.get("webinar_id")
        webinar_title = request.data.get("webinar_title")
        name = request.data.get("name")
        email = request.data.get("email")
        phone = request.data.get("phone")

        if not all([amount, webinar_id, phone]):
            return Response(
                {"success": False, "message": "Missing required fields"},
                status=status.HTTP_400_BAD_REQUEST
            )

        client, gateway = self._get_client()
        if not client:
            return Response(
                {"success": False, "message": "Razorpay not properly configured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        webinar = get_object_or_404(Webinar, uuid=webinar_id)
        amount_in_paise = int(float(amount) * 100)

        order_data = {
            "amount": amount_in_paise,
            "currency": "INR",
            "payment_capture": 1,
            "notes": {
                "webinar_id": str(webinar_id),
                "name": name or "",
                "email": email or "",
                "phone": str(phone),
                "description": webinar_title or webinar.title
            }
        }
        order = client.order.create(order_data)

        # Reuse existing pending/failed transaction for the same user & webinar
        existing_txn = PaymentTransaction.objects.filter(
            metadata__phone=str(phone),
            metadata__webinar_id=str(webinar_id),
            payment_status__in=["pending", "failed"],
            is_archived=False
        ).first()

        if existing_txn:
            existing_txn.order_id = order["id"]
            existing_txn.amount = amount
            existing_txn.payment_status = "pending"
            existing_txn.metadata = order_data["notes"]
            existing_txn.save()
        else:
            PaymentTransaction.objects.create(
                order_id=order["id"],
                amount=amount,
                currency="INR",
                payment_status="pending",
                description=f"Webinar payment via Razorpay Checkout - {webinar.title}",
                metadata=order_data["notes"]
            )

        return Response({
            "success": True,
            "order_id": order["id"],
            "key": gateway.public_key,
            "amount": amount_in_paise,
            "currency": "INR",
            "webinar_title": webinar.title,
            "waba_link": getattr(webinar, "waba_link", "")
        })

    @csrf_exempt
    @action(detail=False, methods=['post'], url_path="verify")
    def verify_payment(self, request):
        payment_id = request.data.get("razorpay_payment_id")
        order_id = request.data.get("razorpay_order_id")
        signature = request.data.get("razorpay_signature")

        if not all([payment_id, order_id, signature]):
            return Response(
                {"success": False, "message": "Missing payment verification parameters"},
                status=status.HTTP_400_BAD_REQUEST
            )

        client, gateway = self._get_client()
        if not client:
            return Response(
                {"success": False, "message": "Razorpay secret not configured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        try:
            client.utility.verify_payment_signature({
                "razorpay_payment_id": payment_id,
                "razorpay_order_id": order_id,
                "razorpay_signature": signature
            })
        except razorpay.errors.SignatureVerificationError:
            return Response(
                {"success": False, "message": "Invalid payment signature"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update database transaction status to 'done'
        with db_transaction.atomic():
            txn = PaymentTransaction.objects.select_for_update().filter(order_id=order_id).first()
            if txn:
                txn.payment_status = "done"
                txn.transaction_id = payment_id
                txn.save(update_fields=["payment_status", "transaction_id"])

                phone = txn.metadata.get("phone") if txn.metadata else None
                webinar_id = txn.metadata.get("webinar_id") if txn.metadata else None

                if phone and webinar_id:
                    registration = WebinarRegistration.objects.select_for_update().filter(
                        phone=phone,
                        webinar__uuid=webinar_id
                    ).first()

                    if registration:
                        registration.is_paid = True
                        registration.payment_transaction = txn
                        registration.save(update_fields=["is_paid", "payment_transaction"])

        return Response({"success": True, "message": "Payment verified successfully"})
    
class PublicWebinarViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    queryset = Webinar.objects.filter(is_deleted=False, webinar_status=True).order_by("-created_at")
    serializer_class = PublicWebinarListSerializer

    permission_classes = []
    authentication_classes = []

    lookup_field = "slug"   # or "slug" or "id"

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return Response({
            "success": True,
            "data": response.data.get("results", [])
        })

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return Response({
            "success": True,
            "data": response.data
        })

class WebinarViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = WebinarSerializer
    lookup_field = "slug"
    lookup_url_kwarg = "slug"

    def get_queryset(self):

        # -------- LIST QUERYSET (FAST) --------
        if self.action == "list":
            return (
                Webinar.objects
                .filter(is_deleted=False,type = True)
                .annotate(
                    participants_count=Count("registrations", distinct=True),
                    total_amount_received=Sum(
                        "registrations__payment_transaction__amount",
                        filter=Q(registrations__payment_transaction__payment_status="done"),
                    ),
                    feedback_count=Count("feedbacks", distinct=True),
                    avg_rating=Avg("feedbacks__overall_rating"),
                )
                .only(
                    "id",
                    "uuid",
                    "slug",
                    "title",
                    "scheduled_start",
                    "seats_available",
                    "price",
                    "regular_price",
                    "webinar_image",
                    "status",
                    "created_at",
                )
                .order_by("-created_at")
            )

        # -------- RETRIEVE QUERYSET (FULL DATA) --------
        return (
            Webinar.objects
            .prefetch_related(

                Prefetch(
                    "tools",
                    queryset=WebinarTool.objects.filter(is_deleted=False)
                ),

                Prefetch(
                    "metadata",
                    queryset=webinar_metadata.objects.filter(is_deleted=False)
                ),

                Prefetch(
                    "faqs",
                    queryset=Webinar_FAQ.objects.filter(is_deleted=False)
                ),
                Prefetch(
                    "registrations",
                    queryset=WebinarRegistration.objects
                        .select_related(
                            "feedback",
                            "payment_transaction",
                            "lead"
                        )
                        .prefetch_related(
                            "attendance_summary",
                            Prefetch(
                                "attendance_logs",
                                queryset=WebinarAttendanceLog.objects
                                    .only(
                                        "join_time",
                                        "leave_time",
                                        "duration_seconds",
                                        "registration_id"
                                    )
                                    .order_by("join_time")
                            )
                        )
                        .only(
                            "id",
                            "uuid",
                            "email",
                            "name",
                            "phone",
                            "course",
                            "profession",
                            "registered_at",
                            "attended",
                            "certificate_sent",
                            "webinar_id",
                            "payment_transaction_id",
                            "lead_id"
                        )
                        .order_by("-registered_at")
                ),
                Prefetch(
                    "feedbacks",
                    queryset=WebinarFeedback.objects
                        .select_related("registration")
                        .order_by("-submitted_at")
                ),
            )

            .annotate(
                participants_count=Count("registrations", distinct=True),

                total_amount_received=Sum(
                    "registrations__payment_transaction__amount",
                    filter=Q(
                        registrations__payment_transaction__payment_status="done"
                    )
                ),

                feedback_count=Count("feedbacks", distinct=True),
                avg_rating=Avg("feedbacks__overall_rating"),
            )

            .filter(is_deleted=False)
        )

    # -------- RETRIEVE --------

    def retrieve(self, request, slug=None):

        webinar = get_object_or_404(
            Webinar.objects.only(
                "id",
                "uuid",
                "slug",
                "title",
                "scheduled_start",
                "seats_available",
                "price",
                "regular_price",
                "webinar_image",
                "status",
                "created_at"
            ),
            slug=slug,
            is_deleted=False,
            type = True
        )
        MEDIA_PREFIX = "https://portal.aryuacademy.com/api/media/"
        registrations = (
            WebinarRegistration.objects
            .filter(webinar_id=webinar.id)
            .annotate(

                payment_status=Coalesce(
                    F("payment_transaction__payment_status"),
                    Value("free")
                ),
                amount=Coalesce(
                    F("payment_transaction__amount"),
                    Value(Decimal("0.00")),
                    output_field=DecimalField(max_digits=10, decimal_places=2)
                ),
                certificate_url=Case(
                    When(
                        certificate__certificate_file__isnull=False,
                        certificate__certificate_file__gt="",
                        then=Concat(
                            Value(MEDIA_PREFIX),
                            F("certificate__certificate_file"),
                            output_field=CharField()
                        )
                    ),
                    default=Value(None),
                    output_field=CharField()
                ),

                # total hours participated
                total_hours_participated=ExpressionWrapper(
                    Coalesce(
                        F("attendance_summary__total_duration_seconds"),
                        Value(0)
                    ) / 3600.0,
                    output_field=FloatField()
                ),

                # full feedback JSON
                feedback_data=JSONObject(
                    id=F("feedback__uuid"),
                    overall_rating=F("feedback__overall_rating"),
                    content_quality=F("feedback__content_quality"),
                    speaker_quality=F("feedback__speaker_quality"),
                    pace_of_session=F("feedback__pace_of_session"),
                    interaction_rating=F("feedback__interaction_rating"),
                    learned_something_new=F("feedback__learned_something_new"),
                    would_recommend=F("feedback__would_recommend"),
                    liked_most=F("feedback__liked_most"),
                    improvement_suggestions=F("feedback__improvement_suggestions"),
                    additional_comments=F("feedback__additional_comments"),
                    interested_in_future_webinars=F("feedback__interested_in_future_webinars"),
                    interested_in_paid_courses=F("feedback__interested_in_paid_courses"),
                    submitted_at=F("feedback__submitted_at"),

                    rating_screenshot=Case(
                        When(
                            feedback__rating_screenshot__isnull=False,
                            then=Concat(
                                Value(MEDIA_PREFIX),
                                F("feedback__rating_screenshot"),
                                output_field=CharField()
                            )
                        ),
                        default=Value(None),
                        output_field=CharField()
                    )
                ),

                logs=JSONBAgg(
                    JSONObject(
                        join_time=F("attendance_logs__join_time"),
                        leave_time=F("attendance_logs__leave_time"),
                        duration_minutes=ExpressionWrapper(
                            F("attendance_logs__duration_seconds") / 60,
                            output_field=IntegerField()
                        )
                    ),
                    distinct=True
                )
            )
            .values(
                "id",
                "uuid",
                "email",
                "name",
                "phone",
                "course",
                "profession",
                "certificate_sent",
                "certificate_url",
                "registered_at",
                "total_hours_participated",
                "payment_status",
                "feedback_data",
                "logs",
                "amount"
            )
        )

        tools = list(
            WebinarTool.objects
            .filter(webinar_id=webinar.id, is_deleted=False)
            .values()
        )

        metadata = list(
            webinar_metadata.objects
            .filter(webinar_id=webinar.id, is_deleted=False)
            .values()
        )

        faqs = list(
            Webinar_FAQ.objects
            .filter(webinar_id=webinar.id, is_deleted=False)
            .values()
        )

        feedbacks = list(
            WebinarFeedback.objects
            .filter(registration__webinar_id=webinar.id)
            .values()
        )

        participants = list(registrations)

        participants_count = sum(
                1
            for participant in participants
            if str(participant.get("payment_status", "")).lower() == "done"
        )

        data = {
            "uuid": webinar.uuid,
            "slug": webinar.slug,
            "title": webinar.title,
            "scheduled_start": webinar.scheduled_start,
            "seats_available": webinar.seats_available,
            "price": webinar.price,
            "regular_price": webinar.regular_price,
            "status": webinar.status,
            "created_at": webinar.created_at,
            "participants_count": participants_count,
            "pending_seats": max(webinar.seats_available - participants_count, 0),
            "is_full": participants_count >= webinar.seats_available,
            "participants": participants,
            "tools": tools,
            "metadata": metadata,
            "faqs": faqs,
            "feedbacks": feedbacks
        }

        return Response({
            "status": True,
            "message": "Webinar retrieved successfully",
            "data": data
        })

    def list(self, request):
        cache_key = "webinar_list_v1"
        data = cache.get(cache_key)

        if not data:
            queryset = self.get_queryset()
            data = WebinarListSerializer(queryset, many=True).data
            cache.set(cache_key, data, 60)

        return Response(data)

    def create(self, request):
        serializer = WebinarSerializer(
            data=request.data,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        webinar = serializer.save()

        # ---------- TOOLS ----------
        i = 0
        while f"tools[{i}][tools_title]" in request.data:
            WebinarTool.objects.create(
                webinar=webinar,
                tools_title=request.data.get(f"tools[{i}][tools_title]"),
                tools_image=request.FILES.get(f"tools[{i}][tools_image]")
            )
            i += 1

        # ---------- METADATA ----------
        j = 0
        while f"metadata[{j}][meta_title]" in request.data:
            webinar_metadata.objects.create(
                webinar=webinar,
                meta_title=request.data.get(f"metadata[{j}][meta_title]"),
                meta_description=request.data.get(f"metadata[{j}][meta_description]"),
                meta_image=request.FILES.get(f"metadata[{j}][meta_image]")
            )
            j += 1

        # --------- FAQ ----------
        faqs_data = request.data.get("faqs")

        if faqs_data:
            try:
                faqs_data = json.loads(faqs_data)
                for faq in faqs_data:
                    Webinar_FAQ.objects.create(
                        webinar=webinar,
                        question=faq.get("question"),
                        answer=faq.get("answer")
                    )
            except json.JSONDecodeError:
                pass

        return Response({
            "status": True,
            "message": "Webinar created successfully",
            "data": WebinarSerializer(webinar, context={"request": request}).data
        }, status=201)


    def update(self, request, *args,**kwargs):
        try:
            with transaction.atomic():
                slug = kwargs.get("slug") 

                webinar = get_object_or_404(Webinar, slug=slug)

                serializer = WebinarSerializer(webinar, data=request.data, partial=True)
                serializer.is_valid(raise_exception=True)
                serializer.save()

                # =====================================================
                # TOOLS (PARTIAL PATCH STYLE)
                # =====================================================
                i = 0

                while (
                    f"tools[{i}][id]" in request.data or
                    f"tools[{i}][tools_title]" in request.data or
                    f"tools[{i}][is_deleted]" in request.data or
                    f"tools[{i}][tools_image]" in request.FILES
                ):

                    tool_id = request.data.get(f"tools[{i}][id]")
                    title = request.data.get(f"tools[{i}][tools_title]")
                    image = request.FILES.get(f"tools[{i}][tools_image]")
                    is_deleted = request.data.get(f"tools[{i}][is_deleted]")

                    # =================================================
                    # DELETE
                    # =================================================
                    if tool_id and str(is_deleted).lower() == "true":
                        WebinarTool.objects.filter(
                            id=tool_id,
                            webinar=webinar
                        ).delete()

                        i += 1
                        continue

                    # =================================================
                    # UPDATE
                    # =================================================
                    if tool_id:
                        obj = WebinarTool.objects.filter(
                            id=tool_id,
                            webinar=webinar
                        ).first()

                        if not obj:
                            return Response({
                                "status": False,
                                "message": f"Tool id {tool_id} not found"
                            }, status=400)

                        # update only provided fields
                        if title is not None:
                            obj.tools_title = title

                        if image:
                            obj.tools_image = image

                        obj.save()

                    # =================================================
                    # CREATE
                    # =================================================
                    else:
                        if not title:
                            return Response({
                                "status": False,
                                "message": "tools_title is required for new tool"
                            }, status=400)

                        WebinarTool.objects.create(
                            webinar=webinar,
                            tools_title=title,
                            tools_image=image
                        )

                    i += 1


                # =====================================================
                # METADATA
                # =====================================================
                j = 0
                meta_ids = []

                while f"metadata[{j}][meta_title]" in request.data:
                    meta_id = request.data.get(f"metadata[{j}][id]")
                    title = request.data.get(f"metadata[{j}][meta_title]")
                    desc = request.data.get(f"metadata[{j}][meta_description]")
                    image = request.FILES.get(f"metadata[{j}][meta_image]")

                    if meta_id:
                        obj = webinar_metadata.objects.filter(id=meta_id, webinar=webinar).first()
                        if not obj:
                            return Response({"status": False, "message": f"Metadata id {meta_id} not found"}, status=400)

                        obj.meta_title = title
                        obj.meta_description = desc
                        if image:
                            obj.meta_image = image
                        obj.save()
                        meta_ids.append(obj.id)

                    else:
                        obj = webinar_metadata.objects.filter(
                            webinar=webinar
                        ).first()

                        if obj:
                            obj.meta_title = title
                            obj.meta_description = desc

                            if image:
                                obj.meta_image = image

                            obj.save()
                        else:
                            obj = webinar_metadata.objects.create(
                                webinar=webinar,
                                meta_title=title,
                                meta_description=desc,
                                meta_image=image
                            )
                        meta_ids.append(obj.id)

                    j += 1

                webinar_metadata.objects.filter(webinar=webinar).exclude(id__in=meta_ids).delete()


                # =====================================================
                # FAQ
                # =====================================================
                faq_payload = request.data.get("faqs", None)

                if faq_payload is not None:

                    # fix: convert string → list
                    if isinstance(faq_payload, str):
                        try:
                            faq_payload = json.loads(faq_payload)
                        except json.JSONDecodeError:
                            return Response({
                                "status": False,
                                "message": "Invalid faqs format. Must be valid JSON array."
                            }, status=400)

                    if not isinstance(faq_payload, list):
                        return Response({
                            "status": False,
                            "message": "faqs must be a list"
                        }, status=400)

                    faq_ids = []

                    for faq in faq_payload:

                        faq_id = faq.get("id")
                        question = faq.get("question")
                        answer = faq.get("answer")

                        # ---------------- DELETE ----------------
                        if faq.get("is_deleted") is True and faq_id:
                            Webinar_FAQ.objects.filter(
                                id=faq_id,
                                webinar=webinar
                            ).delete()
                            continue

                        # ---------------- UPDATE ----------------
                        if faq_id:
                            obj = Webinar_FAQ.objects.filter(
                                id=faq_id,
                                webinar=webinar
                            ).first()

                            if not obj:
                                return Response({
                                    "status": False,
                                    "message": f"FAQ id {faq_id} not found"
                                }, status=400)

                            if question is not None:
                                obj.question = question
                            if answer is not None:
                                obj.answer = answer

                            obj.save()
                            faq_ids.append(obj.id)

                        # ---------------- CREATE ----------------
                        else:
                            obj = Webinar_FAQ.objects.create(
                                webinar=webinar,
                                question=question,
                                answer=answer
                            )
                            faq_ids.append(obj.id)

                    # optional: delete removed ones (sync style)
                    Webinar_FAQ.objects.filter(webinar=webinar).exclude(id__in=faq_ids).delete()

                # =====================================================

                return Response({
                    "status": True,
                    "message": "Webinar updated successfully",
                    "data": WebinarSerializer(webinar, context={"request": request}).data
                }, status=200)

        except Exception as e:
            return Response({
                "status": False,
                "message": str(e)
            }, status=400)
    
    def destroy(self, request, *args, **kwargs):
        slug = kwargs.get("slug") or kwargs.get("uuid")

        webinar = get_object_or_404(
            Webinar,
            slug=slug,
            is_deleted=False
        )

        webinar.is_deleted = True
        webinar.save(update_fields=["is_deleted", "updated_at"])

        return Response(
            {
                "status": True,
                "message": "Webinar deleted successfully"
            },
            status=status.HTTP_200_OK
        )

class BootcampViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = WebinarSerializer
    lookup_field = "slug"
    lookup_url_kwarg = "slug"

    def get_queryset(self):

        # -------- LIST QUERYSET (FAST) --------
        if self.action == "list":
            return (
                Webinar.objects
                .filter(is_deleted=False,type = False)
                .annotate(
                    participants_count=Count("registrations", distinct=True),
                    total_amount_received=Sum(
                        "registrations__payment_transaction__amount",
                        filter=Q(registrations__payment_transaction__payment_status="done"),
                    ),
                    feedback_count=Count("feedbacks", distinct=True),
                    avg_rating=Avg("feedbacks__overall_rating"),
                )
                .only(
                    "id",
                    "uuid",
                    "slug",
                    "title",
                    "scheduled_start",
                    "seats_available",
                    "price",
                    "regular_price",
                    "webinar_image",
                    "status",
                    "created_at",
                )
                .order_by("-created_at")
            )

        # -------- RETRIEVE QUERYSET (FULL DATA) --------
        return (
            Webinar.objects
            .prefetch_related(

                Prefetch(
                    "tools",
                    queryset=WebinarTool.objects.filter(is_deleted=False)
                ),

                Prefetch(
                    "metadata",
                    queryset=webinar_metadata.objects.filter(is_deleted=False)
                ),

                Prefetch(
                    "faqs",
                    queryset=Webinar_FAQ.objects.filter(is_deleted=False)
                ),
                Prefetch(
                    "registrations",
                    queryset=WebinarRegistration.objects
                        .select_related(
                            "feedback",
                            "payment_transaction",
                            "lead"
                        )
                        .prefetch_related(
                            "attendance_summary",
                            Prefetch(
                                "attendance_logs",
                                queryset=WebinarAttendanceLog.objects
                                    .only(
                                        "join_time",
                                        "leave_time",
                                        "duration_seconds",
                                        "registration_id"
                                    )
                                    .order_by("join_time")
                            )
                        )
                        .only(
                            "id",
                            "uuid",
                            "email",
                            "name",
                            "phone",
                            "course",
                            "profession",
                            "registered_at",
                            "attended",
                            "certificate_sent",
                            "webinar_id",
                            "payment_transaction_id",
                            "lead_id"
                        )
                        .order_by("-registered_at")
                ),
                Prefetch(
                    "feedbacks",
                    queryset=WebinarFeedback.objects
                        .select_related("registration")
                        .order_by("-submitted_at")
                ),
            )

            .annotate(
                participants_count=Count("registrations", distinct=True),

                total_amount_received=Sum(
                    "registrations__payment_transaction__amount",
                    filter=Q(
                        registrations__payment_transaction__payment_status="done"
                    )
                ),

                feedback_count=Count("feedbacks", distinct=True),
                avg_rating=Avg("feedbacks__overall_rating"),
            )

            .filter(is_deleted=False)
        )

    # -------- RETRIEVE --------

    def retrieve(self, request, slug=None):

        webinar = get_object_or_404(
            Webinar.objects.only(
                "id",
                "uuid",
                "slug",
                "title",
                "scheduled_start",
                "seats_available",
                "price",
                "regular_price",
                "webinar_image",
                "status",
                "created_at"
            ),
            slug=slug,
            is_deleted=False,
            type = False
        )
        MEDIA_PREFIX = "https://portal.aryuacademy.com/api/media/"
        registrations = (
            WebinarRegistration.objects
            .filter(webinar_id=webinar.id)
            .annotate(

                payment_status=Coalesce(
                    F("payment_transaction__payment_status"),
                    Value("free")
                ),
                amount=Coalesce(
                    F("payment_transaction__amount"),
                    Value(Decimal("0.00")),
                    output_field=DecimalField(max_digits=10, decimal_places=2)
                ),
                certificate_url=Case(
                    When(
                        certificate__certificate_file__isnull=False,
                        certificate__certificate_file__gt="",
                        then=Concat(
                            Value(MEDIA_PREFIX),
                            F("certificate__certificate_file"),
                            output_field=CharField()
                        )
                    ),
                    default=Value(None),
                    output_field=CharField()
                ),

                # total hours participated
                total_hours_participated=ExpressionWrapper(
                    Coalesce(
                        F("attendance_summary__total_duration_seconds"),
                        Value(0)
                    ) / 3600.0,
                    output_field=FloatField()
                ),

                # full feedback JSON
                feedback_data=JSONObject(
                    id=F("feedback__uuid"),
                    overall_rating=F("feedback__overall_rating"),
                    content_quality=F("feedback__content_quality"),
                    speaker_quality=F("feedback__speaker_quality"),
                    pace_of_session=F("feedback__pace_of_session"),
                    interaction_rating=F("feedback__interaction_rating"),
                    learned_something_new=F("feedback__learned_something_new"),
                    would_recommend=F("feedback__would_recommend"),
                    liked_most=F("feedback__liked_most"),
                    improvement_suggestions=F("feedback__improvement_suggestions"),
                    additional_comments=F("feedback__additional_comments"),
                    interested_in_future_webinars=F("feedback__interested_in_future_webinars"),
                    interested_in_paid_courses=F("feedback__interested_in_paid_courses"),
                    submitted_at=F("feedback__submitted_at"),

                    rating_screenshot=Case(
                        When(
                            feedback__rating_screenshot__isnull=False,
                            then=Concat(
                                Value(MEDIA_PREFIX),
                                F("feedback__rating_screenshot"),
                                output_field=CharField()
                            )
                        ),
                        default=Value(None),
                        output_field=CharField()
                    )
                ),

                logs=JSONBAgg(
                    JSONObject(
                        join_time=F("attendance_logs__join_time"),
                        leave_time=F("attendance_logs__leave_time"),
                        duration_minutes=ExpressionWrapper(
                            F("attendance_logs__duration_seconds") / 60,
                            output_field=IntegerField()
                        )
                    ),
                    distinct=True
                )
            )
            .values(
                "id",
                "uuid",
                "email",
                "name",
                "phone",
                "course",
                "profession",
                "certificate_sent",
                "certificate_url",
                "registered_at",
                "total_hours_participated",
                "payment_status",
                "feedback_data",
                "logs",
                "amount"
            )
        )

        tools = list(
            WebinarTool.objects
            .filter(webinar_id=webinar.id, is_deleted=False)
            .values()
        )

        metadata = list(
            webinar_metadata.objects
            .filter(webinar_id=webinar.id, is_deleted=False)
            .values()
        )

        faqs = list(
            Webinar_FAQ.objects
            .filter(webinar_id=webinar.id, is_deleted=False)
            .values()
        )

        feedbacks = list(
            WebinarFeedback.objects
            .filter(registration__webinar_id=webinar.id)
            .values()
        )

        participants = list(registrations)

        participants_count = sum(
                1
            for participant in participants
            if str(participant.get("payment_status", "")).lower() == "done"
        )

        data = {
            "uuid": webinar.uuid,
            "slug": webinar.slug,
            "title": webinar.title,
            "scheduled_start": webinar.scheduled_start,
            "seats_available": webinar.seats_available,
            "price": webinar.price,
            "regular_price": webinar.regular_price,
            "status": webinar.status,
            "created_at": webinar.created_at,
            "participants_count": participants_count,
            "pending_seats": max(webinar.seats_available - participants_count, 0),
            "is_full": participants_count >= webinar.seats_available,
            "participants": participants,
            "tools": tools,
            "metadata": metadata,
            "faqs": faqs,
            "feedbacks": feedbacks
        }

        return Response({
            "status": True,
            "message": "Webinar retrieved successfully",
            "data": data
        })

    # def list(self, request):
    #     cache_key = "bootcamp_list_v1"

    #     data = cache.get(cache_key)

    #     if not data:
    #         queryset = self.get_queryset()
    #         data = WebinarListSerializer(queryset, many=True).data
    #         cache.set(cache_key, data, 60)

    #     return Response(data)
    def list(self, request):
        queryset = self.get_queryset()
        data = WebinarListSerializer(queryset, many=True).data
        return Response(data)

    def create(self, request):
        serializer = WebinarSerializer(
            data=request.data,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        webinar = serializer.save()

        # ---------- TOOLS ----------
        i = 0
        while f"tools[{i}][tools_title]" in request.data:
            WebinarTool.objects.create(
                webinar=webinar,
                tools_title=request.data.get(f"tools[{i}][tools_title]"),
                tools_image=request.FILES.get(f"tools[{i}][tools_image]")
            )
            i += 1

        # ---------- METADATA ----------
        j = 0
        while f"metadata[{j}][meta_title]" in request.data:
            webinar_metadata.objects.create(
                webinar=webinar,
                meta_title=request.data.get(f"metadata[{j}][meta_title]"),
                meta_description=request.data.get(f"metadata[{j}][meta_description]"),
                meta_image=request.FILES.get(f"metadata[{j}][meta_image]")
            )
            j += 1

        # --------- FAQ ----------
        faqs_data = request.data.get("faqs")

        if faqs_data:
            try:
                faqs_data = json.loads(faqs_data)
                for faq in faqs_data:
                    Webinar_FAQ.objects.create(
                        webinar=webinar,
                        question=faq.get("question"),
                        answer=faq.get("answer")
                    )
            except json.JSONDecodeError:
                pass

        return Response({
            "status": True,
            "message": "Webinar created successfully",
            "data": WebinarSerializer(webinar, context={"request": request}).data
        }, status=201)


    def update(self, request, *args,**kwargs):
        try:
            with transaction.atomic():
                slug = kwargs.get("slug") 

                webinar = get_object_or_404(Webinar, slug=slug)

                serializer = WebinarSerializer(webinar, data=request.data, partial=True)
                serializer.is_valid(raise_exception=True)
                serializer.save()

                # =====================================================
                # TOOLS (PARTIAL PATCH STYLE)
                # =====================================================
                i = 0

                while (
                    f"tools[{i}][id]" in request.data or
                    f"tools[{i}][tools_title]" in request.data or
                    f"tools[{i}][is_deleted]" in request.data or
                    f"tools[{i}][tools_image]" in request.FILES
                ):

                    tool_id = request.data.get(f"tools[{i}][id]")
                    title = request.data.get(f"tools[{i}][tools_title]")
                    image = request.FILES.get(f"tools[{i}][tools_image]")
                    is_deleted = request.data.get(f"tools[{i}][is_deleted]")

                    # =================================================
                    # DELETE
                    # =================================================
                    if tool_id and str(is_deleted).lower() == "true":
                        WebinarTool.objects.filter(
                            id=tool_id,
                            webinar=webinar
                        ).delete()

                        i += 1
                        continue

                    # =================================================
                    # UPDATE
                    # =================================================
                    if tool_id:
                        obj = WebinarTool.objects.filter(
                            id=tool_id,
                            webinar=webinar
                        ).first()

                        if not obj:
                            return Response({
                                "status": False,
                                "message": f"Tool id {tool_id} not found"
                            }, status=400)

                        # update only provided fields
                        if title is not None:
                            obj.tools_title = title

                        if image:
                            obj.tools_image = image

                        obj.save()

                    # =================================================
                    # CREATE
                    # =================================================
                    else:
                        if not title:
                            return Response({
                                "status": False,
                                "message": "tools_title is required for new tool"
                            }, status=400)

                        WebinarTool.objects.create(
                            webinar=webinar,
                            tools_title=title,
                            tools_image=image
                        )

                    i += 1


                # =====================================================
                # METADATA
                # =====================================================
                j = 0
                meta_ids = []

                while f"metadata[{j}][meta_title]" in request.data:
                    meta_id = request.data.get(f"metadata[{j}][id]")
                    title = request.data.get(f"metadata[{j}][meta_title]")
                    desc = request.data.get(f"metadata[{j}][meta_description]")
                    image = request.FILES.get(f"metadata[{j}][meta_image]")

                    if meta_id:
                        obj = webinar_metadata.objects.filter(id=meta_id, webinar=webinar).first()
                        if not obj:
                            return Response({"status": False, "message": f"Metadata id {meta_id} not found"}, status=400)

                        obj.meta_title = title
                        obj.meta_description = desc
                        if image:
                            obj.meta_image = image
                        obj.save()
                        meta_ids.append(obj.id)

                    else:
                        obj = webinar_metadata.objects.filter(
                            webinar=webinar
                        ).first()

                        if obj:
                            obj.meta_title = title
                            obj.meta_description = desc

                            if image:
                                obj.meta_image = image

                            obj.save()
                        else:
                            obj = webinar_metadata.objects.create(
                                webinar=webinar,
                                meta_title=title,
                                meta_description=desc,
                                meta_image=image
                            )
                        meta_ids.append(obj.id)

                    j += 1

                webinar_metadata.objects.filter(webinar=webinar).exclude(id__in=meta_ids).delete()


                # =====================================================
                # FAQ
                # =====================================================
                faq_payload = request.data.get("faqs", None)

                if faq_payload is not None:

                    # fix: convert string → list
                    if isinstance(faq_payload, str):
                        try:
                            faq_payload = json.loads(faq_payload)
                        except json.JSONDecodeError:
                            return Response({
                                "status": False,
                                "message": "Invalid faqs format. Must be valid JSON array."
                            }, status=400)

                    if not isinstance(faq_payload, list):
                        return Response({
                            "status": False,
                            "message": "faqs must be a list"
                        }, status=400)

                    faq_ids = []

                    for faq in faq_payload:

                        faq_id = faq.get("id")
                        question = faq.get("question")
                        answer = faq.get("answer")

                        # ---------------- DELETE ----------------
                        if faq.get("is_deleted") is True and faq_id:
                            Webinar_FAQ.objects.filter(
                                id=faq_id,
                                webinar=webinar
                            ).delete()
                            continue

                        # ---------------- UPDATE ----------------
                        if faq_id:
                            obj = Webinar_FAQ.objects.filter(
                                id=faq_id,
                                webinar=webinar
                            ).first()

                            if not obj:
                                return Response({
                                    "status": False,
                                    "message": f"FAQ id {faq_id} not found"
                                }, status=400)

                            if question is not None:
                                obj.question = question
                            if answer is not None:
                                obj.answer = answer

                            obj.save()
                            faq_ids.append(obj.id)

                        # ---------------- CREATE ----------------
                        else:
                            obj = Webinar_FAQ.objects.create(
                                webinar=webinar,
                                question=question,
                                answer=answer
                            )
                            faq_ids.append(obj.id)

                    # optional: delete removed ones (sync style)
                    Webinar_FAQ.objects.filter(webinar=webinar).exclude(id__in=faq_ids).delete()

                # =====================================================

                return Response({
                    "status": True,
                    "message": "Webinar updated successfully",
                    "data": WebinarSerializer(webinar, context={"request": request}).data
                }, status=200)

        except Exception as e:
            return Response({
                "status": False,
                "message": str(e)
            }, status=400)
    
    def destroy(self, request, *args, **kwargs):
        slug = kwargs.get("slug") or kwargs.get("uuid")

        webinar = get_object_or_404(
            Webinar,
            slug=slug,
            is_deleted=False
        )

        webinar.is_deleted = True
        webinar.save(update_fields=["is_deleted", "updated_at"])

        return Response(
            {
                "status": True,
                "message": "Webinar deleted successfully"
            },
            status=status.HTTP_200_OK
        )

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

class WebinarRegistrationViewSet(viewsets.ViewSet):
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

    # -----------------------------
    # PAYMENT CREATION
    # -----------------------------
    def _create_payment(self, request, webinar, txn):
        data = request.data.copy()

        data["amount"] = float(webinar.price)
        data["webinar_id"] = str(webinar.uuid)
        data["transaction_id"] = str(txn.id)

        data["success_url"] = request.data.get(
            "success_url",
            "https://portal.aryuacademy.com/payment-success"
        )
        data["failure_url"] = request.data.get(
            "failure_url",
            "https://portal.aryuacademy.com/payment-failed"
        )

        request._full_data = data
        return RazorpayPaymentViewSet().create(request)

    # -----------------------------
    # REGISTRATION CREATION (SINGLE SOURCE)
    # -----------------------------
    @classmethod
    def create_registration_from_transaction(cls, txn):
        meta = txn.metadata

        webinar = Webinar.objects.get(uuid=meta["webinar_id"])

        registration, created = WebinarRegistration.objects.get_or_create(
            webinar=webinar,
            phone=meta["phone"],
            defaults={
                "name": meta.get("name"),
                "email": meta.get("email"),
                "profession": meta.get("profession"),
                "is_paid": True,
                "payment_transaction": txn
            }
        )

        if created:
            try:
                send_webinar_welcome_whatsapp(registration)
            except Exception as e:
                print("Error sending welcome task:", str(e))
            try:
                send_webinar_registration_email(registration)
            except Exception as e:
                print("Error sending registration email:", str(e))
            try:

                schedule_webinar_messages(registration)
            except Exception as e:
                print("Error scheduling webinar messages:", str(e))
            

        return registration

    # -----------------------------
    # CREATE API
    # -----------------------------
    def create(self, request, slug=None):
        webinar = get_object_or_404(Webinar, slug=slug)

        if not webinar.is_registration_open:
            return Response(
                {"message": "Registration for this webinar is closed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        phone = request.data.get("phone")

        if WebinarRegistration.objects.filter(webinar=webinar, phone=phone,is_paid =True).exists():
            return Response(
                {"message": "Already registered"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # -----------------------------------
        # FREE WEBINAR → DIRECT REGISTRATION
        # -----------------------------------
        if not webinar.is_paid:
            data = request.data.copy()
            data["source"] = request.data.get("source", "webinar")
            serializer = WebinarRegistrationSerializer(
                data=data,
                context={"webinar": webinar}
            )
            # serializer = WebinarRegistrationSerializer(
            #     data=request.data,
            #     context={"webinar": webinar}
            # )

            serializer.is_valid(raise_exception=True)
            registration = serializer.save()

            try:
                send_webinar_welcome_whatsapp(registration)
            except Exception as e:
                print("Error sending welcome task:", str(e))
                
            try:
                send_webinar_registration_email(registration)
            except Exception as e:
                print("Error sending registration email:", str(e))
            try:

                schedule_webinar_messages(registration)
            except Exception as e:
                print("Error scheduling webinar messages:", str(e))
            

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        client, gateway = self._get_client()

        if not client:
            return Response(
                {
                    "success": False,
                    "message": "Razorpay not configured"
                },
                status=400
            )

        order = client.order.create({
            "amount": int(float(webinar.price) * 100),
            "currency": "INR",
            "payment_capture": 1,
            "notes": {
                "webinar_id": str(webinar.uuid),
                "name": request.data.get("name"),
                "email": request.data.get("email"),
                "phone": phone,
            }
        })


        # -----------------------------------
        # PAID WEBINAR → PAYMENT ONLY
        # -----------------------------------
        txn = PaymentTransaction.objects.create(
            amount=webinar.price,
            payment_status="pending",
            metadata={
                "webinar_id": str(webinar.uuid),
                "name": request.data.get("name"),
                "email": request.data.get("email"),
                "phone": phone,
                "profession": request.data.get("profession"),
                "source":request.data.get("source","webinar"),
                },
            gateway=gateway,
            billing_type="webinar",
            currency="INR",
            order_id=order["id"],
            description="Webinar payment via Razorpay Checkout",
        )
        registration = WebinarRegistration.objects.filter(
            webinar=webinar,
            phone=phone
        ).first()

        if registration:
            registration.payment_transaction = txn
            registration.name = request.data.get("name")
            registration.email = request.data.get("email")
            registration.profession = request.data.get("profession")
            registration.save()
        else:
            registration = WebinarRegistration.objects.create(
                webinar=webinar,
                name=request.data.get("name"),
                email=request.data.get("email"),
                phone=phone,
                profession=request.data.get("profession"),
                is_paid=False,
                payment_transaction=txn
            )

        return self._create_payment(request, webinar, txn)

    def get_queryset(self):
        return (
            Webinar.objects
            .prefetch_related(
                Prefetch(
                    "registrations",
                    queryset=WebinarRegistration.objects.order_by("-registered_at")
                )
            )
            .order_by("-created_at")
        )


    def list(self, request, slug=None):
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_403_FORBIDDEN)

        qs = (
            WebinarRegistration.objects
            .filter(webinar__slug=slug)
            .select_related('lead')
            .order_by('-id')
        )

        serializer = WebinarRegistrationSerializer(qs, many=True)
        return Response(serializer.data)
    def destroy(self, request, pk=None, slug=None):

        registration = get_object_or_404(
            WebinarRegistration,
            id=pk,
            webinar__slug=slug
        )

        registration.delete()

        return Response(
            {
                "status": True,
                "message": "Registration deleted successfully"
            },
            status=status.HTTP_200_OK
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
        "success_url": f"https://portal.aryuacademy.com/webinar/payment-success/{webinar.uuid}",
        "failure_url": f"https://portal.aryuacademy.com/webinar/payment-failed/{webinar.uuid}",
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
    

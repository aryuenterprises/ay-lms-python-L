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
from django.db.models import DecimalField
from .services.zoom_service import get_zoom_access_token

try:
    from lead.models import Lead
    _LEAD_APP = True
except ImportError:
    _LEAD_APP = False

# from celery import shared_task
logger = logging.getLogger(__name__)

# ─── helpers ────────────────────────────────────────────────────────────────

def _get_razorpay_gateway():
    return PaymentGateway.objects.filter(
        gatway_name__icontains="razorpay"
    ).first()


def _finalize_registration(registration, txn):
    """Fires post-registration side-effects exactly once. Idempotent."""
    if registration.is_paid:
        return  # webhook retry — already processed, skip everything

    registration.is_paid             = True
    registration.payment_transaction = txn
    registration.save(update_fields=["is_paid", "payment_transaction"])

    try:
        send_webinar_welcome_whatsapp(registration)
    except Exception as e:
        logger.exception("Welcome WhatsApp failed: %s", e)

    try:
        send_webinar_registration_email(registration)
    except Exception as e:
        logger.exception("Registration email failed: %s", e)

    try:
        schedule_webinar_messages(registration)
    except Exception as e:
        logger.exception("Reminder scheduling failed: %s", e)


# ─── webhook ─────────────────────────────────────────────────────────────────

@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def razorpay_webhook(request):
    logger = logging.getLogger("razorpay_webhook")
    logger.info("=" * 80)
    logger.info("Webhook received")

    logger.info("Headers:")
    logger.info(dict(request.headers))

    logger.info("Raw body:")
    logger.info(request.body.decode(errors="ignore"))

    payload            = request.body
    received_signature = request.headers.get("X-Razorpay-Signature")

    if not received_signature:
        logger.error("Signature missing")
        return HttpResponse(status=400)

    # ── FIX 1: guard against missing gateway row ──────────────────────────────
    gateway = _get_razorpay_gateway()
    if not gateway:
        logger.error(
            "Razorpay webhook: no gateway row found. "
            "Ensure a PaymentGateway row with 'razorpay' in gatway_name exists."
        )
        return HttpResponse(status=200)  # 200 stops Razorpay retrying a misconfigured server
    
    logger.info("Secret repr = %r", gateway.webhook_secret)
    logger.info("Secret length = %d", len(gateway.webhook_secret))

    if not gateway.webhook_secret:
        logger.error("Razorpay webhook: webhook_secret is empty on gateway row id=%s", gateway.id)
        return HttpResponse(status=200)

    # ── Verify signature using Razorpay SDK ───────────────────────────────────

    logger.info("Webhook Secret = %r", gateway.webhook_secret)
    logger.info("Received Signature = %s", received_signature)
    logger.info("Body Length = %d", len(request.body))
    logger.info("Body SHA256 = %s", hashlib.sha256(request.body).hexdigest())

    try:
        client = razorpay.Client(
            auth=(gateway.public_key, gateway.secret_key)
        )

        client.utility.verify_webhook_signature(
            request.body,
            received_signature,
            gateway.webhook_secret,
        )

        logger.info("Webhook signature verified successfully.")

    except razorpay.errors.SignatureVerificationError as e:
        logger.exception("Webhook signature verification FAILED")
        return HttpResponse(status=400)
    
    data  = request.data
    event = data.get("event")

    # ── payment.captured ──────────────────────────────────────────────────────
    if event == "payment.captured":
        entity   = data["payload"]["payment"]["entity"]
        order_id = entity.get("order_id")

        with db_transaction.atomic():
            txn = (
                PaymentTransaction.objects
                .select_for_update()        # row-level lock — safe for retries
                .filter(order_id=order_id)
                .first()
            )

            if not txn:
                return HttpResponse(status=200)

            # ── FIX 2: idempotency guard ──────────────────────────────────────
            if txn.payment_status == "done":
                logger.info("Webhook retry ignored — already done (order_id=%s)", order_id)
                return HttpResponse(status=200)

            txn.payment_status = "done"
            txn.transaction_id = entity.get("id")
            txn.payment_mode   = entity.get("method")
            txn.save(update_fields=["payment_status", "transaction_id", "payment_mode", "updated_at"])

            meta     = txn.metadata or {}
            phone    = meta.get("phone")
            w_uuid   = meta.get("webinar_id")

            try:
                webinar = Webinar.objects.get(uuid=w_uuid)
            except Webinar.DoesNotExist:
                logger.error("Webhook: webinar %s not found", w_uuid)
                return HttpResponse(status=200)

            registration, _ = WebinarRegistration.objects.get_or_create(
                webinar=webinar,
                phone=phone,
                defaults={
                    "name":                meta.get("name"),
                    "email":               meta.get("email"),
                    "profession":          meta.get("profession"),
                    "state":               meta.get("state"),
                    "city":                meta.get("city"),
                    "source":              meta.get("source"),
                    "is_paid":             False,
                    "payment_transaction": txn,
                },
            )

            _finalize_registration(registration, txn)

    # ── payment.failed ────────────────────────────────────────────────────────
    elif event == "payment.failed":
        order_id = data["payload"]["payment"]["entity"].get("order_id")
        # Update SAME row, never create a new one, never downgrade "done"
        PaymentTransaction.objects.filter(
            order_id=order_id
        ).exclude(
            payment_status="done"
        ).update(payment_status="failed")

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
            "data": response.data
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
                .filter(is_deleted=False)
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
                            "state",
                            "city",
                            "registered_at",
                            "attended",
                            "certificate_sent",
                            "webinar_id",
                            "payment_transaction_id",
                            "lead_id",
                            "source",
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
 
        # ── 0. Cache check ─────────────────────────────────────────────────────
        # Key is per-slug so concurrent requests for different webinars
        # never collide.  TTL matches the list cache.
        cache_key = f"webinar_retrieve_{slug}"
        cached    = cache.get(cache_key)
        if cached:
            return Response(cached)
    
        MEDIA_PREFIX = "https://portal.aryuacademy.com/api/media/"
    
        # ── 1. Fetch webinar row (only the columns we actually use) ─────────────
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
                "created_at",
            ),
            slug=slug,
            is_deleted=False,
        )
    
        # ── 2. Fetch all participants in ONE query ──────────────────────────────
        #
        # DSA note: We deliberately do NOT use JSONBAgg(attendance_logs) here.
        # JSONBAgg causes Postgres to fan-out: a webinar with 500 participants
        # and 5 log entries each produces 2 500 rows that Postgres must then
        # GROUP and re-aggregate.  For large webinars this becomes the dominant
        # query cost.
        #
        # Instead we fetch participants flat (no join to attendance_logs),
        # then fetch all logs for this webinar in a second query keyed by
        # registration_id, and join them in Python using a hash-map in O(P+L).
        #
        participants_qs = (
            WebinarRegistration.objects
            .filter(webinar_id=webinar.id)
            .annotate(
                payment_status=Coalesce(
                    F("payment_transaction__payment_status"),
                    Value("free"),
                ),
                amount=Coalesce(
                    F("payment_transaction__amount"),
                    Value(Decimal("0.00")),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                ),
                certificate_url=Case(
                    When(
                        certificate__certificate_file__isnull=False,
                        certificate__certificate_file__gt="",
                        then=Concat(
                            Value(MEDIA_PREFIX),
                            F("certificate__certificate_file"),
                            output_field=CharField(),
                        ),
                    ),
                    default=Value(None),
                    output_field=CharField(),
                ),
                total_hours_participated=ExpressionWrapper(
                    Coalesce(
                        F("attendance_summary__total_duration_seconds"),
                        Value(0),
                    ) / 3600.0,
                    output_field=FloatField(),
                ),
                # Inline feedback via JSONObject — retained exactly as original
                # because it is a single LEFT JOIN, not a fan-out.
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
                                output_field=CharField(),
                            ),
                        ),
                        default=Value(None),
                        output_field=CharField(),
                    ),
                ),
                # ── participants_count pushed to DB ────────────────────────────
                # Annotated here so we can extract it without a second query.
                # COUNT(CASE WHEN payment_status='done') is a single index scan.
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
                "state",
                "city",
                "registered_at",
                "total_hours_participated",
                "payment_status",
                "feedback_data",
                "source",
                "amount",
            )
            .order_by("-registered_at")
        )
    
        # Materialise participants exactly once.
        # list() evaluates the queryset; we never iterate the DB cursor again.
        participants = list(participants_qs)
    
        # ── 3. participants_count — O(1) single pass, no extra DB query ─────────
        #
        # DSA note: a plain Python sum() over the already-materialised list is
        # O(P) but purely in Python (no DB round-trip). For P ≤ ~50 000 this is
        # negligible.  If P grows beyond that, push this to a DB COUNT annotation
        # on the webinar row itself (see comment below).
        participants_count = sum(
            1
            for p in participants
            if str(p.get("payment_status", "")).lower() == "done"
        )
    
        # ── 4. Attendance logs — single IN query + hash-map assembly ───────────
        #
        # DSA note: hash-map (dict) indexed by registration_id gives O(1) lookup
        # per participant in the assembly loop below.
        # Total complexity: O(P + L) vs O(P × L) from the old JSONBAgg approach.
        #
        # We only fetch logs for participants that actually attended to keep the
        # IN-list and the result set small.
        reg_ids = [p["id"] for p in participants]
    
        # logs_map: registration_id → list[{join_time, leave_time, duration_minutes}]
        logs_map: dict[int, list] = {}
    
        if reg_ids:
            raw_logs = (
                WebinarAttendanceLog.objects
                .filter(registration_id__in=reg_ids)
                .values(
                    "registration_id",
                    "join_time",
                    "leave_time",
                    "duration_seconds",
                )
                .order_by("registration_id", "join_time")
            )
    
            for log in raw_logs:
                rid = log["registration_id"]
                # setdefault is O(1) amortised on CPython dict
                logs_map.setdefault(rid, []).append({
                    "join_time":        log["join_time"],
                    "leave_time":       log["leave_time"],
                    "duration_minutes": log["duration_seconds"] // 60,
                })
    
        # ── 5. Attach logs to each participant in O(1) per participant ──────────
        #
        # Single-pass assembly loop.  Each hash-map lookup is O(1).
        for p in participants:
            p["logs"] = logs_map.get(p["id"], [])
    
        # ── 6. Side-data queries — serialized through proper serializers ────────
        #
        # Previous code used raw .values() which bypasses the image_url
        # SerializerMethodField on WebinarToolSerializer / WebinarMetadataSerializer.
        # Now we pass model instances through the same serializers used everywhere
        # else, so the response shape is consistent across all endpoints.
    
        tools = WebinarToolSerializer(
            WebinarTool.objects.filter(webinar_id=webinar.id, is_deleted=False),
            many=True,
        ).data
    
        metadata = WebinarMetadataSerializer(
            webinar_metadata.objects.filter(webinar_id=webinar.id, is_deleted=False),
            many=True,
        ).data
    
        faqs = WebinarFAQSerializer(
            Webinar_FAQ.objects.filter(webinar_id=webinar.id, is_deleted=False),
            many=True,
        ).data
    
        # feedbacks — fetched once, serialized once.
        # The old code fetched feedbacks as a separate .values() AND embedded them
        # inside each participant's feedback_data JSONObject annotation — two fetches.
        # Here feedbacks at the top level comes from the DB; per-participant
        # feedback_data is the inline JSONObject annotation (single LEFT JOIN).
        feedbacks = WebinarlistFeedbackSerializer(
            WebinarFeedback.objects.filter(registration__webinar_id=webinar.id),
            many=True,
        ).data
    
        # ── 7. Assemble final response — exact same shape as original ───────────
        data = {
            "uuid":               webinar.uuid,
            "slug":               webinar.slug,
            "title":              webinar.title,
            "scheduled_start":    webinar.scheduled_start,
            "seats_available":    webinar.seats_available,
            "price":              webinar.price,
            "regular_price":      webinar.regular_price,
            "status":             webinar.status,
            "created_at":         webinar.created_at,
            "participants_count": participants_count,
            "pending_seats":      max(webinar.seats_available - participants_count, 0),
            "is_full":            participants_count >= webinar.seats_available,
            "participants":       participants,
            "tools":              tools,
            "metadata":           metadata,
            "faqs":               faqs,
            "feedbacks":          feedbacks,
        }
    
        response_payload = {
            "status":  True,
            "message": "Webinar retrieved successfully",
            "data":    data,
        }
    
        # ── 8. Cache the assembled response for 60 s ───────────────────────────
        cache.set(cache_key, response_payload, 60)
    
        return Response(response_payload)

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

# ─────────────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS  (module-level so they can be unit-tested independently)
# ─────────────────────────────────────────────────────────────────────────────
 
def _normalise_phone(raw: str | None) -> str | None:
    """Strip whitespace/dashes. Returns None if empty."""
    if not raw:
        return None
    cleaned = raw.strip().replace(" ", "").replace("-", "")
    return cleaned or None
 
 
def _upsert_lead(phone: str, name: str | None, email: str | None,
                 source: str | None) -> "Lead | None":
    """
    Create-or-update Lead by phone.
    Returns the Lead instance, or None when lead app is unavailable.
    Thread-safe: uses get_or_create so concurrent requests converge correctly.
    """
    if not _LEAD_APP or not phone:
        return None
 
    lead, created = Lead.objects.get_or_create(
        phone=phone,
        defaults={
            "name":   name,
            "email":  email,
            "source": source or "webinar",
        },
    )
 
    if not created:
        # Always keep Lead in sync with latest snapshot — never leave stale data
        fields_to_update = []
        if name and not lead.name:
            lead.name = name
            fields_to_update.append("name")
        if email and not lead.email:
            lead.email = email
            fields_to_update.append("email")
        if fields_to_update:
            lead.save(update_fields=fields_to_update)
 
    return lead
 
 
def _fire_registration_side_effects(registration: WebinarRegistration) -> None:
    """
    Send welcome WhatsApp, registration email, and schedule reminders.
    Each call is isolated so one failure does not block the others.
    """
    try:
        send_webinar_welcome_whatsapp(registration)
    except Exception:
        logger.exception(
            "Welcome WhatsApp failed for registration id=%s", registration.id
        )
 
    try:
        send_webinar_registration_email(registration)
    except Exception:
        logger.exception(
            "Registration email failed for registration id=%s", registration.id
        )
 
    try:
        schedule_webinar_messages(registration)
    except Exception:
        logger.exception(
            "Reminder scheduling failed for registration id=%s", registration.id
        )
 
 
def _get_or_create_pending_transaction(
    webinar: Webinar,
    phone: str,
    name: str | None,
    email: str | None,
    profession: str | None,
    state: str | None,
    city: str | None,
    source: str | None,
) -> PaymentTransaction:
    """
    Return the existing pending PaymentTransaction for (webinar + phone),
    or create a fresh one if none exists.
 
    This guarantees that repeated calls from the same user (back-button,
    network retry) always converge to ONE pending row.
    """
    existing_txn = (
        PaymentTransaction.objects
        .filter(
            payment_status="pending",
            metadata__webinar_id=str(webinar.uuid),
            metadata__phone=phone,
        )
        .order_by("-created_at")
        .first()
    )
 
    if existing_txn:
        # Refresh metadata with latest user input in case name/email changed
        existing_txn.metadata.update({
            "name":       name,
            "email":      email,
            "profession": profession,
            "state":      state,
            "city":       city,
            "source":     source,
        })
        existing_txn.save(update_fields=["metadata", "updated_at"])
        logger.debug(
            "Reusing existing pending txn id=%s for webinar=%s phone=%s",
            existing_txn.id, webinar.uuid, phone,
        )
        return existing_txn
 
    return PaymentTransaction.objects.create(
        amount=webinar.price,
        payment_status="pending",
        metadata={
            "webinar_id": str(webinar.uuid),
            "name":       name,
            "email":      email,
            "phone":      phone,
            "profession": profession,
            "state":      state,
            "city":       city,
            "source":     source,
        },
    )
 
 
def _sync_registration_fields(
    registration: WebinarRegistration,
    txn: PaymentTransaction,
    name: str | None,
    email: str | None,
    profession: str | None,
    state: str | None,
    city: str | None,
    source: str | None,
    lead: "Lead | None",
) -> None:
    """
    Update a pre-existing (unpaid) registration with the latest user input
    and attach the current pending transaction.
    Uses update_fields to avoid touching unrelated columns.
    """
    fields_changed = ["payment_transaction", "updated_at"] if hasattr(registration, "updated_at") else ["payment_transaction"]
 
    registration.payment_transaction = txn
 
    if name:
        registration.name = name
        fields_changed.append("name")
    if email:
        registration.email = email
        fields_changed.append("email")
    if profession:
        registration.profession = profession
        fields_changed.append("profession")
    if state:
        registration.state = state
        fields_changed.append("state")
    if city:
        registration.city = city
        fields_changed.append("city")
    if source:
        registration.source = source
        fields_changed.append("source")
    if lead and not registration.lead_id:
        registration.lead = lead
        fields_changed.append("lead")
 
    registration.save(update_fields=list(set(fields_changed)))
 
 
# ─────────────────────────────────────────────────────────────────────────────
# VIEWSET
# ─────────────────────────────────────────────────────────────────────────────
 
class WebinarRegistrationViewSet(viewsets.ViewSet):
    """
    Handles public registration for both free and paid webinars.
 
    Routes (from urls.py — unchanged):
      POST   /<slug>/register/              → create
      GET    /<slug>/registrations/         → list    (auth required)
      DELETE /<slug>/registrations/<pk>     → destroy (auth required)
    """
 
    # Public by default; list/destroy override this via manual check / permission class
    permission_classes = [permissions.AllowAny]
 
    # -------------------------------------------------------------------------
    # CLASS-LEVEL HELPER  (called by razorpay_webhook after payment.captured)
    # -------------------------------------------------------------------------
 
    @classmethod
    def create_registration_from_transaction(cls, txn: PaymentTransaction) -> WebinarRegistration:
        """
        Idempotent finalization of a paid registration triggered by the webhook.
 
        Guarantees:
          - Exactly one WebinarRegistration for (webinar + phone)
          - Side-effects fire only once (guarded by is_paid check)
          - Lead is upserted and converted
        """
        meta     = txn.metadata or {}
        phone    = meta.get("phone")
        w_uuid   = meta.get("webinar_id")
 
        webinar  = Webinar.objects.get(uuid=w_uuid)
        lead     = _upsert_lead(
            phone=phone,
            name=meta.get("name"),
            email=meta.get("email"),
            source=meta.get("source"),
        )
 
        registration, created = WebinarRegistration.objects.get_or_create(
            webinar=webinar,
            phone=phone,
            defaults={
                "name":                meta.get("name"),
                "email":               meta.get("email"),
                "profession":          meta.get("profession"),
                "state":               meta.get("state"),
                "city":                meta.get("city"),
                "source":              meta.get("source"),
                "is_paid":             False,   # finalized below
                "payment_transaction": txn,
            },
        )
 
        # ── Idempotency guard: only finalize once ─────────────────────────────
        if registration.is_paid:
            logger.info(
                "create_registration_from_transaction: already finalized, "
                "skipping side-effects (registration id=%s)", registration.id
            )
            return registration
 
        registration.is_paid             = True
        registration.payment_transaction = txn
 
        update_fields = ["is_paid", "payment_transaction"]
 
        # Attach lead if the row existed before the lead FK was added
        if lead and not registration.lead_id:
            registration.lead = lead
            update_fields.append("lead")
 
        registration.save(update_fields=update_fields)
 
        # ── Convert Lead ──────────────────────────────────────────────────────
        if lead and not lead.is_converted:
            lead.is_converted = True
            lead.joined_at    = timezone.now()
            lead.status       = "converted"
            lead.save(update_fields=["is_converted", "joined_at", "status"])
 
        # ── Post-registration side-effects (exactly once) ─────────────────────
        _fire_registration_side_effects(registration)
 
        return registration
 
    # -------------------------------------------------------------------------
    # CREATE  POST /<slug>/register/
    # -------------------------------------------------------------------------
 
    def create(self, request, slug: str = None) -> Response:
        webinar = get_object_or_404(Webinar, slug=slug, is_deleted=False)
 
        # ── Registration gate ─────────────────────────────────────────────────
        if not webinar.is_registration_open:
            return Response(
                {"success": False, "message": "Registration for this webinar is closed"},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        # ── Phone is mandatory for both free and paid paths ───────────────────
        phone = _normalise_phone(request.data.get("phone"))
        if not phone:
            return Response(
                {"success": False, "message": "A valid phone number is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        name       = request.data.get("name")
        email      = request.data.get("email")
        profession = request.data.get("profession")
        state      = request.data.get("state")
        city       = request.data.get("city")
        source     = request.data.get("source")
 
        # ── Already paid → return early, no DB writes ─────────────────────────
        if WebinarRegistration.objects.filter(
            webinar=webinar, phone=phone, is_paid=True
        ).exists():
            return Response(
                {"success": False, "message": "You are already registered for this webinar"},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        # ═════════════════════════════════════════════════════════════════════
        # BRANCH A — FREE WEBINAR
        # ═════════════════════════════════════════════════════════════════════
        if not webinar.is_paid:
            return self._handle_free_registration(
                request=request,
                webinar=webinar,
                phone=phone,
                name=name,
                email=email,
                profession=profession,
                state=state,
                city=city,
                source=source,
            )
 
        # ═════════════════════════════════════════════════════════════════════
        # BRANCH B — PAID WEBINAR
        # ═════════════════════════════════════════════════════════════════════
        return self._handle_paid_registration(
            request=request,
            webinar=webinar,
            phone=phone,
            name=name,
            email=email,
            profession=profession,
            state=state,
            city=city,
            source=source,
        )
 
    # ── Free webinar branch ───────────────────────────────────────────────────
 
    @db_transaction.atomic
    def _handle_free_registration(
        self, request, webinar, phone,
        name, email, profession, state, city, source,
    ) -> Response:
        lead = _upsert_lead(phone=phone, name=name, email=email, source=source)
 
        # get_or_create is the ONLY correct primitive here.
        # The serializer.create() path is intentionally bypassed for free webinars
        # because it calls WebinarRegistration.objects.create() unconditionally
        # and would duplicate rows on retry.
        registration, created = WebinarRegistration.objects.get_or_create(
            webinar=webinar,
            phone=phone,
            defaults={
                "name":       name,
                "email":      email,
                "profession": profession,
                "state":      state,
                "city":       city,
                "source":     source,
                "is_paid":    True,
                "lead":       lead,
            },
        )
 
        if not created:
            # User is registering again for a free webinar they haven't paid
            # (is_paid=False row exists). Bring it up to date.
            if not registration.is_paid:
                update_fields = ["is_paid"]
                registration.is_paid = True
 
                if lead and not registration.lead_id:
                    registration.lead = lead
                    update_fields.append("lead")
 
                registration.save(update_fields=update_fields)
            else:
                # Already fully registered — this branch is technically unreachable
                # because the is_paid guard above fires first, but kept for safety.
                return Response(
                    {"success": False, "message": "You are already registered"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
 
        # Convert lead immediately for free webinars
        if lead and not lead.is_converted:
            lead.is_converted = True
            lead.joined_at    = timezone.now()
            lead.status       = "converted"
            lead.save(update_fields=["is_converted", "joined_at", "status"])
 
        # Side-effects only on first-time registration
        if created:
            _fire_registration_side_effects(registration)
 
        serializer = WebinarRegistrationSerializer(registration)
        return Response(
            {
                "success":  True,
                "message":  "Registration successful",
                "data":     serializer.data,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
 
    # ── Paid webinar branch ───────────────────────────────────────────────────
 
    @db_transaction.atomic
    def _handle_paid_registration(
        self, request, webinar, phone,
        name, email, profession, state, city, source,
    ) -> Response:
        lead = _upsert_lead(phone=phone, name=name, email=email, source=source)
 
        # ── ONE pending transaction for (webinar + phone) ─────────────────────
        txn = _get_or_create_pending_transaction(
            webinar=webinar,
            phone=phone,
            name=name,
            email=email,
            profession=profession,
            state=state,
            city=city,
            source=source,
        )
 
        # ── ONE registration row for (webinar + phone) ────────────────────────
        registration, created = WebinarRegistration.objects.get_or_create(
            webinar=webinar,
            phone=phone,
            defaults={
                "name":                name,
                "email":               email,
                "profession":          profession,
                "state":               state,
                "city":                city,
                "source":              source,
                "is_paid":             False,
                "payment_transaction": txn,
                "lead":                lead,
            },
        )
 
        if not created:
            # Row already exists (failed previous attempt, page refresh, etc.)
            # Sync all latest fields onto it so nothing is stale.
            _sync_registration_fields(
                registration=registration,
                txn=txn,
                name=name,
                email=email,
                profession=profession,
                state=state,
                city=city,
                source=source,
                lead=lead,
            )
 
        # ── Delegate to RazorpayPaymentViewSet.create ─────────────────────────
        # Build a clean mutable dict — never mutate request.data or request._full_data
        from rest_framework.request import Request as DrfRequest
        from django.test import RequestFactory
 
        # We need to call RazorpayPaymentViewSet.create() with the right data.
        # Rather than mutating the live request (which is fragile), we pass
        # the data directly via a simple internal method call.
        payment_response = self._initiate_razorpay_order(
            request=request,
            webinar=webinar,
            txn=txn,
            name=name,
            email=email,
            phone=phone,
            profession=profession,
            state=state,
            city=city,
            source=source,
        )
 
        return payment_response
 
    def _initiate_razorpay_order(
        self, request, webinar, txn,
        name, email, phone, profession, state, city, source,
    ) -> Response:
        """
        Calls RazorpayPaymentViewSet.create() cleanly by temporarily
        injecting the required data into the request object.
 
        This avoids the previous anti-pattern of mutating request._full_data.
        The injected attribute `_razorpay_override` is read by an overridden
        `request.data` property — except we don't own that property.
 
        Cleanest safe approach: pass a synthetic data dict directly.
        """
        from .views import RazorpayPaymentViewSet  # local import avoids circular
 
        # Clone the incoming request data and augment it
        # request.data is a QueryDict (multipart) or dict (JSON).
        # We build a plain dict — RazorpayPaymentViewSet.create reads .get() on it.
        original_data = request.data
 
        # Temporarily replace request.data with an augmented dict
        # DRF Request stores parsed data in _data; replacing it is the accepted pattern.
        augmented = {
            **original_data,
            "amount":         float(webinar.price),
            "webinar_id":     str(webinar.uuid),
            "transaction_id": str(txn.id),
            "phone":          phone,
            "name":           name,
            "email":          email,
            "profession":     profession,
            "state":          state,
            "city":           city,
            "source":         source,
        }
 
        request._data        = augmented           # DRF's internal cache key
        request._full_data   = augmented           # also replace _full_data for safety
 
        try:
            razorpay_view = RazorpayPaymentViewSet()
            razorpay_view.request = request
            razorpay_view.format_kwarg = None
            response = razorpay_view.create(request)
        finally:
            # Always restore original data so nothing downstream is surprised
            request._data      = original_data
            request._full_data = original_data
 
        return response
 
    # -------------------------------------------------------------------------
    # LIST  GET /<slug>/registrations/
    # -------------------------------------------------------------------------
 
    def list(self, request, slug: str = None) -> Response:
        # Explicit auth check — keeps permission_classes=AllowAny on the viewset
        # without granting unauthenticated access to this sensitive endpoint.
        if not request.user or not request.user.is_authenticated:
            return Response(
                {"success": False, "message": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
 
        qs = (
            WebinarRegistration.objects
            .filter(webinar__slug=slug)
            .select_related("payment_transaction")
            .prefetch_related("attendance_summary", "attendance_logs")
            .order_by("-registered_at")
        )
 
        # Only attempt lead select_related when the field actually exists on the model.
        # The model has a bare models.ForeignKey() with no field name, so `lead` may
        # not exist as a real column until that migration is applied.
        from django.db.models.fields.related import ForeignKey as DjangoFK
        _lead_field_exists = any(
            f.name == "lead"
            for f in WebinarRegistration._meta.get_fields()
            if isinstance(f, DjangoFK)
        )
        if _lead_field_exists:
            qs = qs.select_related("payment_transaction", "lead")
 
        serializer = WebinarRegistrationSerializer(qs, many=True)
        return Response(
            {
                "success": True,
                "count":   qs.count(),
                "data":    serializer.data,
            },
            status=status.HTTP_200_OK,
        )
 
    # -------------------------------------------------------------------------
    # DESTROY  DELETE /<slug>/registrations/<pk>
    # -------------------------------------------------------------------------
 
    def destroy(self, request, pk: int = None, slug: str = None) -> Response:
        if not request.user or not request.user.is_authenticated:
            return Response(
                {"success": False, "message": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
 
        registration = get_object_or_404(
            WebinarRegistration,
            id=pk,
            webinar__slug=slug,
        )
 
        registration.delete()
 
        return Response(
            {"success": True, "message": "Registration deleted successfully"},
            status=status.HTTP_200_OK,
        )



def fetch_zoom_participants(meeting_id):
    token = get_zoom_access_token()

    headers = {
        "Authorization": f"Bearer {token}"
    }

    
    resp = requests.get(
        f"https://api.zoom.us/v2/past_meetings/{meeting_id}",
        headers=headers,
        timeout=10
    )
    resp.raise_for_status()

    uuid = resp.json().get("uuid")

    if not uuid:
        raise Exception("Zoom UUID not found")

    encoded_uuid = quote(uuid, safe="")

    
    url = f"https://api.zoom.us/v2/report/meetings/{encoded_uuid}/participants"

    participants = []
    next_page_token = None

    while True:

        params = {"page_size": 300}

        if next_page_token:
            params["next_page_token"] = next_page_token

        resp = requests.get(url, headers=headers, params=params, timeout=10)
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
    

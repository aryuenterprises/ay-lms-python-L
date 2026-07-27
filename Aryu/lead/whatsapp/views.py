"""
whatsapp/views.py

REST API layer for the WhatsApp Broadcast Studio.

Endpoints
─────────
POST /api/whatsapp/campaigns/<campaign_id>/trigger/
    Validates campaign state, seeds recipients, fires Celery task.
    Returns 202 Accepted with a tracking payload immediately (non-blocking).

GET  /api/whatsapp/campaigns/<campaign_id>/status/
    Lightweight counter polling for the broadcast analytics dashboard.
    Returns live counter fields with pre-computed rate metrics.
"""

import logging

from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count, Prefetch, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters as drf_filters
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from .services.meta_client import MetaClient, MetaAPIError
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.permissions import AllowAny
from django.db.models import F
from django.conf import settings
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
import base64
import json
from .services.chat_engine import WhatsAppChatEngine
from .apps import KafkaProducerClient
from .utils import message_deduplicator
from .filters import (
    WhatsAppCampaignFilter,
    WhatsAppCampaignRecipientFilter,
    WhatsAppMessageFilter,
)
from .models import (
    MessageTemplate,
    WhatsAppCampaign,
    WhatsAppCampaignRecipient,
    WhatsAppMessage,
    WhatsAppChat
)
from lead.models import Lead
from .pagination import (
    CampaignPageNumberPagination,
    MessageStreamCursorPagination,
    RecipientCursorPagination,
)
from .serializers import (
    MessageTemplateSerializer,
    WhatsAppCampaignCreateSerializer,
    WhatsAppCampaignListSerializer,
    WhatsAppMessageStreamSerializer,
    CampaignActivityEventSerializer,
    CampaignDuplicateResultSerializer,
    WhatsAppCampaignDetailSerializer,
    WhatsAppCampaignRecipientSerializer,
    WhatsAppCampaignExcelCreateSerializer,
)
from aryuapp.auth import CustomJWTAuthentication
from .validators import (
    validate_cancellable,
    validate_deletable,
    validate_owner_or_staff,
)
from rest_framework.parsers import MultiPartParser, FormParser
from .models import WhatsAppCampaign, WhatsAppCampaignRecipient
from .tasks import trigger_broadcast_task, process_excel_broadcast_task
from .services.template_sync import TemplateSyncService
import os

logger = logging.getLogger("whatsapp")



META_API_VERSION    = os.environ.get("WHATSAPP_API_VERSION", "v19.0")
META_PHONE_ID       = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
META_ACCESS_TOKEN   = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
META_WEBHOOK_VERIFY_TOKEN= os.environ.get("WHATSAPP_VERIFY_TOKEN", "")


# ══════════════════════════════════════════════════════════════════════
# TriggerBroadcastView
# ══════════════════════════════════════════════════════════════════════

class TriggerBroadcastView(APIView):
    """
    POST /api/whatsapp/campaigns/<campaign_id>/trigger/

    Non-blocking broadcast launcher.

    Request body (all fields optional):
    ─────────────────────────────────────
    {
        "audience_filter": {
            "tag_ids": [1, 2, 3],   // filter leads by tag
            "stage":   "hot"         // filter leads by pipeline stage
        }
    }

    Successful 202 response:
    ─────────────────────────
    {
        "campaign_id":       42,
        "status":            "queued",
        "total_recipients":  1250,
        "task_id":           "3c8a2e1f-..."
    }

    Error responses:
    ─────────────────
    400  Campaign not in a triggerable state (not draft / paused)
    400  No eligible recipients found
    404  Campaign not found
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, campaign_id: int) -> Response:

        # ── 1. Load and validate campaign ────────────────────────────
        try:
            campaign = (
                WhatsAppCampaign.objects
                .select_related("template")
                .get(pk=campaign_id)
            )
        except WhatsAppCampaign.DoesNotExist:
            return Response(
                {"error": f"Campaign {campaign_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        triggerable_states = {
            WhatsAppCampaign.STATUS_DRAFT,
            WhatsAppCampaign.STATUS_PAUSED,
        }
        if campaign.status not in triggerable_states:
            return Response(
                {
                    "error": (
                        f"Campaign is '{campaign.status}'. "
                        f"Only 'draft' or 'paused' campaigns can be triggered."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── 2. Seed recipients ────────────────────────────────────────
        audience_filter = request.data.get("audience_filter", {})
        recipient_count = self._seed_recipients(
            campaign=campaign,
            audience_filter=audience_filter,
        )

        if recipient_count == 0:
            return Response(
                {"error": "No eligible recipients found for this campaign."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── 3. Transition to QUEUED (atomic) ─────────────────────────
        with transaction.atomic():
            WhatsAppCampaign.objects.filter(pk=campaign_id).update(
                status=WhatsAppCampaign.STATUS_QUEUED,
                total_recipients=recipient_count,
                # Reset counters on re-trigger after pause.
                sent_count=0,
                delivered_count=0,
                read_count=0,
                failed_count=0,
                click_count=0,
                reply_count=0,
            )

        # ── 4. Fire orchestrator task (non-blocking) ─────────────────
        task = trigger_broadcast_task.apply_async(
            args=[campaign_id],
            queue="whatsapp_broadcast",
        )

        logger.info(
            "Broadcast triggered | campaign=%s recipients=%d task=%s user=%s",
            campaign_id, recipient_count, task.id, request.user,
        )

        return Response(
            {
                "campaign_id":      campaign_id,
                "status":           WhatsAppCampaign.STATUS_QUEUED,
                "total_recipients": recipient_count,
                "task_id":          task.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    # ── Private: recipient seeding ────────────────────────────────────

    @staticmethod
    def _seed_recipients(
        campaign: WhatsAppCampaign,
        audience_filter: dict,
    ) -> int:
        """
        Build WhatsAppCampaignRecipient rows for this broadcast run.

        Strategy:
          • Stream lead PKs via .iterator(chunk_size=500) — never loads
            the full audience into memory.
          • bulk_create with ignore_conflicts=True — idempotent: re-triggering
            a paused campaign safely skips already-seeded recipients.

        Returns: number of NEW recipient rows created.
        """
        leads_qs = TriggerBroadcastView._build_audience_queryset(audience_filter)

        recipients = [
            WhatsAppCampaignRecipient(
                campaign=campaign,
                lead_id=lead_id,
                status=WhatsAppCampaignRecipient.STATUS_PENDING,
            )
            for (lead_id,) in leads_qs.values_list("id").iterator(chunk_size=500)
        ]

        created = WhatsAppCampaignRecipient.objects.bulk_create(
            recipients,
            ignore_conflicts=True,
        )
        return len(created)

    @staticmethod
    def _build_audience_queryset(audience_filter):
        from lead.models import Lead

        qs = Lead.objects.filter(
            phone__isnull=False
        ).exclude(phone="")

        stage = audience_filter.get("stage")
        if stage:
            qs = qs.filter(lead_stage=stage)

        return qs


# ══════════════════════════════════════════════════════════════════════
# CampaignStatusView
# ══════════════════════════════════════════════════════════════════════

class CampaignStatusView(APIView):
    """
    GET /api/whatsapp/campaigns/<campaign_id>/status/

    Polling endpoint for the broadcast analytics dashboard.
    Returns all counter fields with pre-computed percentage rates.
    No serializer overhead — direct dict from ORM values.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, campaign_id: int) -> Response:
        try:
            c = WhatsAppCampaign.objects.get(pk=campaign_id)
        except WhatsAppCampaign.DoesNotExist:
            return Response(
                {"error": "Not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        total = c.total_recipients or 1  # guard div-by-zero on fresh campaigns

        return Response({
            "campaign_id":       c.pk,
            "name":              c.name,
            "status":            c.status,
            "total_recipients":  c.total_recipients,
            "sent_count":        c.sent_count,
            "delivered_count":   c.delivered_count,
            "read_count":        c.read_count,
            "failed_count":      c.failed_count,
            "click_count":       c.click_count,
            "reply_count":       c.reply_count,
            # Pre-computed rates for dashboard top cards
            "delivery_rate":     round(c.delivered_count / total * 100, 2),
            "read_rate":         round(c.read_count      / total * 100, 2),
            "click_rate":        round(c.click_count     / total * 100, 2),
            "response_rate":     round(c.reply_count     / total * 100, 2),
            "updated_at":        c.updated_at,
        })
    

# ══════════════════════════════════════════════════════════════════════
# MessageTemplate endpoints
# ══════════════════════════════════════════════════════════════════════
 
class MessageTemplateListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/whatsapp/templates/   — list templates (search + active filter)
    POST /api/whatsapp/templates/   — create a template
 
    Query params:
        search  — icontains match on name / meta_template_name
        active  — true/false filter
        ordering — name, -name, created_at, -created_at (default: -created_at)
    """
 
    serializer_class = MessageTemplateSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CampaignPageNumberPagination
    filter_backends = [drf_filters.SearchFilter, drf_filters.OrderingFilter]
    search_fields = ["name", "meta_template_name"]
    ordering_fields = ["name", "created_at"]
    ordering = ["-created_at"]
 
    def get_queryset(self):
        # No relational fanout on this model — a flat queryset is already
        # optimal. `active` is a simple equality filter, applied here
        # rather than via django-filter since it's the only extra param.
        qs = MessageTemplate.objects.all()
        active_param = self.request.query_params.get("active")

        active_param = self.request.query_params.get("active")

        if active_param is not None:
            qs = qs.filter(active=active_param.lower() in ("true", "1", "yes"))
        return qs
    
    def perform_create(self, serializer):
        data = serializer.validated_data
        client = MetaClient()

        try:
            # 1. Transmit to Meta first
            meta_response = client.create_template(
                name=data["meta_template_name"],
                language=data.get("language", "en_US"),
                category=data.get("category", "UTILITY"),
                body_text=data["body"],
                body_examples=data.get("body_variable_examples", []),
                header_type=data.get("header_type", "NONE"),
                header_text=data.get("header_text"),
                header_media_url=data.get("header_media_example_url"),
            )
            
            # Meta returns the template ID upon successful creation
            meta_id = meta_response.get("id", "")

            # 2. Save to our database natively if Meta accepts it
            with transaction.atomic():
                serializer.save(
                    meta_id=meta_id,
                    status=MessageTemplate.Status.PENDING # Always starts as pending
                )

        except MetaAPIError as e:
            import traceback
            print("=" * 80)
            print("META ERROR")
            print(type(e))
            print(str(e))

            if hasattr(e, "response"):
                print("Response:")
                print(e.response)

            traceback.print_exc()
            print("=" * 80)
            # Catch Meta's rejection and pipe it back to the React frontend
            raise ValidationError({
                "meta_api_error": str(e),
                "detail": "Meta rejected the template configuration."
            })
 
 
class MessageTemplateDetailView(generics.RetrieveAPIView):
    """
    GET /api/whatsapp/templates/<id>/ — single template detail.
    """
 
    serializer_class = MessageTemplateSerializer
    permission_classes = [IsAuthenticated]
    queryset = MessageTemplate.objects.all()
    lookup_url_kwarg = "template_id"
 

class SyncTemplateAPIView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):

        count = TemplateSyncService.sync_templates()

        return Response({
            "success": True,
            "updated": count
        })
    

# ══════════════════════════════════════════════════════════════════════
# Campaign list / create
# ══════════════════════════════════════════════════════════════════════
 
class CampaignListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/whatsapp/campaigns/   — paginated, filterable campaign list
    POST /api/whatsapp/campaigns/   — create a new draft campaign
 
    GET query params:
        status, template, created_by   — exact filters (see WhatsAppCampaignFilter)
        search                         — icontains on campaign name
        created_after / created_before — ISO 8601 date bounds
        ordering                       — created_at, -created_at, name, -name,
                                          sent_count, -sent_count (default: -created_at)
 
    POST body:
        { "name": "...", "template": <template_id> }
 
    Returns 201 with the created campaign's id, status, and template summary
    so the frontend can immediately call the existing TriggerBroadcastView.
    """
 
    permission_classes = [IsAuthenticated]
    pagination_class = CampaignPageNumberPagination
    filter_backends = [
        DjangoFilterBackend,
        drf_filters.OrderingFilter,
    ]
    filterset_class = WhatsAppCampaignFilter
    ordering_fields = ["created_at", "name", "sent_count", "total_recipients"]
    ordering = ["-created_at"]
 
    def get_serializer_class(self):
        if self.request.method == "POST":
            return WhatsAppCampaignCreateSerializer
        return WhatsAppCampaignListSerializer
 
    def get_queryset(self):
        # select_related("template", "created_by") collapses what would
        # otherwise be 2N queries (one per row, per FK) into a single JOIN.
        # Only the columns the list serializer actually renders are needed
        # off `created_by`, so `.only()` on the joined relation trims the
        # SELECT further for high-row-count pages.
        return (
            WhatsAppCampaign.objects
            .select_related("template", "created_by")
            .only(
                "id", "name", "status",
                "total_recipients", "sent_count", "delivered_count",
                "read_count", "failed_count", "click_count", "reply_count",
                "created_at", "updated_at",
                "template__id", "template__name", "template__meta_template_name",
                "template__language", "template__active",
                "created_by__id", "created_by__full_name"
            )
        )
 
    def get_serializer_context(self):
        # WhatsAppCampaignCreateSerializer.create() reads request.user from
        # context to populate created_by — this wiring is required for POST.
        context = super().get_serializer_context()
        context["request"] = self.request
        return context
 
    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            campaign = serializer.save()
        logger.info(
            "Campaign created | id=%s name=%s user=%s",
            campaign.pk, campaign.name, request.user,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
 
 
# ══════════════════════════════════════════════════════════════════════
# Campaign detail
# ══════════════════════════════════════════════════════════════════════
 
class CampaignDetailView(generics.RetrieveAPIView):
    """
    GET /api/whatsapp/campaigns/<campaign_id>/
 
    Full campaign detail including template body, rate metrics, and
    cancellable/deletable capability flags so the frontend can conditionally
    render action buttons without separately re-deriving the state machine.
    """
 
    serializer_class = WhatsAppCampaignDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "campaign_id"
 
    def get_queryset(self):
        return (
            WhatsAppCampaign.objects
            .select_related("template", "created_by")
        )
 
 
# ══════════════════════════════════════════════════════════════════════
# Campaign analytics (alias/extension of CampaignStatusView)
# ══════════════════════════════════════════════════════════════════════
 
class CampaignAnalyticsView(APIView):
    """
    GET /api/whatsapp/campaigns/<campaign_id>/analytics/
 
    Deliberately distinct from the existing CampaignStatusView (untouched):
    CampaignStatusView is a lightweight polling endpoint for live counters.
    This endpoint additionally breaks down recipient status distribution
    via a single annotated GROUP BY query — useful for a dashboard funnel
    chart (pending → queued → sending → sent → delivered → read / failed).
    """
 
    permission_classes = [IsAuthenticated]
 
    def get(self, request: Request, campaign_id: int) -> Response:
        try:
            campaign = WhatsAppCampaign.objects.get(pk=campaign_id)
        except WhatsAppCampaign.DoesNotExist:
            return Response(
                {"error": f"Campaign {campaign_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
 
        total = campaign.total_recipients or 1
 
        # Single GROUP BY query — O(distinct statuses) rows returned,
        # never O(total_recipients). Avoids looping recipients in Python.
        status_breakdown = dict(
            WhatsAppCampaignRecipient.objects
            .filter(campaign_id=campaign_id)
            .values("status")
            .annotate(count=Count("id"))
            .values_list("status", "count")
        )
 
        return Response({
            "campaign_id": campaign.pk,
            "name": campaign.name,
            "status": campaign.status,
            "total_recipients": campaign.total_recipients,
            "counters": {
                "sent_count": campaign.sent_count,
                "delivered_count": campaign.delivered_count,
                "read_count": campaign.read_count,
                "failed_count": campaign.failed_count,
                "click_count": campaign.click_count,
                "reply_count": campaign.reply_count,
            },
            "rates": {
                "delivery_rate": round(campaign.delivered_count / total * 100, 2),
                "read_rate": round(campaign.read_count / total * 100, 2),
                "click_rate": round(campaign.click_count / total * 100, 2),
                "response_rate": round(campaign.reply_count / total * 100, 2),
                "failure_rate": round(campaign.failed_count / total * 100, 2),
            },
            "recipient_status_breakdown": {
                choice_value: status_breakdown.get(choice_value, 0)
                for choice_value, _ in WhatsAppCampaignRecipient.STATUS_CHOICES
            },
            "updated_at": campaign.updated_at,
        })
 
 
# ══════════════════════════════════════════════════════════════════════
# Campaign recipients
# ══════════════════════════════════════════════════════════════════════
 
class CampaignRecipientListView(generics.ListAPIView):
    """
    GET /api/whatsapp/campaigns/<campaign_id>/recipients/
 
    Cursor-paginated recipient list for a single campaign, filterable by
    status and searchable by lead name/phone.
 
    Query params:
        status   — pending/queued/sending/sent/delivered/read/failed/skipped
        search   — icontains on lead.name / lead.phone
    """
 
    serializer_class = WhatsAppCampaignRecipientSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = RecipientCursorPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = WhatsAppCampaignRecipientFilter
 
    def get_queryset(self):
        campaign_id = self.kwargs["campaign_id"]
        # select_related("lead") avoids one query per row for the
        # lead_name / lead_phone fields the serializer flattens.
        # .only() further restricts the lead columns actually consumed.
        return (
            WhatsAppCampaignRecipient.objects
            .filter(campaign_id=campaign_id)
            .select_related("lead")
            .only(
                "id", "campaign_id", "lead_id", "status",
                "whatsapp_message_id", "custom_context", "error",
                "sent_at", "delivered_at", "read_at", "clicked_at",
                "lead__id", "lead__name", "lead__phone",
            )
        )
 
    def list(self, request: Request, *args, **kwargs) -> Response:
        campaign_id = self.kwargs["campaign_id"]
        if not WhatsAppCampaign.objects.filter(pk=campaign_id).exists():
            return Response(
                {"error": f"Campaign {campaign_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return super().list(request, *args, **kwargs)
 
 
# ══════════════════════════════════════════════════════════════════════
# Campaign activity timeline
# ══════════════════════════════════════════════════════════════════════
 
class CampaignActivityTimelineView(APIView):
    """
    GET /api/whatsapp/campaigns/<campaign_id>/activity/
 
    Merges campaign-level lifecycle timestamps with recipient milestone
    aggregates into a single chronological event list — useful for a
    dashboard "what happened and when" panel.
 
    Each milestone (first sent, first delivered, first read, last failure)
    is derived from a single aggregate query against the indexed
    (campaign, status, id) recipient table rather than iterating rows.
    """
 
    permission_classes = [IsAuthenticated]
 
    def get(self, request: Request, campaign_id: int) -> Response:
        try:
            campaign = WhatsAppCampaign.objects.get(pk=campaign_id)
        except WhatsAppCampaign.DoesNotExist:
            return Response(
                {"error": f"Campaign {campaign_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
 
        from django.db.models import Max, Min
 
        recipients = WhatsAppCampaignRecipient.objects.filter(
            campaign_id=campaign_id
        )
        milestone_aggregates = recipients.aggregate(
            first_sent=Min("sent_at"),
            last_sent=Max("sent_at"),
            first_delivered=Min("delivered_at"),
            first_read=Min("read_at"),
            first_clicked=Min("clicked_at"),
        )
        failed_count = recipients.filter(
            status=WhatsAppCampaignRecipient.STATUS_FAILED
        ).count()
 
        events = [
            {
                "event_type": "created",
                "label": "Campaign created",
                "timestamp": campaign.created_at,
                "count": None,
            },
            {
                "event_type": "first_sent",
                "label": "First message sent",
                "timestamp": milestone_aggregates["first_sent"],
                "count": campaign.sent_count,
            },
            {
                "event_type": "first_delivered",
                "label": "First message delivered",
                "timestamp": milestone_aggregates["first_delivered"],
                "count": campaign.delivered_count,
            },
            {
                "event_type": "first_read",
                "label": "First message read",
                "timestamp": milestone_aggregates["first_read"],
                "count": campaign.read_count,
            },
            {
                "event_type": "first_clicked",
                "label": "First link clicked",
                "timestamp": milestone_aggregates["first_clicked"],
                "count": campaign.click_count,
            },
            {
                "event_type": "failures",
                "label": "Messages failed",
                "timestamp": milestone_aggregates["last_sent"],
                "count": failed_count,
            },
            {
                "event_type": "status_changed",
                "label": f"Campaign is now '{campaign.status}'",
                "timestamp": campaign.updated_at,
                "count": None,
            },
        ]
 
        # Drop events with no timestamp (milestone hasn't happened yet),
        # keep "created" always, then sort chronologically.
        events = [
            e for e in events
            if e["timestamp"] is not None or e["event_type"] == "created"
        ]
        events.sort(key=lambda e: e["timestamp"] or campaign.created_at)
 
        serializer = CampaignActivityEventSerializer(events, many=True)
        return Response({
            "campaign_id": campaign.pk,
            "events": serializer.data,
        })
 
 
# ══════════════════════════════════════════════════════════════════════
# Campaign duplicate
# ══════════════════════════════════════════════════════════════════════
 
class CampaignDuplicateView(APIView):
    """
    POST /api/whatsapp/campaigns/<campaign_id>/duplicate/
 
    Creates a new DRAFT campaign cloned from an existing one (same name
    suffixed " (Copy)", same template). Deliberately does NOT copy
    recipients — duplicating a campaign is for re-running the same
    template against a fresh or re-filtered audience via the existing
    TriggerBroadcastView, not for re-sending to the exact same list
    (which would hit WhatsAppCampaignRecipient's unique_together
    constraint on a fresh campaign anyway, since campaign_id differs).
 
    Response 201:
        { "id": <new_id>, "name": "...", "template": {...}, "status": "draft" }
    """
 
    permission_classes = [IsAuthenticated]
 
    def post(self, request: Request, campaign_id: int) -> Response:
        try:
            source = WhatsAppCampaign.objects.select_related("template").get(
                pk=campaign_id
            )
        except WhatsAppCampaign.DoesNotExist:
            return Response(
                {"error": f"Campaign {campaign_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
 
        custom_name = (request.data or {}).get("name", "").strip()
        new_name = custom_name or f"{source.name} (Copy)"
 
        with transaction.atomic():
            clone = WhatsAppCampaign.objects.create(
                name=new_name,
                template=source.template,
                created_by=request.user,
                status=WhatsAppCampaign.STATUS_DRAFT,
            )
 
        logger.info(
            "Campaign duplicated | source=%s new=%s user=%s",
            campaign_id, clone.pk, request.user,
        )
 
        serializer = CampaignDuplicateResultSerializer(clone)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
 
 
# ══════════════════════════════════════════════════════════════════════
# Campaign cancel
# ══════════════════════════════════════════════════════════════════════
 
class CampaignCancelView(APIView):
    """
    POST /api/whatsapp/campaigns/<campaign_id>/cancel/
 
    Transitions a QUEUED/RUNNING/PAUSED campaign to CANCELLED.
 
    Does NOT touch in-flight Celery tasks directly (no broker-level revoke —
    that's intentionally out of scope here to avoid duplicating the existing
    Celery task architecture). Instead, it flips the campaign row to
    CANCELLED and bulk-updates any still-PENDING/QUEUED recipients to
    SKIPPED. Already-SENDING recipients are left alone since a send is
    in-flight at the HTTP layer with Meta and must be allowed to resolve
    to its terminal state by the existing engine.
    """
 
    permission_classes = [IsAuthenticated]
 
    def post(self, request: Request, campaign_id: int) -> Response:
        try:
            campaign = WhatsAppCampaign.objects.get(pk=campaign_id)
        except WhatsAppCampaign.DoesNotExist:
            return Response(
                {"error": f"Campaign {campaign_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
 
        try:
            validate_cancellable(campaign)
            validate_owner_or_staff(campaign, request.user)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
 
        with transaction.atomic():
            updated = WhatsAppCampaign.objects.filter(
                pk=campaign_id, status=campaign.status
            ).update(status=WhatsAppCampaign.STATUS_CANCELLED)
 
            if not updated:
                # Lost a race with a concurrent state change between the
                # validate_cancellable check and this UPDATE.
                return Response(
                    {"error": "Campaign state changed concurrently. Please retry."},
                    status=status.HTTP_409_CONFLICT,
                )
 
            skipped = WhatsAppCampaignRecipient.objects.filter(
                campaign_id=campaign_id,
                status__in=[
                    WhatsAppCampaignRecipient.STATUS_PENDING,
                    WhatsAppCampaignRecipient.STATUS_QUEUED,
                ],
            ).update(status=WhatsAppCampaignRecipient.STATUS_SKIPPED)
 
        logger.info(
            "Campaign cancelled | campaign=%s skipped_recipients=%d user=%s",
            campaign_id, skipped, request.user,
        )
 
        return Response({
            "campaign_id": campaign_id,
            "status": WhatsAppCampaign.STATUS_CANCELLED,
            "skipped_recipients": skipped,
        })
 
 
# ══════════════════════════════════════════════════════════════════════
# Campaign delete
# ══════════════════════════════════════════════════════════════════════
 
class CampaignDeleteView(APIView):
    """
    DELETE /api/whatsapp/campaigns/<campaign_id>/delete/
 
    Hard-deletes a campaign in a terminal or never-started state.
    Recipients cascade-delete via the model's on_delete=CASCADE FK;
    WhatsAppMessage rows referencing those recipients are preserved
    (their campaign_recipient FK is on_delete=SET_NULL) so historical
    chat threads in the Smart Inbox are never silently erased.
    """
 
    permission_classes = [IsAuthenticated]
 
    def delete(self, request: Request, campaign_id: int) -> Response:
        try:
            campaign = WhatsAppCampaign.objects.get(pk=campaign_id)
        except WhatsAppCampaign.DoesNotExist:
            return Response(
                {"error": f"Campaign {campaign_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
 
        try:
            validate_deletable(campaign)
            validate_owner_or_staff(campaign, request.user)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
 
        campaign_name = campaign.name
        with transaction.atomic():
            campaign.delete()
 
        logger.info(
            "Campaign deleted | id=%s name=%s user=%s",
            campaign_id, campaign_name, request.user,
        )
 
        return Response(status=status.HTTP_204_NO_CONTENT)
 
 
# ══════════════════════════════════════════════════════════════════════
# Campaign preview
# ══════════════════════════════════════════════════════════════════════
 
class CampaignPreviewView(APIView):
    """
    GET /api/whatsapp/campaigns/<campaign_id>/preview/
 
    Renders the campaign's template body against a sample recipient's
    actual custom_context (or generic placeholders if no recipients have
    been seeded yet) so the frontend can show "here's what the customer
    will see" before triggering. Reuses TemplateTokenizer from the existing
    broadcast engine rather than re-implementing variable substitution.
    """
 
    permission_classes = [IsAuthenticated]
 
    def get(self, request: Request, campaign_id: int) -> Response:
        from .services.broadcast_engine import TemplateTokenizer
 
        try:
            campaign = WhatsAppCampaign.objects.select_related("template").get(
                pk=campaign_id
            )
        except WhatsAppCampaign.DoesNotExist:
            return Response(
                {"error": f"Campaign {campaign_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
 
        sample_recipient = (
            WhatsAppCampaignRecipient.objects
            .filter(campaign_id=campaign_id)
            .select_related("lead")
            .only("id", "lead__name", "lead__phone", "custom_context")
            .first()
        )
 
        if sample_recipient is not None:
            context = {
                "name": getattr(sample_recipient.lead, "name", ""),
                "phone": getattr(sample_recipient.lead, "phone", ""),
            }
            context.update(sample_recipient.custom_context or {})
            sample_source = "recipient"
        else:
            # No recipients seeded yet — use generic placeholder values
            # for each declared variable so the preview is still useful.
            context = {key: f"[{key}]" for key in campaign.template.variables}
            sample_source = "placeholder"
 
        tokenizer = TemplateTokenizer(campaign.template.body)
        rendered = tokenizer.render(context)
 
        return Response({
            "campaign_id": campaign.pk,
            "template_name": campaign.template.meta_template_name,
            "language": campaign.template.language,
            "raw_body": campaign.template.body,
            "rendered_preview": rendered,
            "sample_source": sample_source,
            "variables_used": campaign.template.variables,
        })
 
 
# ══════════════════════════════════════════════════════════════════════
# Campaign filter options
# ══════════════════════════════════════════════════════════════════════
 
class CampaignFilterOptionsView(APIView):
    """
    GET /api/whatsapp/campaigns/filters/
 
    Returns the available filter dimensions (status choices, active
    templates) so the frontend can populate filter dropdowns without
    hardcoding choice lists that could drift from the backend's
    STATUS_CHOICES definitions.
    """
 
    permission_classes = [IsAuthenticated]
 
    def get(self, request: Request) -> Response:
        templates = list(
            MessageTemplate.objects.filter(active=True)
            .order_by("name")
            .values("id", "name", "meta_template_name")
        )
        return Response({
            "status_choices": [
                {"value": value, "label": label}
                for value, label in WhatsAppCampaign.STATUS_CHOICES
            ],
            "templates": templates,
        })
 
 
# ══════════════════════════════════════════════════════════════════════
# Global message stream
# ══════════════════════════════════════════════════════════════════════

class GlobalMessageStreamView(generics.ListAPIView):
    """
    GET /api/whatsapp/messages/
 
    Cursor-paginated message stream, filterable by chat_id (customer
    thread) or campaign_id (broadcast log).
 
    Query params:
        chat_id      — filter to one chat thread (Smart Inbox view)
        campaign_id  — filter to one campaign's outbound log
        direction    — incoming / outgoing
        sender_type  — customer / agent / system
        status       — sent / delivered / read / failed
        cursor       — pagination cursor (opaque, from previous response)
        page_size    — up to 200
 
    Requires at least one of chat_id / campaign_id to avoid an unbounded
    full-table scan across the entire message history.
    """
 
    serializer_class = WhatsAppMessageStreamSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = MessageStreamCursorPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = WhatsAppMessageFilter
 
    def get_queryset(self):
        # select_related("campaign_recipient") lets the serializer's
        # get_campaign_id / get_recipient_status methods read cr.campaign_id
        # (a plain FK column, no join needed) and cr.status as attribute
        # access — zero extra queries per row even across a 200-row page.
        # No need to traverse into campaign_recipient__campaign itself:
        # the serializer only ever reads cr.campaign_id, never cr.campaign.*.
        return (
            WhatsAppMessage.objects
            .select_related("campaign_recipient")
            .only(
                "id", "message_id", "chat_id", "sender_type", "direction",
                "message_type", "body", "media_url", "template_name",
                "status", "created_at",
                "campaign_recipient__id", "campaign_recipient__status",
                "campaign_recipient__campaign_id",
            )
        )
 
    def list(self, request: Request, *args, **kwargs) -> Response:
        chat_id = request.query_params.get("chat_id")
        campaign_id = request.query_params.get("campaign_id")
 
        if not chat_id and not campaign_id:
            return Response(
                {
                    "error": (
                        "At least one of 'chat_id' or 'campaign_id' query "
                        "parameters is required."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        return super().list(request, *args, **kwargs)
 
class CampaignExcelBroadcastView(generics.CreateAPIView):
    """
    POST /api/whatsapp/campaigns/excel-broadcast/
    
    Multipart/form-data request containing:
    - name: String
    - template: ID (Integer)
    - file: Binary Excel/CSV file
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = WhatsAppCampaignExcelCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        
        with transaction.atomic():
            campaign = serializer.save()
            
        # Trigger async Celery task to parse data and execute compliant messaging
        process_excel_broadcast_task.delay(campaign.id, campaign._temporary_file_path)
        
        logger.info("Excel Campaign initialized asynchronously | Campaign ID: %s", campaign.id)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class WhatsAppWebhookView(APIView):
    """
    Production-grade Webhook receiver managing Meta Cloud API handshakes,
    mobile app echoes, and simultaneous automated vs. human message routing.
    """
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        mode = request.query_params.get('hub.mode')
        token = request.query_params.get('hub.verify_token')
        challenge = request.query_params.get('hub.challenge')

        if mode and token:
            if mode == 'subscribe' and token == META_WEBHOOK_VERIFY_TOKEN:
                logger.info("Meta Webhook verified successfully.")
                return HttpResponse(challenge, content_type="text/plain")
            return HttpResponse("Verification token mismatch", status=status.HTTP_403_FORBIDDEN)
        return HttpResponse("Invalid arguments", status=status.HTTP_400_BAD_REQUEST)

    def post(self, request, *args, **kwargs):
        payload = request.data

        if not payload.get('object') == 'whatsapp_business_account' or 'entry' not in payload:
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                
                # 1. Process Message Status Updates (Delivered, Read, Failed)
                if 'statuses' in value:
                    for status_obj in value.get('statuses', []):
                        self._handle_status_update(status_obj)
                            
                # 2. Process Inbound Messages & Handset Coexistence Echoes
                if 'messages' in value:
                    customer_name = value.get('contacts', [{}])[0].get('profile', {}).get('name', 'WhatsApp User')
                    for message in value.get('messages', []):
                        message_id = message.get('id')
                        
                        # O(1) De-duplication check
                        if message_deduplicator.contains_and_add(message_id):
                            logger.warning(f"Duplicate message dropped: {message_id}")
                            continue
                        
                        # CRITICAL: Detect if message was sent by an agent via physical phone handset app
                        is_echo = message.get('message_echoes') is True or message.get('from') == META_PHONE_ID
                        
                        self._process_message_lifecycle(message, customer_name, is_echo)

        return Response({"status": "processed"}, status=status.HTTP_200_OK)

    def _process_message_lifecycle(self, message_obj, customer_name, is_echo):
        """
        Manages the message lifecycle matrix, seamlessly balancing automated tracks 
        and manual human interventions.
        """
        from_phone = message_obj.get('from')
        wamid = message_obj.get('id')
        msg_type = message_obj.get('type', 'text')
        
        # Safely capture message content body
        if msg_type == 'text':
            body_content = message_obj.get('text', {}).get('body', '')
        elif msg_type == 'button':
            body_content = message_obj.get('button', {}).get('text', '')
        elif msg_type == 'interactive':
            body_content = message_obj.get('interactive', {}).get('button_reply', {}).get('title', 'Interactive Selection')
        else:
            body_content = f"[{msg_type.upper()} Media Element Received]"

        # Normalize targeting phone schema
        customer_phone = message_obj.get('to') if is_echo else from_phone
        e164_phone = f"+{customer_phone}" if not customer_phone.startswith("+") else customer_phone
        clean_phone = customer_phone.replace("+", "")

        try:
            with transaction.atomic():
                lead_obj, _ = Lead.objects.get_or_create(
                    phone=e164_phone,
                    defaults={'name': customer_name}
                )

                # Fetch chat instance with selective row locking to guarantee serial safety
                chat_obj, created = WhatsAppChat.objects.select_for_update().get_or_create(
                    phone_number=e164_phone,
                    defaults={
                        'lead': lead_obj,
                        'whatsapp_id': f"wa_chat_{clean_phone}",
                        'customer_name': lead_obj.name or customer_name,
                        'status': WhatsAppChat.STATUS_UNASSIGNED,
                        'is_automated': True  # Default fresh conversations to the automation layer
                    }
                )

                if is_echo:
                    # SCENARIO A: Human agent replied directly via their physical smartphone handset app
                    chat_obj.is_automated = False  # Break automation loop instantly
                    chat_obj.last_message_at = timezone.now()
                    chat_obj.save(update_fields=['is_automated', 'last_message_at'])

                    msg_obj, _ = WhatsAppMessage.objects.get_or_create(
                        message_id=wamid,
                        defaults={
                            'chat': chat_obj,
                            'sender_type': 'agent',
                            'direction': 'outgoing',
                            'message_type': msg_type,
                            'body': body_content,
                            'status': 'sent',
                            'meta_payload': message_obj
                        }
                    )
                    # Sync Web UI agent windows to reflect manual handset adjustments
                    self._broadcast_to_dashboard(clean_phone, chat_obj.status, msg_obj)
                    logger.info(f"Handset Echo Intercepted: Automation suspended for chat {clean_phone}")

                else:
                    # SCENARIO B: Inbound customer message
                    if not created:
                        if chat_obj.status == WhatsAppChat.STATUS_RESOLVED:
                            chat_obj.status = WhatsAppChat.STATUS_UNASSIGNED
                        chat_obj.unread_count = F('unread_count') + 1
                    else:
                        chat_obj.unread_count = 1

                    chat_obj.last_message_at = timezone.now()
                    chat_obj.save(update_fields=['status', 'unread_count', 'last_message_at'])

                    msg_obj, _ = WhatsAppMessage.objects.get_or_create(
                        message_id=wamid,
                        defaults={
                            'chat': chat_obj,
                            'sender_type': 'customer',
                            'direction': 'incoming',
                            'message_type': msg_type,
                            'body': body_content,
                            'status': 'delivered',
                            'meta_payload': message_obj
                        }
                    )

                    # ── Simultaneous Routing Routing Engine ──

                    # 1. Conditionally route to AI (Kafka) or handle Live Chat (Direct Broadcast)
                    if chat_obj.is_automated:
                        # Route down to Kafka Automation Top Level Queue for AI bot logic processing.
                        # The Kafka consumer safely manages DB checkpoints and broadcasts to WebSockets, 
                        # avoiding duplicate messages on the UI thread.
                        KafkaProducerClient.publish_event(
                            topic="whatsapp_inbound_messages", 
                            key=clean_phone,
                            value=message_obj
                        )
                        logger.info(f"Routed chat {clean_phone} natively to Automated AI pipeline. WebSocket broadcast deferred to Kafka Consumer.")
                    else:
                        # For Human Live Chat, broadcast immediately from the webhook since it bypasses Kafka entirely
                        self._broadcast_to_dashboard(clean_phone, chat_obj.status, msg_obj)
                        logger.info(f"Routed chat {clean_phone} directly to Human Live Chat Workspace and broadcasted to UI.")

        except Exception as e:
            logger.error(f"Error executing message routing orchestration for {e164_phone}: {str(e)}")

    def _broadcast_to_dashboard(self, clean_phone, queue_status, msg_obj):
        """ Helper method to transmit uniform structured frames down down to Channels layers """
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        
        channel_layer = get_channel_layer()
        payload = {
            "type": "chat_message_inbound",
            "data": {
                "id": msg_obj.id,
                "message_id": msg_obj.message_id,
                "chat_id": msg_obj.chat_id,
                "sender_type": msg_obj.sender_type,
                "direction": msg_obj.direction,
                "message_type": msg_obj.message_type,
                "body": msg_obj.body,
                "status": msg_obj.status,
                "created_at": msg_obj.created_at.isoformat() if msg_obj.created_at else None
            }
        }
        # Direct UI Thread view update
        async_to_sync(channel_layer.group_send)(f"chat_thread_{clean_phone}", payload)
        # General live stream side-bar update
        async_to_sync(channel_layer.group_send)(f"chat_queue_{queue_status}", payload)


class ToggleChatAutomationView(APIView):
    """
    POST /api/whatsapp/chats/<chat_id>/toggle-automation/
    Allows human agents to explicitly hand off conversations back to AI management or vice versa.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, chat_id, *args, **kwargs):
        is_automated = request.data.get("is_automated", True)
        try:
            with transaction.atomic():
                chat = WhatsAppChat.objects.select_for_update().get(pk=chat_id)
                chat.is_automated = is_automated
                if is_automated:
                    chat.status = WhatsAppChat.STATUS_RESOLVED  # Clean workspace queue
                    chat.unread_count = 0
                chat.save(update_fields=['is_automated', 'status', 'unread_count'])
                
            logger.info(f"Chat {chat.phone_number} automation flag flipped to {is_automated} by {request.user}")
            return Response({"status": "success", "is_automated": chat.is_automated}, status=status.HTTP_200_OK)
        except WhatsAppChat.DoesNotExist:
            return Response({"error": "Chat target instance not found."}, status=status.HTTP_404_NOT_FOUND)
        

class WhatsAppChatListView(APIView):
    """
    Retrieves all active unique chat sessions to populate the sidebar inbox.
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        # Fetch all unique chat phone numbers ordered by recent activity
        chats = WhatsAppChat.objects.all().order_by('-updated_at')[:100]
        phone_numbers = [chat.phone_number for chat in chats]
        
        return Response({
            "status": "success",
            "chats": phone_numbers
        }, status=status.HTTP_200_OK)


class WhatsAppChatHistoryAPIView(APIView):
    """
    High-throughput, cursor-paginated API view for retrieving chat history.
    Dynamically fallback-matches variants to accommodate both legacy and normalized E.164 styles.
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    PAGE_SIZE = 50

    def decode_cursor(self, cursor_str):
        if not cursor_str:
            return None
        try:
            decoded_bytes = base64.b64decode(cursor_str.encode('utf-8'))
            cursor_data = json.loads(decoded_bytes.decode('utf-8'))
            return {
                "last_id": cursor_data.get("id"),
                "last_timestamp": cursor_data.get("ts")
            }
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def encode_cursor(self, last_message):
        if not last_message:
            return None
        cursor_data = {
            "id": last_message.id,
            "ts": last_message.created_at.isoformat() if last_message.created_at else None
        }
        serialized = json.dumps(cursor_data)
        return base64.b64encode(serialized.encode('utf-8')).decode('utf-8')

    def get(self, request, phone_number, *args, **kwargs):
        # --- DEBUG LOGGING: Track Incoming Values ---
        logger.info("================== WHATSAPP HISTORY TRACE ==================")
        logger.info(f"Raw urlencoded path parameter 'phone_number': {repr(phone_number)}")
        import urllib.parse
        # 1. Clean URL Decode (Fixes + decoding to spaces or %2B anomalies)
        decoded_phone = urllib.parse.unquote(phone_number).strip()
        
        # If the webserver converted '+' to ' ' (space), restore it
        if decoded_phone.startswith(' '):
            decoded_phone = '+' + decoded_phone[1:].strip()
        elif not decoded_phone.startswith('+') and len(decoded_phone) > 10:
            # Ensure it has a plus sign for E.164 standardization
            decoded_phone = '+' + decoded_phone

        logger.info(f"Unescaped/Sanitized parameter value: {repr(decoded_phone)}")

        try:
            # 2. Standardize formatting safely using your validation rules
            cleaned_phone = WhatsAppChatEngine.validate_and_standardize_phone(decoded_phone)
            legacy_phone = cleaned_phone.replace('+', '')
            logger.info(f"Target matches -> Cleaned: {repr(cleaned_phone)} | Legacy: {repr(legacy_phone)}")
        except Exception as err:
            logger.error(f"Phone Validation failed: {str(err)}")
            return Response(
                {"error": "Malformatted or invalid phone schema structure.", "detail": str(err)},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3. Resilient Database Query across both phone_number and whatsapp_id fields
        lookup_filter = (
            Q(phone_number=cleaned_phone) | 
            Q(phone_number=legacy_phone) |
            Q(whatsapp_id=cleaned_phone) |
            Q(whatsapp_id=legacy_phone) |
            Q(whatsapp_id=f"wa_chat_{legacy_phone}")
        )
        
        # Fallback numeric ID lookup if the input parameter is a raw ID (like chat_id: 8)
        if legacy_phone.isdigit():
            lookup_filter |= Q(id=int(legacy_phone))
            if phone_number.isdigit():
                 lookup_filter |= Q(id=int(phone_number))

        logger.info("Querying WhatsAppChat with filter criteria...")
        chat = WhatsAppChat.objects.filter(lookup_filter).first()

        # --- DEBUG LOGGING: Database Search Results ---
        if chat:
            logger.info(f"SUCCESS: Chat found in DB! ID: {chat.id} | Phone: {chat.phone_number} | WhatsApp ID: {chat.whatsapp_id}")
        else:
            logger.warning(f"FAILURE: No chat matching '{cleaned_phone}' or legacy keys found in database.")
            # Print a quick lookup of what actually exists in the table to help you compare structures
            existing_sample = WhatsAppChat.objects.all().values('id', 'phone_number', 'whatsapp_id')[:3]
            logger.info(f"First 3 records in your DB: {list(existing_sample)}")
            
            return Response(
                {"status": "success", "next_cursor": None, "messages": []},
                status=status.HTTP_200_OK
            )

        cursor_param = request.query_params.get('cursor')
        cursor = self.decode_cursor(cursor_param)
        messages_queryset = WhatsAppMessage.objects.filter(chat=chat)

        if cursor:
            messages_queryset = messages_queryset.filter(
                created_at__lt=cursor["last_timestamp"]
            ) | messages_queryset.filter(
                created_at=cursor["last_timestamp"], 
                id__lt=cursor["last_id"]
            )

        records = list(messages_queryset.order_by('-created_at', '-id')[:self.PAGE_SIZE + 1])
        logger.info(f"Retrieved {len(records)} message history records from the database for Chat ID: {chat.id}.")

        has_next = len(records) > self.PAGE_SIZE
        if has_next:
            sliced_records = records[:self.PAGE_SIZE]
            next_cursor = self.encode_cursor(sliced_records[-1])
        else:
            sliced_records = records
            next_cursor = None

        serialized_messages = [
            {
                "id": msg.id,
                "message_id": msg.message_id,
                "sender_type": msg.sender_type,
                "direction": msg.direction,
                "message_type": msg.message_type,
                "body": msg.body,
                "status": msg.status,
                "created_at": msg.created_at.isoformat() if msg.created_at else None
            }
            for msg in reversed(sliced_records)
        ]

        logger.info("============================================================")
        return Response({
            "status": "success",
            "next_cursor": next_cursor,
            "messages": serialized_messages
        }, status=status.HTTP_200_OK)


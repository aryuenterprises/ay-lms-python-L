"""
reports/services.py

Business logic layer for all report types.

Architecture
------------
* ``ReportService.dispatch()`` routes to individual ``get_*`` methods.
* Each method is responsible for exactly one report type.
* All database work uses the Django ORM — no raw SQL.
* Aggregations are done in the database, never in Python loops.
* QuerySets use ``select_related`` / ``prefetch_related`` / ``values``
  to minimise round-trips and memory usage.
* Pagination is applied at the QuerySet level before serialisation.

Return contract
---------------
Every ``get_*`` method returns a ``dict`` with keys:
    ``count``   – total unsliced row/group count
    ``results`` – serialised page data (plain Python list)
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from django.db.models import (
    Avg,
    Case,
    Count,
    ExpressionWrapper,
    F,
    FloatField,
    IntegerField,
    Max,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, TruncDate
from .models import Lead, LeadCallLog, LeadFollowUp, LeadStatusHistory,LeadDMLog
from aryuapp.models import User

from .constants import (
    DEFAULT_PAGE_SIZE,
    FUNNEL_STAGES,
    MAX_PAGE_SIZE,
    MSG_INVALID_PAGINATION,
    MSG_PAGE_SIZE_EXCEEDED,
    REPORT_ARCHIVED_LEADS,
    REPORT_CALL_REPORT,
    REPORT_CALL_SUMMARY,
    REPORT_CONVERSION,
    REPORT_CONVERTED_LEADS,
    REPORT_COURSE,
    REPORT_DAILY_CALL,
    REPORT_DM,
    REPORT_DUPLICATE_LEADS,
    REPORT_FOLLOWUP,
    REPORT_FUNNEL,
    REPORT_LEAD_CREATION,
    REPORT_LEAD_EXPORT,
    REPORT_LEAD_SOURCE,
    REPORT_LEAD_STATUS,
    REPORT_OVERDUE_FOLLOWUPS,
    REPORT_STATUS_HISTORY,
    REPORT_USER_ASSIGNMENT,
)
from .filters import (
    CallLogFilterEngine,
    DMLogFilterEngine,
    FollowUpFilterEngine,
    ReportFilterEngine,
    StatusHistoryFilterEngine,
)
from .serializers import (
    CallReportSerializer,
    CallSummarySerializer,
    ConversionReportSerializer,
    ConvertedLeadSerializer,
    CourseReportSerializer,
    DMReportSerializer,
    DailyCallReportSerializer,
    FollowUpReportSerializer,
    FunnelReportSerializer,
    LeadCreationReportSerializer,
    LeadExportSerializer,
    LeadSourceReportSerializer,
    LeadStatusReportSerializer,
    OverdueFollowUpSerializer,
    StatusHistoryReportSerializer,
    UserAssignmentReportSerializer,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy model imports (avoids circular imports in some project layouts)
# ---------------------------------------------------------------------------


def _lead_model():

    return Lead


def _call_log_model():

    return LeadCallLog


def _dm_log_model():

    return LeadDMLog


def _followup_model():

    return LeadFollowUp


def _status_history_model():

    return LeadStatusHistory


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------


class PaginationParams:
    """Validated pagination parameters extracted from service-layer inputs."""

    __slots__ = ("page", "page_size", "offset", "limit")

    def __init__(self, page: int, page_size: int) -> None:
        if page < 1 or page_size < 1:
            raise ValueError(MSG_INVALID_PAGINATION)
        if page_size > MAX_PAGE_SIZE:
            raise ValueError(MSG_PAGE_SIZE_EXCEEDED)
        self.page = page
        self.page_size = page_size
        self.limit: int = page_size
        self.offset: int = (page - 1) * page_size


# ---------------------------------------------------------------------------
# Aggregation helper
# ---------------------------------------------------------------------------


def _safe_pct(converted_expr, total_expr) -> Case:
    """Return a SQL expression for conversion percentage (0–100 float)."""
    return Case(
        When(
            **{total_expr + "__gt": 0},
            then=ExpressionWrapper(
                F(converted_expr) * Value(100.0) / F(total_expr),
                output_field=FloatField(),
            ),
        ),
        default=Value(0.0),
        output_field=FloatField(),
    )


# ---------------------------------------------------------------------------
# ReportService
# ---------------------------------------------------------------------------


class ReportService:
    """
    Central service that dispatches report generation.

    All public methods follow the contract:

    ::

        returns {"count": int, "results": list}
    """

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    _DISPATCH_MAP: dict[str, str] = {
        REPORT_LEAD_EXPORT: "get_lead_export",
        REPORT_CONVERTED_LEADS: "get_converted_leads",
        REPORT_CALL_REPORT: "get_call_report",
        REPORT_CALL_SUMMARY: "get_call_summary",
        REPORT_DAILY_CALL: "get_daily_call_report",
        REPORT_LEAD_SOURCE: "get_lead_source_report",
        REPORT_LEAD_STATUS: "get_lead_status_report",
        REPORT_FOLLOWUP: "get_followup_report",
        REPORT_OVERDUE_FOLLOWUPS: "get_overdue_followups",
        REPORT_DM: "get_dm_report",
        REPORT_STATUS_HISTORY: "get_status_history_report",
        REPORT_LEAD_CREATION: "get_lead_creation_report",
        REPORT_CONVERSION: "get_conversion_report",
        REPORT_FUNNEL: "get_funnel_report",
        REPORT_DUPLICATE_LEADS: "get_duplicate_leads",
        REPORT_ARCHIVED_LEADS: "get_archived_leads",
        REPORT_COURSE: "get_course_report",
        REPORT_USER_ASSIGNMENT: "get_user_assignment_report",
    }

    def dispatch(
        self,
        report_type: str,
        filters: dict[str, Any],
        pagination: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Route a report request to the correct handler method.

        Parameters
        ----------
        report_type:
            A validated report type string from :data:`VALID_REPORT_TYPES`.
        filters:
            Validated filter dict (may be empty).
        pagination:
            Dict with ``page`` and ``page_size`` keys.

        Returns
        -------
        dict
            ``{"count": int, "results": list}``
        """
        page = pagination.get("page", 1)
        page_size = pagination.get("page_size", DEFAULT_PAGE_SIZE)
        params = PaginationParams(page=page, page_size=page_size)

        handler_name = self._DISPATCH_MAP[report_type]
        handler = getattr(self, handler_name)
        return handler(filters=filters, params=params)

    # ------------------------------------------------------------------
    # 1. Lead export
    # ------------------------------------------------------------------

    def get_lead_export(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Return all leads matching filters, fully serialised."""
        Lead = _lead_model()
        qs = (
            Lead.objects.select_related(
                "followup_by", "handled_by"
            )
            .order_by("-created_at")
        )
        qs = ReportFilterEngine.apply(qs, filters)
        count = qs.count()
        page_qs = qs[params.offset : params.offset + params.limit]
        serializer = LeadExportSerializer(page_qs, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 2. Converted leads
    # ------------------------------------------------------------------

    def get_converted_leads(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Return converted leads with ``days_to_convert`` annotation."""
        from django.db.models import DurationField
        from django.db.models.functions import Cast

        Lead = _lead_model()
        qs = (
            Lead.objects.filter(is_converted=True)
            .select_related("followup_by", "handled_by")
            .annotate(
                days_to_convert=ExpressionWrapper(
                    TruncDate(F("joined_at")) - TruncDate(F("created_at")),
                    output_field=DurationField(),
                )
            )
            .order_by("-joined_at")
        )
        qs = ReportFilterEngine.apply(qs, filters)
        count = qs.count()
        page_qs = qs[params.offset : params.offset + params.limit]

        rows = []
        for lead in page_qs:
            duration = lead.days_to_convert
            days = duration.days if duration is not None else None
            rows.append(
                {
                    "id": lead.id,
                    "name": lead.name,
                    "phone": lead.phone,
                    "email": lead.email,
                    "course": lead.course,
                    "status": lead.status,
                    "source": lead.source,
                    "joined_at": lead.joined_at,
                    "created_at": lead.created_at,
                    "days_to_convert": days,
                }
            )
        serializer = ConvertedLeadSerializer(rows, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 3. Call report
    # ------------------------------------------------------------------

    def get_call_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Return per-call-log rows with computed duration_minutes."""
        LeadCallLog = _call_log_model()
        qs = (
            LeadCallLog.objects.select_related("lead", "called_by")
            .annotate(
                duration_minutes=ExpressionWrapper(
                    Coalesce(F("duration_seconds"), Value(0)) / Value(60.0),
                    output_field=FloatField(),
                )
            )
            .order_by("-call_time")
        )
        qs = CallLogFilterEngine.apply(qs, filters)
        count = qs.count()
        page_qs = qs.values(
            "id",
            "lead_id",
            "lead__name",
            "lead__phone",
            "called_by__get_full_name",
            "call_time",
            "duration_seconds",
            "duration_minutes",
            "call_status",
            "call_type",
            "remarks",
            "next_followup_date",
            "recording_url",
        )[params.offset : params.offset + params.limit]

        rows = []
        for row in page_qs:
            rows.append(
                {
                    "id": row["id"],
                    "lead_id": row["lead_id"],
                    "lead__name": row["lead__name"],
                    "lead__phone": row["lead__phone"],
                    "called_by": row.get("called_by__get_full_name"),
                    "call_time": row["call_time"],
                    "duration_seconds": row["duration_seconds"],
                    "duration_minutes": row["duration_minutes"],
                    "call_status": row["call_status"],
                    "call_type": row["call_type"],
                    "remarks": row["remarks"],
                    "next_followup_date": row["next_followup_date"],
                    "recording_url": row["recording_url"],
                }
            )
        serializer = CallReportSerializer(rows, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 4. Call summary  (aggregated — no Python loops)
    # ------------------------------------------------------------------

    def get_call_summary(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Group calls by ``called_by`` user, aggregate statistics."""
        LeadCallLog = _call_log_model()
        qs = LeadCallLog.objects.select_related("called_by")
        qs = CallLogFilterEngine.apply(qs, filters)

        aggregated = (
            qs.values("called_by__id", "called_by__first_name", "called_by__last_name")
            .annotate(
                total_calls=Count("id"),
                total_duration_seconds=Coalesce(Sum("duration_seconds"), Value(0)),
                average_call_duration=Avg("duration_seconds"),
                longest_call_duration=Max("duration_seconds"),
            )
            .annotate(
                total_duration_minutes=ExpressionWrapper(
                    F("total_duration_seconds") / Value(60.0),
                    output_field=FloatField(),
                )
            )
            .order_by("-total_calls")
        )

        count = aggregated.count()
        page_data = aggregated[params.offset : params.offset + params.limit]

        rows = [
            {
                "user": f"{r['called_by__first_name']} {r['called_by__last_name']}".strip()
                or str(r["called_by__id"]),
                "total_calls": r["total_calls"],
                "total_duration_seconds": r["total_duration_seconds"],
                "total_duration_minutes": round(r["total_duration_minutes"] or 0, 2),
                "average_call_duration": round(r["average_call_duration"] or 0, 2),
                "longest_call_duration": r["longest_call_duration"],
            }
            for r in page_data
        ]
        serializer = CallSummarySerializer(rows, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 5. Daily call report
    # ------------------------------------------------------------------

    def get_daily_call_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Group calls by date."""
        LeadCallLog = _call_log_model()
        qs = LeadCallLog.objects.all()
        qs = CallLogFilterEngine.apply(qs, filters)

        aggregated = (
            qs.annotate(date=TruncDate("call_time"))
            .values("date")
            .annotate(
                total_calls=Count("id"),
                unique_leads=Count("lead_id", distinct=True),
                total_duration=Coalesce(Sum("duration_seconds"), Value(0)),
            )
            .order_by("-date")
        )

        count = aggregated.count()
        page_data = list(aggregated[params.offset : params.offset + params.limit])
        serializer = DailyCallReportSerializer(page_data, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 6. Lead source report
    # ------------------------------------------------------------------

    def get_lead_source_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Group leads by source with conversion metrics."""
        Lead = _lead_model()
        qs = Lead.objects.all()
        qs = ReportFilterEngine.apply(qs, filters)

        aggregated = (
            qs.values("source")
            .annotate(
                total_leads=Count("id"),
                converted=Count("id", filter=Q(is_converted=True)),
                pending=Count("id", filter=Q(is_converted=False)),
            )
            .annotate(
                conversion_percentage=Case(
                    When(
                        total_leads__gt=0,
                        then=ExpressionWrapper(
                            F("converted") * Value(100.0) / F("total_leads"),
                            output_field=FloatField(),
                        ),
                    ),
                    default=Value(0.0),
                    output_field=FloatField(),
                )
            )
            .order_by("-total_leads")
        )

        count = aggregated.count()
        page_data = list(aggregated[params.offset : params.offset + params.limit])
        serializer = LeadSourceReportSerializer(page_data, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 7. Lead status report
    # ------------------------------------------------------------------

    def get_lead_status_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Group leads by status."""
        Lead = _lead_model()
        qs = Lead.objects.all()
        qs = ReportFilterEngine.apply(qs, filters)

        aggregated = (
            qs.values("status")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        count = aggregated.count()
        page_data = list(aggregated[params.offset : params.offset + params.limit])
        serializer = LeadStatusReportSerializer(page_data, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 8. Follow-up report
    # ------------------------------------------------------------------

    def get_followup_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Return all follow-up records."""
        LeadFollowUp = _followup_model()
        qs = (
            LeadFollowUp.objects.select_related("lead", "assigned_to")
            .order_by("followup_date")
        )
        qs = FollowUpFilterEngine.apply(qs, filters)
        count = qs.count()
        page_qs = qs.values(
            "id",
            "lead_id",
            "lead__name",
            "assigned_to__first_name",
            "assigned_to__last_name",
            "followup_date",
            "status",
            "completed_at",
        )[params.offset : params.offset + params.limit]

        rows = [
            {
                "id": r["id"],
                "lead_id": r["lead_id"],
                "lead_name": r["lead__name"],
                "assigned_to": (
                    f"{r['assigned_to__first_name']} {r['assigned_to__last_name']}".strip()
                    if r.get("assigned_to__first_name")
                    else None
                ),
                "followup_date": r["followup_date"],
                "status": r["status"],
                "completed_at": r["completed_at"],
            }
            for r in page_qs
        ]
        serializer = FollowUpReportSerializer(rows, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 9. Overdue follow-ups
    # ------------------------------------------------------------------

    def get_overdue_followups(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Return pending follow-ups where today > followup_date."""
        from django.utils import timezone

        LeadFollowUp = _followup_model()
        today = timezone.now().date()

        qs = (
            LeadFollowUp.objects.filter(
                followup_date__lt=today,
                status__in=["pending", "scheduled"],
            )
            .select_related("lead", "assigned_to")
            .annotate(
                days_overdue=ExpressionWrapper(
                    Value(today) - F("followup_date"),
                    output_field=IntegerField(),
                )
            )
            .order_by("followup_date")
        )
        qs = FollowUpFilterEngine.apply(qs, filters)
        count = qs.count()
        page_qs = qs[params.offset : params.offset + params.limit]

        rows = []
        for r in page_qs:
            assigned = r.assigned_to
            rows.append(
                {
                    "id": r.id,
                    "lead_id": r.lead_id,
                    "lead_name": r.lead.name if r.lead else None,
                    "assigned_to": (
                        assigned.get_full_name() if assigned else None
                    ),
                    "followup_date": r.followup_date,
                    "days_overdue": r.days_overdue,
                }
            )
        serializer = OverdueFollowUpSerializer(rows, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 10. DM report
    # ------------------------------------------------------------------

    def get_dm_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Return direct-message log rows."""
        LeadDMLog = _dm_log_model()
        qs = (
            LeadDMLog.objects.select_related("lead", "handled_by")
            .order_by("-created_at")
        )
        qs = DMLogFilterEngine.apply(qs, filters)
        count = qs.count()
        page_qs = qs.values(
            "id",
            "lead_id",
            "lead__name",
            "handled_by__first_name",
            "handled_by__last_name",
            "platform",
            "direction",
            "message",
            "created_at",
        )[params.offset : params.offset + params.limit]

        rows = [
            {
                "id": r["id"],
                "lead_id": r["lead_id"],
                "lead_name": r["lead__name"],
                "handled_by": (
                    f"{r['handled_by__first_name']} {r['handled_by__last_name']}".strip()
                    if r.get("handled_by__first_name")
                    else None
                ),
                "platform": r["platform"],
                "direction": r["direction"],
                "message": r["message"],
                "created_at": r["created_at"],
            }
            for r in page_qs
        ]
        serializer = DMReportSerializer(rows, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 11. Status history report
    # ------------------------------------------------------------------

    def get_status_history_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Return lead status transition log."""
        LeadStatusHistory = _status_history_model()
        qs = (
            LeadStatusHistory.objects.select_related("lead", "changed_by")
            .order_by("-created_at")
        )
        qs = StatusHistoryFilterEngine.apply(qs, filters)
        count = qs.count()
        page_qs = qs.values(
            "id",
            "lead_id",
            "lead__name",
            "old_status",
            "new_status",
            "changed_by__first_name",
            "changed_by__last_name",
            "remarks",
            "created_at",
        )[params.offset : params.offset + params.limit]

        rows = [
            {
                "id": r["id"],
                "lead_id": r["lead_id"],
                "lead_name": r["lead__name"],
                "old_status": r["old_status"],
                "new_status": r["new_status"],
                "changed_by": (
                    f"{r['changed_by__first_name']} {r['changed_by__last_name']}".strip()
                    if r.get("changed_by__first_name")
                    else None
                ),
                "remarks": r["remarks"],
                "created_at": r["created_at"],
            }
            for r in page_qs
        ]
        serializer = StatusHistoryReportSerializer(rows, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 12. Lead creation report
    # ------------------------------------------------------------------

    def get_lead_creation_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Group leads by creation date."""
        Lead = _lead_model()
        qs = Lead.objects.all()
        qs = ReportFilterEngine.apply(qs, filters)

        aggregated = (
            qs.annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(total_created=Count("id"))
            .order_by("-date")
        )
        count = aggregated.count()
        page_data = list(aggregated[params.offset : params.offset + params.limit])
        serializer = LeadCreationReportSerializer(page_data, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 13. Conversion report
    # ------------------------------------------------------------------

    def get_conversion_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Group converted leads by joined_at date."""
        Lead = _lead_model()
        qs = Lead.objects.filter(is_converted=True, joined_at__isnull=False)
        qs = ReportFilterEngine.apply(qs, filters)

        aggregated = (
            qs.annotate(date=TruncDate("joined_at"))
            .values("date")
            .annotate(converted_count=Count("id"))
            .order_by("-date")
        )
        count = aggregated.count()
        page_data = list(aggregated[params.offset : params.offset + params.limit])
        serializer = ConversionReportSerializer(page_data, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 14. Funnel report
    # ------------------------------------------------------------------

    def get_funnel_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,  # noqa: ARG002 — funnel is always single page
    ) -> dict[str, Any]:
        """
        Return a single-page funnel aggregate; pagination not applicable.
        """
        Lead = _lead_model()
        qs = Lead.objects.all()
        qs = ReportFilterEngine.apply(qs, filters)

        agg = qs.aggregate(
            **{
                stage: Count("id", filter=Q(status=stage))
                for stage in FUNNEL_STAGES
            }
        )
        funnel = {stage: agg.get(stage, 0) for stage in FUNNEL_STAGES}
        serializer = FunnelReportSerializer(funnel)
        # Funnel is always a single object — count=1 to signal non-empty
        return {"count": 1, "results": serializer.data}

    # ------------------------------------------------------------------
    # 15. Duplicate leads
    # ------------------------------------------------------------------

    def get_duplicate_leads(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Return leads flagged as duplicates."""
        merged_filters = {**filters, "is_duplicate": True}
        return self.get_lead_export(filters=merged_filters, params=params)

    # ------------------------------------------------------------------
    # 16. Archived leads
    # ------------------------------------------------------------------

    def get_archived_leads(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Return leads flagged as archived."""
        merged_filters = {**filters, "is_archived": True}
        return self.get_lead_export(filters=merged_filters, params=params)

    # ------------------------------------------------------------------
    # 17. Course report
    # ------------------------------------------------------------------

    def get_course_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Group leads by course."""
        Lead = _lead_model()
        qs = Lead.objects.all()
        qs = ReportFilterEngine.apply(qs, filters)

        aggregated = (
            qs.values("course")
            .annotate(
                total=Count("id"),
                converted=Count("id", filter=Q(is_converted=True)),
                pending=Count("id", filter=Q(is_converted=False)),
            )
            .annotate(
                conversion_percentage=Case(
                    When(
                        total__gt=0,
                        then=ExpressionWrapper(
                            F("converted") * Value(100.0) / F("total"),
                            output_field=FloatField(),
                        ),
                    ),
                    default=Value(0.0),
                    output_field=FloatField(),
                )
            )
            .order_by("-total")
        )
        count = aggregated.count()
        page_data = list(aggregated[params.offset : params.offset + params.limit])
        serializer = CourseReportSerializer(page_data, many=True)
        return {"count": count, "results": serializer.data}

    # ------------------------------------------------------------------
    # 18. User assignment report
    # ------------------------------------------------------------------

    def get_user_assignment_report(
        self,
        filters: dict[str, Any],
        params: PaginationParams,
    ) -> dict[str, Any]:
        """Group leads by followup_by user."""
        Lead = _lead_model()
        qs = Lead.objects.select_related("followup_by")
        qs = ReportFilterEngine.apply(qs, filters)

        aggregated = (
            qs.values(
                "followup_by__id",
                "followup_by__first_name",
                "followup_by__last_name",
            )
            .annotate(
                assigned_leads=Count("id"),
                converted=Count("id", filter=Q(is_converted=True)),
                pending=Count("id", filter=Q(is_converted=False)),
            )
            .order_by("-assigned_leads")
        )
        count = aggregated.count()
        page_data = aggregated[params.offset : params.offset + params.limit]

        rows = [
            {
                "user": (
                    f"{r['followup_by__first_name']} {r['followup_by__last_name']}".strip()
                    or str(r["followup_by__id"])
                    if r["followup_by__id"]
                    else "Unassigned"
                ),
                "assigned_leads": r["assigned_leads"],
                "converted": r["converted"],
                "pending": r["pending"],
            }
            for r in page_data
        ]
        serializer = UserAssignmentReportSerializer(rows, many=True)
        return {"count": count, "results": serializer.data}
    
    def get_report_dashboard_data(self):
        total_leads = Lead.objects.filter(is_archived=False).count()

        converted = Lead.objects.filter(
            is_archived=False,
            is_converted=True,
        ).count()

        pending = Lead.objects.filter(
            is_archived=False,
            is_converted=False,
        ).count()

        followups = Lead.objects.filter(
            is_archived=False,
            next_followup_date__isnull=False,
        ).count()

        fresh = Lead.objects.filter(
            is_archived=False,
            status="Fresh",
        ).count()

        lost = Lead.objects.filter(
            is_archived=False,
            status="Lost",
        ).count()

        courses = (
            Lead.objects
            .exclude(course__isnull=True)
            .exclude(course="")
            .values_list("course", flat=True)
            .distinct()
            .order_by("course")
        )

        assigned_to = (
            User.objects
            .filter(is_active=True)
            .values("id", "full_name")
            .order_by("full_name")
        )

        status_chart = list(
            Lead.objects
            .values("status")
            .annotate(count=Count("id"))
            .order_by("status")
        )

        return {
            "summary": {
                "total_leads": total_leads,
                "converted": converted,
                "pending": pending,
                "followups": followups,
                "fresh": fresh,
                "lost": lost,
            },
            "dropdowns": {
                "courses": list(courses),
                "assigned_to": [
                    {
                        "id": user["id"],
                        "name": user['full_name'],
                    }
                    for user in assigned_to
                ],
            },
            "charts": {
                "lead_status": status_chart,
            },
        }
    

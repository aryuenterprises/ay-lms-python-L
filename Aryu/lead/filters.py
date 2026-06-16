"""
reports/filters.py

Reusable, composable filtering engine for all report queries.

Design principles
-----------------
* All filter logic lives here — never duplicated in services.
* Only Django ORM is used — no raw SQL.
* Each filter is applied only when the value is present and non-None.
* Date range, list membership, boolean, and FK filters are all handled.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from django.db.models import Q, QuerySet

from .constants import MSG_INVALID_DATE_FORMAT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_date(value):
    if value is None:
        return None

    if isinstance(value, date):
        return value

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(MSG_INVALID_DATE_FORMAT)

    raise ValueError(MSG_INVALID_DATE_FORMAT)


def _to_list(value: Any) -> list:
    """Normalise scalar / list filter values to a plain list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if v is not None]
    return [value]


# ---------------------------------------------------------------------------
# Public filter applicators
# ---------------------------------------------------------------------------


class ReportFilterEngine:
    """
    Stateless helper that applies a dictionary of filter parameters to a
    Django QuerySet.

    Usage
    -----
    ::

        qs = ReportFilterEngine.apply(Lead.objects.all(), filters)

    The ``filters`` dict mirrors the ``filters`` key in the API request body.
    """

    # Keys that contain date range boundaries
    _DATE_FROM_FIELDS: dict[str, str] = {
        "from_date": "created_at__date__gte",
    }
    _DATE_TO_FIELDS: dict[str, str] = {
        "to_date": "created_at__date__lte",
    }

    # Boolean flags that map directly to model fields
    _BOOLEAN_FIELDS: tuple[str, ...] = (
        "is_converted",
        "is_duplicate",
        "is_archived",
    )

    # Scalar FK / char fields (exact match)
    _SCALAR_FIELDS: dict[str, str] = {
        "followup_by": "followup_by_id",
        "handled_by": "handled_by_id",
        "assigned_to": "assigned_to_id",
        "course": "course",
        "priority": "priority",
    }

    # List membership fields (__in lookups)
    _LIST_FIELDS: dict[str, str] = {
        "status": "status__in",
        "source": "source__in",
    }

    @classmethod
    def apply(cls, queryset: QuerySet, filters: dict[str, Any]) -> QuerySet:
        """
        Return a filtered queryset based on the provided filter mapping.

        Parameters
        ----------
        queryset:
            The base queryset to filter.
        filters:
            Raw filter dict from the request payload.

        Returns
        -------
        QuerySet
            A (potentially) filtered queryset; the original is never mutated.
        """
        if not filters:
            return queryset

        queryset = cls._apply_date_range(queryset, filters)
        queryset = cls._apply_boolean_filters(queryset, filters)
        queryset = cls._apply_scalar_filters(queryset, filters)
        queryset = cls._apply_list_filters(queryset, filters)
        return queryset

    # ------------------------------------------------------------------
    # Date-range filtering
    # ------------------------------------------------------------------

    @classmethod
    def _apply_date_range(
        cls, queryset: QuerySet, filters: dict[str, Any]
    ) -> QuerySet:
        from_date_raw = filters.get("from_date")
        to_date_raw = filters.get("to_date")

        if from_date_raw:
            from_date = _parse_date(from_date_raw)
            queryset = queryset.filter(created_at__date__gte=from_date)

        if to_date_raw:
            to_date = _parse_date(to_date_raw)
            queryset = queryset.filter(created_at__date__lte=to_date)

        return queryset

    # ------------------------------------------------------------------
    # Boolean filtering
    # ------------------------------------------------------------------

    @classmethod
    def _apply_boolean_filters(
        cls, queryset: QuerySet, filters: dict[str, Any]
    ) -> QuerySet:
        for field in cls._BOOLEAN_FIELDS:
            value = filters.get(field)
            if value is not None:
                queryset = queryset.filter(**{field: bool(value)})
        return queryset

    # ------------------------------------------------------------------
    # Scalar (exact match) filtering
    # ------------------------------------------------------------------

    @classmethod
    def _apply_scalar_filters(
        cls, queryset: QuerySet, filters: dict[str, Any]
    ) -> QuerySet:
        for key, orm_field in cls._SCALAR_FIELDS.items():
            value = filters.get(key)
            if value is not None and value != "":
                queryset = queryset.filter(**{orm_field: value})
        return queryset

    # ------------------------------------------------------------------
    # List (__in) filtering
    # ------------------------------------------------------------------

    @classmethod
    def _apply_list_filters(
        cls, queryset: QuerySet, filters: dict[str, Any]
    ) -> QuerySet:
        for key, orm_lookup in cls._LIST_FIELDS.items():
            values = _to_list(filters.get(key))
            if values:
                queryset = queryset.filter(**{orm_lookup: values})
        return queryset


# ---------------------------------------------------------------------------
# Specialised filter applicators for related models
# ---------------------------------------------------------------------------


class CallLogFilterEngine:
    """
    Filter engine for ``LeadCallLog``-based reports.

    Supports the same date-range semantics as :class:`ReportFilterEngine`,
    but targets ``call_time`` instead of ``created_at``.
    """

    @staticmethod
    def apply(queryset: QuerySet, filters: dict[str, Any]) -> QuerySet:
        """Apply call-log-specific filters."""
        if not filters:
            return queryset

        from_date_raw = filters.get("from_date")
        to_date_raw = filters.get("to_date")
        call_status = filters.get("call_status")
        handled_by = filters.get("handled_by")
        followup_by = filters.get("followup_by")

        if from_date_raw:
            queryset = queryset.filter(
                call_time__date__gte=_parse_date(from_date_raw)
            )
        if to_date_raw:
            queryset = queryset.filter(
                call_time__date__lte=_parse_date(to_date_raw)
            )
        if call_status:
            queryset = queryset.filter(call_status=call_status)
        if handled_by is not None:
            queryset = queryset.filter(called_by_id=handled_by)
        if followup_by is not None:
            queryset = queryset.filter(lead__followup_by_id=followup_by)

        return queryset


class DMLogFilterEngine:
    """Filter engine for ``LeadDMLog``-based reports."""

    @staticmethod
    def apply(queryset: QuerySet, filters: dict[str, Any]) -> QuerySet:
        if not filters:
            return queryset

        from_date_raw = filters.get("from_date")
        to_date_raw = filters.get("to_date")
        platform = filters.get("platform")
        handled_by = filters.get("handled_by")

        if from_date_raw:
            queryset = queryset.filter(
                created_at__date__gte=_parse_date(from_date_raw)
            )
        if to_date_raw:
            queryset = queryset.filter(
                created_at__date__lte=_parse_date(to_date_raw)
            )
        if platform:
            queryset = queryset.filter(platform=platform)
        if handled_by is not None:
            queryset = queryset.filter(handled_by_id=handled_by)

        return queryset


class FollowUpFilterEngine:
    """Filter engine for ``LeadFollowUp``-based reports."""

    @staticmethod
    def apply(queryset: QuerySet, filters: dict[str, Any]) -> QuerySet:
        if not filters:
            return queryset

        from_date_raw = filters.get("from_date")
        to_date_raw = filters.get("to_date")
        assigned_to = filters.get("assigned_to")
        followup_by = filters.get("followup_by")

        if from_date_raw:
            queryset = queryset.filter(
                followup_date__gte=_parse_date(from_date_raw)
            )
        if to_date_raw:
            queryset = queryset.filter(
                followup_date__lte=_parse_date(to_date_raw)
            )
        if assigned_to is not None:
            queryset = queryset.filter(assigned_to_id=assigned_to)
        if followup_by is not None:
            queryset = queryset.filter(lead__followup_by_id=followup_by)

        return queryset


class StatusHistoryFilterEngine:
    """Filter engine for ``LeadStatusHistory``-based reports."""

    @staticmethod
    def apply(queryset: QuerySet, filters: dict[str, Any]) -> QuerySet:
        if not filters:
            return queryset

        from_date_raw = filters.get("from_date")
        to_date_raw = filters.get("to_date")

        if from_date_raw:
            queryset = queryset.filter(
                created_at__date__gte=_parse_date(from_date_raw)
            )
        if to_date_raw:
            queryset = queryset.filter(
                created_at__date__lte=_parse_date(to_date_raw)
            )

        return queryset
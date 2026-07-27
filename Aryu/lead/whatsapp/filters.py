"""
whatsapp/filters.py

django-filter FilterSet classes for the Broadcast Studio dashboard.

These filters back the query-parameter contracts of:
    GET /campaigns/                    (status, template, created_by, search, date range)
    GET /campaigns/<id>/recipients/     (status, search by lead phone/name)
    GET /messages/                      (chat_id, campaign_id, direction, status)

Kept in a dedicated module — not inlined into views.py — so filter logic is
unit-testable in isolation and reusable across any future viewset that needs
the same campaign/recipient/message filtering contract.
"""

import django_filters
from django.db.models import Q

from .models import (
    WhatsAppCampaign,
    WhatsAppCampaignRecipient,
    WhatsAppMessage,
)


class WhatsAppCampaignFilter(django_filters.FilterSet):
    """
    Filters for GET /campaigns/

    Query params:
        status        — exact match against WhatsAppCampaign.STATUS_CHOICES
        template      — filter by template id
        created_by    — filter by creator user id
        search        — icontains match on campaign name
        created_after — created_at >= value (ISO 8601)
        created_before— created_at <= value (ISO 8601)
    """

    status = django_filters.ChoiceFilter(
        field_name="status",
        choices=WhatsAppCampaign.STATUS_CHOICES,
    )
    template = django_filters.NumberFilter(field_name="template_id")
    created_by = django_filters.NumberFilter(field_name="created_by_id")
    search = django_filters.CharFilter(method="filter_search")
    created_after = django_filters.IsoDateTimeFilter(
        field_name="created_at", lookup_expr="gte"
    )
    created_before = django_filters.IsoDateTimeFilter(
        field_name="created_at", lookup_expr="lte"
    )

    class Meta:
        model = WhatsAppCampaign
        fields = ["status", "template", "created_by"]

    def filter_search(self, queryset, name, value):
        return queryset.filter(Q(name__icontains=value))


class WhatsAppCampaignRecipientFilter(django_filters.FilterSet):
    """
    Filters for GET /campaigns/<id>/recipients/

    Query params:
        status — exact match against WhatsAppCampaignRecipient.STATUS_CHOICES
        search — icontains match against the related lead's name/phone
    """

    status = django_filters.ChoiceFilter(
        field_name="status",
        choices=WhatsAppCampaignRecipient.STATUS_CHOICES,
    )
    search = django_filters.CharFilter(method="filter_search")

    class Meta:
        model = WhatsAppCampaignRecipient
        fields = ["status"]

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(lead__name__icontains=value) | Q(lead__phone__icontains=value)
        )


class WhatsAppMessageFilter(django_filters.FilterSet):
    """
    Filters for GET /messages/

    Query params:
        chat_id     — exact chat thread filter
        campaign_id — exact campaign filter (via campaign_recipient__campaign_id)
        direction   — incoming / outgoing
        status      — sent / delivered / read / failed
        sender_type — customer / agent / system
    """

    chat_id = django_filters.NumberFilter(field_name="chat_id")
    campaign_id = django_filters.NumberFilter(
        field_name="campaign_recipient__campaign_id"
    )
    direction = django_filters.ChoiceFilter(
        field_name="direction",
        choices=WhatsAppMessage.DIRECTION_CHOICES,
    )
    sender_type = django_filters.ChoiceFilter(
        field_name="sender_type",
        choices=WhatsAppMessage.SENDER_CHOICES,
    )
    status = django_filters.CharFilter(field_name="status")

    class Meta:
        model = WhatsAppMessage
        fields = ["chat_id", "campaign_id", "direction", "sender_type", "status"]
        
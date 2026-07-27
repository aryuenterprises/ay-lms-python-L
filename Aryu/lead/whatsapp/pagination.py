"""
whatsapp/pagination.py

Pagination classes for the WhatsApp Broadcast Studio dashboard endpoints.

Why cursor pagination for messages/recipients
──────────────────────────────────────────────
Message streams and recipient lists are append-heavy, high-cardinality
tables (millions of rows at scale). Offset pagination (`LIMIT x OFFSET y`)
degrades linearly with offset depth — page 5000 forces the DB to scan and
discard 500,000 rows before returning the requested 100. Cursor pagination
walks the same composite B-Tree index already defined on these models
(`chat, -created_at` / `campaign, status, id`) so every page costs the same
O(log n) regardless of depth.

Why page-number pagination for campaigns/templates
─────────────────────────────────────────────────────
Campaigns and templates are low-cardinality, dashboard-browsed collections
(tens to low-thousands of rows). Users expect "page 3 of 12" UX with total
counts — cursor pagination cannot answer "how many total campaigns exist"
without an extra query, so plain page-number pagination is the right
trade-off here.
"""

from rest_framework.pagination import CursorPagination, PageNumberPagination


class CampaignPageNumberPagination(PageNumberPagination):
    """
    Used by: CampaignListView, MessageTemplateListView

    Standard page-number pagination with a client-overridable page size,
    capped to prevent abuse (e.g. ?page_size=100000).
    """

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class MessageStreamCursorPagination(CursorPagination):
    """
    Used by: GlobalMessageStreamView

    Ordered by -created_at to match the (chat, -created_at) composite index
    on WhatsAppMessage. Cursor pagination here guarantees stable pages even
    while new messages are being inserted concurrently (no skipped/duplicated
    rows across pages, unlike offset pagination under concurrent writes).
    """

    page_size = 50
    ordering = "-created_at"
    cursor_query_param = "cursor"
    page_size_query_param = "page_size"
    max_page_size = 200


class RecipientCursorPagination(CursorPagination):
    """
    Used by: CampaignRecipientListView

    Ordered by id ascending to match the (campaign, status, id) composite
    index already defined on WhatsAppCampaignRecipient — the exact same
    index the broadcast engine's cursor walk uses, so this pagination
    shares the query plan the DB has already optimized for.
    """

    page_size = 50
    ordering = "id"
    cursor_query_param = "cursor"
    page_size_query_param = "page_size"
    max_page_size = 200
    
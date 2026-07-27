"""
whatsapp/urls.py

URL routing for the WhatsApp Broadcast Studio module.

Mount in root urls.py:
    path("api/whatsapp/", include("whatsapp.urls", namespace="whatsapp")),

Route map
─────────
POST    /campaigns/                          -> CampaignListCreateView (create)
GET     /campaigns/                          -> CampaignListCreateView (list)
GET     /campaigns/filters/                  -> CampaignFilterOptionsView
GET     /campaigns/<id>/                     -> CampaignDetailView
POST    /campaigns/<id>/trigger/             -> TriggerBroadcastView   (existing, untouched)
GET     /campaigns/<id>/status/              -> CampaignStatusView     (existing, untouched)
GET     /campaigns/<id>/analytics/           -> CampaignAnalyticsView
GET     /campaigns/<id>/recipients/          -> CampaignRecipientListView
GET     /campaigns/<id>/activity/            -> CampaignActivityTimelineView
GET     /campaigns/<id>/preview/             -> CampaignPreviewView
POST    /campaigns/<id>/duplicate/           -> CampaignDuplicateView
POST    /campaigns/<id>/cancel/              -> CampaignCancelView
DELETE  /campaigns/<id>/delete/              -> CampaignDeleteView

GET     /templates/                          -> MessageTemplateListCreateView (list)
POST    /templates/                          -> MessageTemplateListCreateView (create)
GET     /templates/<id>/                     -> MessageTemplateDetailView

GET     /messages/                           -> GlobalMessageStreamView

Note on ordering: the literal path "campaigns/filters/" is registered
*before* "campaigns/<int:campaign_id>/" so Django's URL resolver matches
it as a literal segment rather than attempting to cast "filters" to int
and falling through. Django evaluates urlpatterns top-to-bottom, so this
ordering is required, not stylistic. 
"""

from django.urls import path

from .views import (
    CampaignStatusView, 
    TriggerBroadcastView,
    CampaignActivityTimelineView,
    CampaignAnalyticsView,
    CampaignCancelView,
    CampaignDeleteView,
    CampaignDetailView,
    CampaignDuplicateView,
    CampaignFilterOptionsView,
    CampaignListCreateView,
    CampaignPreviewView,
    CampaignRecipientListView,
    GlobalMessageStreamView,
    MessageTemplateDetailView,
    MessageTemplateListCreateView,
    SyncTemplateAPIView,
    CampaignExcelBroadcastView,
    WhatsAppWebhookView,
    WhatsAppChatHistoryAPIView,
    WhatsAppChatListView,
)


urlpatterns = [
    # -- Campaign collection -----------------------------------------
    path("campaigns/",CampaignListCreateView.as_view(),name="campaign-list-create",),
    path("campaigns/filters/",CampaignFilterOptionsView.as_view(),name="campaign-filter-options",),

    # -- Campaign detail & actions -------------------------------------
    path("campaigns/<int:campaign_id>/",CampaignDetailView.as_view(),name="campaign-detail",),
    path("campaigns/<int:campaign_id>/trigger/",TriggerBroadcastView.as_view(),name="campaign-trigger",),
    path("campaigns/<int:campaign_id>/status/",CampaignStatusView.as_view(),name="campaign-status",),
    path("campaigns/<int:campaign_id>/analytics/",CampaignAnalyticsView.as_view(),name="campaign-analytics",),
    path("campaigns/<int:campaign_id>/recipients/",CampaignRecipientListView.as_view(),name="campaign-recipients",),
    path("campaigns/<int:campaign_id>/activity/",CampaignActivityTimelineView.as_view(),name="campaign-activity",),
    path("campaigns/<int:campaign_id>/preview/",CampaignPreviewView.as_view(),name="campaign-preview",),
    path("campaigns/<int:campaign_id>/duplicate/",CampaignDuplicateView.as_view(),name="campaign-duplicate",),
    path("campaigns/<int:campaign_id>/cancel/",CampaignCancelView.as_view(),name="campaign-cancel",),
    path("campaigns/<int:campaign_id>/delete/",CampaignDeleteView.as_view(),name="campaign-delete",),
    path("campaigns/excel-broadcast/",CampaignExcelBroadcastView.as_view(),name="campaign-excel-upload",),

    # -- Templates ------------------------------------------------------
    path("templates/",MessageTemplateListCreateView.as_view(),name="template-list-create",),
    path("templates/<int:template_id>/",MessageTemplateDetailView.as_view(),name="template-detail",),
    path("templates/sync/",SyncTemplateAPIView.as_view(),name="sync_templates",),

    # -- Messages ---------------------------------------------------------
    path("messages/",GlobalMessageStreamView.as_view(),name="message-stream",),
    path('whatsapp/chats/', WhatsAppChatListView.as_view(), name='whatsapp-chat-list'),
    path('whatsapp/history/<str:phone_number>/', WhatsAppChatHistoryAPIView.as_view(), name='whatsapp-chat-history'),
    
    # -- webhook --------------------
    path('whatsapp/webhook/', WhatsAppWebhookView.as_view(), name='whatsapp_webhook'),
]
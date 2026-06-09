from django.urls import path
from .views import *
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [

   # LIST + CREATE
   path("lead-engine/leads/",LeadViewSet.as_view({"get": "list","post": "create",}),name="lead-list-create"),
   path("lead-dashboard",LeadDashboard.as_view({"get": "dashboard",}),name="lead-dashboard"),

   path("lead/bulk-upload/",LeadViewSet.as_view({"post": "bulk_upload",}),name="lead-bulk-create"),
   path("lead/<int:pk>/add_call_log/",LeadViewSet.as_view({"post": "add_call_log",}),name="add-call-log"),

   # DETAIL + UPDATE + DELETE
   path("lead-engine/leads/<int:pk>/",LeadViewSet.as_view({"get": "retrieve","patch": "partial_update","delete": "destroy",}),name="lead-detail"),

   # FULL UPDATE
   path("lead-engine/leads/<int:pk>/update/",LeadViewSet.as_view({"put": "update",}),name="lead-update"),

   # PUBLIC WEBSITE / WEBHOOK / META ADS
   path("lead/submit/",PublicLeadViewSet.as_view({"post": "create",}),name="public-lead-submit"),

   ] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
   

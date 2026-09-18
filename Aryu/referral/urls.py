from django.urls import re_path
from .views import ReferralViewSet

urlpatterns = [
    re_path(r"^referral/?$", ReferralViewSet.as_view({"get": "list", "post": "create"}), name="referral-list"),
    re_path(r"^referral/generate/?$", ReferralViewSet.as_view({"get": "generate", "post": "generate"}), name="referral-generate"),
    re_path(r"^referral/(?P<id>\d+)/?$", ReferralViewSet.as_view({
        "get": "retrieve",
        "put": "update",
        "patch": "partial_update",
        "delete": "destroy",
    }), name="referral-detail"),
]

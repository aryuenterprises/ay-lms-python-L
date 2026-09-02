import os
from django.conf import settings
from rest_framework import serializers
from reports.models import GoogleReview
from reports.views import clean_and_extract_url


class GoogleReviewSerializer(serializers.ModelSerializer):
    screenshot_url = serializers.SerializerMethodField()

    class Meta:
        model = GoogleReview
        fields = [
            "id",
            "student",
            "course",
            "batch",
            "is_google_review",
            "review_date",
            "screenshot",
            "screenshot_url",
            "created_at",
            "updated_at",
        ]

    def get_screenshot_url(self, obj):
        screenshot = getattr(obj, "screenshot", None) or getattr(obj, "screenshot_url", None)
        if not screenshot:
            return None

        # Extract clean file name (e.g., "AYA0826066_review.png")
        if hasattr(screenshot, "name") and screenshot.name:
            filename = os.path.basename(screenshot.name)
        elif isinstance(screenshot, str) and screenshot.strip():
            clean_url = clean_and_extract_url(screenshot)
            filename = clean_url.rstrip("/").split("/")[-1] if clean_url else None
        else:
            return None

        if not filename:
            return None

        # Base URL without trailing slash
        base_url = getattr(settings, "MEDIA_BASE_URL", "").rstrip("/")

        # Ensure /media/ segment is present
        if not base_url.endswith("/media"):
            base_url = f"{base_url}/media"

        return f"{base_url}/{filename}"

import os
from django.conf import settings
from rest_framework import serializers
from reports.models import GoogleReview


class GoogleReviewSerializer(serializers.ModelSerializer):
    review_id = serializers.SerializerMethodField()
    student_id = serializers.SerializerMethodField()
    raw_student_id = serializers.SerializerMethodField()
    student_name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    course_id = serializers.SerializerMethodField()
    course_name = serializers.SerializerMethodField()
    batch_id = serializers.SerializerMethodField()
    batch_name = serializers.SerializerMethodField()

    screenshot_url = serializers.SerializerMethodField()
    linkedin_screenshot_url = serializers.SerializerMethodField()
    facebook_screenshot_url = serializers.SerializerMethodField()
    trustpilot_screenshot_url = serializers.SerializerMethodField()

    class Meta:
        model = GoogleReview
        fields = [
            "id",
            "review_id",
            "student",
            "student_id",
            "raw_student_id",
            "student_name",
            "email",
            "course",
            "course_id",
            "course_name",
            "batch",
            "batch_id",
            "batch_name",
            "is_google_review",
            "review_date",
            "screenshot_url",
            "linkedin_review",
            "linkedin_screenshot_url",
            "facebook_review",
            "facebook_screenshot_url",
            "trustpilot_review",
            "trustpilot_screenshot_url",
            "created_at",
            "updated_at",
        ]

    def _get_absolute_file_url(self, file_field):
        if not file_field:
            return None
        request = self.context.get("request")
        if hasattr(file_field, "url") and file_field.name:
            url = file_field.url
            if request is not None:
                url = request.build_absolute_uri(url)
            else:
                base = getattr(settings, "MEDIA_BASE_URL", "http://localhost:8000").rstrip("/")
                url = f"{base}{url}" if not url.startswith("http") else url
            if "/media/" in url and "/api/media/" not in url:
                url = url.replace("/media/", "/api/media/")
            return url
        if isinstance(file_field, str) and file_field.strip():
            url = file_field.strip()
            if not url.startswith("http"):
                base = getattr(settings, "MEDIA_BASE_URL", "http://localhost:8000").rstrip("/")
                url = f"{base}/{url.lstrip('/')}"
            if "/media/" in url and "/api/media/" not in url:
                url = url.replace("/media/", "/api/media/")
            return url
        return None

    def get_review_id(self, obj):
        return getattr(obj, "id", None)

    def get_student_id(self, obj):
        if not obj.student:
            return None
        return getattr(obj.student, "registration_id", None) or f"std_{obj.student.student_id}"

    def get_raw_student_id(self, obj):
        return getattr(obj.student, "student_id", None) if obj.student else None

    def get_student_name(self, obj):
        if not obj.student:
            return ""
        return f"{getattr(obj.student, 'first_name', '') or ''} {getattr(obj.student, 'last_name', '') or ''}".strip()

    def get_email(self, obj):
        return getattr(obj.student, "email", None) if obj.student else None

    def get_course_id(self, obj):
        return getattr(obj.course, "course_id", None) if obj.course else None

    def get_course_name(self, obj):
        return getattr(obj.course, "course_name", "-") if obj.course else "-"

    def get_batch_id(self, obj):
        return getattr(obj.batch, "batch_id", None) if obj.batch else None

    def get_batch_name(self, obj):
        if obj.batch:
            return getattr(obj.batch, "title", None) or getattr(obj.batch, "batch_name", "-")
        return "-"

    def get_screenshot_url(self, obj):
        return self._get_absolute_file_url(getattr(obj, "screenshot", None)) or getattr(obj, "screenshot_url", None)

    def get_linkedin_screenshot_url(self, obj):
        return self._get_absolute_file_url(getattr(obj, "linkedin_screenshot", None))

    def get_facebook_screenshot_url(self, obj):
        return self._get_absolute_file_url(getattr(obj, "facebook_screenshot", None))

    def get_trustpilot_screenshot_url(self, obj):
        return self._get_absolute_file_url(getattr(obj, "trustpilot_screenshot", None))

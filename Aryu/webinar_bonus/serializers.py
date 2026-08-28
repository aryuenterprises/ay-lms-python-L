from django.conf import settings
from rest_framework import serializers
from .models import Bonus, BonusFile


class BonusFileSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = BonusFile
        fields = ["id", "file", "file_url"]

    def get_file_url(self, obj):
        if obj.file and hasattr(obj.file, "url"):
            base_url = getattr(settings, "MEDIA_BASE_URL", "").rstrip("/")
            file_path = obj.file.url if obj.file.url.startswith("/") else f"/{obj.file.url}"
            return f"{base_url}{file_path}"
        return None

    def to_internal_value(self, data):
        if hasattr(data, '_mutable') and not data._mutable:
            data = data.copy()
        elif isinstance(data, dict):
            data = data.copy()

        for key in list(data.keys()):
            if data[key] in ["undefined", "null", "NaN", ""]:
                data[key] = None
        return super().to_internal_value(data)


class BonusSerializer(serializers.ModelSerializer):
    files = BonusFileSerializer(many=True, read_only=True)
    webinar_name = serializers.CharField(source="webinar.title", read_only=True)
    webinar_id = serializers.IntegerField(source="webinar.id", read_only=True)
    slug = serializers.CharField(source="webinar.slug", read_only=True)

    class Meta:
        model = Bonus  
        fields = ["id", "webinar_id", "description", "created_at", "files", "webinar_name", "slug"]

    def to_internal_value(self, data):
        if hasattr(data, '_mutable') and not data._mutable:
            data = data.copy()
        elif isinstance(data, dict):
            data = data.copy()

        for key in list(data.keys()):
            if data[key] in ["undefined", "null", "NaN", ""]:
                data[key] = None
        return super().to_internal_value(data)
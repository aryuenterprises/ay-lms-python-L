from .models import Announcement
from rest_framework import serializers
from django.conf import settings



class AnnouncementSerializer(serializers.ModelSerializer):
    content_pic_url = serializers.SerializerMethodField()
    background_pic_url = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    updated_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    class Meta:
        model = Announcement
        fields = ['id', 'title', 'content', 'audience', 'content_pic', 'content_pic_url', 'background_pic', 'background_pic_url',  'created_at', 'updated_at', 'created_by']

    def get_content_pic_url(self, obj):
        if obj.content_pic and hasattr(obj.content_pic, 'url'):
            return settings.MEDIA_BASE_URL + obj.content_pic.url
        return None
    
    def get_background_pic_url(self, obj):
        if obj.background_pic and hasattr(obj.background_pic, 'url'):
            return settings.MEDIA_BASE_URL + obj.background_pic.url
        return None
    
    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

            if role in ["trainer", "admin"]:
                validated_data["created_by"] = getattr(request.user, "trainer_id", None)
                validated_data["created_by_type"] = role

            elif role == "super_admin":
                validated_data["created_by"] = getattr(request.user, "user_id", None)
                validated_data["created_by_type"] = role

            elif role == "student":
                validated_data["created_by"] = getattr(request.user, "student_id", None)
                validated_data["created_by_type"] = role

            else:
                validated_data["created_by"] = getattr(request.user, "user_id", None)
                validated_data["created_by_type"] = role
        return super().create(validated_data)

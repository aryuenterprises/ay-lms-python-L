from asyncio.log import logger
from rest_framework import serializers
from .models import *
from rest_framework import serializers
from django.db import transaction
from aryuapp.models import Lead


class WebinarAttendanceLogSerializer(serializers.ModelSerializer):
    join_time = serializers.SerializerMethodField()
    leave_time = serializers.SerializerMethodField()
    duration_minutes = serializers.SerializerMethodField()

    class Meta:
        model = WebinarAttendanceLog
        fields = ("join_time", "leave_time", "duration_minutes")

    def get_join_time(self, obj):
        return obj.join_time.strftime("%Y-%m-%d %H:%M:%S")

    def get_leave_time(self, obj):
        return obj.leave_time.strftime("%Y-%m-%d %H:%M:%S")

    def get_duration_minutes(self, obj):
        return obj.duration_seconds // 60


class WebinarRegistrationSerializer(serializers.ModelSerializer):
    logs = serializers.SerializerMethodField()
    total_duration_minutes = serializers.SerializerMethodField()
    total_hours_participated = serializers.SerializerMethodField()
    join_count = serializers.SerializerMethodField()
    eligible_for_certificate = serializers.SerializerMethodField()
    feedback = serializers.SerializerMethodField()

    class Meta:
        model = WebinarRegistration
        fields = (
            "uuid",
            "email",
            "name",
            "phone",
            "course",
            "profession",
            "state",
            "city",
            "feedback",
            "total_hours_participated",
            "wants_reminder",
            "attended",
            "total_duration_minutes",
            "join_count",
            "eligible_for_certificate",
            "logs",
            "registered_at",
            "certificate_sent",
        )

    def get_logs(self, obj):
        logs = obj.attendance_logs.all().order_by("join_time")
        return WebinarAttendanceLogSerializer(logs, many=True).data
    
    def get_feedback(self, obj):
        if hasattr(obj, "feedback"):
            return WebinarFeedbackSerializer(obj.feedback).data
        return None


    def get_total_duration_minutes(self, obj):
        summary = getattr(obj, "attendance_summary", None)
        return summary.total_duration_seconds // 60 if summary else 0

    def get_total_hours_participated(self, obj):
        summary = getattr(obj, "attendance_summary", None)
        if not summary or not summary.total_duration_seconds:
            return 0

        hours = summary.total_duration_seconds / 3600
        return round(hours, 2)   # e.g., 1.25 hours

    def get_join_count(self, obj):
        summary = getattr(obj, "attendance_summary", None)
        return summary.join_count if summary else 0

    def get_eligible_for_certificate(self, obj):
        summary = getattr(obj, "attendance_summary", None)
        return summary.eligible_for_certificate if summary else False

    def validate(self, data):
        webinar = data['webinar']

        if not webinar.can_register():
            raise serializers.ValidationError(
                "Registration is closed for this webinar."
            )
        return data

    @transaction.atomic
    def create(self, validated_data):
        phone = validated_data.get('phone')
        email = validated_data.get('email')

        # 🔹 Step 1: Create or fetch Lead
        lead, created = Lead.objects.get_or_create(
            phone=phone,
            defaults={
                'name': validated_data.get('name'),
                'email': email,
                'course': validated_data.get('course'),
                'source': 'webinar',
            }
        )

        # Step 2: Create Webinar Registration (snapshot stored)
        registration = WebinarRegistration.objects.create(
            **validated_data,
            lead=lead
        )

        return registration


class WebinarFeedbackSerializer(serializers.ModelSerializer):
    webinar = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Webinar.objects.all()
    )

    class Meta:
        model = WebinarFeedback
        exclude = ("registration",)

    def validate(self, attrs):
        webinar = attrs.get("webinar")
        phone = attrs.get("phone")

        registration = WebinarRegistration.objects.get(
            webinar=webinar,
            phone=phone
        )

        attrs["registration"] = registration
        return attrs

class WebinarToolSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = WebinarTool
        fields = ["id", "tools_title", "tools_image", "image_url"]

    def get_image_url(self, obj):
        if obj.tools_image:
            return f"{settings.MEDIA_BASE_URL}{obj.tools_image.url}"
        return None
    
class WebinarMetadataSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = webinar_metadata
        fields = ["id", "meta_title", "meta_description", "meta_image", "image_url"]

    def get_image_url(self, obj):
        if obj.meta_image:
            return f"{settings.MEDIA_BASE_URL}{obj.meta_image.url}"
        return None

class WebinarSerializer(serializers.ModelSerializer):
    scheduled_start = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    updated_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    webinar_image_url = serializers.SerializerMethodField()
    participants = WebinarRegistrationSerializer(
        many=True,
        read_only=True,
        source="registrations"
    )
    participants_count = serializers.SerializerMethodField()
    tools = WebinarToolSerializer(many=True, read_only=True)
    metadata = WebinarMetadataSerializer(many=True, read_only=True)

    class Meta:
        model = Webinar
        fields = "__all__"
        read_only_fields = ("created_by", "created_by_type")

    def get_webinar_image_url(self, obj):
        if obj.webinar_image and hasattr(obj.webinar_image, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.webinar_image.url
        return None

    def get_participants_count(self, obj):
        return obj.registrations.count()

    import logging
    logger = logging.getLogger(__name__)

    def create(self, validated_data):
        request = self.context.get("request")
        user = request.user

        role = getattr(user, "user_type", None)

        if role in ("tutor", "admin"):
            creator_id = getattr(user, "trainer_id", None)
        elif role == "super_admin":
            creator_id = getattr(user, "user_id", None)
        elif role == "student":
            creator_id = getattr(user, "student_id", None)
        else:
            creator_id = getattr(user, "id", None)

        if not creator_id or not role:
            raise serializers.ValidationError("Invalid authenticated user")

        validated_data["created_by"] = str(creator_id)
        validated_data["created_by_type"] = role

        # 1) Create webinar in DB
        webinar = super().create(validated_data)
        from .services.zoom_service import create_zoom_meeting
        # 2) Create Zoom meeting
        try:
            zoom_data = create_zoom_meeting(
                topic=webinar.title,
                start_time=webinar.scheduled_start,
                duration_minutes=60
            )
        except Exception as e:
            webinar.delete()

            # LOG full error for server logs
            logger.exception("Zoom meeting creation failed")

            # RETURN real error to API caller
            raise serializers.ValidationError(
                {"zoom": str(e)}
            )

        webinar.zoom_meeting_id = zoom_data["meeting_id"]
        webinar.zoom_join_url = zoom_data["join_url"]
        webinar.zoom_link = zoom_data["join_url"]
        webinar.status = "SCHEDULED"

        webinar.save(update_fields=[
            "zoom_meeting_id",
            "zoom_join_url",
            "zoom_link",
            "status"
        ])

        return webinar

class PublicWebinarListSerializer(serializers.ModelSerializer):
    
    webinar_image = serializers.SerializerMethodField()
    class Meta:
        model = Webinar
        fields = "__all__"
    tools = WebinarToolSerializer(many=True, read_only=True)
    metadata = WebinarMetadataSerializer(many=True, read_only=True)
    

    def get_webinar_image(self, obj):
        if obj.webinar_image and hasattr(obj.webinar_image, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.webinar_image.url
        return None

class WebinarSessionSerializer(serializers.ModelSerializer):

    is_live = serializers.SerializerMethodField()

    class Meta:
        model = WebinarSession
        fields = [
            'id',
            'webinar',
            'started_at',
            'ended_at',
            'is_cancelled',
            'is_live',
        ]
        read_only_fields = [
            'started_at',
            'ended_at',
            'is_live',
        ]

    def get_is_live(self, obj):
        return obj.is_live()



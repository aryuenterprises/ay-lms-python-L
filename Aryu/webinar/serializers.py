from asyncio.log import logger
from decimal import ROUND_HALF_UP, Decimal
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
    payment_status = serializers.SerializerMethodField()
    webinar_title = serializers.CharField(
        source="webinar.title",
        read_only=True
    )
    waba_link = serializers.URLField(
        source="webinar.waba_link",
        read_only=True
    )

    class Meta:
        model = WebinarRegistration
        fields = (
            "id",
            "uuid",
            "email",
            "name",
            "phone",
            "waba_link",
            "webinar_title",
            "course",
            "profession",
            "payment_status",
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

    def get_payment_status(self, obj):
        txn = getattr(obj, "payment_transaction", None)
        if not txn:
            return "free"
        return txn.payment_status

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

    @transaction.atomic
    def create(self, validated_data):
        webinar = self.context.get("webinar")

        if not webinar:
            raise serializers.ValidationError("Webinar is required.")

        phone = validated_data.get('phone')
        email = validated_data.get('email')

        # Create or fetch Lead
        lead, created = Lead.objects.get_or_create(
            phone=phone,
            defaults={
                'name': validated_data.get('name'),
                'email': email,
                'course': validated_data.get('course'),
                'source': 'webinar',
            }
        )

        registration = WebinarRegistration.objects.create(
            webinar=webinar,   # explicitly assign
            lead=lead,
            is_paid=False,
            **validated_data
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

        try:
            registration = WebinarRegistration.objects.get(
                webinar=webinar,
                phone=phone
            )
        except WebinarRegistration.DoesNotExist:
            raise serializers.ValidationError({
                "phone": "This phone number is not registered for this webinar."
            })

        attrs["registration"] = registration
        return attrs

class WebinarToolSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = WebinarTool
        fields = "__all__"

    def get_image_url(self, obj):
        if obj.tools_image:
            return f"{settings.MEDIA_BASE_URL}{obj.tools_image.url}"
        return None
    
class WebinarMetadataSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = webinar_metadata
        fields = "__all__"

    def get_image_url(self, obj):
        if obj.meta_image:
            return f"{settings.MEDIA_BASE_URL}{obj.meta_image.url}"
        return None

class WebinarFAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = Webinar_FAQ
        fields = "__all__"

class WebinarSerializer(serializers.ModelSerializer):
    scheduled_start = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    updated_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    webinar_image_url = serializers.SerializerMethodField()
    participants = serializers.SerializerMethodField()
    participants_count = serializers.SerializerMethodField()
    total_amount_received = serializers.SerializerMethodField()
    tools = WebinarToolSerializer(many=True, read_only=True)
    metadata = WebinarMetadataSerializer(many=True, read_only=True)
    faqs = WebinarFAQSerializer(many=True, read_only=True)
    pending_seats = serializers.SerializerMethodField()
    is_full = serializers.SerializerMethodField() 

    class Meta:
        model = Webinar
        fields = "__all__"
        read_only_fields = ("created_by", "created_by_type")

    def get_webinar_image_url(self, obj):
        if obj.webinar_image and hasattr(obj.webinar_image, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.webinar_image.url
        return None
    
    def get_total_amount_received(self, obj):
        from aryuapp.models import PaymentTransaction
        from django.db.models import Sum

        total = PaymentTransaction.objects.filter(
            metadata__webinar_id=str(obj.uuid),
            payment_status="done"
        ).aggregate(total=Sum("amount"))["total"]

        return float(total or 0)
    
    def get_participants(self, obj):
        registrations = obj.registrations.order_by("-registered_at")  # or "-id"
        return WebinarRegistrationSerializer(
            registrations,
            many=True,
            context=self.context
        ).data

    def get_participants_count(self, obj):
        return obj.registrations.count()

    def get_pending_seats(self, obj):
        registered = obj.registrations.count()
        return max(obj.seats_available - registered, 0)

    def get_is_full(self, obj):
        return obj.registrations.count() >= obj.seats_available
    
    import logging
    logger = logging.getLogger(__name__)

    def create(self, validated_data):
        price = validated_data.get("price")
        regular_price = validated_data.get("regular_price")
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
        if price is not None:
            validated_data["price"] = Decimal(str(price)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        if regular_price is not None:
            validated_data["regular_price"] = Decimal(str(regular_price)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

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
    
    def update(self, instance, validated_data):

        if "price" in validated_data and validated_data["price"] is not None:
            validated_data["price"] = Decimal(str(validated_data["price"])).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        if "regular_price" in validated_data and validated_data["regular_price"] is not None:
            validated_data["regular_price"] = Decimal(str(validated_data["regular_price"])).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        return super().update(instance, validated_data)

class PublicWebinarListSerializer(serializers.ModelSerializer):
    registered_count = serializers.SerializerMethodField()
    pending_seats = serializers.SerializerMethodField()
    webinar_image = serializers.SerializerMethodField()
    
    class Meta:
        model = Webinar
        fields = [
            "id",
            "uuid",
            "title",
            "description",
            "scheduled_start",
            "webinar_image",
            "slug",
            "mentor",
            "language",
            "video_url",
            "mode",
            "registration_link",
            "price",
            "regular_price",
            "status",
            "webinar_status",
            "seats_available",
            "registered_count",
            "pending_seats",
            "is_paid",
            "is_registration_open",
            "is_completed",
            "tools",
            "metadata",
            "faqs",
        ]
    tools = WebinarToolSerializer(many=True, read_only=True)
    metadata = WebinarMetadataSerializer(many=True, read_only=True)
    faqs = WebinarFAQSerializer(many=True, read_only=True)

    def get_webinar_image(self, obj):
        if obj.webinar_image and hasattr(obj.webinar_image, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.webinar_image.url
        return None
    
    def get_registered_count(self, obj):
        # change "registrations" if your related_name differs
        return obj.registrations.count()

    def get_pending_seats(self, obj):
        registered = obj.registrations.count()
        return max(obj.seats_available - registered, 0)

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



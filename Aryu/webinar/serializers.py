from asyncio.log import logger
from decimal import ROUND_HALF_UP, Decimal
import logging
from rest_framework import serializers
from .models import *
from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
import re
import json
from aryuapp.models import StudentTicket, TicketAttachment, TicketReply, Certificate
from lead.models import Lead
from django.utils.text import slugify
import requests


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
    certificate_url = serializers.SerializerMethodField()
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
            "certificate_url",
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
            "source",
            "student_type"
        )

    def get_logs(self, obj):
        return [
            {
                "join_time": log.join_time.strftime("%Y-%m-%d %H:%M:%S"),
                "leave_time": log.leave_time.strftime("%Y-%m-%d %H:%M:%S"),
                "duration_minutes": log.duration_seconds // 60,
            }
            for log in obj.attendance_logs.all()
        ]
    
    def get_feedback(self, obj):
        if hasattr(obj, "feedback"):
            return WebinarFeedbackSerializer(obj.feedback).data
        return None

    def get_payment_status(self, obj):
        txn = getattr(obj, "payment_transaction", None)
        if not txn:
            return "free"
        return txn.payment_status
    
    def get_certificate_url(self, obj):
        certificate = getattr(obj, "certificate", None)

        if certificate and certificate.certificate_file:
            return 'https://portal.aryuacademy.com/api' + certificate.certificate_file.url

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

    @transaction.atomic
    def create(self, validated_data):
        webinar = self.context.get("webinar")

        if not webinar:
            raise serializers.ValidationError("Webinar is required.")

        phone = validated_data.get('phone')
        email = validated_data.get('email')
        name = validated_data.get('name')
        

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
        # -----------------------------
        # TELECRM LEAD CREATE
        # -----------------------------
        try:
            url = f"https://next-api.telecrm.in/enterprise/6a13da730fbcb752673e080c/autoupdatelead"

            headers = {
                "Authorization": f"Bearer 2b5fa0b5-b45c-4150-ab6f-09a001575ca01779800797507:0d16d31d-e820-45fa-aafc-869ef640917d",
                "Content-Type": "application/json"
            }

            payload = {
                "fields": {
                    "name": name,
                    "phone": phone,
                    "email": email,
                    "source":validated_data.get('source'),
                    "course":validated_data.get('course'),
                },
                "actions": [
                    {
                        "type": "ACTION_1001",
                        "fields": {
                            "note": "Webinar registration"
                        }
                    }
                ]
            }

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=10
            )

            print("TeleCRM Response:", response.json())

        except Exception as e:
            print("TeleCRM Error:", str(e))

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

class WebinarlistFeedbackSerializer(serializers.ModelSerializer):

    rating_screenshot_url = serializers.SerializerMethodField()

    class Meta:
        model = WebinarFeedback
        fields = "__all__"

    def get_rating_screenshot_url(self, obj):
        if obj.rating_screenshot:
            return f"https://portal.aryuacademy.com/api{obj.rating_screenshot.url}"
        return None

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
    feedbacks = WebinarlistFeedbackSerializer(many=True, read_only=True)
    tools = WebinarToolSerializer(many=True, read_only=True)
    metadata = WebinarMetadataSerializer(many=True, read_only=True)
    faqs = WebinarFAQSerializer(many=True, read_only=True)
    pending_seats = serializers.SerializerMethodField()
    is_full = serializers.SerializerMethodField() 

    class Meta:
        model = Webinar
        fields = "__all__"
        read_only_fields = ("created_by", "created_by_type")
        extra_kwargs = {
            "slug": {
                "validators": []
            }
        }

    # 💡 FIX 2: Custom validation that ONLY checks ACTIVE (non-deleted) webinars
    def validate_slug(self, value):
        queryset = Webinar.objects.filter(slug=value, is_deleted=False)
        
        # If updating, exclude the current instance from the check
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError("An active webinar with this slug already exists.")
            
        return value

    def get_webinar_image_url(self, obj):
        if obj.webinar_image and hasattr(obj.webinar_image, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.webinar_image.url
        return None
    
    def get_total_amount_received(self, obj):
        # reads an already-computed annotation — no extra query
        return float(getattr(obj, "_total_amount_received", None) or 0)
        
    def get_participants(self, obj):
        result = []

        for r in obj.registrations.all():
            summary = getattr(r, "attendance_summary", None)
            txn = getattr(r, "payment_transaction", None)
            certificate = getattr(r, "certificate", None)

            result.append({
                "id": r.id,
                "uuid": r.uuid,
                "email": r.email,
                "name": r.name,
                "phone": r.phone,
                "waba_link": r.webinar.waba_link if r.webinar else None,
                "webinar_title": r.webinar.title if r.webinar else None,
                "course": r.course,
                "profession": r.profession,
                "payment_status": txn.payment_status if txn else "free",
                "certificate_url": (
                    "https://portal.aryuacademy.com/api" + certificate.certificate_file.url
                    if certificate and certificate.certificate_file else None
                ),
                "feedback": WebinarFeedbackSerializer(r.feedback).data if getattr(r, "feedback", None) else None,
                "total_duration_minutes": summary.total_duration_seconds // 60 if summary else 0,
                "total_hours_participated": round(summary.total_duration_seconds / 3600, 2) if summary else 0,
                "join_count": summary.join_count if summary else 0,
                "eligible_for_certificate": summary.eligible_for_certificate if summary else False,
                "logs": [
                    {
                        "join_time": l.join_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "leave_time": l.leave_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "duration_minutes": l.duration_seconds // 60
                    }
                    for l in r.attendance_logs.all()
                ],
                "registered_at": r.registered_at,
                "certificate_sent": r.certificate_sent,
            })

        return result

    def get_participants_count(self, obj):
        return obj.registrations.filter(
            payment_transaction__payment_status="done"
        ).count()

    def get_pending_seats(self, obj):
        registered = getattr(obj, "participants_count", 0)
        return max(obj.seats_available - registered, 0)

    def get_is_full(self, obj):
        return getattr(obj, "participants_count", 0) >= obj.seats_available
    
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

class WebinarListSerializer(serializers.ModelSerializer):
    scheduled_start = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")
    webinar_image_url = serializers.SerializerMethodField()
    tools = WebinarToolSerializer(many=True, read_only=True)
    metadata = WebinarMetadataSerializer(many=True, read_only=True)
    faqs = WebinarFAQSerializer(many=True, read_only=True)
    pending_seats = serializers.SerializerMethodField()
    is_full = serializers.SerializerMethodField() 
    participants_count=serializers.SerializerMethodField()
    total_amount_received=serializers.SerializerMethodField()
    feedback = WebinarlistFeedbackSerializer(source="webinarfeedback_set", many=True, read_only=True)

    class Meta:
        model = Webinar
        fields = "__all__"
        read_only_fields = ("created_by", "created_by_type")

    def get_webinar_image_url(self, obj):
        if obj.webinar_image:
            return 'https://portal.aryuacademy.com/api' + obj.webinar_image.url
        return None

    def get_participants_count(self, obj):
            return obj.registrations.filter(
                payment_transaction__payment_status="done"
            ).count()
    
    def get_pending_seats(self, obj):
        return max(obj.seats_available - obj.participants_count, 0)

    def get_is_full(self, obj):
        return obj.participants_count >= obj.seats_available

    def get_total_amount_received(self, obj):
        return float(obj.total_amount_received or 0)

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

class TicketReplySerializer(serializers.ModelSerializer):
    sender_type = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")

    class Meta:
        model = TicketReply
        fields = ["reply_id", "sender_type", "message", "created_at"]

    def get_sender_type(self, obj):
        if obj.student:
            return "student"
        if obj.trainer:
            return "admin"
        if obj.super_admin:
            return "super_admin"
        return "webinar"
    
class TicketAttachmentSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")

    class Meta:
        model = TicketAttachment
        fields = ["attachment_id", "file", "created_at"]

    def get_file(self, obj):
        return obj.file.url if obj.file else None
    
class WebinarTicketSerializer(serializers.ModelSerializer):
    replies = TicketReplySerializer(many=True, read_only=True)
    attachments = TicketAttachmentSerializer(many=True, read_only=True)
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")
    updated_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")

    class Meta:
        model = StudentTicket
        fields = [
            "ticket_id",
            "subject",
            "message",
            "status",
            "priority",
            "created_at",
            "updated_at",
            "replies",
            "attachments",
        ]

class WebinarTicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=255)
    message = serializers.CharField()
    priority = serializers.ChoiceField(choices=["Low", "Medium", "High"], default="Low")

class WebinarReplyCreateSerializer(serializers.Serializer):
    message = serializers.CharField()


class PublicTicketCreateSerializer(serializers.ModelSerializer):

    class Meta:
        model = StudentTicket
        fields = ["name", 'phone', "message", "subject"]

    def validate_phone(self, value):
        phone = value.strip()

        if phone.startswith("+"):
            phone = phone[1:]

        if not re.match(r"^[1-9]\d{7,14}$", phone):
            raise serializers.ValidationError("Invalid phone number")

        return phone

    def validate_email(self, value):
        if value:
            return value.lower().strip()
        return value

    def create(self, validated_data):
        return StudentTicket.objects.create(
            phone=validated_data["phone"],
            name = validated_data.get("name"),
            message=validated_data["message"],
            subject=validated_data["subject"],

            # SYSTEM CONTROLLED
            ticket_type="support",
            priority="Low",
            status="New",

            student=None,
            webinar_participant=None,
            handled_by_trainer=None,
            handled_by_superadmin_id=3,

            created_at=timezone.now(),
        )

class PublicTicketDetailSerializer(serializers.ModelSerializer):

    replies = TicketReplySerializer(many=True, read_only=True)
    attachments = TicketAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = StudentTicket
        fields = [
            "ticket_id",
            "subject",
            "message",
            "status",
            "priority",
            "created_at",
            "updated_at",
            "replies",
            "attachments"
        ]

class PublicTicketReplySerializer(serializers.Serializer):
    message = serializers.CharField()

class PublicWebinarListSerializer(serializers.ModelSerializer):
    registered_count = serializers.SerializerMethodField()
    pending_seats = serializers.SerializerMethodField()
    webinar_image = serializers.SerializerMethodField()
    testimonial_url = serializers.URLField(
        required=False,
        allow_blank=True,
        allow_null=True
    )
    
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
            "testimonial_url",
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

class AnswerInputSerializer(serializers.Serializer):
    question_id = serializers.IntegerField()

    value_text = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )

    value_json = serializers.JSONField(
        required=False,
        allow_null=True
    )

    value_number = serializers.FloatField(
        required=False,
        allow_null=True
    )

    file_key = serializers.CharField(
        required=False,
        write_only=True,
        allow_null=True
    )

    def validate(self, attrs):
        question_id = attrs.get("question_id")

        try:
            question = Question.objects.get(id=question_id)
        except Question.DoesNotExist:
            raise serializers.ValidationError("Invalid question")

        value_text = attrs.get("value_text")
        value_json = attrs.get("value_json")
        value_number = attrs.get("value_number")
        file_key = attrs.get("file_key")

        # ===============================
        # TEXT + TEXTAREA
        # ===============================
        if question.type in ["TEXT", "TEXTAREA"]:
            if question.is_required and not value_text:
                raise serializers.ValidationError("This field is required.")

            # optional length validation
            rules = question.validation_rules or {}
            min_len = rules.get("min_length")
            max_len = rules.get("max_length")

            if value_text:
                if min_len and len(value_text) < min_len:
                    raise serializers.ValidationError(
                        f"Minimum {min_len} characters required."
                    )
                if max_len and len(value_text) > max_len:
                    raise serializers.ValidationError(
                        f"Maximum {max_len} characters allowed."
                    )

        # ===============================
        # CHECKBOX
        # ===============================
        elif question.type == "CHECKBOX":
            if question.is_required and not value_json:
                raise serializers.ValidationError("At least one option required.")

        # ===============================
        # RATING
        # ===============================
        elif question.type == "RATING":
            if question.is_required and value_number is None:
                raise serializers.ValidationError("Rating is required.")

        # ===============================
        # FILE
        # ===============================
        elif question.type == "FILE":
            if question.is_required and not file_key:
                raise serializers.ValidationError("File is required.")

        return attrs
    
class SubmissionCreateSerializer(serializers.Serializer):
    form_slug = serializers.SlugField()
    answers = AnswerInputSerializer(many=True)

    def validate(self, attrs):
        try:
            form = Form.objects.get(
                slug=attrs["form_slug"],
                is_active=True
            )
        except Form.DoesNotExist:
            raise serializers.ValidationError("Invalid form")

        attrs["form"] = form
        return attrs

class AnswerReadSerializer(serializers.ModelSerializer):
    question_id = serializers.IntegerField(source="question.id")
    question_label = serializers.CharField(source="question.label")

    class Meta:
        model = Answer
        fields = (
            "id",
            "question_id",
            "question_label",
            "value_text",
            "value_json",
            "value_number",
            "value_file",
        )

class SubmissionReadSerializer(serializers.ModelSerializer):
    answers = AnswerReadSerializer(many=True)
    user_id = serializers.IntegerField(source="user.id", allow_null=True)

    class Meta:
        model = Submission
        fields = (
            "id",
            "form_id",
            "user_id",
            "submitted_at",
            "answers",
        )

class QuestionOptionReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionOption
        fields = ["id", "value", "order"]

class QuestionWithAnswersSerializer(serializers.ModelSerializer):
    options = QuestionOptionReadSerializer(many=True, read_only=True)
    answers = serializers.SerializerMethodField()

    class Meta:
        model = Question
        fields = [
            "id",
            "label",
            "type",
            "is_required",
            "order",
            "validation_rules",
            "options",
            "answers",
        ]

    def get_answers(self, obj):
        # answers attached via Prefetch(to_attr)
        answers = getattr(obj, "prefetched_answers", [])
        return QuestionAnswerSerializer(answers, many=True).data

class QuestionAnswerSerializer(serializers.ModelSerializer):
    submission_id = serializers.IntegerField(source="submission.id")
    submission_uuid = serializers.UUIDField(source="submission.uuid")
    submitted_at = serializers.DateTimeField(source="submission.submitted_at")

    class Meta:
        model = Answer
        fields = (
            "submission_id",
            "submission_uuid",
            "submitted_at",
            "value_text",
            "value_json",
            "value_number",
            "value_file",
        )

class SubmissionWithAnswersSerializer(serializers.ModelSerializer):
    answers = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = ["id", "uuid", "submitted_at", "answers"]

    def get_answers(self, obj):
        return [
            {
                "question": answer.question.id,
                "value_text": answer.value_text,
                "value_json": answer.value_json,
                "value_number": answer.value_number,
                "value_file": (
                    answer.value_file.url
                    if answer.value_file
                    else None
                ),
            }
            for answer in obj.answers.all()
        ]

class FormWithAnswersSerializer(serializers.ModelSerializer):
    questions = QuestionWithAnswersSerializer(many=True)
    submissions_count = serializers.SerializerMethodField()
    submissions = serializers.SerializerMethodField()
    form_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Form
        fields = [
            "id",
            "title",
            "form_image_url",
            "description",
            "slug",
            "submissions_count",
            "submissions",
            "is_active",
            "created_at",
            "questions",
        ]

    def get_form_image_url(self, obj):
        if obj.form_image:
            return f"https://portal.aryuacademy.com/api{obj.form_image.url}"
        return None

    def get_submissions_count(self, obj):
        # Count unique submissions for this form
        return Submission.objects.filter(form=obj, is_deleted=False).count()
    
    def get_submissions(self, obj):
        submissions = obj.submission_set.filter(is_deleted=False).order_by("-submitted_at")
        return SubmissionWithAnswersSerializer(submissions, many=True).data

class QuestionOptionCreateSerializer(serializers.Serializer):
    value = serializers.CharField(max_length=255)
    order = serializers.IntegerField()

class QuestionCreateSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=500)
    type = serializers.CharField(max_length=20)
    is_required = serializers.BooleanField(default=False)
    order = serializers.IntegerField()
    validation_rules = serializers.JSONField(required=False)
    options = QuestionOptionCreateSerializer(many=True, required=False)

class FormCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    slug = serializers.SlugField(required=True)
    form_image = serializers.ImageField(required=False, allow_null=True)
    form_image_url = serializers.SerializerMethodField(read_only=True)
    questions = QuestionCreateSerializer(many=True)

    def to_internal_value(self, data):

        if isinstance(data, dict):
            questions = data.get("questions")
            if isinstance(questions, str):
                try:
                    data = data.copy()
                    data["questions"] = json.loads(questions)
                except json.JSONDecodeError:
                    raise serializers.ValidationError(
                        {"questions": "Must be a valid JSON array."}
                    )
        return super().to_internal_value(data)

    def get_form_image_url(self, obj):
        if obj.form_image:
            return f"https://portal.aryuacademy.com/api{obj.form_image.url}"
        return None

    def create(self, validated_data):
        request = self.context.get("request")
        user = request.user

        role = getattr(user, "user_type", None)

        if role == "admin":
            creator_id = getattr(user, "trainer_id", None)
        elif role == "tutor":
            raise serializers.ValidationError("Tutors cannot create forms.")
        elif role == "super_admin":
            creator_id = getattr(user, "user_id", None)
        elif role == "student":
            raise serializers.ValidationError("Students cannot create forms.")
        else:
            raise serializers.ValidationError("Invalid user role.")

        if not creator_id or not role:
            raise serializers.ValidationError("Invalid authenticated user.")

        validated_data["created_by"] = str(creator_id)
        validated_data["created_by_type"] = role

        questions_data = validated_data.pop("questions")

        with transaction.atomic():
            form = Form.objects.create(**validated_data)

            question_objs = [
                Question(
                    form=form,
                    label=q["label"],
                    type=q["type"],
                    is_required=q.get("is_required", False),
                    order=q["order"],
                    validation_rules=q.get("validation_rules", {}),
                )
                for q in questions_data
            ]
            created_questions = Question.objects.bulk_create(question_objs)

            option_objs = [
                QuestionOption(
                    question=question,
                    value=opt["value"],
                    order=opt["order"],
                )
                for question, q_data in zip(created_questions, questions_data)
                for opt in q_data.get("options", [])
            ]

            if option_objs:
                QuestionOption.objects.bulk_create(option_objs)

        return form

class QuestionReadSerializer(serializers.ModelSerializer):
    options = QuestionOptionReadSerializer(many=True, read_only=True)

    class Meta:
        model = Question
        fields = [
            "id",
            "label",
            "type",
            "is_required",
            "order",
            "validation_rules",
            "options",
        ]

class FormReadSerializer(serializers.ModelSerializer):
    questions = QuestionReadSerializer(many=True, read_only=True)
    submissions_count = serializers.IntegerField(read_only=True)
    form_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Form
        fields = [
            "id",
            "title",
            "uuid",
            "slug",
            "form_image",
            "form_image_url",
            "description",
            "submissions_count",
            "questions",
            "is_active",
            "created_at",

        ]

    def get_form_image_url(self, obj):
        if obj.form_image:
            return f"https://portal.aryuacademy.com/api{obj.form_image.url}"
        return None

class FormUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    form_image = serializers.ImageField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    questions = QuestionCreateSerializer(many=True, required=False)

    @transaction.atomic
    def update(self, instance, validated_data):
        questions_data = validated_data.pop("questions", None)

        # Update basic fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # Optional: regenerate slug if title changed
        if "title" in validated_data:
            instance.slug = slugify(validated_data["title"])

        instance.save()

        # If questions provided → replace existing
        if questions_data is not None:
            # Delete old questions (cascade deletes options)
            instance.questions.all().delete()

            question_objs = []
            for q in questions_data:
                question_objs.append(
                    Question(
                        form=instance,
                        label=q["label"],
                        type=q["type"],
                        is_required=q.get("is_required", False),
                        order=q["order"],
                        validation_rules=q.get("validation_rules", {}),
                    )
                )

            created_questions = Question.objects.bulk_create(question_objs)

            option_objs = []
            for question, q_data in zip(created_questions, questions_data):
                for opt in q_data.get("options", []):
                    option_objs.append(
                        QuestionOption(
                            question=question,
                            value=opt["value"],
                            order=opt["order"],
                        )
                    )

            if option_objs:
                QuestionOption.objects.bulk_create(option_objs)

        return instance

class PublicQuestionOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionOption
        fields = ("id", "value", "order")

class PublicQuestionSerializer(serializers.ModelSerializer):
    options = PublicQuestionOptionSerializer(many=True, read_only=True)

    class Meta:
        model = Question
        fields = (
            "id",
            "label",
            "type",
            "is_required",
            "order",
            "validation_rules",
            "options",
        )

class PublicFormSerializer(serializers.ModelSerializer):
    questions = PublicQuestionSerializer(many=True)
    form_image_url = serializers.SerializerMethodField()
    class Meta:
        model = Form
        fields = (
            "title",
            "slug",
            "form_image_url",
            "description",
            "questions",
        )

    def get_form_image_url(self, obj):
        if obj.form_image:
            return f"https://portal.aryuacademy.com/api{obj.form_image.url}"
        return None


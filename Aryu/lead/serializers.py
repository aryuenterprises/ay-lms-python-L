from __future__ import annotations
from .models import *
from rest_framework import serializers
import requests
from aryuapp.models import User
from django.db import transaction
from django.conf import settings
from .telecrm import sync_lead_to_telecrm


# COMMON MIXINS

class SafeUserSerializer(serializers.ModelSerializer):

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
        ]

    def get_full_name(self, obj):
        return obj.full_name


# CHILD SERIALIZERS

class LeadCallLogSerializer(serializers.ModelSerializer):

    called_by_data = SafeUserSerializer(
        source="called_by",
        read_only=True
    )

    recording = serializers.SerializerMethodField()

    class Meta:
        model = LeadCallLog
        fields = [
            "id",
            "call_type",
            "call_time",
            "duration_seconds",
            "call_status",
            "remarks",
            "recording_url",
            "recording",
            "next_followup_date",
            "called_by",
            "called_by_data",
        ]

        read_only_fields = [
            "id",
            "call_time",
        ]

    def get_recording(self, obj):

        if obj.recording_url and hasattr(obj.recording_url, "url"):
            return (
                settings.MEDIA_BASE_URL
                + obj.recording_url.url
            )

        return None


class LeadDMLogSerializer(serializers.ModelSerializer):

    handled_by_data = SafeUserSerializer(
        source="handled_by",
        read_only=True
    )

    class Meta:
        model = LeadDMLog
        fields = [
            "id",
            "platform",
            "message_direction",
            "message",
            "created_at",
            "handled_by",
            "handled_by_data",
        ]

        read_only_fields = [
            "id",
            "created_at",
        ]


class LeadStatusHistorySerializer(serializers.ModelSerializer):

    changed_by_data = SafeUserSerializer(
        source="changed_by",
        read_only=True
    )

    class Meta:
        model = LeadStatusHistory
        fields = [
            "id",
            "old_status",
            "new_status",
            "remarks",
            "created_at",
            "changed_by",
            "changed_by_data",
        ]

        read_only_fields = [
            "id",
            "created_at",
        ]


class LeadFollowUpSerializer(serializers.ModelSerializer):

    assigned_to_data = SafeUserSerializer(
        source="assigned_to",
        read_only=True
    )

    class Meta:
        model = LeadFollowUp
        fields = [
            "id",
            "followup_date",
            "followup_time",
            "status",
            "completed_at",
            "assigned_to",
            "assigned_to_data",
        ]

        read_only_fields = [
            "id",
            "completed_at",
            "created_at",
        ]


# MAIN LEAD SERIALIZER

class LeadSerializer(serializers.ModelSerializer):

    # USER DETAILS
    # =========================

    followup_by_data = SafeUserSerializer(
        source="followup_by",
        read_only=True
    )

    handled_by_data = SafeUserSerializer(
        source="handled_by",
        read_only=True
    )

    # COUNTS
    # =========================

    total_call_logs = serializers.SerializerMethodField()
    total_dm_logs = serializers.SerializerMethodField()
    total_followups = serializers.SerializerMethodField()

    # DISPLAY HELPERS
    # =========================

    created_by_display = serializers.SerializerMethodField()

    full_address = serializers.SerializerMethodField()

    # NESTED DATA
    # =========================

    recent_call_logs = serializers.SerializerMethodField()
    recent_dm_logs = serializers.SerializerMethodField()

    class Meta:
        model = Lead

        fields = [

            # BASIC
            "id",
            "name",
            "phone",
            "alternate_phone",
            "email",
            "gender",
            "qualification",
            "user_type",
            "message",
            "profession",
            "rating",

            # ADDRESS
            "address",
            "city",
            "state",
            "country",
            "pincode",
            "full_address",

            # COURSE
            "course",
            "course_interested_in",
            "interested",
            "reason_to_join",
            "reason_not_joining",
            "fee_discussed",
            "expected_join_month",

            # SOURCE
            "source",
            "source_campaign",
            "source_platform",
            "source_type",
            "facebook_campaign",

            # FOLLOWUP
            "followup_by",
            "followup_by_data",
            "handled_by",
            "handled_by_data",
            "followup_date",
            "next_followup_date",
            "last_contacted_at",
            "demo_scheduled_date",
            "demo_done_date",

            # TRACKING
            "no_of_dms",
            "no_of_calls",
            "no_of_followups",

            # STATUS
            "status",
            "lead_stage",
            "priority",

            # FLAGS
            "is_archived",
            "is_duplicate",
            "is_converted",

            # SYSTEM
            "joined_at",
            "created_at",
            "updated_at",

            # CREATOR
            "created_by",
            "created_by_type",
            "created_by_display",

            # OPTIMIZED COUNTS
            "total_call_logs",
            "total_dm_logs",
            "total_followups",

            # RECENT ACTIVITY
            "recent_call_logs",
            "recent_dm_logs",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "is_duplicate",
        ]

        extra_kwargs = {
            "phone": {
                "required": True,
            },
            "email": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
            },
            "name": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
            },
        }

    # VALIDATIONS
    # =====================================================

    def validate_phone(self, value):

        value = value.strip()

        cleaned = "".join(filter(str.isdigit, value))

        if len(cleaned) < 10:
            raise serializers.ValidationError(
                "Invalid phone number."
            )

        return cleaned

    def validate_email(self, value):

        if value:
            value = value.lower().strip()

        return value

    def validate(self, attrs):

        request = self.context.get("request")

        created_by = attrs.get("created_by")
        created_by_type = attrs.get("created_by_type")

        # PUBLIC API SECURITY
        # ==========================================

        if request and not request.user.is_authenticated:

            allowed_public_types = [
                "website",
                "landing_page",
                "meta_ads",
                "facebook",
                "instagram",
                "whatsapp",
                "api",
                "webhook",
            ]

            if created_by_type:
                if created_by_type.lower() not in allowed_public_types:
                    raise serializers.ValidationError({
                        "created_by_type": "Invalid public source type."
                    })

        # ADMIN CREATION
        # ==========================================

        if request and request.user.is_authenticated:

            if not created_by:
                attrs["created_by"] = str(request.user.id)

            if not created_by_type:
                if request.user.is_superuser:
                    attrs["created_by_type"] = "super_admin"
                else:
                    attrs["created_by_type"] = "admin"

        return attrs

    # CREATE
    # =====================================================

    @transaction.atomic
    def create(self, validated_data):

        phone = validated_data.get("phone")
        name = validated_data.get('name')
        email = validated_data.get('email')

        # DUPLICATE CHECK
        # ==========================================

        existing_lead = Lead.objects.filter(
            phone=phone
        ).first()

        if existing_lead:
            existing_lead.is_duplicate = True
            existing_lead.save(update_fields=["is_duplicate"])

        lead = Lead.objects.create(**validated_data)

        # INITIAL STATUS HISTORY
        # ==========================================

        LeadStatusHistory.objects.create(
            lead=lead,
            old_status=None,
            new_status=lead.status,
            remarks="Lead Created"
        )
        # ==========================================
        # TELECRM LEAD CREATE
        # ==========================================
        sync_lead_to_telecrm(lead, action_note="Lead Created")

        return lead

    # UPDATE
    # =====================================================

    @transaction.atomic
    def update(self, instance, validated_data):

        old_status = instance.status

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        # ==========================================
        # STATUS TRACKING
        # ==========================================

        if old_status != instance.status:

            request = self.context.get("request")

            changed_by_user = None

            if request and request.user.is_authenticated:

                changed_by_user = User.objects.filter(
                    id=getattr(request.user, "user_id", None) or getattr(request.user, "id", None)
                ).first()

            LeadStatusHistory.objects.create(
                lead=instance,
                old_status=old_status,
                new_status=instance.status,
                changed_by=changed_by_user,
                remarks="Status Updated"
            )

        # ==========================================
        # TELECRM LEAD UPDATE
        # ==========================================
        sync_lead_to_telecrm(
            instance,
            action_note=f"Lead Updated: Status={instance.status}"
        )

        return instance

    # =====================================================
    # HELPER METHODS
    # =====================================================

    def get_total_call_logs(self, obj):
        return getattr(
            obj,
            "call_logs_count",
            obj.call_logs.count()
        )

    def get_total_dm_logs(self, obj):
        return getattr(
            obj,
            "dm_logs_count",
            obj.dm_logs.count()
        )

    def get_total_followups(self, obj):
        return getattr(
            obj,
            "followups_count",
            obj.followups.count()
        )

    def get_created_by_display(self, obj):

        if obj.created_by_type and obj.created_by:
            return f"{obj.created_by_type} - {obj.created_by}"

        return None

    def get_full_address(self, obj):

        address_parts = [
            obj.address,
            obj.city,
            obj.state,
            obj.country,
            obj.pincode,
        ]

        return ", ".join(
            [part for part in address_parts if part]
        )

    def get_recent_call_logs(self, obj):

        queryset = obj.call_logs.all()[:5]

        return LeadCallLogSerializer(
            queryset,
            many=True
        ).data

    def get_recent_dm_logs(self, obj):

        queryset = obj.dm_logs.all()[:5]

        return LeadDMLogSerializer(
            queryset,
            many=True
        ).data


# LIGHTWEIGHT LIST SERIALIZER

class LeadListSerializer(serializers.ModelSerializer):

    followup_by_data = SafeUserSerializer(
        source="followup_by",
        read_only=True
    )

    handled_by_data = SafeUserSerializer(
        source="handled_by",
        read_only=True
    )

    call_logs = serializers.SerializerMethodField()

    class Meta:
        model = Lead

        fields = [
            "id",
            "name",
            "phone",
            "city",
            "course",
            "source",
            "status",
            "priority",
            "lead_stage",
            "call_logs",
            "followup_date",
            "next_followup_date",
            "created_at",
            "followup_by_data",
            "handled_by_data",
            "no_of_calls",
            "no_of_dms",
            "message"
        ]

    def get_call_logs(self, obj):

        queryset = obj.call_logs.all()

        return LeadCallLogSerializer(
            queryset,
            many=True
        ).data


# PUBLIC LEAD SERIALIZER

class PublicLeadCreateSerializer(serializers.ModelSerializer):

    """
    Use this serializer for:
    - Website Forms
    - Meta Ads
    - WhatsApp Webhooks
    - Landing Pages
    - Public APIs
    """

    class Meta:
        model = Lead

        fields = [
            "name",
            "phone",
            "email",
            "city",
            "course",
            "source",
            "source_campaign",
            "source_platform",
            "source_type",
            "created_by",
            "created_by_type",
           
        ]

    def validate_phone(self, value):

        cleaned = "".join(filter(str.isdigit, value))

        if len(cleaned) < 10:
            raise serializers.ValidationError(
                "Invalid phone number."
            )

        return cleaned

    def create(self, validated_data):

        validated_data.setdefault(
            "status",
            "fresh"
        )

        validated_data.setdefault(
            "created_by_type",
            "public"
        )

        lead = Lead.objects.create(**validated_data)

        # ==========================================
        # TELECRM LEAD CREATE
        # ==========================================
        sync_lead_to_telecrm(lead, action_note="Lead Created From Website")

        return lead

# ---------------------------------------------------------------------------
# Request payload serializers
# ---------------------------------------------------------------------------
 
 
class PaginationInputSerializer(serializers.Serializer):
    """Validates the ``pagination`` block in the request body."""
 
    page = serializers.IntegerField(default=1, min_value=1)
    page_size = serializers.IntegerField(default=50, min_value=1)
 
 
class FilterInputSerializer(serializers.Serializer):
    """
    Validates the ``filters`` block in the request body.
 
    All fields are optional; missing keys mean "no filter applied".
    """
 
    from_date = serializers.DateField(required=False, allow_null=True)
    to_date = serializers.DateField(required=False, allow_null=True)
 
    # List-type filters
    status = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
        allow_null=True,
    )
    source = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        allow_empty=True,
        allow_null=True,
    )
 
    # Scalar filters
    followup_by = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    handled_by = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    assigned_to = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    course = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=255
    )
    priority = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=50
    )
    call_status = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=100
    )
    platform = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=100
    )
 
    # Boolean filters
    is_converted = serializers.BooleanField(required=False, allow_null=True)
    is_archived = serializers.BooleanField(required=False, allow_null=True)
    is_duplicate = serializers.BooleanField(required=False, allow_null=True)
 
    def validate(self, attrs: dict) -> dict:
        from_date = attrs.get("from_date")
        to_date = attrs.get("to_date")
        if from_date and to_date and from_date > to_date:
            raise serializers.ValidationError(
                {"to_date": "to_date must be on or after from_date."}
            )
        return attrs
 
 
class ReportRequestSerializer(serializers.Serializer):
    """Top-level request body validator."""
 
    from .constants import VALID_REPORT_TYPES, MSG_INVALID_REPORT_TYPE
 
    report_type = serializers.CharField(max_length=100)
    filters = FilterInputSerializer(required=False, allow_null=True, default=dict)
    pagination = PaginationInputSerializer(required=False, default=dict)
 
    def validate_report_type(self, value: str) -> str:
        from .constants import VALID_REPORT_TYPES, MSG_INVALID_REPORT_TYPE
 
        if value not in VALID_REPORT_TYPES:
            raise serializers.ValidationError(MSG_INVALID_REPORT_TYPE)
        return value
 
 
# ---------------------------------------------------------------------------
# Lead export serializer  (ModelSerializer)
# ---------------------------------------------------------------------------
 
 
class LeadExportSerializer(serializers.ModelSerializer):
    """
    Full lead export serializer.
 
    Relies on ``select_related`` being applied in the service layer.
    """
 
    followup_by = serializers.SerializerMethodField()
    handled_by = serializers.SerializerMethodField()
    created_by = serializers.CharField(read_only=True)
 
    class Meta:
        # Imported inline to avoid top-level import issues in standalone files.
 
        model = Lead
        fields = [
            "id",
            "name",
            "phone",
            "alternate_phone",
            "email",
            "gender",
            "qualification",
            "course",
            "course_interested_in",
            "interested",
            "status",
            "lead_stage",
            "priority",
            "source",
            "source_campaign",
            "source_platform",
            "source_type",
            "followup_date",
            "next_followup_date",
            "fee_discussed",
            "expected_join_month",
            "no_of_calls",
            "no_of_dms",
            "no_of_followups",
            "is_converted",
            "is_duplicate",
            "is_archived",
            "joined_at",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_type",
            "followup_by",
            "handled_by",
        ]
 
    def get_followup_by(self, obj) -> dict | None:
        user = obj.followup_by
        if user is None:
            return None
        return {"id": user.id, "name": getattr(user, "get_full_name", lambda: str(user))()}
 
    def get_handled_by(self, obj) -> dict | None:
        user = obj.handled_by
        if user is None:
            return None
        return {"id": user.id, "name": getattr(user, "get_full_name", lambda: str(user))()}
 
    def get_created_by(self, obj):
        if not obj.created_by:
            return None

        return {
            "id": None,
            "name": obj.created_by,
        }
 
 
# ---------------------------------------------------------------------------
# Converted leads serializer
# ---------------------------------------------------------------------------
 
 
class ConvertedLeadSerializer(serializers.Serializer):
    """Converted leads with ``days_to_convert`` annotation."""
 
    id = serializers.IntegerField()
    name = serializers.CharField()
    phone = serializers.CharField()
    email = serializers.EmailField(allow_null=True)
    course = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    source = serializers.CharField(allow_null=True)
    joined_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    days_to_convert = serializers.IntegerField(allow_null=True)
 
 
# ---------------------------------------------------------------------------
# Call report serializer
# ---------------------------------------------------------------------------
 
 
class CallReportSerializer(serializers.Serializer):
    """Per-call-log row serializer."""
 
    id = serializers.IntegerField()
    lead_id = serializers.IntegerField(source="lead_id")
    lead_name = serializers.CharField(source="lead__name", allow_null=True)
    phone = serializers.CharField(source="lead__phone", allow_null=True)
    called_by = serializers.CharField(allow_null=True)
    call_time = serializers.DateTimeField()
    duration_seconds = serializers.IntegerField(allow_null=True)
    duration_minutes = serializers.FloatField(allow_null=True)
    call_status = serializers.CharField(allow_null=True)
    call_type = serializers.CharField(allow_null=True)
    remarks = serializers.CharField(allow_null=True)
    next_followup_date = serializers.DateField(allow_null=True)
    recording_url = serializers.URLField(allow_null=True, allow_blank=True)
 
 
# ---------------------------------------------------------------------------
# Call summary serializer
# ---------------------------------------------------------------------------
 
 
class CallSummarySerializer(serializers.Serializer):
    """Aggregated per-user call statistics."""
 
    user = serializers.CharField(allow_null=True)
    total_calls = serializers.IntegerField()
    total_duration_seconds = serializers.IntegerField(allow_null=True)
    total_duration_minutes = serializers.FloatField(allow_null=True)
    average_call_duration = serializers.FloatField(allow_null=True)
    longest_call_duration = serializers.IntegerField(allow_null=True)
 
 
# ---------------------------------------------------------------------------
# Daily call report serializer
# ---------------------------------------------------------------------------
 
 
class DailyCallReportSerializer(serializers.Serializer):
    date = serializers.DateField()
    total_calls = serializers.IntegerField()
    unique_leads = serializers.IntegerField()
    total_duration = serializers.IntegerField(allow_null=True)
 
 
# ---------------------------------------------------------------------------
# Lead source report serializer
# ---------------------------------------------------------------------------
 
 
class LeadSourceReportSerializer(serializers.Serializer):
    source = serializers.CharField(allow_null=True)
    total_leads = serializers.IntegerField()
    converted = serializers.IntegerField()
    pending = serializers.IntegerField()
    conversion_percentage = serializers.FloatField()
 
 
# ---------------------------------------------------------------------------
# Lead status report serializer
# ---------------------------------------------------------------------------
 
 
class LeadStatusReportSerializer(serializers.Serializer):
    status = serializers.CharField(allow_null=True)
    count = serializers.IntegerField()
 
 
# ---------------------------------------------------------------------------
# Follow-up report serializer
# ---------------------------------------------------------------------------
 
 
class FollowUpReportSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    lead_id = serializers.IntegerField()
    lead_name = serializers.CharField(allow_null=True)
    assigned_to = serializers.CharField(allow_null=True)
    followup_date = serializers.DateField()
    status = serializers.CharField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
 
 
# ---------------------------------------------------------------------------
# Overdue follow-up serializer
# ---------------------------------------------------------------------------
 
 
class OverdueFollowUpSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    lead_id = serializers.IntegerField()
    lead_name = serializers.CharField(allow_null=True)
    assigned_to = serializers.CharField(allow_null=True)
    followup_date = serializers.DateField()
    days_overdue = serializers.IntegerField()
 
 
# ---------------------------------------------------------------------------
# DM report serializer
# ---------------------------------------------------------------------------
 
 
class DMReportSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    lead_id = serializers.IntegerField()
    lead_name = serializers.CharField(allow_null=True)
    handled_by = serializers.CharField(allow_null=True)
    platform = serializers.CharField(allow_null=True)
    direction = serializers.CharField(allow_null=True)
    message = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
 
 
# ---------------------------------------------------------------------------
# Status history report serializer
# ---------------------------------------------------------------------------
 
 
class StatusHistoryReportSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    lead_id = serializers.IntegerField()
    lead_name = serializers.CharField(allow_null=True)
    old_status = serializers.CharField(allow_null=True)
    new_status = serializers.CharField(allow_null=True)
    changed_by = serializers.CharField(allow_null=True)
    remarks = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
 
 
# ---------------------------------------------------------------------------
# Lead creation report serializer
# ---------------------------------------------------------------------------
 
 
class LeadCreationReportSerializer(serializers.Serializer):
    date = serializers.DateField()
    total_created = serializers.IntegerField()
 
 
# ---------------------------------------------------------------------------
# Conversion report serializer
# ---------------------------------------------------------------------------
 
 
class ConversionReportSerializer(serializers.Serializer):
    date = serializers.DateField()
    converted_count = serializers.IntegerField()
 
 
# ---------------------------------------------------------------------------
# Funnel report serializer
# ---------------------------------------------------------------------------
 
 
class FunnelReportSerializer(serializers.Serializer):
    new = serializers.IntegerField()
    contacted = serializers.IntegerField()
    interested = serializers.IntegerField()
    followup = serializers.IntegerField()
    converted = serializers.IntegerField()
    lost = serializers.IntegerField()
 
 
# ---------------------------------------------------------------------------
# Course report serializer
# ---------------------------------------------------------------------------
 
 
class CourseReportSerializer(serializers.Serializer):
    course = serializers.CharField(allow_null=True)
    total = serializers.IntegerField()
    converted = serializers.IntegerField()
    pending = serializers.IntegerField()
    conversion_percentage = serializers.FloatField()
 
 
# ---------------------------------------------------------------------------
# User assignment report serializer
# ---------------------------------------------------------------------------
 
 
class UserAssignmentReportSerializer(serializers.Serializer):
    user = serializers.CharField(allow_null=True)
    assigned_leads = serializers.IntegerField()
    converted = serializers.IntegerField()
    pending = serializers.IntegerField()


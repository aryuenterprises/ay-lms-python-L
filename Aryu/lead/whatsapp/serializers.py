"""
whatsapp/serializers_extra.py

Additional read serializers required by the dashboard endpoints added in
this phase (detail, analytics, recipients, activity timeline).

Kept in a separate module from `serializers.py` (already finalized) to
avoid touching that accepted file. Imports the minimal/list serializers
from `serializers.py` for composition rather than redefining them.
"""

import re
from .models import (
    WhatsAppCampaign,
    WhatsAppCampaignRecipient,
    WhatsAppMessage,
    MessageTemplate
)
from rest_framework.exceptions import ValidationError
from aryuapp.models import User
import os
import pandas as pd
import phonenumbers
from django.db import transaction
from django.conf import settings
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
import logging
from .tasks import process_excel_broadcast_task

logger = logging.getLogger("whatsapp")


class MessageTemplateSerializer(serializers.ModelSerializer):
    body_variable_examples = serializers.ListField(
        child=serializers.CharField(max_length=100),
        default=list,
        required=False
    )

    class Meta:
        model = MessageTemplate
        fields = [
            "id", "name", "meta_template_name", "category", "language",
            "header_type", "header_text", "header_media_example_url",
            "body", "body_variable_examples", "meta_id", "status",
            "active", "created_at"
        ]
        read_only_fields = ["id", "meta_id", "status", "created_at"]

    def validate_meta_template_name(self, value: str) -> str:
        if not re.match(r'^[a-z0-9_]+$', value):
            raise serializers.ValidationError(
                "meta_template_name can only contain lowercase letters, numbers, and underscores."
            )
        qs = MessageTemplate.objects.filter(meta_template_name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f"Template '{value}' already exists.")
        return value

    def validate(self, data):
        header_type = data.get("header_type", "NONE")
        header_text = data.get("header_text", "")
        header_media_url = data.get("header_media_example_url", "")
        body = data.get("body", "")
        examples = data.get("body_variable_examples", [])

        # 1. Validate Header Types
        if header_type == "TEXT" and not header_text:
            raise serializers.ValidationError({"header_text": "Required when header type is TEXT."})
        
        if header_type in ["IMAGE", "VIDEO", "DOCUMENT"] and not header_media_url:
            raise serializers.ValidationError(
                {"header_media_example_url": f"A sample URL is required for {header_type} headers to pass Meta review."}
            )

        # 2. Validate Body Variables Match Examples
        # Find all instances of {{1}}, {{2}} etc.
        variable_markers = set(re.findall(r'\{\{\d+\}\}', body))
        if len(variable_markers) != len(examples):
            raise serializers.ValidationError({
                "body_variable_examples": f"Body contains {len(variable_markers)} variables, but {len(examples)} examples were provided."
            })

        return data
    
 
class MessageTemplateMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageTemplate
        fields = ["id", "name", "meta_template_name", "language", "active"]
        read_only_fields = ["id", "name", "meta_template_name", "language", "active"]
 
 
class WhatsAppCampaignCreateSerializer(serializers.ModelSerializer):
    template = serializers.PrimaryKeyRelatedField(
        queryset=MessageTemplate.objects.filter(active=True),
        error_messages={
            "does_not_exist": (
                "Template {pk_value} does not exist or is inactive. "
                "Activate the template before attaching it to a campaign."
            )
        },
    )
 
    class Meta:
        model = WhatsAppCampaign
        fields = ["id", "name", "template", "status", "created_at"]
        read_only_fields = ["id", "status", "created_at"]
 
    def validate_name(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Campaign name cannot be blank.")
        return value.strip()
 
    def create(self, validated_data):
        user_id = self.context["request"].user.id

        validated_data["created_by"] = User.objects.get(pk=user_id)

        return super().create(validated_data)
 
    def to_representation(self, instance: WhatsAppCampaign) -> dict:
        data = super().to_representation(instance)
        data["template"] = MessageTemplateMinimalSerializer(instance.template).data
        return data
 
 
class WhatsAppCampaignListSerializer(serializers.ModelSerializer):
    template = MessageTemplateMinimalSerializer(read_only=True)
    created_by = serializers.CharField(
        source="created_by.get_full_name",
        default="",
        read_only=True,
    )
    delivery_rate = serializers.SerializerMethodField()
    read_rate = serializers.SerializerMethodField()
    click_rate = serializers.SerializerMethodField()
    response_rate = serializers.SerializerMethodField()
 
    class Meta:
        model = WhatsAppCampaign
        fields = [
            "id",
            "name",
            "status",
            "template",
            "created_by",
            "total_recipients",
            "sent_count",
            "delivered_count",
            "read_count",
            "failed_count",
            "click_count",
            "reply_count",
            "delivery_rate",
            "read_rate",
            "click_rate",
            "response_rate",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "name", "status", "template", "created_by",
            "total_recipients", "sent_count", "delivered_count",
            "read_count", "failed_count", "click_count", "reply_count",
            "delivery_rate", "read_rate", "click_rate", "response_rate",
            "created_at", "updated_at",
        ]
 
    def _safe_rate(self, numerator: int, denominator: int) -> float:
        if not denominator:
            return 0.0
        return round(numerator / denominator * 100, 2)
 
    def get_delivery_rate(self, obj: WhatsAppCampaign) -> float:
        return self._safe_rate(obj.delivered_count, obj.total_recipients)
 
    def get_read_rate(self, obj: WhatsAppCampaign) -> float:
        return self._safe_rate(obj.read_count, obj.total_recipients)
 
    def get_click_rate(self, obj: WhatsAppCampaign) -> float:
        return self._safe_rate(obj.click_count, obj.total_recipients)
 
    def get_response_rate(self, obj: WhatsAppCampaign) -> float:
        return self._safe_rate(obj.reply_count, obj.total_recipients)
 
 
class WhatsAppMessageStreamSerializer(serializers.ModelSerializer):
    chat_id = serializers.IntegerField(source="chat_id", read_only=True)
    campaign_id = serializers.SerializerMethodField()
    recipient_status = serializers.SerializerMethodField()
 
    class Meta:
        model = WhatsAppMessage
        fields = [
            "id",
            "message_id",
            "chat_id",
            "campaign_id",
            "sender_type",
            "direction",
            "message_type",
            "body",
            "media_url",
            "template_name",
            "status",
            "recipient_status",
            "created_at",
        ]
        read_only_fields = [
            "id", "message_id", "chat_id", "campaign_id", "sender_type",
            "direction", "message_type", "body", "media_url", "template_name",
            "status", "recipient_status", "created_at",
        ]
 
    def get_campaign_id(self, obj: WhatsAppMessage):
        if obj.campaign_recipient_id is None:
            return None
        cr = obj.campaign_recipient
        if cr is None:
            return None
        return cr.campaign_id
 
    def get_recipient_status(self, obj: WhatsAppMessage):
        if obj.campaign_recipient_id is None:
            return None
        cr = obj.campaign_recipient
        if cr is None:
            return None
        return cr.status

class WhatsAppCampaignRecipientSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for GET /campaigns/<id>/recipients/

    Lead fields are flattened via source= rather than a nested serializer —
    the recipient list only ever needs name/phone for display, never the
    full Lead object graph. The view's select_related("lead") makes these
    pure attribute reads.
    """

    lead_id = serializers.IntegerField( read_only=True)
    lead_name = serializers.CharField(
        source="lead.name", default="", read_only=True
    )
    lead_phone = serializers.CharField(
        source="lead.phone", default="", read_only=True
    )

    class Meta:
        model = WhatsAppCampaignRecipient
        fields = [
            "id",
            "lead_id",
            "lead_name",
            "lead_phone",
            "status",
            "whatsapp_message_id",
            "custom_context",
            "error",
            "sent_at",
            "delivered_at",
            "read_at",
            "clicked_at",
        ]
        read_only_fields = fields


class WhatsAppCampaignExcelCreateSerializer(serializers.ModelSerializer):
    template = serializers.PrimaryKeyRelatedField(
        queryset=MessageTemplate.objects.filter(active=True),
        error_messages={
            "does_not_exist": "Template {pk_value} does not exist or is inactive."
        },
    )
    # Handle the file upload via the serializer
    file = serializers.FileField(write_only=True, required=True)

    class Meta:
        model = WhatsAppCampaign
        fields = ["id", "name", "template", "status", "file", "created_at"]
        read_only_fields = ["id", "status", "created_at"]

    def validate_file(self, value):
        # Validate file extension
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in [".xlsx", ".xls", ".csv"]:
            raise serializers.ValidationError("Unsupported file format. Please upload an Excel (.xlsx, .xls) or CSV file.")
        
        # Max file size limit (e.g., 10MB)
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("File size exceeds the 10MB limit.")
        return value

    def validate_name(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Campaign name cannot be blank.")
        return value.strip()

    def create(self, validated_data):
        # Extract the file so it doesn't get directly passed to the Model.create()
        excel_file = validated_data.pop("file")
        jwt_user = self.context["request"].user
        
        # 1. Resolve the actual database User model instance using the JWT payload data
        user_id = getattr(jwt_user, "id", getattr(jwt_user, "user_id", None))
        
        try:
            db_user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise ValidationError({"detail": "Authenticated user session could not be verified in the database."})
        
        # 2. Assign the valid database instance safely to pass ORM integrity checks
        validated_data["created_by"] = db_user
        validated_data["status"] = WhatsAppCampaign.STATUS_QUEUED  # Instantly queue the campaign

        # Save the campaign instance inside an atomic transaction
        campaign = super().create(validated_data)
        
        # Save the file temporarily to disk for Celery to pick it up safely
        temp_dir = os.path.join(settings.MEDIA_ROOT, "whatsapp_campaign_files")
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, f"campaign_{campaign.id}{os.path.splitext(excel_file.name)[1]}")
        
        with open(file_path, "wb+") as destination:
            for chunk in excel_file.chunks():
                destination.write(chunk)
                
        # Inject the file path into the campaign instance context for the view layer
        campaign._temporary_file_path = file_path
        return campaign

    def to_representation(self, instance: WhatsAppCampaign) -> dict:
        data = super().to_representation(instance)
        data["template"] = MessageTemplateMinimalSerializer(instance.template).data
        return data

class WhatsAppCampaignDetailSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for GET /campaigns/<id>/

    Superset of WhatsAppCampaignListSerializer's rate computations, plus
    the full template body (needed for a campaign detail/edit screen,
    unlike the list view which only needs the template name).
    """

    template = MessageTemplateMinimalSerializer(read_only=True)
    template_body = serializers.CharField(source="template.body", read_only=True)
    created_by = serializers.CharField(
        source="created_by.get_full_name", default="", read_only=True
    )
    created_by_id = serializers.IntegerField(
        default=None, read_only=True
    )
    delivery_rate = serializers.SerializerMethodField()
    read_rate = serializers.SerializerMethodField()
    click_rate = serializers.SerializerMethodField()
    response_rate = serializers.SerializerMethodField()
    failure_rate = serializers.SerializerMethodField()
    is_cancellable = serializers.SerializerMethodField()
    is_deletable = serializers.SerializerMethodField()

    class Meta:
        model = WhatsAppCampaign
        fields = [
            "id",
            "name",
            "status",
            "template",
            "template_body",
            "created_by",
            "created_by_id",
            "total_recipients",
            "sent_count",
            "delivered_count",
            "read_count",
            "failed_count",
            "click_count",
            "reply_count",
            "delivery_rate",
            "read_rate",
            "click_rate",
            "response_rate",
            "failure_rate",
            "is_cancellable",
            "is_deletable",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _safe_rate(self, numerator: int, denominator: int) -> float:
        if not denominator:
            return 0.0
        return round(numerator / denominator * 100, 2)

    def get_delivery_rate(self, obj: WhatsAppCampaign) -> float:
        return self._safe_rate(obj.delivered_count, obj.total_recipients)

    def get_read_rate(self, obj: WhatsAppCampaign) -> float:
        return self._safe_rate(obj.read_count, obj.total_recipients)

    def get_click_rate(self, obj: WhatsAppCampaign) -> float:
        return self._safe_rate(obj.click_count, obj.total_recipients)

    def get_response_rate(self, obj: WhatsAppCampaign) -> float:
        return self._safe_rate(obj.reply_count, obj.total_recipients)

    def get_failure_rate(self, obj: WhatsAppCampaign) -> float:
        return self._safe_rate(obj.failed_count, obj.total_recipients)

    def get_is_cancellable(self, obj: WhatsAppCampaign) -> bool:
        from .validators import CANCELLABLE_STATES

        return obj.status in CANCELLABLE_STATES

    def get_is_deletable(self, obj: WhatsAppCampaign) -> bool:
        from .validators import DELETABLE_STATES

        return obj.status in DELETABLE_STATES


class CampaignActivityEventSerializer(serializers.Serializer):
    """
    Read-only serializer for a single activity-timeline event.

    Backed by plain dicts assembled in the view (not a model) — the
    timeline merges campaign lifecycle timestamps with recipient-level
    milestone aggregates, which has no single backing table. Declared as
    a plain Serializer (not ModelSerializer) for that reason.
    """

    event_type = serializers.CharField()
    label = serializers.CharField()
    timestamp = serializers.DateTimeField(allow_null=True)
    count = serializers.IntegerField(required=False, default=None)


class CampaignDuplicateResultSerializer(serializers.ModelSerializer):
    """
    Read-only response shape for POST /campaigns/<id>/duplicate/.
    Mirrors the create-response shape from WhatsAppCampaignCreateSerializer
    so frontend handling of "new campaign created" responses is uniform.
    """

    template = MessageTemplateMinimalSerializer(read_only=True)

    class Meta:
        model = WhatsAppCampaign
        fields = ["id", "name", "template", "status", "created_at"]
        read_only_fields = fields


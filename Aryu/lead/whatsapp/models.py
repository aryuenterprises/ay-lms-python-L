from django.db import models
from django.conf import settings
import re
import pandas as pd
import phonenumbers
from django.db import transaction
from django.conf import settings
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
import logging
import os

# ──────────────────────────────────────────────
# Module 1: Inbound Smart Inbox Models
# ──────────────────────────────────────────────

class WhatsAppChat(models.Model):
    # Status paths mapping directly to Conversation Queue Layout
    STATUS_UNASSIGNED = "unassigned"
    STATUS_ACTIVE = "active"
    STATUS_RESOLVED = "resolved"

    CHAT_STATUS_CHOICES = (
        (STATUS_UNASSIGNED, "Unassigned"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_RESOLVED, "Resolved"),
    )

    lead = models.ForeignKey(
        "lead.Lead",
        on_delete=models.CASCADE,
        related_name="whatsapp_chats",
    )
    whatsapp_id = models.CharField(max_length=128, unique=True)
    phone_number = models.CharField(max_length=20, db_index=True)
    customer_name = models.CharField(max_length=255, blank=True)
    is_automated = models.BooleanField(default=True)
    
    # Maps to Conversation Queue UI filtering
    status = models.CharField(
        max_length=20, 
        choices=CHAT_STATUS_CHOICES, 
        default=STATUS_UNASSIGNED,
        db_index=True
    )
    # Added to satisfy the "Starred" queue metric requirement
    is_starred = models.BooleanField(default=False, db_index=True) 
    
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_chats"
    )
    last_message_at = models.DateTimeField(null=True, blank=True)
    unread_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["lead"]),
            models.Index(fields=["status", "-last_message_at"]), # Critical for Smart Inbox performance
            models.Index(fields=["assigned_to", "status", "-last_message_at"]), # My Leads queue
            models.Index(fields=["is_starred", "status"]),
        ]


class WhatsAppMessage(models.Model):
    SENDER_CHOICES = (
        ("customer", "Customer"),     # Layout: Lead Message
        ("agent", "Agent"),           # Layout: Agent Message
        ("system", "System"),         # Layout: Bot Message / Automation adjustments
    )
    DIRECTION_CHOICES = (
        ("incoming", "Incoming"),
        ("outgoing", "Outgoing"),
    )

    chat = models.ForeignKey(WhatsAppChat, on_delete=models.CASCADE, related_name="messages")
    message_id = models.CharField(max_length=255, unique=True)
    sender_type = models.CharField(max_length=20, choices=SENDER_CHOICES)
    direction = models.CharField(max_length=20, choices=DIRECTION_CHOICES)
    
    # Accommodates Text, Image, PDF, Video, Voice Notes, Template Messages
    message_type = models.CharField(max_length=50) 
    body = models.TextField(blank=True, null=True)
    media_url = models.TextField(blank=True, null=True)
    template_name = models.CharField(max_length=200, blank=True, null=True)
    status = models.CharField(max_length=20, default="sent") # sent, delivered, read, failed
    meta_payload = models.JSONField(default=dict, blank=True)

    campaign_recipient = models.ForeignKey(
        "WhatsAppCampaignRecipient",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="whatsapp_messages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["chat", "-created_at"]), # Renders individual historical streams instantly
            models.Index(fields=["status"]),
        ]


# ──────────────────────────────────────────────
# Modules 2 & 3: Automation Framework (Lifecycle & Drip)
# ──────────────────────────────────────────────

class AutomationFlow(models.Model):
    TYPE_LIFECYCLE = "lifecycle"
    TYPE_DRIP = "drip"
    
    FLOW_TYPE_CHOICES = (
        (TYPE_LIFECYCLE, "Lifecycle Rule (Reactive)"),
        (TYPE_DRIP, "Drip Campaign (Nurture)"),
    )

    name = models.CharField(max_length=255)
    flow_type = models.CharField(max_length=20, choices=FLOW_TYPE_CHOICES, default=TYPE_LIFECYCLE)
    
    # Examples from PRD: "Lead Created", "Tag Added", "No Reply 24 Hours"
    trigger = models.CharField(max_length=100) 
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AutomationStep(models.Model):
    flow = models.ForeignKey(AutomationFlow, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField()
    
    # Actions: Send Template, Add Tag, Assign User, Update Stage, Webhook, Wait, Condition
    action = models.CharField(max_length=100)
    
    # Highly adaptable configuration matrix storing delays, specific templates, conditional branches
    config = models.JSONField(default=dict)

    class Meta:
        ordering = ["order"]
        unique_together = [("flow", "order")]


class ChatAutomationState(models.Model):
    chat = models.OneToOneField(WhatsAppChat, on_delete=models.CASCADE)
    flow = models.ForeignKey(AutomationFlow, null=True, on_delete=models.SET_NULL)
    current_step = models.PositiveIntegerField(default=1)
    waiting_for_reply = models.BooleanField(default=False)
    
    # Crucial metadata for managing exact intervals for Module 3's Timeline View/Delays
    next_execution_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_execution = models.DateTimeField(auto_now=True)


# ──────────────────────────────────────────────
# Module 4: Broadcast Studio & Global Campaigns
# ──────────────────────────────────────────────

class MessageTemplate(models.Model):
    class Category(models.TextChoices):
        MARKETING = "MARKETING", "Marketing"
        UTILITY = "UTILITY", "Utility"
        AUTHENTICATION = "AUTHENTICATION", "Authentication"

    class HeaderType(models.TextChoices):
        NONE = "NONE", "None"
        TEXT = "TEXT", "Text"
        IMAGE = "IMAGE", "Image"
        VIDEO = "VIDEO", "Video"
        DOCUMENT = "DOCUMENT", "Document"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending Meta Approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    # Basic Info
    name = models.CharField(max_length=255, help_text="Internal display name")
    meta_template_name = models.CharField(max_length=255, unique=True, help_text="snake_case meta identifier")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.UTILITY)
    language = models.CharField(max_length=20, default="en_US")
    
    # Header Configuration
    header_type = models.CharField(max_length=15, choices=HeaderType.choices, default=HeaderType.NONE)
    header_text = models.CharField(max_length=60, blank=True, help_text="Required if header_type is TEXT. Max 60 chars.")
    header_media_example_url = models.URLField(blank=True, help_text="Public URL for Meta to review the media header.")

    # Body Configuration
    body = models.TextField(help_text="Message body. Max 1024 chars.")
    body_variable_examples = models.JSONField(
        default=list, 
        help_text="List of example strings for variables like {{1}}. E.g., ['John', 'Tuesday']"
    )

    # State
    meta_id = models.CharField(max_length=255, blank=True, help_text="Template ID returned by Meta")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "whatsapp_messagetemplate"

    @property
    def variables(self):
        """
        Returns ['1', '2'] for a template like:
        'Hi {{1}}, welcome to {{2}}'
        """
        return re.findall(r"\{\{(\d+)\}\}", self.body or "")

    def __str__(self):
        return self.name


class WhatsAppCampaign(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_PAUSED = "paused"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    name = models.CharField(max_length=255)
    template = models.ForeignKey(MessageTemplate, on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)

    # Performance Counter Fields supporting Dashboard Top Cards & Analytics
    total_recipients = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    delivered_count = models.PositiveIntegerField(default=0)
    read_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    click_count = models.PositiveIntegerField(default=0)   # Required for CTR Tracking
    reply_count = models.PositiveIntegerField(default=0)   # Required for Response / Conversion Rate tracking

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]


class WhatsAppCampaignRecipient(models.Model):
    STATUS_PENDING = "pending"
    STATUS_QUEUED = "queued"
    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_DELIVERED = "delivered"
    STATUS_READ = "read"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_SENDING, "Sending"),
        (STATUS_SENT, "Sent"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_READ, "Read"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
    )

    campaign = models.ForeignKey(WhatsAppCampaign, related_name="recipients", on_delete=models.CASCADE)
    lead = models.ForeignKey("lead.Lead", on_delete=models.CASCADE)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    whatsapp_message_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Essential for handling trackable variables or individual links per lead
    custom_context = models.JSONField(default=dict, blank=True) 
    error = models.TextField(blank=True, null=True)
    
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)  # Captured via link resolver webhook

    class Meta:
        indexes = [
            models.Index(fields=["campaign", "status", "id"]),
            models.Index(fields=["lead"]),
            models.Index(fields=["whatsapp_message_id"]),
        ]
        unique_together = [("campaign", "lead")]
        


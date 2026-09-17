from django.contrib import admin
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import timedelta
from .models import (
    ResumeRegistration,
    Contact,
    Subscription,
    UserSubscription,
    ResumeTemplate,
    UserResume,
    FeatureUsage,
    PaymentHistory,
    AIUsageLog,
)


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user_display",
        "operation",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_tokens",
        "latency_ms",
        "status",
        "created_at",
    ]
    list_filter = [
        "operation",
        "provider",
        "model",
        "status",
        "created_at",
    ]
    search_fields = [
        "user__email",
        "user__first_name",
        "user__last_name",
        "request_id",
        "operation",
        "model",
    ]
    readonly_fields = [
        "created_at",
        "request_id",
    ]
    ordering = ["-created_at"]
    list_per_page = 50

    def user_display(self, obj):
        if obj.user:
            return f"{obj.user.email} ({obj.user.first_name} {obj.user.last_name})"
        return "Anonymous"
    user_display.short_description = "User"

    def changelist_view(self, request, extra_context=None):
        now = timezone.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        overall = AIUsageLog.objects.aggregate(
            total_tokens=Sum("total_tokens"),
            total_input=Sum("input_tokens"),
            total_output=Sum("output_tokens"),
            total_cached=Sum("cached_tokens"),
            total_calls=Count("id"),
        )
        today = AIUsageLog.objects.filter(created_at__gte=start_of_day).aggregate(
            total_tokens=Sum("total_tokens"),
            total_calls=Count("id"),
        )
        this_week = AIUsageLog.objects.filter(created_at__gte=start_of_week).aggregate(
            total_tokens=Sum("total_tokens"),
            total_calls=Count("id"),
        )
        this_month = AIUsageLog.objects.filter(created_at__gte=start_of_month).aggregate(
            total_tokens=Sum("total_tokens"),
            total_calls=Count("id"),
        )

        extra_context = extra_context or {}
        extra_context["ai_stats"] = {
            "overall": overall,
            "today": today,
            "this_week": this_week,
            "this_month": this_month,
        }
        return super().changelist_view(request, extra_context=extra_context)

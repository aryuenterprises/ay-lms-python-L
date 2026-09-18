from django.contrib import admin
from .models import Referral


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "email", "coupon_code", "url", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "email", "coupon_code")
    readonly_fields = ("coupon_code", "url", "created_at", "updated_at")
    ordering = ("-created_at",)

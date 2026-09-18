from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import Referral


class ReferralSerializer(serializers.ModelSerializer):
    class Meta:
        model = Referral
        fields = [
            "id",
            "name",
            "email",
            "password",
            "coupon_code",
            "url",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "password": {"required": False, "allow_blank": False},
            "coupon_code": {"required": False, "allow_blank": True},
            "url": {"required": False, "allow_blank": True},
        }

    def validate_status(self, value):
        if value:
            val = str(value).strip().lower()
            if val in ["active", "true", "1"]:
                return "active"
            elif val in ["inactive", "false", "0"]:
                return "inactive"
            else:
                raise serializers.ValidationError("Status must be either 'active' or 'inactive'.")
        return "active"

    def create(self, validated_data):
        raw_password = validated_data.pop("password", None)
        referral = Referral(**validated_data)
        if raw_password:
            referral.set_password(raw_password)
        referral.save()
        return referral

    def update(self, instance, validated_data):
        raw_password = validated_data.pop("password", None)
        if raw_password:
            instance.set_password(raw_password)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance

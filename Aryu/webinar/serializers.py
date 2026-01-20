from rest_framework import serializers
from .models import *
from rest_framework import serializers
from django.db import transaction
from aryuapp.models import Lead



class WebinarRegistrationSerializer(serializers.ModelSerializer):

    class Meta:
        model = WebinarRegistration
        fields = [
            'id',
            'webinar',
            'name',
            'phone',
            'email',
            'course',
            'registered_at',
        ]
        read_only_fields = ['registered_at']

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

class WebinarSerializer(serializers.ModelSerializer):
    scheduled_start = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    updated_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    participants = WebinarRegistrationSerializer(
        many=True,
        read_only=True,
        source="registrations"
    )
    participants_count = serializers.SerializerMethodField()

    class Meta:
        model = Webinar
        fields = "__all__"
        read_only_fields = ("created_by", "created_by_type")

    def get_participants_count(self, obj):
        return obj.registrations.count()

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

        return super().create(validated_data)


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


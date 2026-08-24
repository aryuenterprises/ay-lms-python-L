from rest_framework import serializers
import re
from .models import *
from lead.serializers import LeadSerializer
from lead.models import Lead

class LeadCaptureSerializer(serializers.ModelSerializer):
    """
    Validates and sanitizes payload sent from frontend before resource access.
    """
    name = serializers.CharField(max_length=150, required=False, allow_null=True, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=True)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_null=True, allow_blank=True)
    qualification = serializers.CharField(max_length=150, required=False, allow_null=True, allow_blank=True)
    course_interested_in = serializers.CharField(max_length=255, required=False, allow_null=True, allow_blank=True)
    interested = serializers.BooleanField(default=True, required=False)
    source = serializers.CharField(max_length=150, default="Resource Download", required=False)

    class Meta:
        model = Lead
        fields = [
            "name",
            "phone",
            "email",
            "city",
            "qualification",
            "course_interested_in",
            "interested",
            "source",
        ]

    def validate_phone(self, value):
        """Sanitize phone number to digits and standard phone characters."""
        cleaned = re.sub(r"[^\d+]", "", value)
        if len(cleaned) < 7 or len(cleaned) > 15:
            raise serializers.ValidationError("Enter a valid phone number (7-15 digits).")
        return cleaned


class ResourcesSerializer(serializers.ModelSerializer):
    # Declare input fields as write_only so DRF processes the uploaded binary data
    image = serializers.ImageField(write_only=True, required=False)
    file = serializers.FileField(write_only=True, required=False)
    
    image_url = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Resources
        fields = [
            "id", "title", "slug", "image", "file", 
            "image_url", "file_url", "status", "form", "created_at"
        ]
        
    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and hasattr(obj.image, 'url'):
            if request is not None:
                return request.build_absolute_uri(obj.image.url)
            return 'https://aylms.aryuprojects.com/api' + obj.image.url
        return None

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and hasattr(obj.file, 'url'):
            if request is not None:
                return request.build_absolute_uri(obj.file.url)
            return 'https://aylms.aryuprojects.com/api' + obj.file.url
        return None


# =====================================================
# FORM SERIALIZER
# =====================================================

class FormSerializer(serializers.ModelSerializer):

    class Meta:

        model = Form
        fields = "__all__"

    def create(self, validated_data):

        # SAVE FORM
        form = Form.objects.create(**validated_data)

        # CREATE LEAD
        lead_payload = {

            "name":validated_data.get("name"),
            "phone":validated_data.get("phone"),
            "email":validated_data.get("email"),
            "city":validated_data.get("city"),
            "course_interested_in":validated_data.get("prefered_course"),
            "interested":validated_data.get("interesed_course",True),
            "source":"Resource Download",
            "source_platform": "Website",
            "source_type":"Resources Form",
            "created_by_type":"website",
            "status":"new"
        }

        lead_serializer = LeadSerializer(data=lead_payload)

        if lead_serializer.is_valid():

            lead_serializer.save()

        

        return form
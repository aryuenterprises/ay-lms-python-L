from rest_framework import serializers

from .models import *
from lead.serializers import LeadSerializer

# =====================================================
# RESOURCE SERIALIZER
# =====================================================

class ResourcesSerializers(serializers.ModelSerializer):

    image_url = (serializers.SerializerMethodField())
    file_url = (serializers.SerializerMethodField())
    form = serializers.BooleanField(required=False, default=False)
    class Meta:

        model = Resources
        fields = "__all__"

    def get_image_url(self, obj):
        if obj.image and hasattr(obj.image, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.image.url
        return None

    def get_file_url(self, obj):
        if obj.file and hasattr(obj.file, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.file.url
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
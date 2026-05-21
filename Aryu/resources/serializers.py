from rest_framework import serializers
from .models import *


class ResourcesSerializers(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    file_url = serializers.SerializerMethodField()
    class Meta:
        model =Resources
        fields="__all__"
    def get_image_url(self, obj):
            if obj.image and hasattr(obj.image, 'url'):
                return 'https://portal.aryuacademy.com/api' + obj.image.url
            return None
        
    def get_file_url(self, obj):
            if obj.file and hasattr(obj.file, 'url'):
                return 'https://portal.aryuacademy.com/api' + obj.file.url
            return None
        

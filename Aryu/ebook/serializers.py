from rest_framework import serializers
from .models import *
import json
import requests
from django.core.files.base import ContentFile
import re
from urllib.parse import urlparse
from rest_framework import viewsets, status, mixins
from django.utils.text import slugify
from payments.models import PaymentTransaction




# ---------------- SEO ----------------
class EbookSEOSerializer(serializers.ModelSerializer):
    seo_image_url = serializers.SerializerMethodField(read_only=True)
    class Meta:
        model = EbookSEO
        fields = ['id', 'seo_title', 'seo_description', 'seo_image', 'seo_image_url']

    def get_seo_image_url(self, obj):
        if obj.seo_image and hasattr(obj.seo_image, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.seo_image.url
        return None


# ---------------- TOOLS ----------------
class EbookToolSerializer(serializers.ModelSerializer):
    tool_image_url = serializers.SerializerMethodField(read_only = True)
    class Meta:
        model = EbookTool
        fields = ['id', 'tool_title', 'tool_image','tool_image_url']
    def get_tool_image_url(self, obj):
        if obj.tool_image and hasattr(obj.tool_image, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.tool_image.url
        return None


# ---------------- FAQ ----------------
class EbookFAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = EbookFAQ
        fields = ['id', 'faq_question', 'faq_answer']


# ---------------- MAIN EBOOK ----------------
class EbookSerializer(serializers.ModelSerializer):
    seo = EbookSEOSerializer(many=True, read_only=True)
    tools = EbookToolSerializer(many=True, read_only=True)
    faqs = EbookFAQSerializer(many=True, read_only=True)
    participants_count = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    reviews_count = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()

    ebook_image_url = serializers.SerializerMethodField(read_only = True)
    pdf_url = serializers.SerializerMethodField(read_only = True)
    
    role_id = serializers.SerializerMethodField()
    role_name = serializers.SerializerMethodField()
    user_type = serializers.SerializerMethodField()
    is_paid = serializers.BooleanField(required=False)
    tags = serializers.ListField(
    child=serializers.CharField(),
    required=False
    )
    created_by = serializers.SerializerMethodField()

    
    def get_created_by(self, obj):
        print(type(obj.created_by), obj.created_by)
        return None

    class Meta:
        model = Ebook
        # fields = [
        #     'id',
        #     'title',
        #     'slug',
        #     'sub_title',
        #     'key',
        #     'price',
        #     'regular_price',
        #     'ebook_image',
        #     'description',
        #     'pdf',
        #     'is_paid',
        #     'is_deleted',
        #     'seats_available',
        #     'seo',
        #     'tools',
        #     'faqs',
        #     'ebook_image_url',
        #     'pdf_url',
        #     'participants_count',
        #     'reviews',
        #     'reviews_count',
        #     'average_rating',
        #     "role_id",
        #     "role_name",
        #     "user_type",
        #     "language",
        #     "order",
        #     "tags",
        #     "youtube",
        #     "testimonial"
        # ]
        fields="__all__"

    def get_role_id(self, obj):
        return 50   # ✅ fixed value

    def get_role_name(self, obj):
        return "ebook user"   # ✅ fixed value

    def get_user_type(self, obj):
        return "ebookuser"

    def get_ebook_image_url(self, obj):
        if obj.ebook_image and hasattr(obj.ebook_image, 'url'):
            return 'https://aylms.aryuprojects.com/api/' + obj.ebook_image.url
        return None
    
    def get_pdf_url(self, obj):
        if obj.pdf and hasattr(obj.pdf, 'url'):
            return 'https://aylms.aryuprojects.com/api/' + obj.pdf.url
        return None
    
    def get_participants_count(self, obj):
        # Count total registrations
        return obj.registrations.count()
    
    def get_reviews(self, obj):
        reviews = Reviews.objects.filter(registration__ebook=obj).order_by('-created_at')
        return ReviewSerializer(reviews, many=True).data
    
    def get_reviews_count(self, obj):
        return Reviews.objects.filter(registration__ebook=obj).count()


    def get_average_rating(self, obj):
        reviews = Reviews.objects.filter(registration__ebook=obj)

        if not reviews.exists():
            return 0

        total = sum([r.rating for r in reviews])
        return round(total / reviews.count(), 1)
    
    def extract_nested_data(self, data, field_name):
        """
        Convert form-data like:
        seo[0][seo_title], seo[0][seo_description]
        into:
        [
            {'seo_title': '...', 'seo_description': '...'}
        ]
        """
        result = {}

        for key, value in data.items():
            if key.startswith(field_name):
                parts = key.replace(']', '').split('[')
                # ['seo', '0', 'seo_title']

                if len(parts) >= 3:
                    index = int(parts[1])
                    sub_key = parts[2]

                    if index not in result:
                        result[index] = {}

                    result[index][sub_key] = value

        return list(result.values())

    def create(self, validated_data):
        title = validated_data.get("title", "")
        input_slug = validated_data.get("slug")

        # use given slug or generate from title
        base_slug = slugify(input_slug or title)

        slug = base_slug
        counter = 1

        # 🔥 ensure unique slug
        while Ebook.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        validated_data["slug"] = slug

        return super().create(validated_data)
    # ---------------- UPDATE ----------------
    def update(self, instance, validated_data):
        input_slug = validated_data.get("slug", instance.slug)

        base_slug = slugify(input_slug)
        slug = base_slug
        counter = 1

        while Ebook.objects.filter(slug=slug).exclude(id=instance.id).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        validated_data["slug"] = slug

        return super().update(instance, validated_data)
    
class PublicEbookListSerializer(serializers.ModelSerializer):
    # registered_count = serializers.SerializerMethodField()
    # pending_seats = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    role_id = serializers.SerializerMethodField()
    role_name = serializers.SerializerMethodField()
    user_type = serializers.SerializerMethodField()
    tags = models.JSONField(default=list, blank=True)
    language = serializers.SerializerMethodField()
    popular = serializers.SerializerMethodField()

    # ✅ file fields
    youtube = models.FileField(upload_to='ebooks/youtube/', null=True, blank=True)
    testimonial = models.FileField(upload_to='ebooks/testimonials/', null=True, blank=True)
    
    class Meta:
        model = Ebook
        # fields = [
        #     "id",
        #     "title",
        #     "sub_title",
        #     "slug",
        #     "description",
        #     "price",
        #     "regular_price",
        #     "ebook_image",
        #     "image",
        #     "seo",
        #     "tools",
        #     "faqs",
        #     "role_id",
        #     "role_name",
        #     "user_type"
        # ]
        fields = "__all__"
    seo = EbookSEOSerializer(many=True, required=False)
    tools = EbookToolSerializer(many=True, required=False)
    faqs = EbookFAQSerializer(many=True, required=False)

    def get_image(self, obj):
        if obj.ebook_image and hasattr(obj.ebook_image, 'url'):
            return 'https://aylms.aryuprojects.com/api/' + obj.ebook_image.url
        return None
    def get_youtube_url(self, obj):
        if obj.youtube and hasattr(obj.youtube, 'url'):
            return 'https://aylms.aryuprojects.com/api/' + obj.youtube.url
        return None

    def get_testimonial_url(self, obj):
        if obj.testimonial and hasattr(obj.testimonial, 'url'):
            return 'https://aylms.aryuprojects.com/api/' + obj.testimonial.url
        return None
    
    def get_language(self, obj):
        return obj.language

    def get_popular(self, obj):
        return obj.popular
    # def get_registered_count(self, obj):
    #     # change "registrations" if your related_name differs
    #     return obj.registrations.count()

    # def get_pending_seats(self, obj):
    #     registered = obj.registrations.count()
    #     return max(obj.seats_available - registered, 0)

    def get_role_id(self, obj):
        return 50   # ✅ fixed value

    def get_role_name(self, obj):
        return "ebook user"   # ✅ fixed value

    def get_user_type(self, obj):
        return "ebookuser"

class ReviewSerializer(serializers.ModelSerializer):

    # ✅ Input fields
    email = serializers.EmailField(write_only=True)
    slug = serializers.CharField(write_only=True)

    # ✅ Read-only fields
    name = serializers.CharField(source="registration.name", read_only=True)
    title = serializers.CharField(source="registration.ebook.title", read_only=True)
    ebook_slug = serializers.CharField(source="registration.ebook.slug", read_only=True)
    is_approved = serializers.BooleanField(required=False)

    class Meta:
        model = Reviews
        fields = [
            'id',
            'registration',
            'rating',
            'comment',
            'email',
            'slug',
            'name',
            'title',
            'ebook_slug',
            'created_at',
            'is_approved'
        ]
        extra_kwargs = {
            "registration": {"required": False}
        }

    def create(self, validated_data):
        email = validated_data.pop("email", "").strip()
        slug = validated_data.pop("slug", "").strip()

        registration = EbookRegistration.objects.filter(
            email__iexact=email,
            ebook__slug__iexact=slug
        ).first()

        if not registration:
            raise serializers.ValidationError({
                "error": f"No registration found for email={email} and slug={slug}"
            })

        if not registration.is_paid:
            raise serializers.ValidationError({
                "error": "You must purchase this ebook to review"
            })

        if Reviews.objects.filter(registration=registration).exists():
            raise serializers.ValidationError({
                "error": "Review already submitted"
            })

        validated_data["registration"] = registration

        return super().create(validated_data)
class EbookRegistrationSerializer(serializers.ModelSerializer):

    name = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    phone = serializers.CharField(required=False, allow_null=True, allow_blank=True)
  
    role_id = serializers.SerializerMethodField()
    role_name = serializers.SerializerMethodField()
    user_type = serializers.SerializerMethodField()
    slug = serializers.CharField(source="ebook.slug", read_only=True)
    title = serializers.CharField(source="ebook.title",read_only=True)
    

    is_paid = serializers.BooleanField(required=False)

    class Meta:
        model = EbookRegistration
        # fields = "__all__"
        fields = [
            'name',
            'email',
            'phone',
            'role_id',
            'role_name',
            'user_type',
            'is_paid',
            'ebook',
            'id',
            'password',
            'slug',
            'title',
            'profile_pic',
            'created_at'
           
            
        ]
        def get_created_at(self,obj):
            return obj.created_at
        read_only_fields = ["ebook", "is_paid", "registered_at"]
        extra_kwargs = {
            "name": {"required": True},
            "email": {"required": True},
            "phone": {"required": True},
            "created_at":{"required":True}
        }

    def create(self, validated_data):
        ebook = self.context.get("ebook")
        request = self.context.get("request")

        name = validated_data.get("name") or request.data.get("name") or ""
        email = validated_data.get("email") or request.data.get("email") or ""
        phone = validated_data.get("phone") or request.data.get("phone") or ""

        return EbookRegistration.objects.create(
            ebook=ebook,
            name=name,
            email=email,
            phone=phone,
            is_paid=False
        )

    def validate(self, data):
        if not data.get("email") and not data.get("phone"):
            raise serializers.ValidationError("Email or Phone is required")
        return data

    def get_role_id(self, obj):
        return 50

    def get_role_name(self, obj):
        return "ebook user"

    def get_user_type(self, obj):
        return "ebookuser"
    def get_profile_pic(self, obj):
        if obj.profile_pic and hasattr(obj.profile_pic, 'url'):
            return 'https://aylms.aryuprojects.com/api' + obj.profile_pic.url
        return None

class PaymentTransactionListSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    slug = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)
    # registration_id = serializers.IntegerField()

    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "transaction_id",
            "order_id",
            "amount",
            "currency",
            "payment_status",
            "created_at",
            "name",
            "email",
            "phone",
            "title",
            "slug",
            "metadata"
        ]

    def _get_meta(self, obj):
        if isinstance(obj.metadata, dict):
            return obj.metadata
        if isinstance(obj.metadata, list) and obj.metadata:
            return obj.metadata[0]
        return {}

    def get_name(self, obj):
        return self._get_meta(obj).get("name")

    def get_email(self, obj):
        return self._get_meta(obj).get("email")

    def get_phone(self, obj):
        return self._get_meta(obj).get("phone")

    def get_title(self, obj):
        return self._get_meta(obj).get("ebook_title")

    def get_slug(self, obj):
        return self._get_meta(obj).get("ebook_slug")
    

    
class EbookDetailSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Ebook
        fields = "__all__"

    def get_image_url(self, obj):
        if obj.ebook_image and hasattr(obj.ebook_image, "url"):
            return self.context["request"].build_absolute_uri(obj.ebook_image.url)
        return None
import hashlib
from django.conf import settings
from django.core.cache import cache
from rest_framework import serializers
from django.utils import timezone
import re
from payments.models import PaymentTransaction
from .models import ResumeRegistration,Contact,Subscription,PaymentHistory, UserSubscription, UserResume, ResumeTemplate
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework.exceptions import AuthenticationFailed
from django.utils.timezone import now

class ResumeRegistrationSerializers(serializers.ModelSerializer):

    current_subscription = serializers.PrimaryKeyRelatedField(
        queryset=Subscription.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = ResumeRegistration
        fields = "__all__"


class SecureLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True)

class SecureSignupSerializer(serializers.Serializer):
    first_name = serializers.CharField(required=False, allow_blank=True, default="")
    last_name = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=True)
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    password = serializers.CharField(required=True)
    city = serializers.CharField(required=False, allow_blank=True, default="")
    state = serializers.CharField(required=False, allow_blank=True, default="")
    country = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError("Password must be minimum 8 characters")
        if not re.search(r"[A-Z]", value):
            raise serializers.ValidationError("Password must contain one uppercase letter")
        if not re.search(r"[a-z]", value):
            raise serializers.ValidationError("Password must contain one lowercase letter")
        if not re.search(r"[0-9]", value):
            raise serializers.ValidationError("Password must contain one number")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", value):
            raise serializers.ValidationError("Password must contain one special character")
        return value

class ContactSerializers(serializers.ModelSerializer):

    class Meta:
        model = Contact
        fields ="__all__"

class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    # Make the default input requirement optional since we read from cookies or body
    refresh = serializers.CharField(required=False, allow_null=True)
    refresh_token = serializers.CharField(required=False, allow_null=True)

    def validate(self, attrs):
        # 1. Grab the token string passed from the view
        refresh_token_string = attrs.get("refresh")

        if not refresh_token_string:
            raise AuthenticationFailed("Refresh token is required.")

        token_str = str(refresh_token_string).strip()
        token_hash = hashlib.sha256(token_str.encode("utf-8")).hexdigest()
        cache_key = f"resume_refreshed_token_{token_hash}"

        # Resilient concurrency grace period:
        # If parallel frontend requests fire simultaneously with the same valid refresh token,
        # return the freshly rotated tokens from the short-lived cache without erroring.
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

        try:
            # Decode and validate refresh token structure/cryptography
            refresh = RefreshToken(token_str)
            user_id = refresh.get("user_id") or refresh.get("id")

            if not user_id:
                raise AuthenticationFailed("Invalid token payload: missing user ID.")

            # Validate user
            user = ResumeRegistration.objects.get(
                id=user_id,
                status=True,
                is_deleted=False,
                is_verified=True,
            )

            # ROTATE REFRESH TOKEN: Issue fresh refresh token with all claims
            new_refresh = RefreshToken()
            new_refresh["user_id"] = user.id
            new_refresh["id"] = user.id
            new_refresh["email"] = user.email
            new_refresh["user_type"] = "resume_user"
            new_refresh["first_name"] = user.first_name
            new_refresh["last_name"] = user.last_name

            new_access_token = str(new_refresh.access_token)
            new_refresh_str = str(new_refresh)
            access_token = str(new_refresh.access_token)

            response_data = {
                "access_token": new_access_token,
                "access": new_access_token,
                "refresh_token": new_refresh_str,
                "refresh": new_refresh_str,
                "refresh_token_obj": new_refresh,
            }

            # Blacklist old refresh token safely if rotation/blacklisting is supported
            try:
                refresh.blacklist()
            except Exception:
                pass

            # Cache the response for 30 seconds for concurrent request tolerance
            cache.set(cache_key, response_data, timeout=30)

            return response_data

        except ResumeRegistration.DoesNotExist:
            raise AuthenticationFailed("User does not exist, is inactive, unverified, or deleted.")
        except (TokenError, InvalidToken):
            raise InvalidToken({"detail": "Token is invalid or expired."})

class SubscriptionSerializer(serializers.ModelSerializer):

    final_price = serializers.SerializerMethodField()
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        trim_whitespace=False  
    )

    class Meta:
        model = Subscription
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "price",
            "discount_price",
            "final_price",
            "billing_type",
            "duration_days",
            "limit",
            "is_active"
        ]

    def create(self, validated_data):
        return Subscription.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.final_price = (
            validated_data.get("discount_price")
            or instance.discount_price
            or validated_data.get("price")
            or instance.price
        )

        instance.save()
        return instance

    def get_final_price(self, obj):
        return obj.discount_price if obj.discount_price else obj.price

class UserSubscriptionSerializer(
    serializers.ModelSerializer
):

    subscription = SubscriptionSerializer()

    days_remaining = serializers.SerializerMethodField()

    is_expired = serializers.SerializerMethodField()

    class Meta:

        model = UserSubscription

        fields = [

            "id",

            "status",

            "start_date",

            "end_date",

            "days_remaining",

            "is_expired",

            "subscription"
        ]

    def get_days_remaining(self, obj):

        if not obj.end_date:
            return None

        remaining = (
            obj.end_date.date() -
            timezone.now().date()
        ).days

        if remaining < 0:
            return 0

        return remaining

    def get_is_expired(self, obj):

        if not obj.end_date:
            return False

        return timezone.now() > obj.end_date
    
class ResumeTemplateListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer optimized for grid listings and dashboard browsing.
    Excludes heavy HTML structure fields to conserve bandwidth.
    """
    class Meta:
        model = ResumeTemplate
        fields = ['id', 'name', 'slug', 'structure', 'description', 'tier', 'thumbnail']


class ResumeTemplateDetailSerializer(serializers.ModelSerializer):
    """
    Comprehensive serializer utilized ONLY when a user selects a single blueprint 
    to initialize a resume build session.
    """
    class Meta:
        model = ResumeTemplate
        fields = ['id', 'name', 'slug', 'description', 'tier', 'structure', 'html_markup', 'thumbnail']
    
class ResumeTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResumeTemplate
        fields = ['id', 'name', 'slug', 'tier', 'structure', "thumbnail"]


class UserResumeSerializer(serializers.ModelSerializer):
    template_details = ResumeTemplateSerializer(source='template', read_only=True)

    class Meta:
        model = UserResume
        fields = [
            'id', 'user', 'template', 'template_details', 
            'resume_title', 'resume_data', 
            'last_completed_section', 'is_completed', 
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']


class IncrementalSectionUpdateSerializer(serializers.Serializer):
    """
    Validates input payloads for progressive section updates.
    """
    section_name = serializers.CharField(max_length=100)
    # Allows validation of flexible list of data or single dictionaries
    section_payload = serializers.JSONField() 
    is_completed = serializers.BooleanField(required=False, default=False)

class DashboardSubscriptionSerializer(serializers.ModelSerializer):

    name = serializers.CharField(
        source="subscription.name"
    )

    slug = serializers.CharField(
        source="subscription.slug"
    )

    description = serializers.CharField(
        source="subscription.description",
        required=False,
        allow_blank=True,
        allow_null=True,
        trim_whitespace=False
    )

    price = serializers.DecimalField(
        source="subscription.price",
        max_digits=10,
        decimal_places=2
    )

    discount_price = serializers.DecimalField(
        source="subscription.discount_price",
        max_digits=10,
        decimal_places=2,
        allow_null=True
    )

    billing_type = serializers.CharField(
        source="subscription.billing_type"
    )

    duration_days = serializers.CharField(
        source="subscription.duration_days"
    )

    limit = serializers.CharField(
        source="subscription.limit"
    )

    validity = serializers.SerializerMethodField()

    expires_at = serializers.DateTimeField(
        source="end_date",
        allow_null=True
    )

    days_remaining = serializers.SerializerMethodField()

    purchased_at = serializers.DateTimeField(
        source="start_date"
    )

    class Meta:

        model = UserSubscription

        fields = [
            'name',
            'slug',
            'description',
            'price',
            'discount_price',
            'billing_type',
            'duration_days',
            'limit',
            'validity',
            'expires_at',
            'days_remaining',
            'purchased_at'
        ]

    # ----------------------------------------
    # VALIDITY
    # ----------------------------------------

    def get_validity(self, obj):

        if obj.subscription.billing_type == "lifetime":
            return "Lifetime"

        return f"{obj.subscription.duration_days} Days"

    # ----------------------------------------
    # DAYS REMAINING
    # ----------------------------------------

    def get_days_remaining(self, obj):

        if not obj.end_date:
            return None

        remaining = (
            obj.end_date.date()
            - now().date()
        ).days

        return max(remaining, 0)
    
class DashboardCurrentSubscriptionSerializer(serializers.Serializer):
    plan_name = serializers.CharField()
    slug = serializers.CharField()
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        trim_whitespace=False
    )
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    discount_price = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    billing_type = serializers.CharField()
    duration_days = serializers.CharField()
    limit = serializers.IntegerField()

    validity_type = serializers.SerializerMethodField()
    expires_at = serializers.DateTimeField(allow_null=True)
    days_remaining = serializers.SerializerMethodField()

    def get_validity_type(self, obj):

        # obj = current_subscription object

        if obj.subscription.billing_type == "lifetime":
            return "Lifetime"

        return "Limited"

    def get_days_remaining(self, obj):

        if not obj.end_date:
            return None

        remaining = (obj.end_date - now()).days

        return max(remaining, 0)

class DashboardSubscriptionHistorySerializer(serializers.ModelSerializer):

    plan_name = serializers.CharField(
        source="subscription.name"
    )

    amount = serializers.SerializerMethodField()

    currency = serializers.SerializerMethodField()

    payment_status = serializers.SerializerMethodField()

    payment_mode = serializers.SerializerMethodField()

    invoice_no = serializers.SerializerMethodField()

    invoice_date = serializers.SerializerMethodField()


    class Meta:

        model = UserSubscription

        fields = [
            "id",
            "plan_name",
            "amount",
            "currency",
            "payment_status",
            "payment_mode",
            "invoice_no",
            "invoice_date",
        ]

    # ----------------------------------------
    # AMOUNT
    # ----------------------------------------

    def get_amount(self, obj):

        if obj.payment_transaction:
            return obj.payment_transaction.amount

        return "0.00"

    # ----------------------------------------
    # CURRENCY
    # ----------------------------------------

    def get_currency(self, obj):

        if obj.payment_transaction:
            return obj.payment_transaction.currency

        return "INR"

    # ----------------------------------------
    # PAYMENT STATUS
    # ----------------------------------------

    def get_payment_status(self, obj):

        if obj.payment_transaction:
            return obj.payment_transaction.payment_status

        return "free"

    # ----------------------------------------
    # PAYMENT MODE
    # ----------------------------------------

    def get_payment_mode(self, obj):

        if obj.payment_transaction:
            return obj.payment_transaction.payment_mode

        return "free"

    # ----------------------------------------
    # INVOICE
    # ----------------------------------------

    def get_invoice_no(self, obj):

        if obj.payment_transaction:
            return obj.payment_transaction.invoice_no

        return "free"

    def get_invoice_date(self, obj):

        if (
            obj.payment_transaction and
            obj.payment_transaction.invoice_date
        ):
            return obj.payment_transaction.invoice_date

        return obj.start_date
    
class DashboardTransactionSerializer(serializers.ModelSerializer):
    """Returns safe transaction history for the user."""
    class Meta:
        model = PaymentTransaction
        fields = [
            'transaction_id', 'amount', 'currency', 'payment_status', 
            'payment_mode', 'invoice_no', 'invoice_date', 'created_at'
        ]

class DashboardTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResumeTemplate
        fields = ['id', 'name', 'tier', 'thumbnail']

class DashboardResumeSerializer(serializers.ModelSerializer):
    # Nest the template so they know which blueprint they used
    template = DashboardTemplateSerializer(read_only=True)
    
    class Meta:
        model = UserResume
        fields = [
            'id', 'resume_title', 'resume_data', 'last_completed_section', 
            'is_completed', 'updated_at', 'template'
        ]

class PaymentHistorySerializers(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = PaymentHistory
        fields = [
            "id",
            "user",
            "user_name",
            "plan_name",
            "price",
            "payment_status",
            "created_at"
        ]

    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"
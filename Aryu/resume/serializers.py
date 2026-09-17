import hashlib
from django.conf import settings
from django.core.cache import cache
from rest_framework import serializers
from django.utils import timezone
import re
import hashlib
from django.core.cache import cache
from payments.models import PaymentTransaction
from aryuapp.models import StudentTicket, TicketReply, TicketAttachment
from .models import ResumeRegistration,Contact,Subscription,PaymentHistory, UserSubscription, UserResume, ResumeTemplate, AIUsageLog
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework.exceptions import AuthenticationFailed
from django.utils.timezone import now
import logging

logger = logging.getLogger("resume")

class ResumeRegistrationSerializers(serializers.ModelSerializer):

    current_subscription = serializers.PrimaryKeyRelatedField(
        queryset=Subscription.objects.all(),
        required=False,
        allow_null=True
    )
    ai_token_usage = serializers.SerializerMethodField()

    class Meta:
        model = ResumeRegistration
        fields = "__all__"

    def get_ai_token_usage(self, obj):
        ai_token_usage_map = self.context.get("ai_token_usage_map")
        if ai_token_usage_map is not None and obj.id in ai_token_usage_map:
            return ai_token_usage_map[obj.id]
        from .services.ai_usage_service import AIUsageService
        return AIUsageService.get_user_token_usage(obj.id)

class GoogleLoginSerializer(serializers.Serializer):
    credential = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        help_text="Google ID Token credential returned by Google Identity Services GIS SDK."
    )
    
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
        refresh_token_string = attrs.get("refresh") or attrs.get("refresh_token")

        if not refresh_token_string:
            raise AuthenticationFailed("Refresh token is required.", code="missing_refresh_token")

        token_str = str(refresh_token_string).strip()
        token_hash = hashlib.sha256(token_str.encode("utf-8")).hexdigest()
        cache_key = f"resume_refreshed_token_{token_hash}"

        # Resilient concurrency grace period:
        # If parallel frontend requests fire simultaneously with the same valid refresh token,
        # return the freshly rotated tokens from the short-lived cache without erroring.
        cached_response = cache.get(cache_key)
        if cached_response and isinstance(cached_response, dict):
            return cached_response

        # 2. Decode and validate refresh token structure/cryptography
        try:
            refresh = RefreshToken(token_str)
        except TokenError as exc:
            err_msg = str(exc).lower()
            if "blacklisted" in err_msg:
                raise InvalidToken({"detail": "Refresh token is blacklisted.", "code": "token_blacklisted"})
            elif "expired" in err_msg:
                raise InvalidToken({"detail": "Refresh token is expired.", "code": "token_expired"})
            elif "type" in err_msg:
                raise InvalidToken({"detail": "Token is not a valid refresh token.", "code": "invalid_token_type"})
            else:
                raise InvalidToken({"detail": "Token is invalid or expired.", "code": "invalid_token"})

        # Strictly ensure this is a refresh token and NOT an access token
        token_type = refresh.get("token_type") or getattr(refresh, "payload", {}).get("token_type")
        logger.debug(f'token type: {token_type}')
        if token_type and token_type != "refresh":
            raise InvalidToken({"detail": "Token is not a valid refresh token.", "code": "invalid_token_type"})

        user_id = refresh.get("user_id") or refresh.get("id")
        logger.debug(f'user id: {user_id}')
        if not user_id:
            raise AuthenticationFailed("Invalid token payload: missing user ID.", code="missing_user_id")

        # 3. Granular user validation: distinguish non-existent, deleted, inactive, and unverified
        logger.info("[RESUME REFRESH] User validation started")
        user = ResumeRegistration.objects.filter(id=user_id).first()
        logger.debug(f'user: {user}')
        if not user:
            raise AuthenticationFailed("User does not exist, is inactive, unverified, or deleted.", code="user_not_found")
        if getattr(user, "is_deleted", False):
            raise AuthenticationFailed("User does not exist, is inactive, unverified, or deleted.", code="user_deleted")
        if not getattr(user, "status", True):
            raise AuthenticationFailed("User does not exist, is inactive, unverified, or deleted.", code="user_inactive")
        if not getattr(user, "is_verified", False):
            raise AuthenticationFailed("User does not exist, is inactive, unverified, or deleted.", code="user_unverified")

        # 4. ROTATE REFRESH TOKEN: Issue fresh refresh token with all claims
        logger.info("[RESUME REFRESH] Token rotation started")
        new_refresh = RefreshToken()
        new_refresh["user_id"] = user.id
        new_refresh["id"] = user.id
        new_refresh["email"] = user.email
        new_refresh["user_type"] = "resume_user"
        new_refresh["first_name"] = user.first_name
        new_refresh["last_name"] = user.last_name

        new_access_token = str(new_refresh.access_token)
        new_refresh_str = str(new_refresh)

        # Pure serializable dict (no live Python RefreshToken objects stored in cache)
        response_data = {
            "access_token": new_access_token,
            "access": new_access_token,
            "refresh_token": new_refresh_str,
            "refresh": new_refresh_str,
        }

        # 5. Blacklist old refresh token safely if rotation/blacklisting is supported
        try:
            refresh.blacklist()
        except Exception as blacklist_err:
            logger.warning("[RESUME REFRESH] Old token blacklist note: %s", blacklist_err)

        # 6. Cache the response for 30 seconds for concurrent request tolerance
        cache.set(cache_key, response_data, timeout=30)

        return response_data

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
        source="subscription.name",
        read_only=True
    )

    transaction_id = serializers.SerializerMethodField()

    amount = serializers.SerializerMethodField()

    currency = serializers.SerializerMethodField()

    payment_status = serializers.SerializerMethodField()

    payment_mode = serializers.SerializerMethodField()

    invoice_no = serializers.SerializerMethodField()

    invoice_date = serializers.SerializerMethodField()

    created_date = serializers.SerializerMethodField()

    created_at = serializers.SerializerMethodField()

    class Meta:

        model = UserSubscription

        fields = [
            "id",
            "transaction_id",
            "plan_name",
            "amount",
            "currency",
            "payment_status",
            "payment_mode",
            "invoice_no",
            "invoice_date",
            "created_date",
            "created_at",
        ]

    # ----------------------------------------
    # TRANSACTION ID
    # ----------------------------------------

    def get_transaction_id(self, obj):

        if obj.payment_transaction and obj.payment_transaction.transaction_id:
            return obj.payment_transaction.transaction_id

        if obj.payment_transaction:
            return str(obj.payment_transaction.id)

        return None

    # ----------------------------------------
    # AMOUNT
    # ----------------------------------------

    def get_amount(self, obj):

        if obj.payment_transaction and obj.payment_transaction.amount is not None:
            return obj.payment_transaction.amount

        return "0.00"

    # ----------------------------------------
    # CURRENCY
    # ----------------------------------------

    def get_currency(self, obj):

        if obj.payment_transaction and obj.payment_transaction.currency:
            return obj.payment_transaction.currency

        return "INR"

    # ----------------------------------------
    # PAYMENT STATUS
    # ----------------------------------------

    def get_payment_status(self, obj):

        if obj.payment_transaction and obj.payment_transaction.payment_status:
            return obj.payment_transaction.payment_status

        return "free"

    # ----------------------------------------
    # PAYMENT MODE
    # ----------------------------------------

    def get_payment_mode(self, obj):

        if obj.payment_transaction and obj.payment_transaction.payment_mode:
            return obj.payment_transaction.payment_mode

        if obj.payment_transaction:
            return "razorpay"

        return "free"

    # ----------------------------------------
    # INVOICE
    # ----------------------------------------

    def get_invoice_no(self, obj):

        if obj.payment_transaction and obj.payment_transaction.invoice_no:
            return obj.payment_transaction.invoice_no

        return "free" if not obj.payment_transaction else None

    def get_invoice_date(self, obj):

        if (
            obj.payment_transaction and
            obj.payment_transaction.invoice_date
        ):
            return obj.payment_transaction.invoice_date

        if obj.start_date:
            return obj.start_date.date() if hasattr(obj.start_date, 'date') else obj.start_date

        return None

    # ----------------------------------------
    # CREATED AT / CREATED DATE
    # ----------------------------------------

    def get_created_at(self, obj):

        if obj.payment_transaction and obj.payment_transaction.created_at:
            return obj.payment_transaction.created_at

        return obj.created_at

    def get_created_date(self, obj):

        dt = self.get_created_at(obj)

        if dt:
            return dt.date() if hasattr(dt, 'date') else dt

        return None
    
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


# =========================================================================
# RESUME APP TICKET / SUPPORT SERIALIZERS (REUSING ARYUAPP TICKET MODELS)
# =========================================================================

class ResumeTicketAttachmentSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)

    class Meta:
        model = TicketAttachment
        fields = ["attachment_id", "file", "created_at"]

    def get_file(self, obj):
        if obj.file and hasattr(obj.file, 'url'):
            media_base = getattr(settings, 'MEDIA_BASE_URL', '')
            if media_base:
                return media_base.rstrip('/') + obj.file.url
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return None


class ResumeTicketReplySerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="reply_id", read_only=True)
    sender_type = serializers.SerializerMethodField()
    sender_name = serializers.SerializerMethodField()
    sender = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)

    class Meta:
        model = TicketReply
        fields = ["reply_id", "id", "sender_type", "sender_name", "sender", "message", "created_at"]

    def get_sender_type(self, obj):
        if getattr(obj, "resume_user", None):
            return "resume_user"
        return "admin"

    def get_sender_name(self, obj):
        if getattr(obj, "resume_user", None):
            name = f"{getattr(obj.resume_user, 'first_name', '')} {getattr(obj.resume_user, 'last_name', '')}".strip()
            return name or getattr(obj.resume_user, 'email', 'Resume User')
        if getattr(obj, "super_admin", None):
            admin = obj.super_admin
            name = f"{getattr(admin, 'first_name', '')} {getattr(admin, 'last_name', '')}".strip()
            return name or getattr(admin, "full_name", None) or getattr(admin, "username", "Support Team")
        return "Support Team"

    def get_sender(self, obj):
        sender_type = self.get_sender_type(obj)
        sender_name = self.get_sender_name(obj)
        email = None
        if getattr(obj, "resume_user", None):
            email = getattr(obj.resume_user, "email", None)
        elif getattr(obj, "super_admin", None):
            email = getattr(obj.super_admin, "email", None)

        return {
            "name": sender_name,
            "email": email,
            "type": sender_type,
            "sender_type": sender_type,
        }


def _get_ticket_user_info(obj):
    resume_user = getattr(obj, "resume_user", None)
    if resume_user:
        first_name = getattr(resume_user, "first_name", "") or ""
        last_name = getattr(resume_user, "last_name", "") or ""
        full_name = f"{first_name} {last_name}".strip()
        user_name = full_name or getattr(obj, "name", "") or ""
        user_email = getattr(resume_user, "email", "") or getattr(obj, "email", "") or ""
        user_phone = getattr(resume_user, "phone", None) if getattr(resume_user, "phone", None) is not None else getattr(obj, "phone", None)
        user_id = getattr(resume_user, "id", None)
    else:
        user_name = getattr(obj, "name", "") or ""
        user_email = getattr(obj, "email", "") or ""
        user_phone = getattr(obj, "phone", None)
        user_id = None

    phone_val = str(user_phone).strip() if (user_phone is not None and str(user_phone).strip() != "") else None

    return {
        "id": user_id,
        "name": user_name,
        "email": user_email,
        "mobile": phone_val,
        "phone": phone_val,
    }


class ResumeTicketListSerializer(serializers.ModelSerializer):
    attachments = ResumeTicketAttachmentSerializer(many=True, read_only=True)
    replies = ResumeTicketReplySerializer(many=True, read_only=True)
    reply_count = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    updated_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    mobile = serializers.SerializerMethodField()
    raised_by = serializers.SerializerMethodField()

    class Meta:
        model = StudentTicket
        fields = [
            "ticket_id",
            "ticket_token",
            "subject",
            "message",
            "ticket_type",
            "status",
            "priority",
            "name",
            "email",
            "phone",
            "mobile",
            "raised_by",
            "reply_count",
            "replies",
            "attachments",
            "created_at",
            "updated_at",
        ]

    def get_reply_count(self, obj):
        if hasattr(obj, "replies_count"):
            return obj.replies_count
        if hasattr(obj, "replies"):
            return obj.replies.count()
        return 0

    def get_raised_by(self, obj):
        return _get_ticket_user_info(obj)

    def get_name(self, obj):
        return _get_ticket_user_info(obj)["name"]

    def get_email(self, obj):
        return _get_ticket_user_info(obj)["email"]

    def get_phone(self, obj):
        return _get_ticket_user_info(obj)["phone"]

    def get_mobile(self, obj):
        return _get_ticket_user_info(obj)["mobile"]


class ResumeTicketDetailSerializer(serializers.ModelSerializer):
    attachments = ResumeTicketAttachmentSerializer(many=True, read_only=True)
    replies = ResumeTicketReplySerializer(many=True, read_only=True)
    reply_count = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    updated_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    mobile = serializers.SerializerMethodField()
    raised_by = serializers.SerializerMethodField()

    class Meta:
        model = StudentTicket
        fields = [
            "ticket_id",
            "ticket_token",
            "subject",
            "message",
            "ticket_type",
            "status",
            "priority",
            "name",
            "email",
            "phone",
            "mobile",
            "raised_by",
            "attachments",
            "reply_count",
            "replies",
            "created_at",
            "updated_at",
        ]

    def get_reply_count(self, obj):
        if hasattr(obj, "replies_count"):
            return obj.replies_count
        if hasattr(obj, "replies"):
            return obj.replies.count()
        return 0

    def get_raised_by(self, obj):
        return _get_ticket_user_info(obj)

    def get_name(self, obj):
        return _get_ticket_user_info(obj)["name"]

    def get_email(self, obj):
        return _get_ticket_user_info(obj)["email"]

    def get_phone(self, obj):
        return _get_ticket_user_info(obj)["phone"]

    def get_mobile(self, obj):
        return _get_ticket_user_info(obj)["mobile"]


class ResumeTicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=255, required=True, allow_blank=False)
    message = serializers.CharField(required=True, allow_blank=False)
    ticket_type = serializers.CharField(max_length=30, default="support", required=False)
    priority = serializers.ChoiceField(
        choices=["Low", "Medium", "High", "low", "medium", "high"],
        default="Low",
        required=False
    )


class ResumeTicketReplyCreateSerializer(serializers.Serializer):
    message = serializers.CharField(required=True, allow_blank=False)
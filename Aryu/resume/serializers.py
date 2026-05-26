from rest_framework import serializers
from django.utils import timezone
from payments.models import PaymentTransaction
from .models import ResumeRegistration,Contact,Subscription,PaymentHistory, UserSubscription, UserResume, ResumeTemplate
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
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

class ContactSerializers(serializers.ModelSerializer):

    class Meta:
        model = Contact
        fields ="__all__"

class CustomTokenRefreshSerializer(serializers.Serializer):
    # Accept the 'refresh' key exactly like standard Simple JWT
    refresh = serializers.CharField()

    def validate(self, attrs):
        refresh_token_string = attrs.get("refresh")

        try:
            # 1. Validate and decode the incoming token string
            decoded_token = UntypedToken(refresh_token_string)
            
            # 2. Extract the identifier (usually 'user_id' in the token payload)
            user_id = decoded_token.get("user_id")
            if not user_id:
                raise AuthenticationFailed("Invalid token payload: missing user identifier.")

            # 3. Query your CUSTOM ResumeRegistration table instead of auth.User
            user_profile = ResumeRegistration.objects.get(
                id=user_id, 
                status=True,      # Ensure user is active
                is_deleted=False  # Ensure user is not soft-deleted
            )

        except ResumeRegistration.DoesNotExist:
            # Captures when the custom user record is missing, inactive, or deleted
            raise AuthenticationFailed("Session invalid: Registered user does not exist or is deactivated.")
        except (TokenError, InvalidToken) as e:
            # Captures expired or tampered-with refresh tokens
            raise InvalidToken({"detail": "Token is invalid or expired."})

        # 4. If the user exists and is valid, generate a brand-new access token
        refresh_token_obj = RefreshToken(refresh_token_string)
        
        return {
            "access": str(refresh_token_obj.access_token),
        }

class SubscriptionSerializer(serializers.ModelSerializer):

    final_price = serializers.SerializerMethodField()

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

    def get_final_price(self, obj):

        if obj.discount_price:

            return obj.discount_price

        return obj.price


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

    validity_type = serializers.SerializerMethodField()
    expires_at = serializers.SerializerMethodField()
    days_remaining = serializers.SerializerMethodField()
    purchased_at = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            'name',
            'slug',
            'description',
            'price',
            'discount_price',
            'billing_type',
            'duration_days',
            'limit',
            'validity_type',
            'expires_at',
            'days_remaining',
            'purchased_at'
        ]

    def get_validity_type(self, obj):

        return (
            "Lifetime"
            if obj.billing_type == "lifetime"
            else "Limited"
        )

    def get_expires_at(self, obj):

        current_subscription = self.context.get(
            "current_subscription"
        )

        if current_subscription:
            return current_subscription.end_date

        return None

    def get_days_remaining(self, obj):

        current_subscription = self.context.get(
            "current_subscription"
        )

        if (
            not current_subscription or
            not current_subscription.end_date
        ):
            return None

        remaining = (
            current_subscription.end_date - now()
        ).days

        return max(remaining, 0)

    def get_purchased_at(self, obj):

        current_subscription = self.context.get(
            "current_subscription"
        )

        user = self.context.get("user")

        if current_subscription:
            return current_subscription.start_date

        return user.created_at

class DashboardCurrentSubscriptionSerializer(serializers.Serializer):
    plan_name = serializers.CharField()
    slug = serializers.CharField()
    description = serializers.CharField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    discount_price = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    billing_type = serializers.CharField()
    duration_days = serializers.IntegerField()
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

    class Meta:
        model = PaymentHistory
        fields = "__all__"
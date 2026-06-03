from rest_framework import serializers
from django.utils import timezone
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

class ContactSerializers(serializers.ModelSerializer):

    class Meta:
        model = Contact
        fields ="__all__"

class CustomTokenRefreshSerializer(TokenRefreshSerializer):

    def validate(self, attrs):

        refresh_token_string = attrs.get("refresh")

        try:

            # Decode refresh token
            refresh = RefreshToken(refresh_token_string)

            user_id = refresh.get("user_id")

            if not user_id:
                raise AuthenticationFailed(
                    "Invalid token payload."
                )

            # Validate user
            user = ResumeRegistration.objects.get(
                id=user_id,
                status=True,
                is_deleted=False
            )

            # Create new access token
            access_token = str(refresh.access_token)

            response_data = {
                "access_token": access_token,
            }

            # OPTIONAL REFRESH ROTATION
            # Create new refresh token manually

            new_refresh = RefreshToken()

            new_refresh["user_id"] = user.id
            new_refresh["id"] = user.id

            new_refresh["email"] = user.email
            new_refresh["user_type"] = "resume_user"

            new_refresh["first_name"] = user.first_name
            new_refresh["last_name"] = user.last_name

            response_data["refresh_token"] = str(new_refresh)

            return response_data

        except ResumeRegistration.DoesNotExist:
            raise AuthenticationFailed(
                "User inactive or deleted."
            )

        except (TokenError, InvalidToken):
            raise InvalidToken(
                {"detail": "Token invalid or expired."}
            )

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

    def create(self, validated_data):

        validated_data["final_price"] = (
            validated_data.get("discount_price")
            or validated_data.get("price")
        )

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

        return obj.final_price or obj.price


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
        source="subscription.description"
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

    duration_days = serializers.IntegerField(
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

    class Meta:
        model = PaymentHistory
        fields = "__all__"
import json
import logging
import secrets
import string
import uuid
import razorpay
import hashlib
import hmac

from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.core.cache import cache
from django.db import transaction as db_transaction
from django.db.models import Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from aryuapp.auth import CustomJWTAuthentication
from payments.models import PaymentGateway, PaymentTransaction
from payments.services.razorpay_service import (
    get_active_razorpay_gateway,
    get_webhook_secret,
    process_razorpay_webhook_event,
    verify_razorpay_signature,
)
from rest_framework.authentication import SessionAuthentication
from .ebook_emails import send_ebook_registration_email
from .models import *
from .serializers import *
from .whatsapp import *

logger = logging.getLogger('razorpay_webhook')


def generate_secure_password(length=12):
    """
    OWASP Aligned: Cryptographically secure random password generator using system CSPRNG.
    Ensures minimum complexity constraints (uppercase, lowercase, digits, symbols).
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pwd)
                and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd)
                and any(c in "!@#$%^&*" for c in pwd)):
            return pwd


# ─────────────────────────────────────────────────────────────────────────────
# 1. EbookViewSet (Authenticated Admin Management)
# ─────────────────────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class EbookViewSet(viewsets.ModelViewSet):
    queryset = Ebook.objects.all()
    serializer_class = EbookSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    lookup_field = "slug"

    def extract_tags(self, request):
    # Check if request.data has the 'getlist' method (e.g., QueryDict from form-data)
        if hasattr(request.data, 'getlist'):
            tags = request.data.getlist("tags")
            # If passed as a single comma-separated string inside form-data
            if len(tags) == 1 and isinstance(tags[0], str) and "," in tags[0]:
                return [tag.strip() for tag in tags[0].split(",") if tag.strip()]
            return tags

        # Fallback for standard dict (JSON payloads)
        tags = request.data.get("tags", [])

        # Handle string input if sent as a comma-separated string in JSON
        if isinstance(tags, str):
            return [tag.strip() for tag in tags.split(",") if tag.strip()]

        # Return as list if already a list, or empty list if None/invalid
        return tags if isinstance(tags, list) else []

    @db_transaction.atomic
    def create(self, request, *args, **kwargs):
        logger.debug(f"CREATE EBOOK REQUEST DATA: {request.data}")
        tags = self.extract_tags(request)

        data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
        data["tags"] = tags

        serializer = self.get_serializer(data=data, context={'request': request})
        if not serializer.is_valid():
            logger.error(f"EBOOK CREATE ERRORS: {serializer.errors}")
            return Response({
                "status": False,
                "message": "Validation failed",
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        ebook = serializer.save()

        # ---------- SEO ----------
        i = 0
        while f"seo[{i}][seo_title]" in request.data:
            EbookSEO.objects.create(
                ebook=ebook,
                seo_title=request.data.get(f"seo[{i}][seo_title]"),
                seo_description=request.data.get(f"seo[{i}][seo_description]"),
                seo_image=request.FILES.get(f"seo[{i}][seo_image]")
            )
            i += 1

        # ---------- TOOLS ----------
        j = 0
        while f"tools[{j}][tool_title]" in request.data:
            EbookTool.objects.create(
                ebook=ebook,
                tool_title=request.data.get(f"tools[{j}][tool_title]"),
                tool_image=request.FILES.get(f"tools[{j}][tool_image_url]")
            )
            j += 1

        # ---------- FAQ ----------
        k = 0
        while f"faqs[{k}][faq_question]" in request.data:
            EbookFAQ.objects.create(
                ebook=ebook,
                faq_question=request.data.get(f"faqs[{k}][faq_question]"),
                faq_answer=request.data.get(f"faqs[{k}][faq_answer]")
            )
            k += 1

        return Response({
            "status": True,
            "message": "Ebook created successfully",
            "data": EbookSerializer(ebook, context={'request': request}).data
        }, status=status.HTTP_201_CREATED)

    @db_transaction.atomic
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        tags = self.extract_tags(request)

        data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
        data["tags"] = tags

        serializer = self.get_serializer(
            instance,
            data=data,
            partial=True,
            context={'request': request}
        )

        if not serializer.is_valid():
            logger.error(f"EBOOK UPDATE ERRORS: {serializer.errors}")
            return Response({
                "status": False,
                "message": "Validation failed",
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        ebook = serializer.save()

        # ---------- DELETE OLD NESTED DATA ----------
        ebook.seo.all().delete()
        ebook.tools.all().delete()
        ebook.faqs.all().delete()

        # ---------- SEO ----------
        i = 0
        while f"seo[{i}][seo_title]" in request.data:
            EbookSEO.objects.create(
                ebook=ebook,
                seo_title=request.data.get(f"seo[{i}][seo_title]"),
                seo_description=request.data.get(f"seo[{i}][seo_description]"),
                seo_image=request.FILES.get(f"seo[{i}][seo_image_url]")
            )
            i += 1

        # ---------- TOOLS ----------
        j = 0
        while f"tools[{j}][tool_title]" in request.data:
            EbookTool.objects.create(
                ebook=ebook,
                tool_title=request.data.get(f"tools[{j}][tool_title]"),
                tool_image=request.FILES.get(f"tools[{j}][tool_image_url]")
            )
            j += 1

        # ---------- FAQ ----------
        k = 0
        while f"faqs[{k}][faq_question]" in request.data:
            EbookFAQ.objects.create(
                ebook=ebook,
                faq_question=request.data.get(f"faqs[{k}][faq_question]"),
                faq_answer=request.data.get(f"faqs[{k}][faq_answer]")
            )
            k += 1

        return Response({
            "status": True,
            "message": "Ebook updated successfully",
            "data": EbookSerializer(ebook, context={'request': request}).data
        }, status=status.HTTP_200_OK)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, context={'request': request})
        return Response({
            "status": True,
            "message": "Ebook retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(
            queryset,
            many=True,
            context={'request': request}
        )
        return Response({
            "status": True,
            "message": "Ebooks retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    @db_transaction.atomic
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.seo.all().delete()
        instance.tools.all().delete()
        instance.faqs.all().delete()
        instance.delete()

        return Response({
            "status": True,
            "message": "Ebook deleted successfully"
        }, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Public Ebook Views
# ─────────────────────────────────────────────────────────────────────────────
class EbookPublicListAPIView(viewsets.ModelViewSet):
    queryset = Ebook.objects.filter(is_deleted=False)
    serializer_class = EbookDetailSerializer
    authentication_classes = []
    permission_classes = [AllowAny]


class PublicEbookViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    queryset = Ebook.objects.filter(is_deleted=False, status=True)
    serializer_class = PublicEbookListSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = "slug"

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return Response({
            "success": True,
            "data": response.data
        })

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        return Response({
            "success": True,
            "data": response.data
        })


# ─────────────────────────────────────────────────────────────────────────────
# 3. WhatsApp Webhook
# ─────────────────────────────────────────────────────────────────────────────
@csrf_exempt
@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def whatsapp_webhook(request):
    verify_token = getattr(settings, "WHATSAPP_VERIFY_TOKEN", "akzworld")

    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        if mode == "subscribe" and token == verify_token:
            return HttpResponse(challenge)
        return HttpResponse("Invalid token", status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid payload"}, status=400)

    logger.info("===== WHATSAPP WEBHOOK RECEIVED =====")
    logger.debug(json.dumps(payload, indent=2))

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            for status_item in value.get("statuses", []):
                logger.debug(
                    f"STATUS: {status_item.get('status')} | "
                    f"TIME: {status_item.get('timestamp')} | "
                    f"PHONE: {status_item.get('recipient_id')} | "
                    f"MESSAGE_ID: {status_item.get('id')}"
                )

            for message in value.get("messages", []):
                phone = message.get("from", "")

                if message.get("type") == "button":
                    button_text = message.get("button", {}).get("text", "").strip().lower()
                    registration = EbookRegistration.objects.filter(phone=phone[-10:]).last()

                    if not registration:
                        continue

                    if button_text in ["remaind me", "remind me"]:
                        registration.wants_reminder = True
                        registration.save()
                        send_ebook_reminder.delay(registration.id, time_left="15 mins")
                        logger.info(f"Reminder opted by {phone}")

    return JsonResponse({"status": "ok"})


# ─────────────────────────────────────────────────────────────────────────────
# 4. Razorpay Webhook
# ─────────────────────────────────────────────────────────────────────────────
@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def razorpay_webhook(request):
    logger.info("Ebook Webhook received")

    raw_body = request.body
    received_signature = request.headers.get("X-Razorpay-Signature") or request.META.get("HTTP_X_RAZORPAY_SIGNATURE")
    event_id = request.headers.get("X-Razorpay-Event-Id") or request.META.get("HTTP_X_RAZORPAY_EVENT_ID")

    if not received_signature:
        logger.error("Razorpay Webhook: Missing signature header")
        return HttpResponse("Missing signature", status=400)

    gateway = get_active_razorpay_gateway()
    webhook_secret = get_webhook_secret(gateway)

    if not webhook_secret:
        logger.error("Razorpay Webhook: Gateway config or webhook_secret missing")
        return HttpResponse("Gateway config error", status=500)

    if not verify_razorpay_signature(raw_body, received_signature, webhook_secret, event_id=event_id):
        logger.error("Razorpay Webhook: Signature verification failed")
        return HttpResponse("Invalid signature", status=400)

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("Razorpay Webhook: Invalid JSON payload")
        return HttpResponse("Invalid JSON", status=400)

    process_razorpay_webhook_event(data)
    return HttpResponse(status=200)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Razorpay Payment ViewSet
# ─────────────────────────────────────────────────────────────────────────────
@method_decorator(csrf_exempt, name='dispatch')
class RazorpayPaymentViewSet(viewsets.ViewSet):
    authentication_classes = []
    permission_classes = [AllowAny]

    def _get_client(self):
        gateway = PaymentGateway.objects.filter(gatway_name__icontains="razorpay").first()
        if not gateway:
            return None, None
        client = razorpay.Client(auth=(gateway.public_key, gateway.secret_key))
        return client, gateway

    @action(detail=False, methods=["post"])
    def create(self, request):
        transaction_id = f"TXN_{uuid.uuid4().hex[:12].upper()}"
        ebook_id = request.data.get("ebook_id")
        registration_id = request.data.get("registration_id")
        name = request.data.get("name")
        email = request.data.get("email")
        phone = request.data.get("phone")
        role_id = request.data.get("role_id")
        role_name = request.data.get("role_name")

        if not all([ebook_id, phone]):
            return Response(
                {"success": False, "message": "Missing required fields"},
                status=status.HTTP_400_BAD_REQUEST
            )

        client, gateway = self._get_client()
        if not client:
            return Response(
                {"success": False, "message": "Razorpay not configured"},
                status=status.HTTP_400_BAD_REQUEST
            )

        ebook = get_object_or_404(Ebook, id=ebook_id)
        amount = ebook.price

        registration = None
        if registration_id:
            registration = EbookRegistration.objects.filter(id=registration_id).first()

        order = client.order.create({
            "amount": int(float(amount) * 100),
            "receipt": transaction_id,
            "currency": "INR",
            "payment_capture": 1,
            "notes": {
                "ebook_id": str(ebook_id),
                "registration_id": str(registration_id) if registration_id else "",
                "name": name,
                "email": email,
                "phone": phone,
            }
        })

        txn = PaymentTransaction.objects.create(
            gateway=gateway,
            amount=amount,
            currency="INR",
            payment_status="pending",
            order_id=order["id"],
            transaction_id=transaction_id,
            phone=phone,
            metadata={
                "ebook_id": str(ebook_id),
                "registration_id": str(registration_id) if registration_id else "",
                "name": name,
                "email": email,
                "phone": phone,
            }
        )

        if registration:
            registration.payment_transaction = txn
            registration.save()

        return Response({
            "success": True,
            "order_id": order["id"],
            "receipt": transaction_id,
            "key": gateway.public_key,
            "amount": int(float(amount) * 100),
            "currency": "INR",
            "ebook_title": ebook.title,
            "ebook_slug": ebook.slug,
            "email": registration.email if registration and registration.email else email,
            "name": registration.name if registration and registration.name else name,
            "phone": registration.phone if registration and registration.phone else phone,
            "registration_id": registration_id,
            "role_id": role_id,
            "role_name": role_name,
            "created_at": ebook.created_at
        })

    @action(detail=False, methods=['post'], url_path="verify")
    def verify_payment(self, request):
        payment_id = request.data.get("razorpay_payment_id")
        order_id = request.data.get("razorpay_order_id")
        signature = request.data.get("razorpay_signature")

        if not all([payment_id, order_id, signature]):
            return Response(
                {"success": False, "message": "Missing fields"},
                status=status.HTTP_400_BAD_REQUEST
            )

        gateway = PaymentGateway.objects.filter(gatway_name__icontains="razorpay").first()
        if not gateway:
            return Response(
                {"success": False, "message": "Gateway not configured"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            razorpay_client = razorpay.Client(auth=(gateway.public_key, gateway.secret_key))
            razorpay_client.utility.verify_payment_signature({
                "razorpay_payment_id": payment_id,
                "razorpay_order_id": order_id,
                "razorpay_signature": signature
            })

            txn = PaymentTransaction.objects.filter(order_id=order_id).first()
            if txn:
                txn.razorpay_payment_id = payment_id
                txn.payment_status = "done"
                txn.save()

                EbookRegistrationViewSet.update_registration_after_payment(txn)

        except razorpay.errors.SignatureVerificationError:
            return Response(
                {"success": False, "message": "Invalid signature"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({"success": True})


# ─────────────────────────────────────────────────────────────────────────────
# 6. Ebook Registration ViewSet
# ─────────────────────────────────────────────────────────────────────────────
@method_decorator(csrf_exempt, name='dispatch')
class EbookRegistrationViewSet(viewsets.ViewSet):
    # authentication_classes = []
    # permission_classes = [AllowAny]

    def _is_first_time_user(self, email, phone, current_registration_id=None):
        q_filter = Q()
        if email:
            q_filter |= Q(email__iexact=email)
        if phone:
            q_filter |= Q(phone=phone)

        if not q_filter:
            return True

        query = EbookRegistration.objects.filter(q_filter)
        if current_registration_id:
            query = query.exclude(id=current_registration_id)

        return query.count() == 0

    def _create_payment(self, request, ebook, existing_registration=None, is_new_user=False):
        transaction_id = f"TXN_{uuid.uuid4().hex[:12].upper()}"
        registration = existing_registration

        if not registration:
            email = request.data.get("email")
            phone = request.data.get("phone")
            name = request.data.get("name")
            q_user = Q()
            if email:
                q_user |= Q(email__iexact=email)
            if phone:
                q_user |= Q(phone=phone)

            existing_user_reg = EbookRegistration.objects.filter(q_user).exclude(
                password__isnull=True
            ).exclude(password="").order_by("-id").first()

            if existing_user_reg:
                user_password = existing_user_reg.password
                name = name or existing_user_reg.name
            else:
                raw_pwd = generate_secure_password(12)
                user_password = make_password(raw_pwd)

            registration = EbookRegistration.objects.create(
                ebook=ebook,
                name=name,
                email=email,
                phone=phone,
                password=user_password,
                is_paid=False
            )
            created = True
        else:
            created = False

        registration.name = request.data.get("name") or registration.name
        registration.phone = request.data.get("phone") or registration.phone
        registration.save()

        gateway = PaymentGateway.objects.filter(gatway_name__icontains="razorpay").first()
        if not gateway:
            return Response(
                {"error": "Razorpay payment gateway configuration not found."},
                status=status.HTTP_400_BAD_REQUEST
            )

        client = razorpay.Client(auth=(gateway.public_key, gateway.secret_key))
        amount = int(float(ebook.price) * 100)

        order = client.order.create({
            "amount": amount,
            "currency": "INR",
            "payment_capture": 1
        })

        txn = PaymentTransaction.objects.create(
            ebookregistration=registration,
            order_id=order["id"],
            transaction_id=transaction_id,
            amount=ebook.price,
            currency="INR",
            payment_status="pending",
            phone=registration.phone,
            metadata={
                "ebook_id": str(ebook.id),
                "registration_id": str(registration.id),
                "email": registration.email,
                "name": registration.name,
                "phone": registration.phone,
            }
        )

        registration.payment_transaction = txn
        registration.save()

        return Response({
            "success": True,
            "order_id": order["id"],
            "transaction_id": transaction_id,
            "key": gateway.public_key if gateway else getattr(settings, "RAZORPAY_KEY_ID", None),
            "amount": amount,
            "currency": "INR",
            "registration_id": registration.id,
            "transaction_db_id": txn.id,
            "is_existing": not created,
            "name": registration.name,
            "email": registration.email,
            "phone": registration.phone,
            "ebook_title": ebook.title,
            "ebook_slug": ebook.slug,
            "created_at": ebook.created_at,
        })

    def create(self, request, slug=None):
        ebook = get_object_or_404(Ebook, slug=slug)

        email = request.data.get("email")
        phone = request.data.get("phone")
        name = request.data.get("name")

        if not email and not phone:
            return Response(
                {"message": "Email or Phone is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        q_this_ebook = Q()
        if email:
            q_this_ebook |= Q(email__iexact=email)
        if phone:
            q_this_ebook |= Q(phone=phone)

        existing_registration = EbookRegistration.objects.filter(
            Q(ebook=ebook) & q_this_ebook
        ).first()

        if existing_registration:
            if not ebook.is_paid:
                return Response(
                    {"message": "Already registered for this ebook"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if existing_registration.is_paid:
                return Response(
                    {"message": "Already paid for this ebook"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            txn = existing_registration.payment_transaction

            global_user = EbookRegistration.objects.filter(
                Q(phone=phone) | Q(email__iexact=email)
            ).order_by("-id").first()

            resolved_name = (
                existing_registration.name
                or (global_user.name if global_user else None)
                or name
            )
            resolved_email = (
                existing_registration.email
                or (global_user.email if global_user else None)
                or email
            )
            resolved_phone = (
                existing_registration.phone
                or (global_user.phone if global_user else None)
                or phone
            )

            existing_registration.name = resolved_name
            existing_registration.email = resolved_email
            existing_registration.phone = resolved_phone
            existing_registration.save()

            if not txn or not txn.order_id:
                return self._create_payment(request, ebook, existing_registration)

            amount = int(float(txn.amount) * 100)
            gateway = PaymentGateway.objects.filter(gatway_name__icontains="razorpay").first()

            return Response({
                "success": True,
                "order_id": txn.order_id,
                "recepit": txn.transaction_id,
                "key": gateway.public_key if gateway else None,
                "amount": amount,
                "currency": txn.currency if txn else "INR",
                "registration_id": existing_registration.id,
                "is_existing": True,
                "name": resolved_name or "",
                "email": resolved_email or "",
                "phone": resolved_phone or "",
                "ebook_title": ebook.title,
                "ebook_slug": ebook.slug,
                "created_at": ebook.created_at
            })

        q_user = Q()
        if email:
            q_user |= Q(email__iexact=email)
        if phone:
            q_user |= Q(phone=phone)

        existing_user_reg = EbookRegistration.objects.filter(q_user).exclude(
            password__isnull=True
        ).exclude(password="").order_by("-id").first()

        if not existing_user_reg:
            existing_user_reg = EbookRegistration.objects.filter(q_user).order_by("-id").first()

        raw_password_for_email = None

        if existing_user_reg:
            user_password = existing_user_reg.password
            name = name or existing_user_reg.name
            email = email or existing_user_reg.email
            phone = phone or existing_user_reg.phone
            is_first_time = False
        else:
            raw_password_for_email = generate_secure_password(12)
            user_password = make_password(raw_password_for_email)
            is_first_time = True

        registration = EbookRegistration.objects.create(
            ebook=ebook,
            name=name,
            email=email,
            phone=phone,
            password=user_password,
            is_paid=False
        )

        if raw_password_for_email:
            cache.set(f"ebook_raw_pwd_{registration.id}", raw_password_for_email, timeout=3600)

        if not ebook.is_paid:
            try:
                logger.info(f"📧 Sending email for registration: {registration.email or registration.phone}")
                send_ebook_registration_email(registration, password=raw_password_for_email)
            except Exception as e:
                logger.error(f"EMAIL ERROR: {str(e)}")

            serializer = EbookRegistrationSerializer(registration, context={"request": request, "ebook": ebook})
            return Response({
                "success": True,
                "message": "Registered successfully",
                "data": serializer.data,
                "is_first_time_user": is_first_time
            })

        return self._create_payment(request, ebook, registration, is_new_user=is_first_time)

    @classmethod
    def update_registration_after_payment(cls, txn):
        meta = txn.metadata or {}
        registration_id = meta.get("registration_id")

        if not registration_id:
            logger.error("No registration_id found in transaction metadata")
            return None

        try:
            registration = EbookRegistration.objects.filter(id=int(registration_id)).first()
        except (ValueError, TypeError):
            logger.error(f"Invalid registration_id: {registration_id}")
            return None

        if not registration:
            logger.error(f"EbookRegistration not found for ID: {registration_id}")
            return None

        registration.is_paid = True
        registration.payment_transaction = txn
        registration.save()

        raw_password = cache.get(f"ebook_raw_pwd_{registration.id}")
        if raw_password:
            cache.delete(f"ebook_raw_pwd_{registration.id}")

        try:
            logger.info(f"📧 Sending email after payment confirmation to: {registration.email or registration.phone}")
            send_ebook_registration_email(registration, password=raw_password)
        except Exception as e:
            logger.error(f"EMAIL ERROR: {str(e)}")

        return registration

    @classmethod
    def create_registration_from_transaction(cls, txn):
        return cls.update_registration_after_payment(txn)

    def list(self, request, slug=None):
        if not request.user.is_authenticated:
            return Response(
                {"success": False, "message": "Authentication required"},
                status=status.HTTP_403_FORBIDDEN
            )

        qs = (
            EbookRegistration.objects
            .filter(ebook__slug=slug)
            .select_related('ebook', 'payment_transaction')
            .order_by('-registered_at')
        )

        serializer = EbookRegistrationSerializer(qs, many=True)
        return Response({
            "success": True,
            "data": serializer.data
        })

    @action(detail=False, methods=["get"], url_path="all-transactions")
    def all_transactions(self, request):
        queryset = PaymentTransaction.objects.select_related(
            "ebookregistration", "ebookregistration__ebook"
        ).order_by("-id")

        serializer = PaymentTransactionListSerializer(queryset, many=True)
        return Response({
            "success": True,
            "count": queryset.count(),
            "data": serializer.data
        })

    @action(detail=False, methods=["get"], url_path="user-history")
    def user_transaction_history(self, request):
        # 1. Sanitize & Normalize Inputs (Prevents subtle bypasses via extra spaces)
        email = request.query_params.get("email", "").strip()
        phone = request.query_params.get("phone", "").strip()

        if not email and not phone:
            return Response(
                {"success": False, "message": "Email or phone required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Build Registration Filter efficiently
        reg_filter = Q()
        if email:
            reg_filter |= Q(email__iexact=email)
        if phone:
            reg_filter |= Q(phone=phone)

        # Fetch registration IDs directly (Flat list of integers - lightweight memory footprint)
        reg_ids = EbookRegistration.objects.filter(reg_filter).values_list(
            "id", flat=True
        )

        # 3. Build Transaction Filter
        txn_filter = Q()
        if reg_ids:
            txn_filter |= Q(ebookregistration_id__in=reg_ids)
        if phone:
            txn_filter |= Q(phone=phone) | Q(metadata__phone=phone)
        if email:
            txn_filter |= Q(metadata__email__iexact=email)

        # 4. Optimized Query Execution ($O(N)$ DB operation using native values parsing)
        # Fetches exact fields including transaction_id and payment_mode
        transactions = (
            PaymentTransaction.objects.filter(txn_filter)
            .order_by("-id")
            .distinct()
            .values(
                "id",
                "amount",
                "payment_status",
                "transaction_id",
                "payment_mode",
                "metadata",
                "created_at",
                "ebookregistration__ebook__title",
                "ebookregistration__ebook__slug",
            )
        )

        # 5. Transform records efficiently
        data = [
            {
                "id": txn["id"],
                "amount": txn["amount"],
                "status": txn["payment_status"],
                "transaction_id": txn["transaction_id"],
                "payment_mode": txn["payment_mode"],
                "phone": txn["metadata"].get("phone") if txn["metadata"] else None,
                "email": txn["metadata"].get("email") if txn["metadata"] else None,
                "created_at": txn["created_at"],
                "ebook_title": txn["ebookregistration__ebook__title"],
                "ebook_slug": txn["ebookregistration__ebook__slug"],
            }
            for txn in transactions
        ]

        return Response({"success": True, "count": len(data), "data": data})


# ─────────────────────────────────────────────────────────────────────────────
# 7. Ebook User ViewSet
# ─────────────────────────────────────────────────────────────────────────────
class EbookUserViewSet(viewsets.ViewSet):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def list(self, request, slug=None, pk=None):
        if not pk or str(pk) == "undefined":
            return Response(
                {"success": False, "message": "Invalid student id"},
                status=status.HTTP_400_BAD_REQUEST
            )

        qs = (
            EbookRegistration.objects
            .filter(id=pk)
            .select_related('ebook', 'payment_transaction')
            .order_by('-registered_at')
        )

        serializer = EbookRegistrationSerializer(qs, many=True)
        return Response({
            "success": True,
            "data": serializer.data
        })

    def partial_update(self, request, slug=None, pk=None):
        registration = EbookRegistration.objects.filter(id=pk).first()
        if not registration:
            return Response({"message": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        password = request.data.get("password")
        if password:
            # OWASP A02: Cryptographic Failures - Hash password before saving
            registration.password = make_password(password)
            registration.save()

        qs = (
            EbookRegistration.objects
            .filter(id=pk)
            .select_related('ebook', 'payment_transaction')
            .order_by('-registered_at')
        )
        serializer = EbookRegistrationSerializer(qs, many=True)

        return Response({
            "success": True,
            "data": serializer.data,
            "message": "Password updated successfully"
        })


# ─────────────────────────────────────────────────────────────────────────────
# 8. Reviews Views
# ─────────────────────────────────────────────────────────────────────────────
# @method_decorator(csrf_exempt, name='dispatch')
class UnsafeSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return  # Bypasses CSRF validation for API requests


@method_decorator(csrf_exempt, name='dispatch')
class ReviewListCreateView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, JSONParser]

    def get(self, request, slug=None):
        slug_param = slug or request.query_params.get("slug", None)
        reviews = Reviews.objects.filter(is_approved=True)

        if slug_param:
            reviews = reviews.filter(registration__ebook__slug=slug_param)

        serializer = ReviewSerializer(reviews, many=True)
        return Response({
            "status": True,
            "reviews_count": reviews.count(),
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request, slug=None):
        serializer = ReviewSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "status": True,
                "message": "Review created successfully",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)

        return Response({
            "status": False,
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name='dispatch')
class ReviewDetailView(APIView):
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_object(self, pk):
        try:
            return Reviews.objects.get(pk=pk)
        except Reviews.DoesNotExist:
            return None

    def get(self, request, pk):
        review = self.get_object(pk)
        if not review:
            return Response({
                "status": False, 
                "message": "Review not found"
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = ReviewSerializer(review)
        return Response({
            "status": True, 
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    def put(self, request, pk):
        review = self.get_object(pk)
        if not review:
            return Response({
                "status": False, 
                "message": "Review not found"
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = ReviewSerializer(review, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "status": True, 
                "data": serializer.data
            }, status=status.HTTP_200_OK)

        return Response({
            "status": False, 
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        review = self.get_object(pk)
        if not review:
            return Response({
                "status": False, 
                "message": "Review not found"
            }, status=status.HTTP_404_NOT_FOUND)

        review.delete()
        return Response({
            "status": True, 
            "message": "Review deleted successfully"
        }, status=status.HTTP_200_OK)

        
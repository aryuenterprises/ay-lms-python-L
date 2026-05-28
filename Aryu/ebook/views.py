from rest_framework import viewsets, status,permissions
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.http import HttpResponse, JsonResponse
from payments.models import PaymentTransaction,PaymentGateway
from django.db.models import  Prefetch
from django.db.models import Q
import razorpay
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from .ebook_emails import send_ebook_registration_email
from rest_framework.decorators import action
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import IsAuthenticated
from aryuapp.auth import CustomJWTAuthentication
# from django.db.models import Avg
from .models import *
from .serializers import *
from .whatsapp import *
import json
import uuid
from django.db import transaction as db_transaction
from rest_framework.decorators import action
from django.views.decorators.csrf import csrf_exempt
import hmac
import hashlib
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import api_view, permission_classes


class EbookViewSet(viewsets.ModelViewSet):
    queryset = Ebook.objects.all()
    serializer_class = EbookSerializer
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    lookup_field = "slug"

    # ─────────────────────────────────────────
    # HELPER: extract tags from request
    # ─────────────────────────────────────────
    def extract_tags(self, request):
        tags = request.data.getlist("tags")

        # If sent as a single JSON string e.g. '["python","django"]'
        if len(tags) == 1:
            try:
                parsed = json.loads(tags[0])
                if isinstance(parsed, list):
                    tags = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        return tags

    # ─────────────────────────────────────────
    # CREATE
    # ─────────────────────────────────────────
    def create(self, request, *args, **kwargs):
        print("REQUEST DATA:", request.data)

        tags = self.extract_tags(request)

        data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
        data["tags"] = tags

        serializer = self.get_serializer(
            data=data,
            context={'request': request}
        )

        if not serializer.is_valid():
            print("ERRORS:", serializer.errors)
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

    # ─────────────────────────────────────────
    # UPDATE
    # ─────────────────────────────────────────
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
            print("ERRORS:", serializer.errors)
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

    # ─────────────────────────────────────────
    # RETRIEVE (single ebook by slug)
    # ─────────────────────────────────────────
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, context={'request': request})
        return Response({
            "status": True,
            "message": "Ebook retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    # ─────────────────────────────────────────
    # LIST (all ebooks)
    # ─────────────────────────────────────────
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

    # ─────────────────────────────────────────
    # DESTROY (delete ebook)
    # ─────────────────────────────────────────
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        # Also clean up nested related objects before deleting
        instance.seo.all().delete()
        instance.tools.all().delete()
        instance.faqs.all().delete()

        instance.delete()

        return Response({
            "status": True,
            "message": "Ebook deleted successfully"
        }, status=status.HTTP_200_OK)
class EbookPublicListAPIView(viewsets.ModelViewSet):
    queryset = Ebook.objects.filter(is_deleted=False)
    serializer_class = EbookDetailSerializer 
    
class PublicEbookViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    queryset = Ebook.objects.filter(is_deleted=False, )
    serializer_class = PublicEbookListSerializer

    permission_classes = []
    authentication_classes = []

    lookup_field = "slug"   # or "slug" or "id"

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
VERIFY_TOKEN = "akzworld" 
def whatsapp_webhook(request):

    # =================================
    # META VERIFICATION (GET)
    # =================================
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            return HttpResponse(challenge)

        return HttpResponse("Invalid token", status=403)


    # =================================
    # EVENTS (POST)
    # =================================
    payload = json.loads(request.body.decode("utf-8"))

    print("===== WHATSAPP WEBHOOK RECEIVED =====")
    print(json.dumps(payload, indent=2))
    print("===================================")

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # =================================
            # A) DELIVERY STATUS (IMPORTANT)
            # =================================
            for status in value.get("statuses", []):
                print(
                    "STATUS:",
                    status.get("status"),           # sent/delivered/read/failed
                    "TIME:",
                    status.get("timestamp"),
                    "PHONE:",
                    status.get("recipient_id"),
                    "MESSAGE_ID:",
                    status.get("id")
                )

            # =================================
            # B) USER MESSAGES (buttons etc.)
            # =================================
            for message in value.get("messages", []):

                phone = message["from"]

                if message["type"] == "button":
                    button_text = message["button"]["text"].strip().lower()

                    registration = EbookRegistration.objects.filter(
                        phone=phone[-10:]
                    ).last()

                    if not registration:
                        continue

                    if button_text in ["remaind me", "remind me"]:
                        registration.wants_reminder = True
                        registration.save()

                        send_ebook_reminder.delay(
                            registration.id,
                            time_left="15 mins"
                        )

                        print(f"Reminder opted by {phone}")

    return JsonResponse({"status": "ok"})

@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def razorpay_webhook(request):
    payload = request.body
    received_signature = request.headers.get("X-Razorpay-Signature")

    if not received_signature:
        return HttpResponse(status=400)

    gateway = PaymentGateway.objects.filter(
        gatway_name__icontains="razorpay"
    ).first()

    expected_signature = hmac.new(
        gateway.webhook_secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, received_signature):
        return HttpResponse(status=400)

    data = request.data
    event = data.get("event")

    if event == "payment.captured":
        entity = data["payload"]["payment"]["entity"]
        order_id = entity.get("order_id")

        with db_transaction.atomic():
            txn = PaymentTransaction.objects.select_for_update().filter(
                order_id=order_id,
                payment_status="pending"
            ).first()

            if not txn:
                return HttpResponse(status=200)

            txn.payment_status = "done"
            txn.transaction_id = entity["id"]
            txn.save()

            EbookRegistrationViewSet.create_registration_from_transaction(txn)

    elif event == "payment.failed":
        entity = data["payload"]["payment"]["entity"]
        order_id = entity.get("order_id")

        PaymentTransaction.objects.filter(
            order_id=order_id
        ).update(payment_status="failed")

    return HttpResponse(status=200)

class RazorpayPaymentViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]
    

    def _get_client(self):
        gateway = PaymentGateway.objects.filter(
            gatway_name__icontains="razorpay"
        ).first()

        if not gateway:
            return None, None

        client = razorpay.Client(
            auth=(gateway.public_key, gateway.secret_key)
        )
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
                status=400
            )

        client, gateway = self._get_client()
        if not client:
            return Response(
                {"success": False, "message": "Razorpay not configured"},
                status=400
            )

        # ✅ Always fetch correct amount
        ebook = get_object_or_404(Ebook, id=ebook_id)
        amount = ebook.price

        # ✅ Fetch registration
        registration = None
        if registration_id:
            registration = EbookRegistration.objects.filter(id=registration_id).first()

        order = client.order.create({
            "amount": int(float(amount) * 100),
            "receipt": transaction_id,
            "currency": "INR",
            "payment_capture": 1,
            "notes": {
                "ebook_id": ebook_id,
                "registration_id": registration_id,
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
            transaction_id = transaction_id,
            phone=phone,
            metadata={
                "ebook_id": ebook_id,
                "registration_id": registration_id,
                "name": name,
                "email": email,
                "phone": phone,
            }
        )

        # ✅ Link txn to registration
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
            "created_at":ebook.created_at
        })
    
    @csrf_exempt
    @action(detail=False, methods=['post'], url_path="verify")
    def verify_payment(self, request):
        payment_id = request.data.get("razorpay_payment_id")
        order_id = request.data.get("razorpay_order_id")
        signature = request.data.get("razorpay_signature")

        if not all([payment_id, order_id, signature]):
            return Response(
                {"success": False, "message": "Missing fields"},
                status=400
            )

        gateway = PaymentGateway.objects.filter(
            gatway_name__icontains="razorpay"
        ).first()

        try:
            razorpay_client = razorpay.Client(
                auth=(gateway.public_key, gateway.secret_key)
            )

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
                status=400
            )

        return Response({"success": True}) 
     
class EbookRegistrationViewSet(viewsets.ViewSet):

    permission_classes = [permissions.AllowAny]
    
    
    def _create_payment(self, request, ebook, existing_registration=None):

        import razorpay
        from django.conf import settings
        import uuid

        transaction_id = f"TXN_{uuid.uuid4().hex[:12].upper()}"

        registration = existing_registration

        if not registration:
            registration = EbookRegistration.objects.create(
                ebook=ebook,
                name=request.data.get("name"),
                email=request.data.get("email"),
                phone=request.data.get("phone"),
            )
            created = True
        else:
            created = False

        registration.name = request.data.get("name") or registration.name
        registration.phone = request.data.get("phone") or registration.phone
        registration.save()

        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )

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
            }
        )
        gateway = PaymentGateway.objects.filter(
            gatway_name__icontains="razorpay"
        ).first()

        return Response({
        "success": True,
        "order_id": order["id"],
        "transaction_id": transaction_id,
        "key": gateway.public_key if gateway else settings.RAZORPAY_KEY_ID,
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
    def _is_first_time_user(self, email, phone, current_registration_id=None):
        """
        Check if this is the user's first registration across ALL ebooks
        """
        q_filter = Q()
        if email:
            q_filter |= Q(email=email)
        if phone:
            q_filter |= Q(phone=phone)
        
        # Count previous registrations (excluding current one if provided)
        query = EbookRegistration.objects.filter(q_filter)
        if current_registration_id:
            query = query.exclude(id=current_registration_id)
        
        previous_count = query.count()
        
        # If no previous registrations, this is a first-time user
        return previous_count == 0
         
    def create(self, request, slug=None):
        transaction_id = f"TXN_{uuid.uuid4().hex[:12].upper()}"
        ebook = get_object_or_404(Ebook, slug=slug)

        email = request.data.get("email")
        phone = request.data.get("phone")

        # ✅ Validate input
        if not email and not phone:
            return Response(
                {"message": "Email or Phone is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ===============================
        # 1. CHECK EXISTING REGISTRATION FOR THIS EBOOK
        # ===============================
        q_filter = Q()
        if email:
            q_filter |= Q(email=email)
        if phone:
            q_filter |= Q(phone=phone)
        
        # Check if user already registered for THIS specific ebook
        existing_registration = EbookRegistration.objects.filter(
            Q(phone=phone) | Q(email=email)
        ).filter(q_filter).first()

        if existing_registration:
            # User already registered for THIS ebook

            # FREE EBOOK
            if not ebook.is_paid:
                return Response(
                    {"message": "Already registered for this ebook"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # ALREADY PAID
            if existing_registration.is_paid:
                return Response(
                    {"message": "Already paid for this ebook"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 🔁 RESUME PAYMENT
            txn = existing_registration.payment_transaction

            # ✅ Get global user data
            global_user = EbookRegistration.objects.filter(
                Q(phone=phone) | Q(email=email)
            ).order_by("-id").first()
                
            # existing_user = EbookRegistration.objects.filter(
            #     global_user
            # ).exclude(id=existing_registration.id).order_by("-id").first()
            
            # ✅ Resolve values
            resolved_name = (
                existing_registration.name
                or (global_user.name if global_user else None)
                or request.data.get("name")
            )

            resolved_email = (
                existing_registration.email
                or (global_user.email if global_user else None)
                or request.data.get("email")
            )

            resolved_phone = (
                existing_registration.phone
                or (global_user.phone if global_user else None)
                or request.data.get("phone")
            )
            
            # ✅ Update DB if missing
            existing_registration.name = resolved_name
            existing_registration.email = resolved_email
            existing_registration.phone = resolved_phone
            existing_registration.save()

                    

            # ✅ FIX: ensure order exists
            if not txn or not txn.order_id:
                return self._create_payment(request, ebook, existing_registration)

            amount = int(float(txn.amount) * 100)

            gateway = PaymentGateway.objects.filter(
                gatway_name__icontains="razorpay"
            ).first()

            return Response({
                "success": True,
                "order_id": txn.order_id,
                "recepit": transaction_id,
                "key": gateway.public_key if gateway else None,
                "amount": amount,
                "currency": txn.currency if txn else "INR",
                "registration_id": existing_registration.id,
                "is_existing": True,

                # ✅ always filled now
                "name": resolved_name or "",
                "email": resolved_email or "",
                "phone": resolved_phone or "",

                "ebook_title": ebook.title,
                "ebook_slug": ebook.slug,
                "created_at": ebook.created_at
            })

        # ===============================
        # 2. CREATE NEW REGISTRATION
        # ===============================
        serializer = EbookRegistrationSerializer(
            data=request.data,
            context={
                "request": request,
                "ebook": ebook
            }
        )
        serializer.is_valid(raise_exception=True)

        registration = serializer.save(ebook=ebook)
        
        if request.data.get("name"):
            registration.name = request.data.get("name")

        if request.data.get("email"):
            registration.email = request.data.get("email")

        if request.data.get("phone"):
            registration.phone = request.data.get("phone")

        registration.save()

        # ✅ CHECK IF FIRST-TIME USER (across all ebooks)
        is_first_time = self._is_first_time_user(
            email=registration.email,
            phone=registration.phone,
            current_registration_id=registration.id
        )

        # ===============================
        # 3. FREE EBOOK
        # ===============================
        if not ebook.is_paid:
            # ✅ SEND EMAIL ONLY TO FIRST-TIME USERS
            if is_first_time:
                try:
                    print(f"📧 Sending email to FIRST-TIME user: {registration.email or registration.phone}")
                    send_ebook_registration_email(registration)
                except Exception as e:
                    print("EMAIL ERROR:", str(e))
            else:
                print(f"⏭️ Skipping email - returning user: {registration.email or registration.phone}")

            return Response({
                "success": True,
                "message": "Registered successfully",
                "data": serializer.data,
                "is_first_time_user": is_first_time
            })

        # ===============================
        # 4. CREATE PAYMENT TRANSACTION (PAID EBOOK)
        # ===============================
        txn = PaymentTransaction.objects.create(
            amount=ebook.price,
            currency="INR",
            payment_status="pending",
            phone=registration.phone if registration.phone else registration.email,
            metadata={
                "ebook_id": str(ebook.id),
                "registration_id": str(registration.id),
                "email": registration.email,
                "phone": registration.phone,
                "name":registration.name,
                "is_first_time_user": is_first_time ,
                
            }
        )

        registration.payment_transaction = txn
        registration.save()

        return self._create_payment(request, ebook, registration)


    # ============================================
    # UPDATE REGISTRATION AFTER SUCCESSFUL PAYMENT
    # ============================================
    @classmethod
    def update_registration_after_payment(cls, txn):
        meta = txn.metadata
        registration_id = meta.get("registration_id")

        registration = EbookRegistration.objects.filter(
            id=int(registration_id)
        ).first()

        if not registration:
            return None

        # ✅ Mark as paid
        registration.is_paid = True
        registration.payment_transaction = txn
        registration.save()

        # ✅ SEND EMAIL ONLY TO FIRST-TIME USERS
        is_first_time = meta.get("is_first_time_user", False)
        
        if is_first_time:
            try:
                print(f"📧 Sending email to FIRST-TIME user (after payment): {registration.email or registration.phone}")
                send_ebook_registration_email(registration)
            except Exception as e:
                print("EMAIL ERROR:", str(e))
        else:
            print(f"⏭️ Skipping email - returning user (after payment): {registration.email or registration.phone}")

        return registration
    
    # ============================================
    # LEGACY METHOD (Keep for backward compatibility)
    # ============================================
    @classmethod
    def create_registration_from_transaction(cls, txn):
        """Legacy method - redirects to update method"""
        return cls.update_registration_after_payment(txn)

    # ============================================
    # LIST REGISTRATIONS
    # ============================================
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
    # @action(detail=False, methods=["get"], url_path="history")
    # def transaction_history(self, request):
    #     queryset = PaymentTransaction.objects.filter(
    #         metadata__isnull=False
    #     ).order_by("-id")

    #     serializer = PaymentTransactionListSerializer(queryset, many=True)

    #     return Response({
    #         "success": True,
    #         "data": serializer.data
    #     })    

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
    
    # @action(detail=True, methods=["get"], url_path="transaction-history")
    # def transaction_history(self, request, pk=None):

    #     # ✅ Step 1: get registration
    #     try:
    #         registration = EbookRegistration.objects.get(pk=pk)
    #     except EbookRegistration.DoesNotExist:
    #         return Response(
    #             {"success": False, "message": "Registration not found"},
    #             status=404
    #         )

    #     email = registration.email
    #     phone = registration.phone

    #     # ✅ Step 2: validate
    #     if not email and not phone:
    #         return Response(
    #             {"success": False, "message": "No email or phone found for this user"},
    #             status=400
    #         )

    #     # ✅ Step 3: find all registrations of this user
    #     user_registrations = EbookRegistration.objects.filter(
    #         Q(email__iexact=email) | Q(phone=phone)
    #     )

    #     # ✅ Step 4: get all transactions
    #     transactions = PaymentTransaction.objects.filter(
    #         Q(ebookregistration__in=user_registrations) |
    #         Q(email__iexact=email) |
    #         Q(phone=phone)
    #     ).order_by("-id").distinct()

    #     # ✅ Step 5: serialize
    #     serializer = PaymentTransactionListSerializer(
    #         transactions,
    #         many=True,
    #         context={"request": request}
    #     )

    #     return Response({
    #         "success": True,
    #         "registration_id": registration.id,
    #         "user_email": email,
    #         "user_phone": phone,
    #         "count": transactions.count(),
    #         "data": serializer.data
    #     })   
    
    @action(detail=False, methods=["get"], url_path="user-history")
    def user_transaction_history(self, request):

        email = request.query_params.get("email")
        phone = request.query_params.get("phone")

        if not email and not phone:
            return Response(
                {"success": False, "message": "Email or phone required"},
                status=400
            )

       
        reg_filter = Q()
        if email:
            reg_filter |= Q(email__iexact=email)
        if phone:
            reg_filter |= Q(phone=phone)

        registrations = EbookRegistration.objects.filter(reg_filter)

       
        txn_filter = Q()

        # 🔹 1. linked transactions
        if registrations.exists():
            txn_filter |= Q(ebookregistration__in=registrations)

        # 🔹 2. fallback (OLD DATA)
        if phone:
            txn_filter |= Q(phone=phone)
            txn_filter |= Q(metadata__phone=phone)

        if email:
            txn_filter |= Q(metadata__email__iexact=email)

        transactions = PaymentTransaction.objects.filter(txn_filter)\
            .select_related("ebookregistration", "ebookregistration__ebook")\
            .order_by("-id")\
            .distinct()

        
        data = []
        for txn in transactions:
            ebook = None

            if txn.ebookregistration:
                ebook = txn.ebookregistration.ebook

            data.append({
                "id": txn.id,
                "amount": txn.amount,
                "status": txn.payment_status,
                "phone": txn.metadata.get("phone") if txn.metadata else None,
                "email": txn.metadata.get("email") if txn.metadata else None,
                "created_at": txn.created_at,

                "ebook_title": ebook.title if ebook else None,
                "ebook_slug": ebook.slug if ebook else None,
            })

        return Response({
            "success": True,
            "count": len(data),
            "data": data
        })
    
class EbookUserViewSet(viewsets.ViewSet):
    # ============================================
    # LIST REGISTRATIONS for each user
    # ============================================
    def list(self, request, slug=None, pk=None):
        if not request.user.is_authenticated:
            return Response(
                {"success": False, "message": "Authentication required"},
                status=status.HTTP_403_FORBIDDEN
            )

        # ❗ prevent crash if pk is undefined
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

        # ✅ filter by student id
        # qs = qs.filter(id=pk)

        serializer = EbookRegistrationSerializer(qs, many=True)

        return Response({
            "success": True,
            "data": serializer.data
        })
    def partial_update(self, request, slug=None, pk=None):
        registration = EbookRegistration.objects.filter(
            id=pk,
            
        ).first()

        if not registration:
            return Response({"message": "Not found"}, status=404)

        password = request.data.get("password")

        if password:
            registration.password = password  # ⚠️ hash if needed
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
                "data":serializer.data,
                "message": "Password updated"
            })
    
class ReviewListCreateView(APIView):

    def get(self, request):
        slug = request.query_params.get("slug",None)

        reviews = Reviews.objects.filter(is_approved=True)

        if slug:
            reviews = reviews.filter(registration__ebook__slug=slug)

        # avg_rating = reviews.aggregate(avg=Avg('rating'))['avg']

        serializer = ReviewSerializer(reviews, many=True)

        return Response({
            "status": True,
            # "average_rating": avg_rating,
            "data": serializer.data
        })

    def post(self, request):
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
    
class ReviewDetailView(APIView):

    def get_object(self, pk):
        try:
            return Reviews.objects.get(pk=pk)
        except Reviews.DoesNotExist:
            return None

    def get(self, request, pk):
        review = self.get_object(pk)
        if not review:
            return Response({"status": False, "message": "Not found"}, status=404)

        serializer = ReviewSerializer(review)
        return Response({"status": True, "data": serializer.data})

    def put(self, request, pk):
        review = self.get_object(pk)
        if not review:
            return Response({"status": False, "message": "Not found"}, status=404)

        serializer = ReviewSerializer(review, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": True, "data": serializer.data})

        return Response({"status": False, "errors": serializer.errors}, status=400)

    def delete(self, request, pk):
        review = self.get_object(pk)
        if not review:
            return Response({"status": False, "message": "Not found"}, status=404)

        review.delete()
        return Response({"status": True, "message": "Deleted successfully"})
    
class EbookReviewBySlugView(APIView):

    def get(self, request, slug):
        ebook = get_object_or_404(Ebook, slug=slug)

        reviews = Reviews.objects.filter(
            registration__ebook=ebook
        ).order_by('-created_at')

        serializer = ReviewSerializer(reviews, many=True)

        return Response({
            "status": True,
            "ebook": ebook.title,
            "reviews_count": reviews.count(),
            "data": serializer.data
        })
    

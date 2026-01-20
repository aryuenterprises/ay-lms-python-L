from datetime import datetime
import json
from django.shortcuts import render
from django.db import transaction as db_transaction
from requests import request
import requests
from rest_framework import viewsets, permissions, status, mixins
from .services.whatsapp import send_webinar_reminder, send_webinar_welcome_whatsapp
from aryuapp.models import PaymentGateway, PaymentTransaction
import razorpay
from rest_framework.response import Response
import json
from django.http import HttpResponse, JsonResponse
from .services.webinar_emails import send_webinar_registration_email
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from django.views.decorators.csrf import csrf_exempt
import hmac
import hashlib
from django.conf import settings
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from aryuapp.auth import CustomJWTAuthentication
from .models import *
from .serializers import *


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

    # PAYMENT SUCCESS
    if event == "payment.captured":
        entity = data["payload"]["payment"]["entity"]
        payment_id = entity["id"]
        order_id = entity.get("order_id")

        with db_transaction.atomic():
            txn = PaymentTransaction.objects.select_for_update().filter(
                order_id=order_id,
                payment_status="pending"
            ).first()

            if not txn:
                return HttpResponse(status=200)  # idempotent

            txn.payment_status = "done"
            txn.transaction_id = payment_id
            txn.save()

            meta = txn.metadata
            webinar_id = meta.get("webinar_id")

            webinar = Webinar.objects.get(uuid=webinar_id)

            # CREATE REGISTRATION HERE
            registration, created = WebinarRegistration.objects.get_or_create(
                webinar=webinar,
                phone=meta.get("phone"),
                defaults={
                    "name": meta.get("name"),
                    "email": meta.get("email"),
                    "is_paid": True,
                    "payment_transaction": txn
                }
            )

            if created:
                send_webinar_registration_email(registration)
                try:
                    send_webinar_welcome_whatsapp(registration)
                except Exception as e:
                    print("WhatsApp error:", e) 

    # PAYMENT FAILED
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
        amount = request.data.get("amount")
        webinar_id = request.data.get("webinar_id")
        name = request.data.get("name")
        email = request.data.get("email")
        phone = request.data.get("phone")

        if not all([amount, webinar_id, phone]):
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

        order = client.order.create({
            "amount": int(float(amount) * 100),
            "currency": "INR",
            "payment_capture": 1,
            "notes": {
                "webinar_id": webinar_id,
                "phone": phone,
                "email": email,
                "name": name
            }
        })

        PaymentTransaction.objects.create(
            gateway=gateway,
            amount=amount,
            currency="INR",
            payment_status="pending",
            order_id=order["id"],
            metadata={
                "webinar_id": webinar_id,
                "name": name,
                "email": email,
                "phone": phone,
            },
            description="Webinar payment via Razorpay Checkout",
        )

        return Response({
            "success": True,
            "order_id": order["id"],
            "key": gateway.public_key,
            "amount": int(float(amount) * 100),
            "currency": "INR"
        })

        
    # -------------------------
    # Verify Razorpay Payment
    # -------------------------
    @csrf_exempt
    @action(detail=False, methods=['post'], url_path="verify")
    def verify_payment(self, request):
        payment_id = request.data.get("razorpay_payment_id")
        order_id = request.data.get("razorpay_order_id")
        signature = request.data.get("razorpay_signature")

        if not all([payment_id, order_id, signature]):
            return Response(
                {"success": False, "message": "Missing payment verification fields"},
                status=400
            )

        gateway = PaymentGateway.objects.filter(
            gatway_name__icontains="razorpay"
        ).first()

        if not gateway or not gateway.secret_key:
            return Response(
                {"success": False, "message": "Razorpay secret not configured"},
                status=500
            )

        try:
            razorpay_client = razorpay.Client(
                auth=(gateway.public_key, gateway.secret_key)
            )

            razorpay_client.utility.verify_payment_signature({
                "razorpay_payment_id": payment_id,
                "razorpay_order_id": order_id,
                "razorpay_signature": signature
            })

        except razorpay.errors.SignatureVerificationError:
            return Response(
                {"success": False, "message": "Invalid payment signature"},
                status=400
            )

        # Let webhook handle final status

        return Response({"success": True})


class WebinarViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    serializer_class = WebinarSerializer
    lookup_field = "uuid"
    lookup_url_kwarg = "uuid"

    def get_queryset(self):
        return (
            Webinar.objects
            .prefetch_related(
                "registrations"
            ).filter(is_deleted=False)
            .order_by("-created_at")
        )

    def list(self, request):
        qs = self.get_queryset()
        serializer = WebinarSerializer(qs, many=True)
        return Response(serializer.data)

    def retrieve(self, request, uuid=None):
        queryset = self.get_queryset()
        webinar = get_object_or_404(queryset, uuid=uuid)
        serializer = WebinarSerializer(webinar)
        return Response(serializer.data)

    def create(self, request):
        serializer = WebinarSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        webinar = serializer.save()
        return Response({
            "status": True,
            "message": "Webinar created successfully",
            'data': WebinarSerializer(webinar).data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, uuid=None):
        webinar = get_object_or_404(Webinar, uuid=uuid)
        serializer = WebinarSerializer(webinar, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"status": True, "message": "Webinar updated successfully", "data": serializer.data})
    
    @action(
        detail=True,
        methods=["post"],        
    )
    def send_certificates(self, request, uuid=None):
        webinar = self.get_object()

        if webinar.status != "COMPLETED":
            return Response(
                {"message": "Webinar must be completed first"},
                status=400
            )

        sent = 0
        for registration in webinar.registrations.select_related(
            "webinarcertificate"
        ):
            if hasattr(registration, "webinarcertificate"):
                send_webinar_certificate_email(
                    registration,
                    registration.webinarcertificate.certificate_file
                )
                sent += 1

        return Response({
            "message": f"Certificates sent to {sent} participants"
        })
    
    def delete(self, request, uuid):
        webinar = get_object_or_404(
            Webinar,
            uuid=uuid,
            is_deleted=False
        )
        webinar.is_deleted = True
        webinar.save(update_fields=["is_deleted", "updated_at"])

        return Response(
            {
                "status": True,
                "message": "Webinar deleted successfully"
            },
            status=status.HTTP_200_OK
        )


class WebinarRegistrationViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    def _create_payment(self, request, webinar):
        data = request.data.copy()

        data["amount"] = float(webinar.price)
        data["webinar_id"] = str(webinar.uuid)

        data["success_url"] = request.data.get(
            "success_url",
            "https://aylms.aryuprojects.com/payment-success"
        )
        data["failure_url"] = request.data.get(
            "failure_url",
            "https://aylms.aryuprojects.com/payment-failed"
        )

        request._full_data = data

        return RazorpayPaymentViewSet().create(request)

    def create(self, request, uuid=None):
        webinar = get_object_or_404(Webinar, uuid=uuid)

        if not webinar.can_register():
            return Response(
                {"message": "Registration closed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        phone = request.data.get("phone")
        if WebinarRegistration.objects.filter(webinar=webinar, phone=phone).exists():
            return Response(
                {"message": "Already registered"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🔹 PAID WEBINAR → INITIATE PAYMENT
        if webinar.is_paid:
            return self._create_payment(request, webinar)

        # 🔹 FREE WEBINAR → DIRECT REGISTER
        data = request.data.copy()
        data["webinar"] = webinar.id
        data["is_paid"] = False

        serializer = WebinarRegistrationSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        registration = serializer.save()

        send_webinar_registration_email(registration)

        try:
            send_webinar_welcome_whatsapp(registration)
        except Exception as e:
            print("WhatsApp error:", e) 

        return Response(serializer.data, status=status.HTTP_201_CREATED)


    def list(self, request, uuid=None):
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_403_FORBIDDEN)

        qs = (
            WebinarRegistration.objects
            .filter(webinar_id=uuid)
            .select_related('lead')
            .order_by('-registered_at')
        )

        serializer = WebinarRegistrationSerializer(qs, many=True)
        return Response(serializer.data)


VERIFY_TOKEN = "akzworld"  # same token you give Meta

@csrf_exempt
def whatsapp_webhook(request):
    # 🔹 STEP 1: Verification (GET)
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            return HttpResponse(challenge)
        return HttpResponse("Invalid token", status=403)

    # 🔹 STEP 2: Receive events (POST)
    if request.method == "POST":
        payload = json.loads(request.body)
        print("WhatsApp Webhook:", payload)  # log or process
        return JsonResponse({"status": "ok"})

@csrf_exempt
def whatsapp_webhook(request):
    payload = json.loads(request.body)

    try:
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError):
        return JsonResponse({"status": "ignored"})

    phone = message["from"]

    if message["type"] == "button":
        button_text = message["button"]["text"]

        registration = WebinarRegistration.objects.filter(
            phone=phone
        ).last()

        if not registration:
            return JsonResponse({"status": "no_registration"})

        if button_text == "Yes, remind me":
            registration.wants_reminder = True
            registration.save()

            send_webinar_reminder(registration)

        return JsonResponse({"status": "ok"})

    return JsonResponse({"status": "ignored"})


def send_webinar_reminder_email(registration):
    webinar = registration.webinar

    subject = f"⏰ Reminder: {webinar.title} starts soon!"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [registration.email]

    background_url = "https://aylms.aryuprojects.com/api/media/email/banner.svg"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0; padding:0; font-family:Arial, Helvetica, sans-serif;">

      <!-- FULL BACKGROUND -->
      <table width="100%" cellpadding="0" cellspacing="0"
        style="background:url('{background_url}') no-repeat center top;
               background-size:cover; padding:70px 0;">

        <tr>
          <td align="right" style="padding-right:10vw;">

            <!-- FLOATING CARD -->
            <table width="440" cellpadding="0" cellspacing="0"
              style="background:#0c0c0c;
                     border-radius:16px;
                     box-shadow:0 0 30px rgba(255,0,0,0.45);
                     overflow:hidden;">

              <!-- BODY -->
              <tr>
                <td style="padding:38px 38px; text-align:center;">

                  <h2 style="margin:0; color:#ffffff; font-size:26px;">
                    Webinar Reminder ⏰
                  </h2>

                  <p style="color:#cccccc; margin-top:12px; font-size:14px;">
                    Your webinar is about to start
                  </p>

                  <!-- WEBINAR TITLE -->
                  <div style="
                    margin-top:22px;
                    background:linear-gradient(135deg, #4a0000, #b30000);
                    padding:16px 22px;
                    border-radius:12px;
                    color:#ffffff;
                    font-size:18px;
                    font-weight:700;
                    box-shadow:0 0 14px rgba(255,0,0,0.6);
                  ">
                    {webinar.title}
                  </div>

                  <!-- DETAILS -->
                  <p style="margin-top:22px; font-size:14px; color:#dddddd; line-height:22px;">
                    📅 <b>Date:</b> {webinar.scheduled_start.strftime('%d %b %Y')}<br>
                    ⏰ <b>Time:</b> {webinar.scheduled_start.strftime('%I:%M %p')}
                  </p>

                  <!-- JOIN BUTTON -->
                  <div style="margin-top:28px;">
                    <a href="{webinar.zoom_link or '#'}"
                       style="
                        display:inline-block;
                        background:linear-gradient(135deg,#b30000,#ff1a1a);
                        color:#ffffff;
                        padding:12px 26px;
                        font-size:15px;
                        font-weight:bold;
                        border-radius:8px;
                        text-decoration:none;
                        box-shadow:0 0 16px rgba(255,0,0,0.7);
                       ">
                      🔗 Join Webinar
                    </a>
                  </div>

                  <p style="margin-top:22px; font-size:13px; color:#aaaaaa;">
                    Please join 5 minutes early for best experience.
                  </p>

                </td>
              </tr>

              <!-- FOOTER -->
              <tr>
                <td style="background:#0c0c0c; padding:15px; text-align:center;
                           font-size:12px; color:#888;">
                  © {datetime.now().year} Aryu Academy. All rights reserved.
                </td>
              </tr>

            </table>

          </td>
        </tr>

      </table>

    </body>
    </html>
    """

    email_msg = EmailMultiAlternatives(
        subject,
        "",
        from_email,
        to
    )
    email_msg.attach_alternative(html_content, "text/html")
    return email_msg.send()

@action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
def send_reminder(self, request, uuid=None):
    webinar = Webinar.objects.get(uuid=uuid)

    for reg in webinar.registrations.all():
        send_webinar_reminder_email(reg)

    return Response({"message": "Webinar reminder emails sent"})

def _create_payment(self, request, webinar):
    razorpay_view = RazorpayPaymentViewSet()

    payment_request = request._request
    payment_request.data = {
        "amount": webinar.price,
        "currency": "INR",
        "success_url": f"https://portal.aryuacademy.com/webinar/payment-success/{webinar.uuid}",
        "failure_url": f"https://portal.aryuacademy.com/webinar/payment-failed/{webinar.uuid}",
    }

    return razorpay_view.create(payment_request)

def send_webinar_certificate_email(registration, certificate_file):
    webinar = registration.webinar

    subject = f"🎓 Certificate of Completion – {webinar.title}"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [registration.email]

    background_url = "https://aylms.aryuprojects.com/api/media/email/banner.svg"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0; padding:0; font-family:Arial, Helvetica, sans-serif;">

      <!-- FULL BACKGROUND -->
      <table width="100%" cellpadding="0" cellspacing="0"
        style="background:url('{background_url}') no-repeat center top;
               background-size:cover; padding:70px 0;">

        <tr>
          <td align="right" style="padding-right:10vw;">

            <!-- FLOATING CERTIFICATE CARD -->
            <table width="460" cellpadding="0" cellspacing="0"
              style="background:#0c0c0c;
                     border-radius:18px;
                     box-shadow:0 0 35px rgba(255,0,0,0.45);
                     overflow:hidden;">

              <!-- BODY -->
              <tr>
                <td style="padding:40px 40px; text-align:center;">

                  <h2 style="margin:0; color:#ffffff; font-size:26px;">
                    🎉 Thank You for Joining!
                  </h2>

                  <p style="color:#cccccc; margin-top:14px; font-size:14px;">
                    We’re glad you attended our webinar
                  </p>

                  <!-- WEBINAR TITLE -->
                  <div style="
                    margin-top:24px;
                    background:linear-gradient(135deg, #4a0000, #b30000);
                    padding:18px 24px;
                    border-radius:14px;
                    color:#ffffff;
                    font-size:18px;
                    font-weight:700;
                    box-shadow:0 0 18px rgba(255,0,0,0.65);
                  ">
                    {webinar.title}
                  </div>

                  <!-- MESSAGE -->
                  <p style="margin-top:24px; font-size:14px; color:#dddddd; line-height:24px;">
                    Hi <b>{registration.name or "Participant"}</b>,<br><br>
                    Thank you for actively participating in our webinar.<br>
                    We appreciate the time and effort you invested in learning with us.
                  </p>

                  <p style="margin-top:16px; font-size:14px; color:#bbbbbb;">
                    📄 Your <b>Certificate of Completion</b> is attached to this email as a PDF.
                  </p>

                  <p style="margin-top:20px; font-size:13px; color:#aaaaaa;">
                    Keep learning. Keep growing. 🚀
                  </p>

                </td>
              </tr>

              <!-- FOOTER -->
              <tr>
                <td style="background:#0c0c0c; padding:16px; text-align:center;
                           font-size:12px; color:#888;">
                  © {datetime.now().year} Aryu Academy. All rights reserved.
                </td>
              </tr>

            </table>

          </td>
        </tr>

      </table>

    </body>
    </html>
    """

    email_msg = EmailMultiAlternatives(
        subject,
        "Thank you for joining the webinar. Your certificate is attached.",
        from_email,
        to
    )

    # Attach HTML
    email_msg.attach_alternative(html_content, "text/html")

    # Attach Certificate PDF
    email_msg.attach_file(certificate_file.path)

    return email_msg.send()


class WebinarSessionViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    def retrieve(self, request, uuid=None):
        webinar = get_object_or_404(Webinar, uuid=uuid)
        session = getattr(webinar, 'session', None)

        if not session:
            return Response({
                "is_live": False,
                "started": False
            })

        serializer = WebinarSessionSerializer(session)
        return Response(serializer.data)
    
class WebinarLifecycleViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, uuid=None):
        webinar = get_object_or_404(Webinar, uuid=uuid)

        if webinar.status in ['LIVE', 'COMPLETED']:
            return Response(
                {"detail": "Cannot cancel live/completed webinar"},
                status=status.HTTP_400_BAD_REQUEST
            )

        webinar.status = 'CANCELLED'
        webinar.is_registration_open = False
        webinar.save()

        return Response({"detail": "Webinar cancelled"})
    

def get_webinar_participants(webinar_id, access_token):
    url = f"https://api.zoom.us/v2/report/webinars/{webinar_id}/participants"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    params = {
        "page_size": 300
    }

    response = requests.get(url, headers=headers, params=params)
    return response.json()["participants"]


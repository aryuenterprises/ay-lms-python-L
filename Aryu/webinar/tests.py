import hmac
import hashlib
import json
import uuid
from django.test import TransactionTestCase, Client
from django.urls import reverse
from django.utils import timezone
from payments.models import PaymentGateway, PaymentTransaction
from webinar.models import Webinar, WebinarRegistration

class WebinarWebhookTestCase(TransactionTestCase):

    def setUp(self):
        PaymentGateway.objects.filter(gatway_name__icontains="razorpay").delete()
        self.secret = "WebinarSecret321"
        self.gateway = PaymentGateway.objects.create(
            gatway_name="razorpay",
            public_key="rzp_test_public",
            secret_key="rzp_test_secret",
            webhook_secret=self.secret,
            is_archived=False
        )
        self.client = Client()
        self.webhook_url = reverse("razorpay-webhook")  # Route defined in webinar/urls.py

        self.webinar = Webinar.objects.create(
            title="Test Webinar",
            price=500.00,
            scheduled_start=timezone.now(),
            is_paid=True
        )

        self.registration = WebinarRegistration.objects.create(
            webinar=self.webinar,
            name="John Doe",
            email="john@example.com",
            phone="9876543210",
            is_paid=False
        )

        self.order_id = "order_webinar_999"
        self.txn = PaymentTransaction.objects.create(
            gateway=self.gateway,
            order_id=self.order_id,
            transaction_id="TXN_WEBINAR_1",
            amount=500.00,
            currency="INR",
            payment_status="pending",
            webinar_registration=self.registration,
            metadata={
                "webinar_id": str(self.webinar.uuid),
                "phone": self.registration.phone
            }
        )

    def test_webhook_missing_signature(self):
        response = self.client.post(
            self.webhook_url,
            data=json.dumps({"event": "payment.captured"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_webhook_invalid_signature(self):
        payload = json.dumps({"event": "payment.captured"}).encode("utf-8")
        response = self.client.post(
            self.webhook_url,
            data=payload,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE="invalid_sig_123"
        )
        self.assertEqual(response.status_code, 400)

    def test_webhook_valid_signature_payment_captured(self):
        payload_dict = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_webinar_pay_id",
                        "order_id": self.order_id
                    }
                }
            }
        }
        raw_payload = json.dumps(payload_dict).encode("utf-8")
        computed_sig = hmac.new(
            self.secret.encode("utf-8"),
            raw_payload,
            hashlib.sha256
        ).hexdigest()

        response = self.client.post(
            self.webhook_url,
            data=raw_payload,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=computed_sig
        )
        self.assertEqual(response.status_code, 200)

        self.txn.refresh_from_db()
        self.assertEqual(self.txn.payment_status, "done")
        self.assertEqual((self.txn.metadata or {}).get("razorpay_payment_id"), "pay_webinar_pay_id")

        self.registration.refresh_from_db()
        self.assertTrue(self.registration.is_paid)

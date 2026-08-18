import hmac
import hashlib
import json
from django.test import TransactionTestCase, Client
from django.urls import reverse
from payments.models import PaymentGateway, PaymentTransaction
from ebook.models import Ebook, EbookRegistration

class EbookWebhookTestCase(TransactionTestCase):

    def setUp(self):
        PaymentGateway.objects.filter(gatway_name__icontains="razorpay").delete()
        self.secret = "EbookSecret456"
        self.gateway = PaymentGateway.objects.create(
            gatway_name="razorpay",
            public_key="rzp_test_ebook_pub",
            secret_key="rzp_test_ebook_sec",
            webhook_secret=self.secret,
            is_archived=False
        )
        self.client = Client()
        self.webhook_url = reverse("ebook-razorpay-webhook")

        self.ebook = Ebook.objects.create(
            title="Test Ebook",
            price=299.00,
            is_paid=True
        )

        self.registration = EbookRegistration.objects.create(
            ebook=self.ebook,
            name="Jane Doe",
            email="jane@example.com",
            phone="9123456789",
            is_paid=False
        )

        self.order_id = "order_ebook_888"
        self.txn = PaymentTransaction.objects.create(
            gateway=self.gateway,
            order_id=self.order_id,
            transaction_id="TXN_EBOOK_1",
            amount=299.00,
            currency="INR",
            payment_status="pending",
            ebookregistration=self.registration,
            metadata={
                "ebook_id": self.ebook.id,
                "registration_id": self.registration.id
            }
        )

    def test_ebook_webhook_missing_signature(self):
        response = self.client.post(
            self.webhook_url,
            data=json.dumps({"event": "payment.captured"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_ebook_webhook_invalid_signature(self):
        payload = json.dumps({"event": "payment.captured"}).encode("utf-8")
        response = self.client.post(
            self.webhook_url,
            data=payload,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE="invalid_sig_xyz"
        )
        self.assertEqual(response.status_code, 400)

    def test_ebook_webhook_valid_signature_payment_captured(self):
        payload_dict = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_ebook_pay_999",
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
        self.assertEqual((self.txn.metadata or {}).get("razorpay_payment_id"), "pay_ebook_pay_999")

        self.registration.refresh_from_db()
        self.assertTrue(self.registration.is_paid)

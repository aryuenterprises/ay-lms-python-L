import hmac
import hashlib
import json
import uuid
from unittest.mock import patch
from django.test import TransactionTestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core.cache import cache
from payments.models import PaymentGateway, PaymentTransaction
from webinar.models import Webinar, WebinarRegistration

class WebinarWebhookTestCase(TransactionTestCase):

    def setUp(self):
        cache.clear()
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


class WebinarRegistrationFlowTestCase(TransactionTestCase):

    def setUp(self):
        cache.clear()
        PaymentGateway.objects.filter(gatway_name__icontains="razorpay").delete()
        self.secret = "WebinarSecretKey777"
        self.gateway = PaymentGateway.objects.create(
            gatway_name="razorpay",
            public_key="rzp_test_public_key_123",
            secret_key="rzp_test_secret_key_456",
            webhook_secret=self.secret,
            is_archived=False
        )
        self.client = Client()
        self.webinar = Webinar.objects.create(
            title="Advanced Python Masterclass",
            slug="advanced-python-masterclass",
            price=999.00,
            scheduled_start=timezone.now(),
            is_paid=True
        )

    @patch("razorpay.Client")
    def test_webinar_registration_single_order_creation(self, mock_rzp):
        mock_client = mock_rzp.return_value
        mock_client.order.create.return_value = {"id": "order_single_rzp_99999"}

        url = reverse("webinar-register", kwargs={"slug": self.webinar.slug})
        payload = {
            "name": "Alice Bob",
            "email": "alice.bob@example.com",
            "phone": "9876500000",
            "profession": "Developer"
        }

        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, 200)

        # Requirement 12 Assertion: Assert client.order.create was called EXACTLY ONCE
        mock_client.order.create.assert_called_once()

        # Requirement 12 Assertion: Assert txn.order_id == response.data["order_id"]
        response_data = response.json()
        self.assertTrue(response_data.get("success"))
        order_id_returned = response_data.get("order_id")
        self.assertEqual(order_id_returned, "order_single_rzp_99999")

        txn = PaymentTransaction.objects.filter(order_id=order_id_returned).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.order_id, order_id_returned)
        self.assertEqual(txn.payment_status, "pending")

        # Verify WebinarRegistration is linked to txn
        registration = WebinarRegistration.objects.get(phone="9876500000", webinar=self.webinar)
        self.assertEqual(registration.payment_transaction, txn)
        self.assertFalse(registration.is_paid)

    @patch("razorpay.Client")
    def test_webinar_payment_webhook_flow_end_to_end(self, mock_rzp):
        mock_client = mock_rzp.return_value
        order_id = "order_end2end_88888"
        mock_client.order.create.return_value = {"id": order_id}

        # 1. Frontend initiates webinar registration
        register_url = reverse("webinar-register", kwargs={"slug": self.webinar.slug})
        resp = self.client.post(register_url, data={
            "name": "Charlie",
            "email": "charlie@example.com",
            "phone": "9998887776"
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["order_id"], order_id)

        # 2. Razorpay webhook fires with matching order_id
        webhook_url = reverse("razorpay-webhook")
        payload_dict = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_charlie_payment_777",
                        "order_id": order_id
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

        webhook_resp = self.client.post(
            webhook_url,
            data=raw_payload,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=computed_sig
        )
        self.assertEqual(webhook_resp.status_code, 200)

        # 3. Assert PaymentTransaction is found and updated
        txn = PaymentTransaction.objects.get(order_id=order_id)
        self.assertEqual(txn.payment_status, "done")
        self.assertEqual((txn.metadata or {}).get("razorpay_payment_id"), "pay_charlie_payment_777")

        # 4. Assert WebinarRegistration becomes paid
        reg = WebinarRegistration.objects.get(phone="9998887776", webinar=self.webinar)
        self.assertTrue(reg.is_paid)

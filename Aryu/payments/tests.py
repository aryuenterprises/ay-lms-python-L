import hmac
import hashlib
import json
from django.test import TestCase
from payments.models import PaymentGateway, PaymentTransaction
from payments.services.razorpay_service import (
    verify_razorpay_signature,
    get_active_razorpay_gateway,
    get_webhook_secret,
    process_razorpay_webhook_event
)

class RazorpayServiceTestCase(TestCase):
    def setUp(self):
        # Clear existing razorpay payment gateways for test isolation
        PaymentGateway.objects.filter(gatway_name__icontains="razorpay").delete()

        self.secret = "Aryu_Academy_wev26"
        self.gateway = PaymentGateway.objects.create(
            gatway_name="razorpay",
            public_key="rzp_live_SKfiZYRJEe8WuU",
            secret_key="Du4L7ebKchXQSOMcgzx5wE3h",
            webhook_secret=f"  {self.secret}\n  ",  # Intentionally test trailing/leading whitespace
            is_archived=False
        )

    def test_verify_razorpay_signature_valid(self):
        raw_body = b'{"event":"payment.captured","payload":{"payment":{"entity":{"id":"pay_123","order_id":"order_456"}}}}'
        computed_sig = hmac.new(
            self.secret.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        self.assertTrue(verify_razorpay_signature(raw_body, computed_sig, self.secret))
        # Test with whitespace in secret argument
        self.assertTrue(verify_razorpay_signature(raw_body, computed_sig, f" {self.secret} "))

    def test_verify_razorpay_signature_invalid(self):
        raw_body = b'{"event":"payment.captured"}'
        invalid_sig = "a" * 64
        self.assertFalse(verify_razorpay_signature(raw_body, invalid_sig, self.secret))

    def test_verify_razorpay_signature_tampered_payload(self):
        raw_body = b'{"event":"payment.captured"}'
        computed_sig = hmac.new(self.secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        tampered_body = b'{"event":"payment.captured","hacked":true}'
        self.assertFalse(verify_razorpay_signature(tampered_body, computed_sig, self.secret))

    def test_secret_key_not_used_as_fallback(self):
        # Ensure secret_key (API key secret) is NEVER returned when webhook_secret is missing
        gw = PaymentGateway.objects.create(
            gatway_name="razorpay",
            public_key="rzp_live_SKfiZYRJEe8WuU",
            secret_key="Du4L7ebKchXQSOMcgzx5wE3h",
            webhook_secret=None,
            is_archived=False
        )
        self.assertIsNone(get_webhook_secret(gw))

    def test_middleware_preserves_webhook_raw_body(self):
        from core.middleware.security_sanitizer import InputSanitizationMiddleware
        middleware = InputSanitizationMiddleware(lambda r: None)

        class DummyRequest:
            path = "/api/webinar/razorpay/webhook/"
            method = "POST"
            content_type = "application/json"
            body = b'{"event":"payment.captured","test":true}'
            _body = body

        req = DummyRequest()
        res = middleware.process_request(req)
        self.assertIsNone(res)
        self.assertEqual(req._body, b'{"event":"payment.captured","test":true}')

    def test_get_active_razorpay_gateway(self):
        active_gw = get_active_razorpay_gateway()
        self.assertIsNotNone(active_gw)
        self.assertEqual(active_gw.id, self.gateway.id)
        self.assertEqual(get_webhook_secret(active_gw), self.secret)

        # Ensure archived gateway is ignored
        self.gateway.is_archived = True
        self.gateway.save()
        self.assertIsNone(get_active_razorpay_gateway())

    def test_process_webhook_event_payment_captured_and_idempotency(self):
        order_id = "order_test_captured_001"
        txn = PaymentTransaction.objects.create(
            gateway=self.gateway,
            order_id=order_id,
            transaction_id="TXN_001",
            amount=100.00,
            currency="INR",
            payment_status="pending"
        )

        payload = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_captured_999",
                        "order_id": order_id
                    }
                }
            }
        }

        # First event execution
        res1 = process_razorpay_webhook_event(payload)
        self.assertTrue(res1["processed"])
        txn.refresh_from_db()
        self.assertEqual(txn.payment_status, "captured")
        self.assertEqual((txn.metadata or {}).get("razorpay_payment_id"), "pay_captured_999")

        # Duplicate event execution (Idempotency)
        res2 = process_razorpay_webhook_event(payload)
        self.assertTrue(res2["processed"])
        self.assertEqual(res2["message"], "Already processed")
        txn.refresh_from_db()
        self.assertEqual(txn.payment_status, "captured")

    def test_process_webhook_event_payment_failed(self):
        order_id = "order_test_failed_001"
        txn = PaymentTransaction.objects.create(
            gateway=self.gateway,
            order_id=order_id,
            transaction_id="TXN_002",
            amount=100.00,
            currency="INR",
            payment_status="pending"
        )

        payload = {
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_failed_888",
                        "order_id": order_id
                    }
                }
            }
        }

        res = process_razorpay_webhook_event(payload)
        self.assertTrue(res["processed"])
        txn.refresh_from_db()
        self.assertEqual(txn.payment_status, "failed")

from unittest.mock import patch, MagicMock
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

class RazorpayViewTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Ensure active gateway exists
        PaymentGateway.objects.filter(gatway_name__icontains="razorpay").delete()
        self.gateway = PaymentGateway.objects.create(
            gatway_name="razorpay",
            public_key="rzp_live_SKfiZYRJEe8WuU",
            secret_key="Du4L7ebKchXQSOMcgzx5wE3h",
            webhook_secret="Aryu_Academy_wev26",
            is_archived=False
        )

    @patch("razorpay.Client")
    def test_payments_list_metrics(self, mock_client_class):
        # Mock payment list returned by razorpay
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.payment.all.return_value = {
            "items": [
                {
                    "id": "pay_001",
                    "amount": 5000,  # 50.00
                    "status": "captured",
                    "method": "upi",
                    "created_at": 1713518400,
                    "notes": {"name": "Alice", "email": "alice@example.com"}
                },
                {
                    "id": "pay_002",
                    "amount": 7500,  # 75.00
                    "status": "failed",
                    "method": "card",
                    "created_at": 1713518400,
                    "notes": {"name": "Bob", "email": "bob@example.com"}
                }
            ]
        }

        # Call endpoint (payments viewset get)
        from rest_framework.test import APIRequestFactory, force_authenticate
        from payments.views import RazorpayPaymentViewSet
        factory = APIRequestFactory()
        request = factory.get("/api/razorpay-payments/", {"page": "1", "page_size": "10"})
        force_authenticate(request, user=self.user)
        view = RazorpayPaymentViewSet.as_view({"get": "get"})
        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertTrue(data["success"])
        self.assertEqual(data["total_count"], 2)
        self.assertEqual(data["total_amount"], 125.0)
        self.assertEqual(data["total_captured_amount"], 50.0)
        self.assertEqual(data["total_failed_amount"], 75.0)

    @patch("requests.get")
    def test_settlements_list_metrics(self, mock_requests_get):
        # Mock settlement API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [
                {
                    "id": "setl_001",
                    "entity": "settlement",
                    "amount": 10000,  # 100.00
                    "status": "processed",
                    "fees": 200,
                    "tax": 36,
                    "utr": "UTR123",
                    "created_at": 1713518400
                },
                {
                    "id": "setl_002",
                    "entity": "settlement",
                    "amount": 25000,  # 250.00
                    "status": "processed",
                    "fees": 500,
                    "tax": 90,
                    "utr": "UTR456",
                    "created_at": 1713518400
                }
            ]
        }
        mock_requests_get.return_value = mock_response

        # Call endpoint (settlements viewset list)
        from rest_framework.test import APIRequestFactory, force_authenticate
        from payments.views import RazorpaySettlementViewSet
        factory = APIRequestFactory()
        request = factory.get("/api/razorpay-settlements/", {"page": "1", "page_size": "10"})
        force_authenticate(request, user=self.user)
        view = RazorpaySettlementViewSet.as_view({"get": "list"})
        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertTrue(data["success"])
        self.assertEqual(data["total_settlements"], 2)
        self.assertEqual(data["total_amount"], 350.0)
        self.assertEqual(data["data"]["count"], 2)
        self.assertEqual(len(data["data"]["items"]), 2)

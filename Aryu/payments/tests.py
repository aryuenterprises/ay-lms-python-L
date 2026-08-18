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

        self.secret = "TestWebhookSecret123"
        self.gateway = PaymentGateway.objects.create(
            gatway_name="razorpay",
            public_key="rzp_test_public_key",
            secret_key="rzp_test_secret_key",
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
        self.assertEqual(txn.payment_status, "done")
        self.assertEqual((txn.metadata or {}).get("razorpay_payment_id"), "pay_captured_999")

        # Duplicate event execution (Idempotency)
        res2 = process_razorpay_webhook_event(payload)
        self.assertTrue(res2["processed"])
        self.assertEqual(res2["message"], "Already processed")
        txn.refresh_from_db()
        self.assertEqual(txn.payment_status, "done")

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

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
            webhook_secret="",
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

    def test_student_auto_created_on_payment_done(self):
        from aryuapp.models import Student
        email = "tamilselvi@aryuacademy.com"
        name = "Tamil selvi"
        phone = "916303411390"

        txn = PaymentTransaction.objects.create(
            gateway=self.gateway,
            order_id="order_student_001",
            transaction_id="TXN_STU_001",
            amount=1.00,
            currency="INR",
            payment_status="pending",
            metadata={
                "email": email,
                "name": name,
                "phone": phone
            }
        )

        # Mark payment_status as done to fire the post_save signal
        txn.payment_status = "done"
        txn.save()

        # Check if Student instance was automatically created
        student = Student.objects.filter(email=email).first()
        self.assertIsNotNone(student)
        self.assertEqual(student.first_name, "Tamil")
        self.assertEqual(student.last_name, "selvi")
        self.assertEqual(student.contact_no, phone)
        self.assertTrue(student.status)

        txn.refresh_from_db()
        self.assertEqual(txn.student_id, student.student_id)

    def test_student_auto_creation_idempotency(self):
        from aryuapp.models import Student
        email = "tamilselvi@aryuacademy.com"

        # Pre-create student
        existing_student = Student.objects.create(
            username="tamilselvi",
            password="hashedpassword123",
            first_name="Tamil",
            last_name="selvi",
            email=email,
            contact_no="916303411390",
            status=True,
            current_address="N/A",
            permanent_address="N/A",
            city="N/A",
            state="N/A",
            country="India",
            converter="bootcamp"
        )

        txn = PaymentTransaction.objects.create(
            gateway=self.gateway,
            order_id="order_student_002",
            transaction_id="TXN_STU_002",
            amount=1.00,
            currency="INR",
            payment_status="done",
            metadata={
                "email": email.upper(),  # Test uppercase email matching
                "name": "Tamil selvi",
                "phone": "916303411390"
            }
        )

        # Ensure no duplicate Student was created
        student_count = Student.objects.filter(email=email).count()
        self.assertEqual(student_count, 1)
        
        txn.refresh_from_db()
        self.assertEqual(txn.student_id, existing_student.student_id)

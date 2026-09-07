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


from decimal import Decimal
from unittest.mock import patch
from rest_framework.test import APIRequestFactory, force_authenticate
from aryuapp.models import Student, User, StudentCourse, Settings
from courses.models import Course, CourseCategory
from batches.models import NewBatch
from payments.views import PaymentTransactionViewSet


class PaymentReportAPITransactionPersistenceTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.settings = Settings.objects.create(
            company_name="Aryu Enterprises",
            cgst_percentage=Decimal("9.0"),
            sgst_percentage=Decimal("9.0"),
            igst_percentage=Decimal("18.0"),
            is_archived=False
        )
        self.admin = User.objects.create(
            email="admin@example.com",
            user_type="super_admin",
            full_name="Super Admin",
            username="superadmin"
        )
        self.category = CourseCategory.objects.create(category_name="Engineering")
        self.course_1 = Course.objects.create(
            course_name="Python Mastery",
            course_category=self.category,
            fee=Decimal("10000.00"),
            status="Active"
        )
        self.course_2 = Course.objects.create(
            course_name="React Mastery",
            course_category=self.category,
            fee=Decimal("8000.00"),
            status="Active"
        )
        self.student_a = Student.objects.create(
            email="student.a@example.com",
            first_name="Alice",
            last_name="Smith",
            contact_no="9876543211",
            discount=Decimal("500.00")
        )
        self.student_b = Student.objects.create(
            email="student.b@example.com",
            first_name="Bob",
            last_name="Jones",
            contact_no="9876543222",
            discount=Decimal("0.00")
        )
        self.batch_a = NewBatch.objects.create(
            title="Batch A",
            course=self.course_1,
            start_date="2026-01-01",
            end_date="2026-03-01",
            start_time="10:00:00",
            end_time="11:00:00",
            slots=30,
            status=True
        )
        self.batch_a.students.add(self.student_a)
        self.sc_a1 = StudentCourse.objects.create(
            student=self.student_a,
            course=self.course_1,
            batch=self.batch_a
        )

        self.batch_b = NewBatch.objects.create(
            title="Batch B",
            course=self.course_2,
            start_date="2026-01-01",
            end_date="2026-03-01",
            start_time="11:00:00",
            end_time="12:00:00",
            slots=30,
            status=True
        )
        self.batch_b.students.add(self.student_b)
        self.sc_b2 = StudentCourse.objects.create(
            student=self.student_b,
            course=self.course_2,
            batch=self.batch_b
        )

        self.view = PaymentTransactionViewSet.as_view({"get": "list", "post": "create"})

    @patch("payments.services.invoice_service.InvoiceService.generate_invoice")
    def test_transaction_created_persisted_and_returned_in_report_and_on_refresh(self, mock_inv):
        mock_inv.side_effect = lambda tx_id, *args, **kwargs: PaymentTransaction.objects.get(id=tx_id) if isinstance(tx_id, int) else tx_id
        import json

        # 1. Create transaction via API with student_id and course_id
        create_req = self.factory.post(
            "/api/payment_transaction",
            data=json.dumps({
                "student_id": self.student_a.student_id,
                "course_id": self.course_1.course_id,
                "amount": 3000.0,
                "payment_mode": "OFFLINE",
                "payment_status": "done"
            }),
            content_type="application/json"
        )
        force_authenticate(create_req, user=self.admin)
        create_resp = self.view(create_req)
        self.assertEqual(create_resp.status_code, 200)
        self.assertTrue(create_resp.data["success"])

        # 2. Verify transaction is actually persisted in DB with foreign keys
        saved_tx = PaymentTransaction.objects.filter(student=self.student_a, course=self.course_1).first()
        self.assertIsNotNone(saved_tx)
        self.assertEqual(float(saved_tx.amount), 3000.0)
        self.assertEqual(saved_tx.payment_status, "done")
        self.assertEqual(saved_tx.student_id, self.student_a.student_id)
        self.assertEqual(saved_tx.course_id, self.course_1.course_id)

        # 3. Immediate API request
        list_req_1 = self.factory.get("/api/payment_transaction")
        force_authenticate(list_req_1, user=self.admin)
        list_resp_1 = self.view(list_req_1)
        self.assertEqual(list_resp_1.status_code, 200)

        summaries_1 = list_resp_1.data.get("student_payment_summaries", [])
        student_a_summary_1 = next((s for s in summaries_1 if s["student_id"] == self.student_a.student_id), None)
        self.assertIsNotNone(student_a_summary_1)
        course_1_data_1 = next((c for c in student_a_summary_1["courses"] if c["course_id"] == self.course_1.course_id), None)
        self.assertIsNotNone(course_1_data_1)
        self.assertEqual(len(course_1_data_1["transactions"]), 1)
        self.assertEqual(course_1_data_1["transactions"][0]["transaction_id"], saved_tx.transaction_id)
        self.assertEqual(course_1_data_1["paid_amount"], 3000.0)

        # 4. Page refresh (second fresh API request)
        list_req_2 = self.factory.get("/api/payment_transaction")
        force_authenticate(list_req_2, user=self.admin)
        list_resp_2 = self.view(list_req_2)
        self.assertEqual(list_resp_2.status_code, 200)

        summaries_2 = list_resp_2.data.get("student_payment_summaries", [])
        student_a_summary_2 = next((s for s in summaries_2 if s["student_id"] == self.student_a.student_id), None)
        self.assertIsNotNone(student_a_summary_2)
        course_1_data_2 = next((c for c in student_a_summary_2["courses"] if c["course_id"] == self.course_1.course_id), None)
        self.assertIsNotNone(course_1_data_2)
        self.assertEqual(len(course_1_data_2["transactions"]), 1)
        self.assertEqual(course_1_data_2["transactions"][0]["transaction_id"], saved_tx.transaction_id)
        self.assertEqual(course_1_data_2["paid_amount"], 3000.0)

    @patch("payments.services.invoice_service.InvoiceService.generate_invoice")
    def test_creation_with_registration_id(self, mock_inv):
        mock_inv.side_effect = lambda tx_id, *args, **kwargs: PaymentTransaction.objects.get(id=tx_id) if isinstance(tx_id, int) else tx_id
        import json

        create_req = self.factory.post(
            "/api/payment_transaction",
            data=json.dumps({
                "registration_id": self.student_a.registration_id,
                "course_id": self.course_1.course_id,
                "amount": 2500.0,
                "payment_mode": "OFFLINE",
                "payment_status": "done"
            }),
            content_type="application/json"
        )
        force_authenticate(create_req, user=self.admin)
        create_resp = self.view(create_req)
        self.assertEqual(create_resp.status_code, 200)

        saved_tx = PaymentTransaction.objects.filter(student=self.student_a, course=self.course_1).first()
        self.assertIsNotNone(saved_tx)
        self.assertEqual(saved_tx.student_id, self.student_a.student_id)

        # Fresh request retrieves it
        list_req = self.factory.get("/api/payment_transaction")
        force_authenticate(list_req, user=self.admin)
        resp = self.view(list_req)
        summary = next(s for s in resp.data["student_payment_summaries"] if s["student_id"] == self.student_a.student_id)
        course = next(c for c in summary["courses"] if c["course_id"] == self.course_1.course_id)
        self.assertEqual(len(course["transactions"]), 1)

    @patch("payments.services.invoice_service.InvoiceService.generate_invoice")
    def test_unrelated_students_and_courses_do_not_receive_transaction(self, mock_inv):
        mock_inv.side_effect = lambda tx_id, *args, **kwargs: PaymentTransaction.objects.get(id=tx_id) if isinstance(tx_id, int) else tx_id
        import json

        # Also enroll Student A in Course 2
        StudentCourse.objects.create(student=self.student_a, course=self.course_2, batch=self.batch_b)

        # Create payment specifically for Student A and Course 1
        PaymentTransaction.objects.create(
            student=self.student_a,
            course=self.course_1,
            amount=Decimal("4000.00"),
            payment_mode="OFFLINE",
            payment_status="done",
            transaction_id="TXN_ISO_001"
        )

        list_req = self.factory.get("/api/payment_transaction")
        force_authenticate(list_req, user=self.admin)
        resp = self.view(list_req)

        summaries = resp.data["student_payment_summaries"]
        student_a_summary = next(s for s in summaries if s["student_id"] == self.student_a.student_id)
        student_b_summary = next(s for s in summaries if s["student_id"] == self.student_b.student_id)

        # Student A Course 1 has the transaction
        c1_a = next(c for c in student_a_summary["courses"] if c["course_id"] == self.course_1.course_id)
        self.assertEqual(len(c1_a["transactions"]), 1)
        self.assertEqual(c1_a["transactions"][0]["transaction_id"], "TXN_ISO_001")

        # Student A Course 2 does NOT have the transaction
        c2_a = next(c for c in student_a_summary["courses"] if c["course_id"] == self.course_2.course_id)
        self.assertEqual(len(c2_a["transactions"]), 0)

        # Student B does NOT receive Student A's transaction
        for c_b in student_b_summary["courses"]:
            self.assertEqual(len(c_b["transactions"]), 0)

    @patch("payments.services.invoice_service.InvoiceService.generate_invoice")
    def test_multiple_transactions_for_same_course(self, mock_inv):
        mock_inv.side_effect = lambda tx_id, *args, **kwargs: PaymentTransaction.objects.get(id=tx_id) if isinstance(tx_id, int) else tx_id

        PaymentTransaction.objects.create(
            student=self.student_a,
            course=self.course_1,
            amount=Decimal("2000.00"),
            payment_mode="OFFLINE",
            payment_status="done",
            transaction_id="TXN_MULT_01"
        )
        PaymentTransaction.objects.create(
            student=self.student_a,
            course=self.course_1,
            amount=Decimal("3000.00"),
            payment_mode="OFFLINE",
            payment_status="done",
            transaction_id="TXN_MULT_02"
        )

        list_req = self.factory.get("/api/payment_transaction")
        force_authenticate(list_req, user=self.admin)
        resp = self.view(list_req)

        summary = next(s for s in resp.data["student_payment_summaries"] if s["student_id"] == self.student_a.student_id)
        course = next(c for c in summary["courses"] if c["course_id"] == self.course_1.course_id)

        self.assertEqual(len(course["transactions"]), 2)
        tx_ids = [t["transaction_id"] for t in course["transactions"]]
        self.assertIn("TXN_MULT_01", tx_ids)
        self.assertIn("TXN_MULT_02", tx_ids)
        self.assertEqual(course["paid_amount"], 5000.0)

    @patch("payments.services.invoice_service.InvoiceService.generate_invoice")
    def test_gateway_transaction_fallback_to_enrolled_course(self, mock_inv):
        mock_inv.side_effect = lambda tx_id, *args, **kwargs: PaymentTransaction.objects.get(id=tx_id) if isinstance(tx_id, int) else tx_id

        # Transaction with course=None (e.g. gateway payment)
        PaymentTransaction.objects.create(
            student=self.student_a,
            course=None,
            amount=Decimal("1500.00"),
            payment_mode="GATEWAY",
            payment_status="done",
            transaction_id="TXN_GW_001"
        )

        list_req = self.factory.get("/api/payment_transaction")
        force_authenticate(list_req, user=self.admin)
        resp = self.view(list_req)

        summary = next(s for s in resp.data["student_payment_summaries"] if s["student_id"] == self.student_a.student_id)
        course = next(c for c in summary["courses"] if c["course_id"] == self.course_1.course_id)

        self.assertEqual(len(course["transactions"]), 1)
        self.assertEqual(course["transactions"][0]["transaction_id"], "TXN_GW_001")
        self.assertEqual(course["paid_amount"], 1500.0)


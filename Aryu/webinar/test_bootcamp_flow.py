import hmac
import hashlib
import json
from unittest.mock import patch
from django.test import TransactionTestCase, Client
from django.urls import reverse
from django.utils import timezone
from webinar.models import Webinar, WebinarRegistration
from payments.models import PaymentGateway, PaymentTransaction, PaymentReport
from aryuapp.models import Student, StudentCourse

class BootcampFlowStagingTestCase(TransactionTestCase):

    def setUp(self):
        # Create test Razorpay gateway
        PaymentGateway.objects.filter(gatway_name__icontains="razorpay").delete()
        self.gateway = PaymentGateway.objects.create(
            gatway_name="razorpay",
            public_key="rzp_test_TTtwQmxo1jnhGB",
            secret_key="7yQ86SeXssbgvTPRsLluBzes",
            webhook_secret="TestSecretKey123",
            is_archived=False
        )
        self.client = Client()
        # Initialize test Webinar/Bootcamp
        self.webinar = Webinar.objects.create(
            title="Staging Test Bootcamp",
            slug="staging-test-bootcamp",
            price=1999.00,
            scheduled_start=timezone.now(),
            is_paid=True
        )

    @patch("razorpay.Client")
    def test_bootcamp_flow_staging(self, mock_rzp):
        mock_client = mock_rzp.return_value
        order_id = "order_staging_test_999"
        mock_client.order.create.return_value = {"id": order_id}

        # 2. Trigger POST to /api/webinars/<slug>/register/ with student payload
        url = reverse("webinar-register", kwargs={"slug": self.webinar.slug})
        payload = {
            "name": "Tamil Selvi",
            "email": "tamilselvi12022004@gmail.com",
            "phone": "9876543210",
            "source": "bootcamp",
            "profession": "Developer"
        }
        response = self.client.post(url, data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["order_id"], order_id)

        # 3. Simulate payment capture callback via create_registration_from_transaction(txn)
        txn = PaymentTransaction.objects.get(order_id=order_id)
        self.assertEqual(txn.payment_status, "pending")
        
        # Simulate payment captured update
        txn.metadata["razorpay_payment_id"] = "pay_tamil_captured_999"
        txn.save(update_fields=["metadata"])

        # Call ViewSet create_registration_from_transaction method
        from webinar.views import WebinarRegistrationViewSet
        registration = WebinarRegistrationViewSet.create_registration_from_transaction(txn)
        
        # 4. Assertions:
        # - assert Student.objects.filter(email="tamilselvi12022004@gmail.com").exists()
        student_exists = Student.objects.filter(email="tamilselvi12022004@gmail.com").exists()
        self.assertTrue(student_exists, "Student should have been created/found with target email")
        
        # - assert StudentCourse.objects.filter(student__email="tamilselvi12022004@gmail.com", is_paid=True).exists()
        sc_exists = StudentCourse.objects.filter(
            student__email="tamilselvi12022004@gmail.com",
            course__course_name=self.webinar.title,
            is_paid=True,
            status="active"
        ).exists()
        self.assertTrue(sc_exists, "Student should be enrolled in StudentCourse with active status and is_paid=True")

        # - assert PaymentTransaction.objects.filter(student__email="tamilselvi12022004@gmail.com", payment_status__in=["captured", "success"]).exists()
        txn_updated = PaymentTransaction.objects.filter(
            student__email="tamilselvi12022004@gmail.com",
            payment_status__in=["captured", "success"]
        ).exists()
        self.assertTrue(txn_updated, "Payment transaction should be linked to the student and updated to captured/success")

        # - Verify email send function executed without errors.
        report = PaymentReport.objects.filter(transaction_id=str(txn.id)).first()
        self.assertIsNotNone(report, "Payment report should have been created")
        self.assertEqual(report.payment_status, "COMPLETED")

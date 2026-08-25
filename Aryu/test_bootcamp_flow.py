import os
import sys
import django
from django.db import transaction
from django.utils import timezone
from unittest.mock import patch

# Setup django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Aryu.settings')
django.setup()

from webinar.models import Webinar, WebinarRegistration
from payments.models import PaymentGateway, PaymentTransaction, PaymentReport
from aryuapp.models import Student, StudentCourse
from webinar.views import WebinarRegistrationViewSet
from django.test import RequestFactory

def run_test():
    print("Initializing Staging Verification for Bootcamp Registration...")

    # Create Razorpay gateway configuration if not exists
    PaymentGateway.objects.filter(gatway_name__icontains="razorpay").delete()
    gateway = PaymentGateway.objects.create(
        gatway_name="razorpay",
        public_key="rzp_test_TTtwQmxo1jnhGB",
        secret_key="7yQ86SeXssbgvTPRsLluBzes",
        webhook_secret="TestSecretKey123",
        is_archived=False
    )
    print("1. Gateway Initialized with Test Keys.")

    # Initialize Webinar/Bootcamp
    webinar, created = Webinar.objects.get_or_create(
        slug="staging-test-bootcamp",
        defaults={
            "title": "Staging Test Bootcamp",
            "price": 1999.00,
            "scheduled_start": timezone.now(),
            "is_paid": True
        }
    )
    print(f"2. Webinar Initialized: {webinar.title} (Slug: {webinar.slug})")

    # Initialize test client/request
    factory = RequestFactory()
    student_payload = {
        "name": "Tamil Selvi",
        "email": "tamilselvi12022004@gmail.com",
        "phone": "9876543210",
        "source": "bootcamp",
        "profession": "Developer"
    }
    
    # We mock razorpay order creation
    with patch("razorpay.Client") as mock_rzp:
        mock_client = mock_rzp.return_value
        order_id = "order_staging_test_999"
        mock_client.order.create.return_value = {"id": order_id}

        request = factory.post(
            f"/api/webinars/{webinar.slug}/register/",
            data=student_payload,
            content_type="application/json"
        )
        # Call the ViewSet directly
        view = WebinarRegistrationViewSet.as_view({"post": "create"})
        response = view(request, slug=webinar.slug)
        assert response.status_code == 200, f"Registration response failed: {response.data}"
        assert response.data["order_id"] == order_id, "Order ID does not match"
        print("3. Register Endpoint successfully responded and initialized Razorpay checkout.")

    txn = PaymentTransaction.objects.get(order_id=order_id)
    assert txn.payment_status == "pending", "Transaction should start as pending"
    
    # Simulate payment capture
    txn.metadata["razorpay_payment_id"] = "pay_tamil_captured_999"
    txn.save(update_fields=["metadata"])
    print("4. Simulated Razorpay capture event.")

    # Execute post-payment registration/provisioning hook
    registration = WebinarRegistrationViewSet.create_registration_from_transaction(txn)
    
    # Assertions
    # A1. Student account exists
    student = Student.objects.filter(email="tamilselvi12022004@gmail.com").first()
    assert student is not None, "Student record was not created!"
    assert student.status is True, "Student account status should be active (True)"
    print(f"5. Assert: Student '{student.first_name} {student.last_name}' onboarding successful. Status: Active.")

    # A2. StudentCourse enrollment exists
    student_course = StudentCourse.objects.filter(
        student=student,
        course__course_name=webinar.title
    ).first()
    assert student_course is not None, "StudentCourse record was not created!"
    assert student_course.is_paid is True, "StudentCourse should be marked as paid"
    assert student_course.status == "active", "StudentCourse status should be active"
    print(f"6. Assert: Student Course Enrollment successful (is_paid=True, status=active).")

    # A3. PaymentTransaction updated to captured
    txn.refresh_from_db()
    assert txn.student == student, "Transaction should be linked to student"
    assert txn.payment_status in ["captured", "success"], f"PaymentTransaction status is {txn.payment_status}"
    print(f"7. Assert: PaymentTransaction updated to 'captured' and linked to student.")

    # A4. PaymentReport created and COMPLETED
    report = PaymentReport.objects.filter(transaction_id=str(txn.id)).first()
    assert report is not None, "PaymentReport was not created!"
    assert report.payment_status == "COMPLETED", f"PaymentReport status is {report.payment_status}"
    print("8. Assert: PaymentReport created with COMPLETED status for master list sync.")

    print("\n------------------------------------------------")
    print("All Pipeline Assertions PASSED successfully!")
    print("------------------------------------------------")

if __name__ == "__main__":
    # Run test inside transaction atomic block that rolls back at the end to keep database pristine
    try:
        with transaction.atomic():
            run_test()
            # Raise exception to rollback
            raise RuntimeError("ROLLBACK_FOR_TEST")
    except RuntimeError as e:
        if str(e) == "ROLLBACK_FOR_TEST":
            print("Database transaction rolled back. Database remains clean.")
        else:
            raise e

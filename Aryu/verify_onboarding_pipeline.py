import os
import sys
import django

# Setup django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Aryu.settings")
django.setup()

from django.conf import settings
settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

import logging
from django.db import transaction as db_transaction
from django.utils import timezone
from django.core import mail
from decimal import Decimal

# Import models & views
from webinar.models import Webinar, WebinarRegistration
from payments.models import PaymentGateway, PaymentTransaction, PaymentReport
from aryuapp.models import Student, StudentCourse, NewBatch, Course
from webinar.views import WebinarRegistrationViewSet
from aryuapp.services.dashboard.student_registration_service import _safe_send_welcome_email

# Set up logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("verify_pipeline")

def run_verification():
    logger.info("==================================================")
    logger.info("Starting Onboarding Pipeline verification...")
    logger.info("==================================================")

    # Wrap everything in a database transaction to roll back at the end
    try:
        with db_transaction.atomic():
            # 1. Configure the PaymentGateway entry for Razorpay
            logger.info("Configuring Razorpay PaymentGateway...")
            gateway, _ = PaymentGateway.objects.get_or_create(
                gatway_name="razorpay",
                defaults={
                    "public_key": "rzp_test_TTtwQmxo1jnhGB",
                    "secret_key": "7yQ86SeXssbgvTPRsLluBzes",
                    "webhook_secret": "TestSecretKey123",
                    "is_archived": False
                }
            )
            # Enforce staging/test credentials
            gateway.public_key = "rzp_test_TTtwQmxo1jnhGB"
            gateway.secret_key = "7yQ86SeXssbgvTPRsLluBzes"
            gateway.is_archived = False
            gateway.save()
            logger.info(f"PaymentGateway ID: {gateway.id}, Name: {gateway.gatway_name}")

            # 2. Setup a test Course & Batch
            logger.info("Setting up test Course and Batch...")
            course, _ = Course.objects.get_or_create(
                course_name="Python Full Stack Bootcamp",
                defaults={
                    "course_category_id": 1,
                    "is_active": True
                }
            )
            logger.info(f"Course: {course.course_name}")

            batch, _ = NewBatch.objects.get_or_create(
                title="Python Full Stack Bootcamp Batch 1",
                course=course,
                defaults={
                    "is_archived": False,
                    "start_date": timezone.now().date(),
                    "end_date": (timezone.now() + timezone.timedelta(days=30)).date(),
                    "start_time": timezone.datetime.strptime("10:00:00", "%H:%M:%S").time(),
                    "end_time": timezone.datetime.strptime("11:00:00", "%H:%M:%S").time(),
                    "slots": 100,
                    "status": True
                }
            )
            logger.info(f"Batch: {batch.title}")

            # 3. Create a test Webinar/Bootcamp
            logger.info("Creating test Webinar...")
            webinar = Webinar.objects.create(
                title="Python Full Stack Bootcamp",
                slug=f"verify-test-bootcamp-{int(timezone.now().timestamp())}",
                price=Decimal("499.00"),
                scheduled_start=timezone.now() + timezone.timedelta(days=1),
                is_paid=True,
                course=course,
                created_by="3",
                created_by_type="super_admin"
            )
            logger.info(f"Webinar: {webinar.title}, Price: {webinar.price}, Slug: {webinar.slug}")

            # 4. Create a successful payment transaction (Razorpay capture/success)
            logger.info("Creating test PaymentTransaction...")
            txn = PaymentTransaction.objects.create(
                gateway=gateway,
                transaction_id="pay_test_capture_onboarding_123",
                order_id="order_test_onboarding_456",
                amount=Decimal("499.00"),
                payment_status="captured",
                metadata={
                    "name": "Tamil Selvi",
                    "email": "tamilselvi12022004@gmail.com",
                    "phone": "9876543210",
                    "source": "bootcamp",
                    "profession": "Developer",
                    "webinar_id": str(webinar.uuid)
                }
            )
            logger.info(f"PaymentTransaction ID: {txn.id}, Status: {txn.payment_status}")

            # Clear any mock outbox
            mail.outbox = []

            # 5. Execute create_registration_from_transaction(txn)
            logger.info("Executing create_registration_from_transaction flow...")
            registration = WebinarRegistrationViewSet.create_registration_from_transaction(txn)
            logger.info(f"WebinarRegistration successfully created: {registration}")

            # 6. Verify database records
            logger.info("Verifying database records...")
            
            # Check Student
            student = Student.objects.filter(email="tamilselvi12022004@gmail.com").first()
            if not student:
                raise AssertionError("Student record was not created!")
            logger.info(f"SUCCESS: Student created - ID: {student.student_id}, Name: {student.first_name} {student.last_name}")

            # Check StudentCourse
            student_course = StudentCourse.objects.filter(student=student, course=course).first()
            if not student_course:
                raise AssertionError("StudentCourse enrollment record was not created!")
            if student_course.status != "active" or not student_course.is_paid:
                raise AssertionError(f"StudentCourse enrollment has invalid state: status={student_course.status}, is_paid={student_course.is_paid}")
            logger.info(f"SUCCESS: Student enrolled in StudentCourse - Status: {student_course.status}, Paid: {student_course.is_paid}")

            # Check Batch association
            if not NewBatch.objects.filter(course=course, students=student).exists():
                raise AssertionError("Student was not added to the Course Batch!")
            logger.info("SUCCESS: Student successfully mapped to the Batch.")

            # Check PaymentTransaction updated/linked to student
            txn_check = PaymentTransaction.objects.get(id=txn.id)
            if txn_check.student != student:
                raise AssertionError(f"PaymentTransaction is not linked to the student! Link: {txn_check.student}")
            logger.info("SUCCESS: PaymentTransaction is correctly linked to the Student.")

            # 7. Manually invoke email dispatch (since transaction will roll back and on_commit won't fire)
            logger.info("Simulating welcome email and PDF invoice dispatch...")
            _safe_send_welcome_email(student=student, password="TemporaryPass123", transaction_id=txn.id)

            # 8. Assertions on Email Outbox
            if len(mail.outbox) == 0:
                raise AssertionError("No emails were dispatched!")
            
            sent_email = None
            for email_msg in mail.outbox:
                if "Welcome" in email_msg.subject or "Registration" in email_msg.subject or "Invoice" in email_msg.subject:
                    if "Confirmed" not in email_msg.subject: # Skip webinar registration confirmation
                        sent_email = email_msg
                        break
            
            if not sent_email:
                raise AssertionError(f"Welcome/credentials email not found in outbox. Sent: {[e.subject for e in mail.outbox]}")
                
            logger.info(f"SUCCESS: Email intercepted in test outbox. Subject: '{sent_email.subject}'")
            logger.info(f"Recipient: {sent_email.to}")

            # Verify credentials in text body
            body_text = sent_email.body
            logger.info("-------------------- EMAIL BODY START --------------------")
            logger.info(body_text)
            logger.info("-------------------- EMAIL BODY END --------------------")

            if "Portal URL" not in body_text or "Username / Registered Email" not in body_text or "TemporaryPass123" not in body_text:
                raise AssertionError("Credentials or Portal URL missing from email text body!")

            # Verify attachments (PDF invoice)
            if not sent_email.attachments:
                raise AssertionError("Welcome email is missing the PDF invoice attachment!")
            
            attachment_name, attachment_content, attachment_mime = sent_email.attachments[0]
            logger.info(f"SUCCESS: Attachment found. Filename: '{attachment_name}', MIME: '{attachment_mime}', Size: {len(attachment_content)} bytes")
            
            if attachment_mime != "application/pdf":
                raise AssertionError(f"Attachment is not a PDF! MIME is '{attachment_mime}'")
            if len(attachment_content) < 1000:
                raise AssertionError(f"PDF attachment is suspiciously small: {len(attachment_content)} bytes")

            logger.info("Onboarding Pipeline verification completed successfully! All assertions passed.")
            
            # Force transaction rollback to avoid polluting the DB
            raise RuntimeWarning("Rolling back database transaction to keep data clean.")

    except RuntimeWarning as rw:
        logger.info(str(rw))
        logger.info("Verification transaction rolled back cleanly.")
    except Exception as e:
        logger.error("Verification FAILED with exception:", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    run_verification()

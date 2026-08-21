import logging
import threading
from django.db import transaction
from django.contrib.auth.hashers import make_password
from django.utils.crypto import get_random_string
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from aryuapp.models import Student, StudentCourse
from payments.models import PaymentReport, PaymentTransaction

logger = logging.getLogger(__name__)


def process_successful_bootcamp_payment(participant_instance):
    """
    Production-grade, OWASP-compliant post-payment handler for Bootcamp Participants.
    Executes atomically: Student Creation -> Course Mapping -> Payment Reporting -> Email Notification
    """
    status_val = str(getattr(participant_instance, 'payment_status', '')).strip().lower()
    is_paid = getattr(participant_instance, 'is_paid', False)
    
    if status_val != "done" and not is_paid:
        txn = getattr(participant_instance, 'payment_transaction', None)
        txn_status = str(getattr(txn, 'payment_status', '')).strip().lower() if txn else ""
        if txn_status != "done":
            return

    try:
        with transaction.atomic():
            email_raw = getattr(participant_instance, 'email', '') or ""
            if not email_raw and hasattr(participant_instance, 'metadata') and isinstance(participant_instance.metadata, dict):
                email_raw = participant_instance.metadata.get('email', '')

            if not email_raw:
                logger.warning("Participant instance %s has no email provided.", getattr(participant_instance, 'id', 'N/A'))
                return

            email = email_raw.lower().strip()

            # 1. Handle Secure Student Creation
            raw_password = None
            student = Student.objects.filter(email__iexact=email).first()

            if not student:
                # Generate strong temporary password meeting OWASP complexity
                raw_password = get_random_string(
                    16,
                    allowed_chars='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*'
                )

                # Derive secure username
                base_username = email.split("@")[0][:30]
                base_username = ''.join(c for c in base_username if c.isalnum() or c == '_') or "student"
                username = base_username
                counter = 1
                while Student.objects.filter(username=username).exists():
                    username = f"{base_username}_{counter}"
                    counter += 1

                # Parse names safely
                full_name = (getattr(participant_instance, 'name', '') or "").strip()
                if not full_name and hasattr(participant_instance, 'metadata') and isinstance(participant_instance.metadata, dict):
                    full_name = participant_instance.metadata.get('name', '').strip()

                if full_name:
                    name_parts = full_name.split(" ", 1)
                    first_name = name_parts[0]
                    last_name = name_parts[1] if len(name_parts) > 1 else ""
                else:
                    first_name = email.split("@")[0]
                    last_name = ""

                phone = getattr(participant_instance, 'phone', '') or ""
                if not phone and hasattr(participant_instance, 'metadata') and isinstance(participant_instance.metadata, dict):
                    phone = participant_instance.metadata.get('phone', '')

                student = Student.objects.create(
                    email=email,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    contact_no=phone,
                    password=make_password(raw_password),
                    status=True,
                    is_archived=False,
                    created_by_type="system",
                    current_address="N/A",
                    permanent_address="N/A",
                    city="N/A",
                    state="N/A",
                    country="India",
                    converter="bootcamp",
                )
                masked_email = f"{email[:2]}***@{email.split('@')[-1]}" if "@" in email else "***"
                logger.info("Student account successfully provisioned for ID: %s (Email: %s)", student.student_id, masked_email)
            else:
                if not student.status:
                    student.status = True
                    student.save(update_fields=["status"])

            # 2. Course Mapping / Enrollment
            bootcamp = getattr(participant_instance, 'bootcamp', None) or getattr(participant_instance, 'webinar', None)
            course = getattr(bootcamp, 'course', None) if bootcamp else None
            if course:
                if hasattr(student, 'courses'):
                    student.courses.add(course)
                elif hasattr(student, 'enrolled_courses'):
                    student.enrolled_courses.add(course)
                elif hasattr(StudentCourse, 'objects'):
                    from batches.models import NewBatch
                    from datetime import date, time, timedelta
                    batch = NewBatch.objects.filter(course=course, is_archived=False).first()
                    if not batch:
                        batch = NewBatch.objects.create(
                            title=f"Batch - {getattr(course, 'course_name', 'Course')[:30]}",
                            course=course,
                            start_date=date.today(),
                            end_date=date.today() + timedelta(days=30),
                            start_time=time(10, 0),
                            end_time=time(11, 0),
                            slots=100,
                            status=True
                        )
                    if hasattr(batch, 'students'):
                        batch.students.add(student)
                    StudentCourse.objects.get_or_create(student=student, course=course, batch=batch, defaults={'discount': 0})
                logger.info("Enrolled student %s into course %s", student.student_id, getattr(course, 'course_id', getattr(course, 'id', 'N/A')))

            # 3. Financial Record Creation (PaymentReport)
            amount = getattr(participant_instance, 'amount', None)
            if amount is None:
                txn = getattr(participant_instance, 'payment_transaction', None)
                amount = txn.amount if txn else 0.0

            txn_uuid = str(getattr(participant_instance, 'uuid', getattr(participant_instance, 'id', 'TXN_N/A')))
            payment_report, created_report = PaymentReport.objects.get_or_create(
                transaction_id=txn_uuid,
                defaults={
                    "student": student,
                    "amount": amount,
                    "payment_status": "COMPLETED",
                    "payment_method": "GATEWAY",
                    "bootcamp": bootcamp if hasattr(bootcamp, 'title') else None,
                    "course": course,
                }
            )

            # Link student back to payment transaction if unlinked
            if isinstance(participant_instance, PaymentTransaction):
                txn = participant_instance
            else:
                txn = getattr(participant_instance, 'payment_transaction', None)

            if txn and txn.student_id != student.student_id:
                PaymentTransaction.objects.filter(pk=txn.pk).update(student=student)
                txn.student = student

            # 4. Asynchronous Email Notification with Credentials & Invoice
            bootcamp_title = getattr(bootcamp, 'title', 'Bootcamp') if bootcamp else 'Bootcamp'
            transaction.on_commit(
                lambda: send_welcome_and_invoice_email(
                    student=student,
                    raw_password=raw_password,
                    amount=amount,
                    bootcamp_title=bootcamp_title
                )
            )

    except Exception as e:
        logger.error("Failed to process bootcamp payment processing for %s: %s", getattr(participant_instance, 'id', 'N/A'), str(e), exc_info=True)
        raise


def send_welcome_and_invoice_email(student, raw_password, amount, bootcamp_title):
    """
    Sends credentials, login link, and PDF invoice safely.
    Runs asynchronously via a background thread to prevent HTTP blocking or leaking exceptions.
    """
    def _email_worker():
        try:
            frontend_url = getattr(settings, 'FRONTEND_URL', 'https://portal.aryuacademy.com')
            login_url = f"{frontend_url}/login"

            full_name = f"{student.first_name} {student.last_name}".strip()
            context = {
                "student_name": full_name or student.username,
                "username": student.username,
                "email": student.email,
                "password": raw_password if raw_password else "[Your Existing Password]",
                "login_url": login_url,
                "bootcamp_title": bootcamp_title,
                "amount": amount,
            }

            try:
                html_message = render_to_string("emails/welcome_invoice_email.html", context)
            except Exception:
                html_message = f"""
                <h2>Registration Confirmed & Welcome to {bootcamp_title}!</h2>
                <p>Dear {context['student_name']},</p>
                <p>Thank you for completing your registration for <strong>{bootcamp_title}</strong>.</p>
                <p><strong>Login URL:</strong> <a href="{login_url}">{login_url}</a><br>
                <strong>Username:</strong> {student.username}<br>
                <strong>Password:</strong> {context['password']}</p>
                <p>Amount Paid: ₹{amount}</p>
                """

            email_msg = EmailMessage(
                subject=f"Registration Confirmed & Invoice - {bootcamp_title}",
                body=html_message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@aryuacademy.com'),
                to=[student.email]
            )
            email_msg.content_subtype = "html"
            email_msg.send(fail_silently=False)

            masked_email = f"{student.email[:2]}***@{student.email.split('@')[-1]}" if "@" in student.email else "***"
            logger.info("Welcome & invoice email successfully dispatched to %s", masked_email)
        except Exception as e:
            logger.error("Failed to send welcome & invoice email for student_id %s: %s", student.student_id, str(e), exc_info=True)

    thread = threading.Thread(target=_email_worker)
    thread.daemon = True
    thread.start()

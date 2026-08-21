import logging
import re
import secrets
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.hashers import make_password
from webinar.models import WebinarRegistration
from aryuapp.models import Student

logger = logging.getLogger(__name__)


@receiver(post_save, sender=WebinarRegistration)
def sync_student_on_webinar_registration_paid(sender, instance, created, **kwargs):
    """
    Listen to post_save on WebinarRegistration.
    If the participant is paid or their transaction status is 'done',
    automatically synchronize and ensure a Student database record exists.
    Wrapped in a safe try-except block with error logging.
    """
    try:
        txn = instance.payment_transaction
        payment_status = str(txn.payment_status if txn else "").strip().lower()

        # Check if participant is paid or payment transaction status is done
        if not (instance.is_paid or payment_status == "done"):
            return

        email = instance.email or ""
        if not email:
            return

        email_clean = email.strip().lower()
        phone_clean = instance.phone.strip() if instance.phone else ""
        name_clean = (instance.name or "").strip()

        if name_clean:
            name_parts = name_clean.split(maxsplit=1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ""
        else:
            first_name = email_clean.split("@")[0]
            last_name = ""

        email_handle = email_clean.split("@")[0]
        base_username = re.sub(r'[^a-zA-Z0-9_]', '', email_handle) or "student"
        base_username = base_username[:30]

        username = base_username
        counter = 1
        while Student.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        raw_password = secrets.token_urlsafe(8)
        hashed_password = make_password(raw_password)

        student, student_created = Student.objects.get_or_create(
            email=email_clean,
            defaults={
                "username": username,
                "password": hashed_password,
                "first_name": first_name,
                "last_name": last_name,
                "contact_no": phone_clean,
                "status": True,
                "current_address": "N/A",
                "permanent_address": "N/A",
                "city": "N/A",
                "state": "N/A",
                "country": "India",
                "converter": "bootcamp",
                "created_by_type": "public",
            }
        )

        if student_created:
            logger.info(
                "Created Student ID %s (%s) via WebinarRegistration %s signal.",
                student.student_id, email_clean, instance.id
            )
        else:
            logger.info(
                "Retrieved existing Student ID %s (%s) via WebinarRegistration %s signal.",
                student.student_id, email_clean, instance.id
            )
            if not student.status:
                student.status = True
                student.save(update_fields=["status"])

        if txn and txn.student_id != student.student_id:
            from payments.models import PaymentTransaction
            PaymentTransaction.objects.filter(pk=txn.pk).update(student=student)

    except Exception as e:
        logger.exception(
            "Error in post_save signal sync_student_on_webinar_registration_paid for WebinarRegistration %s: %s",
            getattr(instance, "id", "N/A"),
            str(e)
        )

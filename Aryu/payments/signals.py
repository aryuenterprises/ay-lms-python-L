import logging
import re
import secrets
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.hashers import make_password
from payments.models import PaymentTransaction
from aryuapp.models import Student

logger = logging.getLogger(__name__)


def create_or_sync_student_for_payment(txn: PaymentTransaction):
    """
    Helper to get or create a Student database instance for a successful payment transaction.
    Uses email.lower() to avoid duplicates, parses first_name/last_name from name,
    generates a unique username safely, and passes essential default fields.
    """
    metadata = txn.metadata if isinstance(txn.metadata, dict) else {}
    email = metadata.get("email") or ""
    name = metadata.get("name") or ""
    phone = metadata.get("phone") or txn.phone or ""

    # Fallback to linked webinar registration
    if not email and txn.webinar_registration:
        web_reg = txn.webinar_registration
        email = web_reg.email or ""
        name = name or web_reg.name or ""
        phone = phone or web_reg.phone or ""

    if not email:
        logger.warning(
            "PaymentTransaction %s status is marked as 'done' but no email found in metadata or registration.",
            txn.id
        )
        return None, False

    email_clean = email.strip().lower()
    phone_clean = phone.strip() if phone else ""
    name_clean = name.strip() if name else ""

    # Parse first_name and last_name from the name field
    if name_clean:
        name_parts = name_clean.split(maxsplit=1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""
    else:
        first_name = email_clean.split("@")[0]
        last_name = ""

    # Safely generate a unique username from email handle
    email_handle = email_clean.split("@")[0]
    base_username = re.sub(r'[^a-zA-Z0-9_]', '', email_handle) or "student"
    base_username = base_username[:30]

    username = base_username
    counter = 1
    while Student.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1

    # Generate random secure password
    raw_password = secrets.token_urlsafe(8)
    hashed_password = make_password(raw_password)

    # Use Student.objects.get_or_create(...) using email.lower()
    student, created = Student.objects.get_or_create(
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

    if created:
        logger.info(
            "Created Student ID %s (%s) for completed PaymentTransaction %s.",
            student.student_id, email_clean, txn.id
        )
    else:
        logger.info(
            "Retrieved existing Student ID %s (%s) for completed PaymentTransaction %s.",
            student.student_id, email_clean, txn.id
        )
        # Ensure student status is True for active state
        if not student.status:
            student.status = True
            student.save(update_fields=["status"])

    # Safely associate Student back to PaymentTransaction if unlinked
    if txn.student_id != student.student_id:
        PaymentTransaction.objects.filter(pk=txn.pk).update(student=student)

    return student, created


@receiver(post_save, sender=PaymentTransaction)
def sync_student_on_payment_transaction_done(sender, instance, created, **kwargs):
    """
    Listen to post_save on PaymentTransaction.
    Whenever payment_status is 'done', ensure automatic synchronization with Student model.
    Wrapped in a safe try-except block with error logging.
    """
    try:
        status_str = str(instance.payment_status or "").strip().lower()
        if status_str == "done":
            create_or_sync_student_for_payment(instance)
    except Exception as e:
        logger.exception(
            "Error in post_save signal sync_student_on_payment_transaction_done for PaymentTransaction %s: %s",
            getattr(instance, "id", "N/A"),
            str(e)
        )

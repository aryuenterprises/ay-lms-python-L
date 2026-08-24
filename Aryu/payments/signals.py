import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from payments.models import PaymentTransaction
from payments.services.bootcamp_payment_service import process_successful_bootcamp_payment

logger = logging.getLogger(__name__)


@receiver(post_save, sender=PaymentTransaction)
def sync_student_on_payment_transaction_done(sender, instance, created, **kwargs):
    """
    Listen to post_save on PaymentTransaction.
    Whenever payment_status is 'done', ensure automatic OWASP-compliant workflow:
    Student Provisioning -> Course Enrollment -> PaymentReport Creation -> Async Credentials/Invoice Dispatch.
    """
    try:
        status_str = str(instance.payment_status or "").strip().lower()
        if status_str == "done":
            process_successful_bootcamp_payment(instance)
    except Exception as e:
        logger.exception(
            "Error in post_save signal sync_student_on_payment_transaction_done for PaymentTransaction %s: %s",
            getattr(instance, "id", "N/A"),
            str(e)
        )

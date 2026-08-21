import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from webinar.models import WebinarRegistration
from payments.services.bootcamp_payment_service import process_successful_bootcamp_payment

logger = logging.getLogger(__name__)


@receiver(post_save, sender=WebinarRegistration)
def sync_student_on_webinar_registration_paid(sender, instance, created, **kwargs):
    """
    Listen to post_save on WebinarRegistration.
    If the participant is marked as paid or their transaction status is 'done',
    trigger the OWASP-compliant bootcamp payment workflow.
    """
    try:
        txn = instance.payment_transaction
        payment_status = str(txn.payment_status if txn else "").strip().lower()

        if instance.is_paid or payment_status == "done":
            process_successful_bootcamp_payment(instance)
    except Exception as e:
        logger.exception(
            "Error in post_save signal sync_student_on_webinar_registration_paid for WebinarRegistration %s: %s",
            getattr(instance, "id", "N/A"),
            str(e)
        )

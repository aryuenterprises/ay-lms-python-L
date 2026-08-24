import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from webinar.models import WebinarRegistration
from payments.services.bootcamp_payment_service import process_successful_bootcamp_payment

logger = logging.getLogger(__name__)


@receiver(post_save, sender=WebinarRegistration)
def sync_student_on_webinar_registration(sender, instance, created, **kwargs):
    """
    Listen to post_save on WebinarRegistration.
    Automatically provisions/syncs the Student account (generating a unique registration_id),
    assigns the associated Course, and dispatches welcome/invoice emails upon payment.
    """
    try:
        process_successful_bootcamp_payment(instance)
    except Exception as e:
        logger.exception(
            "Error in post_save signal sync_student_on_webinar_registration for WebinarRegistration %s: %s",
            getattr(instance, "id", "N/A"),
            str(e)
        )

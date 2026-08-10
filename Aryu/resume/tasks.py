from celery import shared_task
from resume.models import ResumeRegistration
from django.core.mail import EmailMultiAlternatives
import logging
import time
from django.conf import settings

logger = logging.getLogger(__name__)

@shared_task
def resume_reg(registration_id):

    start = time.perf_counter()

    logger.info("Task started")

    # existing code

    logger.info(
        f"Task completed in "
        f"{time.perf_counter() - start:.4f}s"
    )

# tasks.py
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    default_retry_delay=60,
)
def send_verification_email_task(
    self, subject: str, body: str, html_message: str, recipient_email: str
):
    """
    Production-ready Celery task for asynchronous HTML email delivery.
    Includes exponential backoff retries for transient SMTP/network issues.
    """
    try:
        email_message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email],
        )
        email_message.attach_alternative(html_message, "text/html")
        email_message.extra_headers = {
            "Reply-To": getattr(settings, "SUPPORT_EMAIL", "support@aryuacademy.com"),
            "X-Auto-Response-Suppress": "OOF, AutoReply",
        }

        email_message.send(fail_silently=False)
        logger.info(f"Verification email successfully sent to {recipient_email}")
        return True

    except Exception as exc:
        logger.error(
            f"Failed to send verification email to {recipient_email}: {str(exc)}"
        )
        raise self.retry(exc=exc)
        
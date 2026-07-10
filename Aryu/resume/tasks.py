from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
import logging
import time
from django.conf import settings

logger = logging.getLogger(__name__)

@shared_task
def send_verification_email(subject, body, html_message, recipient):
    logger.info(f"Sending verification email to {recipient}")

    try:
        email_message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )

        email_message.attach_alternative(
            html_message,
            "text/html"
        )

        email_message.send(fail_silently=False)

        logger.info("Verification email sent successfully")

    except Exception as e:
        logger.exception(f"Email sending failed: {e}")
        raise
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



@shared_task
def send_verification_email(
    subject,
    body,
    html_message,
    recipient
):
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

    email_message.send(
        fail_silently=False
    )
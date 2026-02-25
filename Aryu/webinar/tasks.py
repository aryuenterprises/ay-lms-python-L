from celery import shared_task
from django.db import close_old_connections
from .services.certificate_generation import generate_and_send_certificate_pdf
from webinar.models import Webinar, WebinarRegistration
from datetime import timedelta
from aryuapp.models import Certificate
from .services.whatsapp import send_webinar_live_whatsapp, send_webinar_reminder, send_webinar_joining_whatsapp, send_webinar_welcome_whatsapp
from django.utils.timezone import now
from webinar.services.webinar_emails import send_webinar_certificate_email
from pathlib import Path
from django.conf import settings


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=30)
def send_webinar_welcome_task(self, registration_id):
    reg = WebinarRegistration.objects.select_related("webinar").get(id=registration_id)
    print("📱 Sending WhatsApp welcome message for registration ID:", registration_id)
    send_webinar_welcome_whatsapp(reg)

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=30, retry_kwargs={"max_retries": 3})
def send_webinar_reminder_task(self, registration_id, time_left, instruction):
    send_webinar_reminder(
        registration_id=registration_id,
        time_left=time_left,
        instruction=instruction
    )

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=30, retry_kwargs={'max_retries': 3})
def send_webinar_joining_task(self, registration_id):
    from webinar.models import WebinarRegistration

    registration = WebinarRegistration.objects.select_related("webinar").get(id=registration_id)
    webinar = registration.webinar

    # Pick correct join URL
    join_url = webinar.zoom_join_url or webinar.zoom_link

    if not join_url:
        print("❌ No join URL found for webinar", webinar.id)
        return

    send_webinar_joining_whatsapp(registration, join_url)

@shared_task
def send_certificate_task(reg_id, user_id, user_type):
    reg = WebinarRegistration.objects.get(id=reg_id)

    certificate, _ = Certificate.objects.get_or_create(
        webinar_registration=reg,
        defaults={
            "student": getattr(reg, "student", None),
            "student_name": reg.name,
            "course_name": reg.webinar.title,
            "course_duration": "3 Hours",
            "created_by": user_id,
            "created_by_type": user_type
        }
    )

    generate_and_send_certificate_pdf(
        certificate=certificate,
        phone=reg.phone
    )

    reg.certificate_sent = True
    reg.save(update_fields=["certificate_sent"])

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=30, retry_kwargs={"max_retries": 3})
def daily_webinar_reminder_scheduler(self):
    """
    Runs DAILY at 10:00 AM IST via celery-beat
    """

    current_time = now()

    registrations = WebinarRegistration.objects.select_related("webinar").filter(
        wants_reminder=True,
        webinar__is_completed=False,
    )

    for reg in registrations:
        webinar = reg.webinar
        start = webinar.scheduled_start
        diff = start - current_time

        # Webinar already over
        if diff.total_seconds() <= 0:
            continue

        # 15 minutes reminder
        if timedelta(minutes=14) <= diff <= timedelta(minutes=16):
            send_webinar_reminder.delay(
                reg.id,
                "15 mins",
                "Please keep your laptop ready and join on time."
            )

        # Same day reminder (morning)
        elif start.date() == current_time.date():
            send_webinar_reminder.delay(
                reg.id,
                "today",
                "Make sure you are in a calm place with a stable internet connection."
            )

        # Tomorrow reminder
        elif start.date() == (current_time + timedelta(days=1)).date():
            send_webinar_reminder.delay(
                reg.id,
                "24 hours",
                "Please block your calendar and prepare in advance."
            )
    

@shared_task(bind=True, retry_kwargs={'max_retries': 3})
def send_webinar_live_task(self, registration_id):

    try:
        reg = WebinarRegistration.objects.select_related("webinar").get(id=registration_id)
    except WebinarRegistration.DoesNotExist:
        print(f"[LIVE TASK] Registration {registration_id} not found. Skipping.")
        return

    send_webinar_live_whatsapp(reg)
    return "LIVE message sent"

@shared_task
def celery_health_check():
    return "Celery is running fine!"
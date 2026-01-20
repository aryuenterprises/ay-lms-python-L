from celery import shared_task
from datetime import timedelta
from django.utils import timezone
from webinar.models import WebinarRegistration
from webinar.services.whatsapp import send_webinar_reminder


@shared_task
def send_webinar_reminder(registration_id, label, instruction):
    reg = WebinarRegistration.objects.get(id=registration_id)
    if not reg.wants_reminder:
        return

    send_webinar_reminder(reg, label, instruction)

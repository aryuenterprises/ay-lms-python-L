from Aryu.celery import shared_task
from django.db import close_old_connections
from webinar.models import Webinar, WebinarRegistration
from aryuapp.models import Certificate
from webinar.services.webinar_emails import send_webinar_certificate_email
from webinar.utils import generate_certificate_image  
from pathlib import Path
from django.conf import settings


@shared_task
def send_webinar_reminder(registration_id, label, instruction):
    reg = WebinarRegistration.objects.get(id=registration_id)
    if not reg.wants_reminder:
        return             

    send_webinar_reminder(reg, label, instruction)
    
def generate_and_send_certificates(webinar):
    close_old_connections()

    registrations = WebinarRegistration.objects.filter(
        webinar=webinar,
        attended=True,
        certificate_sent=False,
    ).iterator(chunk_size=5)

    sent_count = 0

    for reg in registrations:
        close_old_connections()

        # Skip if certificate already exists
        if hasattr(reg, "certificate"):
            continue

        # Create Certificate object
        certificate = Certificate.objects.create(
            webinar_registration=reg,
            student_name=reg.name,
            course_name=webinar.title,
        )

        # Use your existing certificate image generator
        certificate_file_path = generate_certificate_image(
            registration=reg,
            template_path=Path(settings.BASE_DIR) / "media/certificates/40106369-ai.png",
            certificate_number=certificate.certificate_number,
        )

        certificate.certificate_file = f"certificates/{certificate_file_path.name}"
        certificate.save(update_fields=["certificate_file"])

        # Send email
        if reg.email:
            send_webinar_certificate_email(reg, certificate_file_path)

        # Mark as sent
        reg.certificate_sent = True
        reg.save(update_fields=["certificate_sent"])

        sent_count += 1

    return f"Certificates sent for {sent_count} attendees"

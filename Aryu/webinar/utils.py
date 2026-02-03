from pathlib import Path
from django.conf import settings
from django.db import close_old_connections
from PIL import Image, ImageDraw, ImageFont

from webinar.models import WebinarRegistration
from aryuapp.models import Certificate
from webinar.services.webinar_emails import send_webinar_certificate_email




# -----------------------------
# Certificate text coordinates
# -----------------------------
TEMPLATE_COORDS = {
    "name": (600, 350),
    "course_name": (600, 450),
    "certificate_number": (1000, 100),
    "date": (600, 550),
}


# -----------------------------
# Generate certificate image
# -----------------------------
def generate_certificate_image(registration, template_path, certificate):
    from pathlib import Path
    from django.conf import settings
    from PIL import Image, ImageDraw, ImageFont

    webinar = registration.webinar

    output_dir = Path(settings.MEDIA_ROOT) / "certificates"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file_path = output_dir / f"{registration.id}_certificate.png"

    template_path = Path(template_path)
    print("🔖 Generating certificate for:", registration.name)
    if not template_path.exists():
        raise Exception(f"Template not found: {template_path}")

    img = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    try:
        font_path = Path(settings.MEDIA_ROOT) / "fonts" / "Roboto-Regular.ttf"
        font = ImageFont.truetype(str(font_path), 60)
    except Exception:
        font = ImageFont.load_default()
        print("⚠️  Could not load custom font, using default font.")

    replacements = {
        "name": registration.name,
        "course_name": webinar.title,
        "certificate_number": certificate.certificate_number,
        "date": webinar.scheduled_start.strftime("%d-%m-%Y"),
    }

    for key, value in replacements.items():
        x, y = TEMPLATE_COORDS[key]
        draw.text((x, y), str(value), fill="black", font=font)

    img.save(output_file_path)
    print("✅ Certificate saved at:", output_file_path)

    return output_file_path



# -----------------------------
# Generate and send certificates
# -----------------------------
def generate_and_send_certificates(webinar):
    # Reset DB connection to prevent connection closed errors
    close_old_connections()

    registrations = WebinarRegistration.objects.filter(
        webinar=webinar,
        attended=True,
        certificate_sent=False,
    ).iterator(chunk_size=5)  # Use iterator for large webinars

    sent_count = 0

    for reg in registrations:
        close_old_connections()  # Reconnect to DB if needed

        # Check if certificate already exists
        try:
            reg.certificate
            continue  # Skip if already exists
        except Certificate.DoesNotExist:
            pass

        # Create Certificate object (uses your model to auto-generate certificate_number)
        certificate = Certificate.objects.create(
            webinar_registration=reg,
            student_name=reg.name,
            course_name=webinar.title,
        )

        # Generate certificate image
        certificate_file_path = generate_certificate_image(
            registration=reg,
            template_path=Path(settings.BASE_DIR) / "media/certificates/40106369-ai.png",
            certificate_number=certificate.certificate_number,
        )

        # Save certificate image path in DB
        certificate.certificate_file = f"certificates/{certificate_file_path.name}"
        certificate.save(update_fields=["certificate_file"])

        # Send email with certificate
        if reg.email:
            send_webinar_certificate_email(reg, certificate_file_path)

        # Mark registration as certificate sent
        reg.certificate_sent = True
        reg.save(update_fields=["certificate_sent"])

        sent_count += 1

    return f"Certificates sent for {sent_count} attendees"

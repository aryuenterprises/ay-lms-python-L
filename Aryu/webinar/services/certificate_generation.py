from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from django.core.files import File
from django.conf import settings
import logging
from .webinar_emails import send_webinar_certificate_email
logger = logging.getLogger(__name__)
from .whatsapp import send_webinar_certificate_whatsapp
from celery import shared_task

def center_x(draw, text, font, img_width):
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    return (img_width - text_width) // 2


def fit_font(draw, text, font_path, max_width, start_size):
    size = start_size
    font = ImageFont.truetype(str(font_path), size)
    while draw.textbbox((0, 0), text, font=font)[2] > max_width and size > 18:
        size -= 1
        font = ImageFont.truetype(str(font_path), size)
    return font


def generate_certificate_image_and_save(certificate):

    template_path = Path(settings.MEDIA_ROOT) / "certificates" / "AK20.png"
    # template_path = Path(settings.MEDIA_ROOT) / "jp.png"
    output_dir = Path(settings.MEDIA_ROOT) / "certificates"

    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{certificate.certificate_number}.png"

    img = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    img_width, img_height = img.size
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    # font_path = "C:/Windows/Fonts/arialbd.ttf"

    name = certificate.student_name.title()
    course = certificate.course_name

    name_font = fit_font(draw, name, font_path, img_width * 0.45, 54)
    course_font = fit_font(draw, course, font_path, img_width * 0.45, 44)
    small_font = ImageFont.truetype(str(font_path), 30)
    large_font = ImageFont.truetype(str(font_path), 18)

    draw.text((int(img_width * 0.184), int(img_height * 0.136)),
              certificate.certificate_number, fill="black", font=large_font)

    name_y = int(img_height * 0.43)
    draw.text((center_x(draw, name, name_font, img_width), name_y),name,fill="black",font=name_font)

    course_y = name_y + 170
    # draw.text((int(img_width * 0.280), course_y),
    #           course, fill="black", font=course_font)


    draw.text(
        (center_x(draw, course, course_font, img_width), course_y),
        course,
        fill="black",
        font=course_font
    )
    
    date_y = 0.635

    draw.text((int(img_width * 0.450), int(img_height * date_y)),
              certificate.issued_date.strftime("%d-%m-%Y"),
              fill="black", font=small_font)

    img.save(output_path)

    return output_path

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def center_x(draw, text, font, img_width):
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    return (img_width - text_width) // 2


def fit_font(draw, text, font_path, max_width, start_size):
    size = start_size
    font = ImageFont.truetype(str(font_path), size)
    while draw.textbbox((0, 0), text, font=font)[2] > max_width and size > 18:
        size -= 1
        font = ImageFont.truetype(str(font_path), size)
    return font


def convert_certificate_image_to_pdf(image_path: Path):
    """
    Takes a PNG certificate image and converts it to PDF
    """
    pdf_path = image_path.with_suffix(".pdf")

    image = Image.open(image_path).convert("RGB")
    image.save(pdf_path, "PDF", resolution=300.0)

    return pdf_path
@shared_task
def generate_and_send_certificate_pdf(certificate, phone):
    """
    Uses existing Certificate model fields only
    """
    registration = certificate.webinar_registration
    # Generate image
    image_path = generate_certificate_image_and_save(certificate)

    # Convert image → PDF
    pdf_path = convert_certificate_image_to_pdf(Path(image_path))

    # Save PDF into certificate_file
    with open(pdf_path, "rb") as f:
        certificate.certificate_file.save(
            pdf_path.name,
            File(f),
            save=True
        )
    
    #send email with PDF attachment
    email_sent = False
    try:
        send_webinar_certificate_email(
            registration=registration,
            certificate_file=certificate.certificate_file
        )
        logger.info("Certificate email sent to %s for registration ID %s", registration.email, registration.id)
        email_sent = True
    except Exception as e:
        logger.exception("Email certificate sending failed: %s", e)

    # Send WhatsApp PDF
    send_webinar_certificate_whatsapp(
        certificate=certificate,
        phone=phone
    )


import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from django.core.files import File
from django.conf import settings
from .models import Certificate
import logging

logger = logging.getLogger(__name__)


def _get_font(font_path, size):
    """
    Safely load a truetype font or fallback gracefully.
    """
    if font_path and os.path.exists(font_path):
        try:
            return ImageFont.truetype(str(font_path), size)
        except Exception:
            pass
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def center_x(draw, text, font, img_width):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
    except Exception:
        text_width = len(text) * 10
    return max(0, (img_width - text_width) // 2)


def fit_font(draw, text, font_path, max_width, start_size):
    size = start_size
    font = _get_font(font_path, size)
    while size > 18:
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            if bbox[2] - bbox[0] <= max_width:
                break
        except Exception:
            break
        size -= 1
        font = _get_font(font_path, size)
    return font


def generate_certificate_image_and_save(certificate):
    template_candidates = [
        Path(settings.MEDIA_ROOT) / "certificates" / "course_completion_certificate.png",
        Path(settings.MEDIA_ROOT) / "certificates" / "AdhhK20.png",
        Path(settings.MEDIA_ROOT) / "certificates" / "aryu-certificate.png",
        Path(settings.MEDIA_ROOT) / "certificates" / "Akdgbh2.png",
        Path(settings.MEDIA_ROOT) / "certificates" / "40163dhxh69-ai.png",
    ]

    template_path = None
    for candidate in template_candidates:
        if candidate.exists():
            template_path = candidate
            break

    output_dir = Path(settings.MEDIA_ROOT) / "certificates"
    output_dir.mkdir(parents=True, exist_ok=True)

    cert_num = certificate.certificate_number or f"CERT_{certificate.id}"
    output_path = output_dir / f"{cert_num}.png"

    if template_path and template_path.exists():
        img = Image.open(template_path).convert("RGBA")
    else:
        img = Image.new("RGBA", (1920, 1080), (255, 255, 255, 255))

    draw = ImageDraw.Draw(img)
    img_width, img_height = img.size
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    name = (certificate.student_name or "").title()
    course = certificate.course_name or ""
    duration = certificate.course_duration or ""
    issued_date_str = certificate.issued_date.strftime("%d-%m-%Y") if certificate.issued_date else ""

    name_font = fit_font(draw, name, font_path, img_width * 0.45, 54)
    course_font = fit_font(draw, course, font_path, img_width * 0.45, 44)
    small_font = _get_font(font_path, 30)
    large_font = _get_font(font_path, 18)

    # Certificate Number
    draw.text((int(img_width * 0.184), int(img_height * 0.136)),
              cert_num, fill="black", font=large_font)

    # Student Name
    name_y = int(img_height * 0.43)
    draw.text((center_x(draw, name, name_font, img_width), name_y), name, fill="black", font=name_font)

    # Course Name
    course_y = name_y + 170
    draw.text((center_x(draw, course, course_font, img_width), course_y),
              course, fill="black", font=course_font)

    # Duration / Date
    date_y = 0.635
    text_to_draw = duration or issued_date_str
    draw.text((int(img_width * 0.570), int(img_height * date_y)),
              text_to_draw, fill="black", font=small_font)

    img.save(output_path)
    return output_path


def convert_certificate_image_to_pdf(image_path: Path):
    """
    Takes a PNG certificate image and converts it to PDF
    """
    pdf_path = image_path.with_suffix(".pdf")
    image = Image.open(image_path).convert("RGB")
    image.save(pdf_path, "PDF", resolution=300.0)
    return pdf_path


def generate_and_send_certificate_pdf(certificate_or_id):
    """
    Generate certificate image and PDF, then save it to the Certificate model.
    """
    if isinstance(certificate_or_id, Certificate):
        certificate = certificate_or_id
    else:
        certificate = Certificate.objects.get(pk=certificate_or_id)

    # Generate certificate image
    image_path = generate_certificate_image_and_save(certificate)

    # Convert image to PDF
    pdf_path = convert_certificate_image_to_pdf(Path(image_path))

    # Save PDF to certificate_file
    with open(pdf_path, "rb") as f:
        certificate.certificate_file.save(
            pdf_path.name,
            File(f),
            save=True
        )

    logger.info(
        "Certificate PDF generated successfully for certificate %s",
        certificate.certificate_number
    )

    return certificate.certificate_file.path



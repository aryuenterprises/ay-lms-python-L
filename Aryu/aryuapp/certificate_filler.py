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
        Path(settings.MEDIA_ROOT) / "certificates" / "course_completion_certificate_new.png",
        Path(settings.MEDIA_ROOT) / "certificates" / "course_completion_certificate.png",
        Path(settings.MEDIA_ROOT) / "certificates" / "aryu-certificate.png",
        Path(settings.MEDIA_ROOT) / "certificates" / "AK20.png",
        Path(settings.MEDIA_ROOT) / "certificates" / "AK2.png",
        Path(settings.MEDIA_ROOT) / "certificates" / "Ak2.png",
        Path(settings.MEDIA_ROOT) / "certificates" / "4016369-ai.png",
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

    font_bold_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    font_regular_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    font_bold_path = next((f for f in font_bold_candidates if os.path.exists(f)), None)
    font_regular_path = next((f for f in font_regular_candidates if os.path.exists(f)), None)

    scale_x = img_width / 1640.0
    scale_y = img_height / 1160.0

    name = (certificate.student_name or "").strip()
    course = (certificate.course_name or "").strip()
    if course and not (course.startswith("“") or course.startswith('"') or course.startswith("'")):
        course = f"“{course}”"

    if getattr(certificate, 'issued_date', None):
        try:
            issued_date_str = f"{certificate.issued_date.day} {certificate.issued_date.strftime('%B %Y')}"
        except Exception:
            issued_date_str = str(certificate.issued_date)
    else:
        issued_date_str = ""

    dark_color = (25, 25, 30)
    purple_color = (85, 20, 150)

    # 1. Certificate ID (e.g. AA/2026/00125)
    id_font_size = max(14, int(18 * scale_y))
    id_font = _get_font(font_bold_path, id_font_size)
    draw.text((int(305 * scale_x), int(154 * scale_y)), cert_num, fill=dark_color, font=id_font)

    # 2. Student Name (e.g. Aruna V) - centered above line at y=543, purple bold
    name_font_size = max(30, int(54 * scale_y))
    name_font = fit_font(draw, name, font_bold_path, img_width * 0.65, name_font_size)
    try:
        ascent, descent = name_font.getmetrics()
        name_y = int(538 * scale_y) - (ascent + descent)
    except Exception:
        name_y = int(475 * scale_y)
    draw.text((center_x(draw, name, name_font, img_width), name_y), name, fill=purple_color, font=name_font)

    # 3. Course Name (e.g. “AI Frontend”) - centered between y=612 and y=711, purple bold
    course_font_size = max(24, int(40 * scale_y))
    course_font = fit_font(draw, course, font_bold_path, img_width * 0.65, course_font_size)
    try:
        c_bbox = draw.textbbox((0, 0), course, font=course_font)
        c_h = c_bbox[3] - c_bbox[1]
        course_y = int(661 * scale_y) - c_h // 2
    except Exception:
        course_y = int(640 * scale_y)
    draw.text((center_x(draw, course, course_font, img_width), course_y), course, fill=purple_color, font=course_font)

    # 4. Date of Completion (e.g. 17 September 2026)
    date_font_size = max(14, int(20 * scale_y))
    date_font = _get_font(font_regular_path, date_font_size)
    draw.text((int(420 * scale_x), int(928 * scale_y)), issued_date_str, fill=dark_color, font=date_font)

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



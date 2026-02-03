from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from django.conf import settings


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

    template_path = Path(settings.MEDIA_ROOT) / "certificates" / "4016369-ai (1).png"
    output_dir = Path(settings.MEDIA_ROOT) / "certificates"

    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{certificate.certificate_number}.png"

    img = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    img_width, img_height = img.size
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    name = certificate.student_name
    course = certificate.course_name

    name_font = fit_font(draw, name, font_path, img_width * 0.45, 54)
    course_font = fit_font(draw, course, font_path, img_width * 0.5, 36)
    small_font = ImageFont.truetype(str(font_path), 18)

    draw.text((int(img_width * 0.865), int(img_height * 0.055)),
              certificate.certificate_number, fill="black", font=small_font)

    name_y = int(img_height * 0.45)
    draw.text((center_x(draw, name, name_font, img_width), name_y),
              name, fill="black", font=name_font)

    course_y = name_y + 140
    draw.text((center_x(draw, course, course_font, img_width), course_y),
              course, fill="black", font=course_font)
    
    date_y = 0.79
    duration_y = 0.83

    draw.text((int(img_width * 0.14), int(img_height * date_y)),
              certificate.issued_date.strftime("%d-%m-%Y"),
              fill="black", font=small_font)

    draw.text((int(img_width * 0.14), int(img_height * duration_y)),
              certificate.course_duration,
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



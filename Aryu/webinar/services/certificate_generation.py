from PIL import Image, ImageDraw, ImageFont
from datetime import date
import os
import uuid


def generate_certificate(
    template_path,
    output_dir,          # ⬅ directory, NOT full file path
    name,
    course_name,
    issue_date,
    duration,
    certificate_id
):
    """
    Generates a high-quality JPEG certificate with cache-safe output
    """

    # Always create unique filename (IMPORTANT for JPEG)
    filename = f"certificate_{certificate_id}_{uuid.uuid4().hex}.jpg"
    output_path = os.path.join(output_dir, filename)

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Load template safely
    with Image.open(template_path) as base_img:
        image = base_img.convert("RGB")

    draw = ImageDraw.Draw(image)

    # Font paths (Linux)
    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    name_font = ImageFont.truetype(FONT_BOLD, 70)
    course_font = ImageFont.truetype(FONT_BOLD, 48)
    small_font = ImageFont.truetype(FONT_REGULAR, 30)

    # ---- TEXT POSITIONS ----
    NAME_Y = 540
    COURSE_Y = 650
    DATE_POS = (350, 820)
    DURATION_POS = (350, 870)
    CERT_ID_POS = (1450, 120)

    # Helper for center alignment
    def center_text(text, font, y):
        width = draw.textlength(text, font=font)
        return ((image.width - width) // 2, y)

    # ---- DRAW TEXT ----
    draw.text(
        center_text(name, name_font, NAME_Y),
        name,
        fill="#000000",
        font=name_font
    )

    draw.text(
        center_text(course_name, course_font, COURSE_Y),
        course_name,
        fill="#c57b2a",
        font=course_font
    )

    draw.text(
        DATE_POS,
        f"DATE: {issue_date}",
        fill="#000000",
        font=small_font
    )

    draw.text(
        DURATION_POS,
        f"DURATION: {duration}",
        fill="#000000",
        font=small_font
    )

    draw.text(
        CERT_ID_POS,
        f"Certificate ID: {certificate_id}",
        fill="#8a8a8a",
        font=small_font
    )

    # SAVE JPEG PROPERLY (THIS IS THE KEY)
    image.save(
        output_path,
        format="JPEG",
        quality=95,
        subsampling=0,   # ⬅ Prevents text blur
        optimize=True
    )

    return output_path

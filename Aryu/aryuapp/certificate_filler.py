import re
import os
from PIL import Image, ImageDraw, ImageFont

def fill_certificate_template(template_path, output_path, replacements, font_path):
    """
    Replaces placeholders like {{ Name }} in a certificate template image with actual values.
    """

    # Load template image
    img = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # Font settings (adjust as needed)
    base_font_size = 40
    font = ImageFont.truetype(font_path, base_font_size)

    # Define approximate positions for known placeholders
    placeholder_positions = {
        "Student_Name": (850, 430),
        "Course_Name": (850, 550),
        "Duration": (850, 600),
        "Issuing_Date": (320, 850),
        "Signature": (1350, 850)
    }

    # Function to auto-adjust font size to fit within width limit
    def fit_text_to_width(draw, text, font_path, max_width, start_size=60):
        font_size = start_size
        font = ImageFont.truetype(font_path, font_size)
        text_width = draw.textlength(text, font=font)
        while text_width > max_width and font_size > 10:
            font_size -= 2
            font = ImageFont.truetype(font_path, font_size)
            text_width = draw.textlength(text, font=font)
        return font

    # Iterate through placeholders and draw text
    for key, value in replacements.items():
        if key not in placeholder_positions:
            print(f"⚠️ Skipping unknown placeholder: {key}")
            continue

        x, y = placeholder_positions[key]

        # Remove curly braces manually if still in template text
        clean_text = re.sub(r"[\{\}]+", "", str(value)).strip()

        # Adjust font size dynamically
        font = fit_text_to_width(draw, clean_text, font_path, 500)

        # Draw the text centered horizontally
        text_width = draw.textlength(clean_text, font=font)
        draw.text((x - text_width / 2, y), clean_text, fill=(0, 0, 0), font=font)

        print(f"✅ Filled '{key}' with '{clean_text}' at position ({x}, {y})")

    # Save output image
    img.save(output_path)
    print(f"\n🎉 Certificate saved to: {output_path}")

if __name__ == "__main__":
    template_path = r"D:\LMS - Summa\ay-lms-python\Aryu\aryuapp\static\aryuapp\img\certificate of Completion (3).png"
    output_path = r"D:\LMS - Summa\ay-lms-python\Aryu\aryuapp\static\aryuapp\img\certificate_filled_final.png"
    font_path = r"C:\Windows\Fonts\arialbd.ttf"  # bold Arial font looks better for certificates

    replacements = {
        "Student_Name": "John Doe",
        "Course_Name": "Japanese Level 1",
        "Duration": "Jan 2024 - Mar 2024",
        "Issuing_Date": "27 Oct 2025",
        "Signature": "Mr. Tanaka"
    }

    fill_certificate_template(template_path, output_path, replacements, font_path)
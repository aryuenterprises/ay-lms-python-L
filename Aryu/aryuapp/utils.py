from .models import *
from PIL import Image, ImageDraw, ImageFont
import os
import re
from django.core.cache import cache
from rest_framework.response import Response
import pytesseract
from PIL import Image, ImageDraw, ImageFont
from pytesseract import Output
import random
import hashlib
import json
import string
from django.core.mail import send_mail, EmailMultiAlternatives
from django.conf import settings



def get_real_user(self, jwt_user):
            user_type = getattr(jwt_user, "user_type", None)
            if user_type == "student":
                return Student.objects.filter(student_id=jwt_user.student_id).first()
            elif user_type == "admin":
                return Trainer.objects.filter(username=jwt_user.username).first()
            elif user_type == "super_admin":
                return User.objects.filter(id=jwt_user.id).first()
            return None

def generate_cache_key(prefix, request, args, kwargs):

    data = {
        "prefix": prefix,
        "path": request.path,
        "query_params": request.query_params.dict(),
        "args": args,
        "kwargs": kwargs,
    }

    raw = json.dumps(data, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()


def cache_api(prefix, timeout=120):

    def decorator(func):
        def wrapper(self, request, *args, **kwargs):

            # Only cache GET requests
            if request.method != "GET":
                return func(self, request, *args, **kwargs)

            # Build cache key
            cache_key = generate_cache_key(prefix, request, args, kwargs)

            # Fetch from Redis
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)

            # Run the function
            response = func(self, request, *args, **kwargs)

            # Cache successful responses
            if response.status_code in (200, 201):
                cache.set(cache_key, response.data, timeout)

            return response

        return wrapper
    return decorator

def delete_cache_pattern(pattern):
    try:
        redis_client = cache.client.get_client(write=True)
        cursor = 0
        keys = []
        while True:
            cursor, found_keys = redis_client.scan(cursor, match=pattern)
            keys.extend(found_keys)
            if cursor == 0:
                break
        if keys:
            redis_client.delete(*keys)
    except Exception as e:
        print("Cache cleanup error:", e)

def generate_complex_otp(length=6):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choices(chars, k=length))

def send_otp_email(email, otp):
    subject = "Aryu Academy – Password Reset OTP"

    background_url = "https://aylms.aryuprojects.com/api/media/email/banner.svg"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0; padding:0; font-family:Arial, Helvetica, sans-serif;">

      <!-- FULL BACKGROUND -->
      <table width="100%" cellpadding="0" cellspacing="0"
        style="background:url('{background_url}') no-repeat center top;
               background-size:cover; padding:60px 0;">

        <tr>
          <td align="right" style="padding-right:10vw;">

            <!-- FLOATING OTP CARD -->
            <table width="420" cellpadding="0" cellspacing="0"
              style="background:#0c0c0c;
                     border-radius:14px;
                     backdrop-filter:blur(8px);
                     box-shadow:0 0 25px rgba(255,0,0,0.45);
                     overflow:hidden;">

              <!-- BODY -->
              <tr>
                <td style="padding:35px 35px; text-align:center;">

                  <h2 style="margin:0; color:#ffffff; font-size:26px; font-weight:700;">
                    Password Reset OTP
                  </h2>

                  <p style="color:#cccccc; margin-top:10px; font-size:14px;">
                    Use the OTP below to reset your password.
                  </p>

                  <!-- OTP BOX -->
                  <div style="
                    margin-top:25px;
                    background:linear-gradient(135deg, #4a0000, #b30000);
                    padding:22px 30px;
                    border-radius:12px;
                    font-size:32px;
                    font-weight:700;
                    color:#ffffff;
                    letter-spacing:6px;
                    box-shadow:
                      0 0 12px rgba(255, 0, 0, 0.60),
                      inset 0 0 10px rgba(0, 0, 0, 0.5);
                  ">
                    {otp}
                  </div>

                  <p style="margin-top:25px; font-size:14px; color:#cccccc; line-height:22px;">
                    This OTP is valid for <strong>10 minutes</strong>.<br>
                    Do not share this code with anyone.
                  </p>

                </td>
              </tr>

              <!-- FOOTER -->
              <tr>
                <td style="background:#0c0c0.45c; padding:15px; text-align:center;
                           font-size:12px; color:#888;">
                  © {datetime.now().year} Aryu Academy. All rights reserved.
                </td>
              </tr>

            </table>

          </td>
        </tr>

      </table>

    </body>
    </html>
    """

    email_msg = EmailMultiAlternatives(
        subject,
        "",
        settings.DEFAULT_FROM_EMAIL,
        [email]
    )
    email_msg.attach_alternative(html_content, "text/html")
    return email_msg.send()


def send_welcome_email(student):
    subject = f"🎉 Welcome {student.first_name}! Your Aryu Academy Journey Begins 🚀"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [student.email]

    text_content = f"""
Hi {student.first_name},

Welcome to Aryu Academy! 🎓 We are thrilled to have you join our learning community.

👉 Use the button below to log in and start your journey:
https://portal.aryuacademy.com/dashboard

📞 For queries, call us at 9685741253.

Best wishes,  
Team Aryu Academy
"""

    html_content = f"""
    <html>
      <body style="font-family: 'Segoe UI', Roboto, Arial, sans-serif; margin:0; padding:0; background:#f4f7fb;">
        <table align="center" width="650" cellpadding="0" cellspacing="0" 
               style="background:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 8px 20px rgba(0,0,0,0.1); margin:40px auto;">
          
          <!-- Header Banner -->
          <tr>
            <td align="center" bgcolor="#800000" style="padding:35px 20px;">
              <h1 style="color:#ffffff; font-size:32px; margin:0;">Aryu Academy</h1>
              <p style="color:#f8d7da; font-size:16px; margin:10px 0 0;">Unlock your future with learning</p>
            </td>
          </tr>

          <!-- Hero Section -->
          <tr>
            <td align="center" style="padding:40px 30px;">
              <h2 style="color:#333; margin:0 0 15px;">Welcome aboard, <span style="color:#800000;">{student.first_name}</span>! 🚀</h2>
              <p style="color:#666; font-size:16px; line-height:1.6; margin:0;">
                You’ve taken the first step towards mastering your future.  
                Let’s make your learning journey <b>fun, engaging, and successful</b>.  
              </p>
            </td>
          </tr>

          <!-- Details Card -->
        <div style="background:#f9f9f9; padding:12px; border-radius:8px; 
            font-family:Arial, sans-serif; font-size:13px; color:#333;">

            <p style="margin:0; font-weight:bold; font-size:14px;">
                📌 Your Registration Details:
            </p>

            <p style="margin:6px 0 0; font-size:12px; line-height:2;">
                👤 <b>Username:</b> {student.username} &nbsp; | &nbsp; <br>
                📧 <b>Email:</b> {student.email} &nbsp; | &nbsp; <br>
                🆔 <b>ID:</b> {student.registration_id}
            </p>
        </div>

            <!-- Smaller button -->
            <div style="text-align:center; margin:18px 0;">
            <a href="https://portal.aryuacademy.com/dashboard"
                style="display:inline-block; background:linear-gradient(45deg,#b22222,#8b0000);
                        color:#fff; padding:8px 18px; font-size:14px; font-weight:bold;
                        border-radius:6px; text-decoration:none;">
                🔑 Go to Dashboard
            </a>
            </div>

          <!-- Bonus Section -->
          <tr>
            <td align="center" style="padding:20px 30px; background:#fafafa; border-top:1px solid #eee;">
              <h3 style="margin:0; color:#333;">✨ What’s Next?</h3>
              <p style="margin:10px 0 0; color:#555; font-size:15px; line-height:1.6;">
                ✅ Explore your courses <br>
                ✅ Track your progress <br>
                ✅ Get certificates on completion 🏅
              </p>
            </td>
          </tr>

          <!-- Support -->
          <tr>
            <td align="center" style="padding:30px 20px; color:#555; font-size:14px;">
              📞 Need help? Call us at <b>8122869706</b>
              <br>or visit <a href="https://aryuacademy.com" style="color:#800000; text-decoration:none;">Aryu Academy Portal</a>.
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td bgcolor="#800000" style="padding:15px; text-align:center; font-size:12px; color:#fff;">
              © {datetime.now().year} Aryu Academy. All rights reserved.
              <br><span style="color:#ddd;">Building careers, one student at a time 💡</span>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """

    email = EmailMultiAlternatives(subject, text_content, from_email, to)
    email.attach_alternative(html_content, "text/html")
    email.send()

def has_permission(user, module_id, actions, require_all=False):
    """
    Check if a user (any type) has permission(s) on a module.
    """
    # Get role ID as integer
    role = getattr(user, "role", None)
    role_id = getattr(user, "role_id", None)
    
    if role:
        role_id = role.role_id  # always integer
    if not role_id:
        return False

    # Super admin check
    try:
        role_obj = Role.objects.get(pk=role_id)
        if role_obj.name.lower() == "super_admin":
            return True
    except Role.DoesNotExist:
        return False

    # Fetch RoleModulePermission
    try:
        role_module_perm = RoleModulePermission.objects.get(
            role_id=role_id,
            module_permission_id=module_id
        )
    except RoleModulePermission.DoesNotExist:
        return False

    allowed_actions = set(role_module_perm.allowed_actions)
    actions_set = set(actions)

    if require_all:
        return actions_set.issubset(allowed_actions)  # All actions required
    else:
        return bool(allowed_actions & actions_set)    # At least one action allowed


def get_protected_file_url(request, file_field):
    """
    Returns full URL for file if request has a valid authenticated user.
    Otherwise returns None.
    """
    if not request or not getattr(request.user, "is_authenticated", False):
        return None

    if file_field and hasattr(file_field, 'url'):
        # build absolute URL
        return request.build_absolute_uri(file_field.url)
    return None

def _safe_int_conf(val):
    try:
        return int(val)
    except Exception:
        return -1


def _fit_font_to_box(draw, text, font_path, box_w, box_h, manual_size=None, max_size=130, min_size=8, scale_factor=1.15):
    """
    Fit text automatically OR use a manually provided font size.
    """
    if manual_size:
        try:
            return ImageFont.truetype(font_path, manual_size)
        except Exception:
            return ImageFont.load_default()

    if font_path:
        size = max_size
        while size >= min_size:
            try:
                f = ImageFont.truetype(font_path, size)
            except Exception:
                return ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=f)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            if tw <= box_w / scale_factor and th <= box_h / scale_factor:
                return f
            size -= 2
        try:
            return ImageFont.truetype(font_path, min_size)
        except Exception:
            return ImageFont.load_default()
    else:
        return ImageFont.load_default()


def replace_placeholders_using_ocr(template_path, output_path, replacements, font_path=None, preview=False):
    """
    Replaces placeholders ({{ Student_Name }}, etc.) with actual text, using OCR to locate them.
    Adds per-field manual font size and alignment control.
    """

    img = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    ocr = pytesseract.image_to_data(img, output_type=Output.DICT)

    lines = {}
    n = len(ocr['level'])
    for i in range(n):
        txt = str(ocr['text'][i]).strip()
        if txt == "":
            continue
        key = (ocr['block_num'][i], ocr['par_num'][i], ocr['line_num'][i])
        if key not in lines:
            lines[key] = {'words': [], 'boxes': []}
        left = int(ocr['left'][i])
        top = int(ocr['top'][i])
        w = int(ocr['width'][i])
        h = int(ocr['height'][i])
        lines[key]['words'].append(txt)
        lines[key]['boxes'].append((left, top, left + w, top + h))

    placeholder_re = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

    # Manual font size for each placeholder
    manual_font_sizes = {
        "Student_Name": 90,
        "Course_Name": 80,
        "Duration": 76,
        "Date": 65,
        "Signature": 75,
    }

    # Manual alignment offset (x, y)
    offsets = {
        "Student_Name": (0, 0),
        "Course_Name": (0, 0),
        "Duration": (0, 0),
        "Date": (0, 0),
        "Signature": (0, 0),
    }

    for key, info in lines.items():
        words = info['words']
        boxes = info['boxes']

        joined = ""
        word_spans = []
        for w in words:
            start = len(joined)
            if joined != "":
                joined += " "
            joined += w
            end = len(joined)
            word_spans.append((start, end))

        for match in placeholder_re.finditer(joined):
            key_name = match.group(1)
            if key_name not in replacements:
                continue

            match_start, match_end = match.span()
            idxs = [i for i, (s, e) in enumerate(word_spans) if not (e <= match_start or s >= match_end)]
            if not idxs:
                continue

            xs = [boxes[i][0] for i in idxs]
            ys = [boxes[i][1] for i in idxs]
            xs2 = [boxes[i][2] for i in idxs]
            ys2 = [boxes[i][3] for i in idxs]
            left = min(xs)
            top = min(ys)
            right = max(xs2)
            bottom = max(ys2)

            pad_x = max(2, int((right - left) * 0.05))
            pad_y = max(2, int((bottom - top) * 0.25))
            left_p = max(0, left - pad_x)
            top_p = max(0, top - pad_y)
            right_p = min(img.width, right + pad_x)
            bottom_p = min(img.height, bottom + pad_y)
            box_w = right_p - left_p
            box_h = bottom_p - top_p

            if preview:
                draw.rectangle([(left_p, top_p), (right_p, bottom_p)], outline="red", width=2)

            sample_x = min(max(1, left_p + 2), img.width - 1)
            sample_y = min(max(1, top_p + 2), img.height - 1)
            try:
                bg_color = img.getpixel((sample_x, sample_y))
            except Exception:
                bg_color = (255, 255, 255, 255)

            draw.rectangle([(left_p, top_p), (right_p, bottom_p)], fill=bg_color)

            new_text = str(replacements[key_name]).strip()

            # 🅰️ Use manual font size if specified
            manual_size = manual_font_sizes.get(key_name)
            font = _fit_font_to_box(draw, new_text, font_path, box_w - 4, box_h - 4, manual_size=manual_size)

            tb = draw.textbbox((0, 0), new_text, font=font)
            text_w = tb[2] - tb[0]
            text_h = tb[3] - tb[1]

            text_x = left_p + (box_w - text_w) / 2
            text_y = top_p + (box_h - text_h) / 2

            # ✏️ Apply per-field offset
            if key_name in offsets:
                dx, dy = offsets[key_name]
                text_x += dx
                text_y += dy

            try:
                draw.text((text_x, text_y), new_text, font=font, fill=(0, 0, 0), stroke_width=1, stroke_fill=(255, 255, 255))
            except TypeError:
                draw.text((text_x, text_y), new_text, font=font, fill=(0, 0, 0))

    img.save(output_path)
    print(f"✅ Certificate saved at: {output_path}")

    if preview:
        try:
            img.show()
        except Exception:
            pass



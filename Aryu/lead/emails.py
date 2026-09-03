"""
lead/emails.py

Email utilities and dispatchers for the Lead module.
Handles Contact Us thank-you emails strictly when source == 'contact_us'.
Reuses existing project SMTP configuration, email structures, and branding.
"""

import logging
from datetime import datetime
from typing import Any, Dict
from aryuapp.models import Settings
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def get_brand_logo_url() -> str:
    """
    Resolves the official logo URL using the secondary_logo field from the Settings model.
    Optimized for O(1) performance using database-level field projection.
    """
    media_base_url = getattr(settings, "MEDIA_BASE_URL", "https://portal.aryuacademy.com/api").rstrip("/")

    try:
        # Fetch only the secondary_logo field value without loading the full model object into memory
        logo_file = Settings.objects.values_list("secondary_logo", flat=True).first()

        if logo_file:
            # Clean leading slash if present to guarantee well-formed URL join
            logo_path = logo_file if logo_file.startswith("media/") else f"media/{logo_file.lstrip('/')}"
            return f"{media_base_url}/{logo_path}"

    except Exception as exc:
        logger.debug("Failed to retrieve Settings model for secondary_logo: %s", exc)

    # Fallback to standard email logo path
    return f"{media_base_url}/media/logos/aryu_logo_Vgz0Png.png"


def build_contact_us_email_context(lead: Any) -> Dict[str, Any]:
    """
    Builds the template context dictionary for the Contact Us thank-you email.
    """
    name = (getattr(lead, "name", None) or "").strip() or "Valued Customer"
    email = (getattr(lead, "email", None) or "").strip()
    phone = (getattr(lead, "phone", None) or "").strip()
    course = (
        getattr(lead, "course", None)
        or getattr(lead, "course_interested_in", None)
        or ""
    ).strip()
    message = (getattr(lead, "message", None) or "").strip()
    city = (getattr(lead, "city", None) or "").strip()
    website_url = getattr(settings, "FRONTEND_URL", "https://aryuacademy.com").rstrip("/")
    if "portal.aryuacademy.com" in website_url:
        website_url = "https://aryuacademy.com"

    return {
        "lead_name": name,
        "lead_email": email,
        "lead_phone": phone,
        "course": course,
        "message": message,
        "city": city,
        "website_url": website_url,
        "logo_url": get_brand_logo_url(),
        "current_year": datetime.now().year,
        "support_email": getattr(settings, "DEFAULT_FROM_EMAIL", "support@aryuacademy.com"),
    }


def send_contact_us_thank_you_email(lead: Any, run_on_commit: bool = True) -> bool:
    """
    Sends a Contact Us thank-you email strictly when lead.source == 'contact_us'.

    Rules & Invariants:
      1. Source check: ONLY sends when source == 'contact_us'. Any other source sends NO email.
      2. Valid email: Gracefully skips without error if email is missing, blank, or invalid.
      3. Transaction safety: Dispatches via transaction.on_commit when inside an atomic block,
         guaranteeing the email is NEVER sent if database lead creation fails or rolls back.
      4. Resilience: All network/SMTP errors are logged and caught so lead creation never fails.
    """
    if not lead:
        return False

    # 1. Strict source check: ONLY when source == 'contact_us'
    source = str(getattr(lead, "source", None) or "").strip().lower()
    if source != "contact_us":
        logger.debug(
            "[Contact Us Email] Skipped for Lead ID=%s: source '%s' is not 'contact_us'.",
            getattr(lead, "id", "N/A"),
            source,
        )
        return False

    # 2. Validate recipient email gracefully
    recipient_email = str(getattr(lead, "email", None) or "").strip()
    if not recipient_email or "@" not in recipient_email:
        logger.info(
            "[Contact Us Email] Skipped for Lead ID=%s: missing or invalid email ('%s').",
            getattr(lead, "id", "N/A"),
            recipient_email,
        )
        return False

    context = build_contact_us_email_context(lead)
    subject = "Thank You for Contacting Aryu Academy"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "support@aryuacademy.com")

    # Plain text version
    course_line = f"Course / Interest: {context['course']}\n" if context["course"] else ""
    city_line = f"City: {context['city']}\n" if context["city"] else ""
    message_line = f"Message: {context['message']}\n" if context["message"] else ""

    text_content = f"""Dear {context['lead_name']},

Thank you for contacting Aryu Academy! We have successfully received your enquiry.

Your Enquiry Details:
----------------------------------------
Name: {context['lead_name']}
Email: {context['lead_email']}
Phone: {context['lead_phone']}
{course_line}{city_line}{message_line}----------------------------------------

What happens next?
1. Our academic team will review your enquiry.
2. One of our counsellors will contact you to provide course details, syllabus, and schedules.
3. We'll assist you in choosing the best program tailored to your career goals.

For immediate assistance, call us at +91 81228 69706 or reply to this email at {context['support_email']}.

Best regards,
Aryu Academy Team
{context['website_url']}
"""

    def _execute_send() -> bool:
        try:
            html_content = render_to_string(
                "emails/contact_us_thank_you.html",
                context,
            )

            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=from_email,
                to=[recipient_email],
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)

            logger.info(
                "[Contact Us Email] Thank-you email successfully sent to %s for Lead ID=%s.",
                recipient_email,
                getattr(lead, "id", "N/A"),
            )
            return True
        except Exception as exc:
            logger.exception(
                "[Contact Us Email] Error sending thank-you email to %s for Lead ID=%s: %s",
                recipient_email,
                getattr(lead, "id", "N/A"),
                exc,
            )
            return False

    connection = transaction.get_connection()
    if run_on_commit and connection.in_atomic_block:
        logger.info(
            "[Contact Us Email] Registered on_commit hook for Lead ID=%s (Email: %s).",
            getattr(lead, "id", "N/A"),
            recipient_email,
        )
        transaction.on_commit(_execute_send)
        return True
    else:
        return _execute_send()

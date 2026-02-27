# utils/webinar_token.py
import hashlib
from django.utils import timezone
from aryuapp.models import StudentTicket


def get_webinar_duration_text(webinar):
    """
    Returns a human-readable duration string for certificate.
    Webinar model does not store duration explicitly.
    """

    # If webinar is completed, we can assume a standard duration
    if webinar.is_completed:
        return "Webinar Session"

    # Otherwise fallback
    return "Live Webinar"


def get_ticket_from_token(raw_token):
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    return (
        StudentTicket.objects
        .select_related("webinar_participant")
        .prefetch_related(
            "attachments",
            "replies"
        )
        .filter(
            token_hash=token_hash,
            token_expires_at__gt=timezone.now()
        )
        .first()
    )
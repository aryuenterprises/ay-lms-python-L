from datetime import timedelta


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

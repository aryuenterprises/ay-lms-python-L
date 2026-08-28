# webinar_bonus/services.py

from webinar.models import WebinarRegistration
from webinar_bonus.models import BonusFile
from django.core.mail import EmailMultiAlternatives
from django.conf import settings

MIN_DURATION = 90 * 60  # 1.5 hours


def process_webinar_bonus(webinar):

    registrations = WebinarRegistration.objects.filter(webinar=webinar)

    bonus_files = BonusFile.objects.filter(
        bonus__webinar=webinar
    )

    for reg in registrations:

        summary = getattr(reg, "attendance_summary", None)

        # ❌ skip if no attendance
        if not summary:
            continue

        # ✅ CONDITION → 1.5 hours
        if summary.total_duration_seconds >= MIN_DURATION:

            send_bonus_email(reg, webinar, bonus_files)
#serives/zoom_attendance_service.py
from datetime import datetime
from django.utils.timezone import make_aware
from webinar.models import *
from webinar.views import fetch_zoom_participants


MIN_CERTIFICATE_SECONDS = 45 * 60

def sync_zoom_attendance(session: WebinarSession):
    participants = fetch_zoom_participants(session.zoom_meeting_id)

    for p in participants:
        email = p.get("user_email")
        if not email:
            continue

        try:
            registration = WebinarRegistration.objects.get(
                webinar=session.webinar,
                email=email
            )
        except WebinarRegistration.DoesNotExist:
            continue

        join_time = make_aware(
            datetime.fromisoformat(p["join_time"].replace("Z", "+00:00"))
        )
        leave_time = make_aware(
            datetime.fromisoformat(p["leave_time"].replace("Z", "+00:00"))
        )

        duration = p["duration"] * 60

        WebinarAttendanceLog.objects.create(
            registration=registration,
            join_time=join_time,
            leave_time=leave_time,
            duration_seconds=duration
        )

    _update_attendance_summary(session.webinar)

def _update_attendance_summary(webinar):
    for reg in webinar.registrations.all():
        logs = reg.attendance_logs.all()
        if not logs.exists():
            continue

        total_seconds = sum(l.duration_seconds for l in logs)

        summary, _ = WebinarAttendanceSummary.objects.get_or_create(
            registration=reg
        )

        summary.total_duration_seconds = total_seconds
        summary.join_count = logs.count()
        summary.first_join_at = logs.first().join_time
        summary.last_leave_at = logs.last().leave_time
        summary.eligible_for_certificate = (
            total_seconds >= MIN_CERTIFICATE_SECONDS
        )
        summary.save()

        reg.attended = True
        reg.save(update_fields=["attended"])

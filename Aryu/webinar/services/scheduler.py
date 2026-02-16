from datetime import timedelta
from django.utils.timezone import now

from webinar.tasks import (
    send_webinar_reminder_task,
    send_webinar_joining_task,
    send_webinar_live_task,
)


def schedule_webinar_messages(registration):
    """
    Schedules ALL future WhatsApp messages for a webinar registration.
    Called ONCE after successful registration / payment.
    """

    webinar = registration.webinar
    start = webinar.scheduled_start
    current_time = now()

    # Do not schedule past webinars
    if start <= current_time:
        return

    # -------------------------
    # 3 DAYS BEFORE
    # -------------------------
    eta_3d = start - timedelta(days=3)
    if eta_3d > current_time:
        send_webinar_reminder_task.apply_async(
            args=[registration.id, "3 days",
                  "Your webinar is coming soon. Make sure you don't miss it!"],
            eta=eta_3d
        )

    # -------------------------
    # 2 DAYS BEFORE
    # -------------------------
    eta_2d = start - timedelta(days=2)
    if eta_2d > current_time:
        send_webinar_reminder_task.apply_async(
            args=[registration.id, "2 days",
                  "Your webinar is approaching. Stay prepared!"],
            eta=eta_2d
        )

    # -------------------------
    # 1 DAY BEFORE
    # -------------------------
    eta_1d = start - timedelta(days=1)
    if eta_1d > current_time:
        send_webinar_reminder_task.apply_async(
            args=[registration.id, "1 day",
                  "Your webinar is tomorrow. Block your calendar!"],
            eta=eta_1d
        )

    # -------------------------
    # SAME DAY (10 AM)
    # -------------------------
    same_day_morning = start.replace(hour=10, minute=0, second=0, microsecond=0)
    if same_day_morning > current_time:
        send_webinar_reminder_task.apply_async(
            args=[registration.id, "today",
                  "Make sure you are in a calm place with a stable internet connection."],
            eta=same_day_morning
        )

    # -------------------------
    # 15 MINUTES BEFORE
    # -------------------------
    eta_15m = start - timedelta(minutes=15)
    if eta_15m > current_time:
        send_webinar_reminder_task.apply_async(
            args=[registration.id, "15 mins",
                  "Please keep your laptop ready and join on time."],
            eta=eta_15m
        )

    # -------------------------
    # JOINING MESSAGE (5 MIN BEFORE)
    # -------------------------
    eta_join = start - timedelta(minutes=5)
    if eta_join > current_time:
        send_webinar_joining_task.apply_async(
            args=[registration.id],
            eta=eta_join
        )

    # -------------------------
    # LIVE MESSAGE (AT START TIME)
    # -------------------------
    if start > current_time:
        send_webinar_live_task.apply_async(
            args=[registration.id],
            eta=start
        )


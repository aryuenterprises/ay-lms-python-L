# webinar/services/signaling.py

from django.utils import timezone
from django.db import transaction
from asgiref.sync import async_to_sync

from channels.layers import get_channel_layer

from webinar.models import Webinar, WebinarSession


def _notify(webinar_id, event, payload):
    """
    Internal helper to notify webinar WebSocket group
    """
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"webinar_{webinar_id}",
        {
            "type": "webinar_message",
            "event": event,
            "payload": payload,
        }
    )


@transaction.atomic
def start_webinar(webinar_id, user=None):
    """
    Start a webinar session (idempotent)
    """
    webinar = Webinar.objects.select_for_update().get(id=webinar_id)

    if webinar.status == "LIVE":
        return  # already live

    session, _ = WebinarSession.objects.get_or_create(webinar=webinar)

    if not session.started_at:
        session.started_at = timezone.now()
        session.started_by = user
        session.save()

    webinar.status = "LIVE"
    webinar.save(update_fields=["status"])

    _notify(
        webinar_id,
        event="start",
        payload={
            "started_at": session.started_at.isoformat(),
        }
    )


@transaction.atomic
def end_webinar(webinar_id):
    """
    End a live webinar
    """
    webinar = Webinar.objects.select_for_update().get(id=webinar_id)

    if webinar.status != "LIVE":
        return

    session = webinar.session
    session.ended_at = timezone.now()
    session.save(update_fields=["ended_at"])

    webinar.status = "COMPLETED"
    webinar.save(update_fields=["status"])

    _notify(
        webinar_id,
        event="end",
        payload={
            "ended_at": session.ended_at.isoformat(),
        }
    )


@transaction.atomic
def cancel_webinar(webinar_id):
    """
    Cancel a webinar before it starts
    """
    webinar = Webinar.objects.select_for_update().get(id=webinar_id)

    if webinar.status in ["LIVE", "COMPLETED"]:
        raise ValueError("Cannot cancel live or completed webinar")

    webinar.status = "CANCELLED"
    webinar.is_registration_open = False
    webinar.save(update_fields=["status", "is_registration_open"])

    _notify(
        webinar_id,
        event="cancel",
        payload={"message": "Webinar cancelled"},
    )

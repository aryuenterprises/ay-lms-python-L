import requests
from django.conf import settings

def get_zoom_access_token():
    url = "https://zoom.us/oauth/token"
    payload = {
        "grant_type": "account_credentials",
        "account_id": settings.ZOOM_ACCOUNT_ID
    }

    resp = requests.post(
        url,
        data=payload,
        auth=(settings.ZOOM_CLIENT_ID, settings.ZOOM_CLIENT_SECRET)
    )

    if resp.status_code != 200:
        raise Exception(f"Zoom token error {resp.status_code}: {resp.text}")

    return resp.json()["access_token"]


def create_zoom_meeting(topic, start_time, duration_minutes=60):
    token = get_zoom_access_token()

    url = "https://api.zoom.us/v2/users/me/meetings"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "topic": topic,
        "type": 2,
        "start_time": start_time.isoformat(),
        "duration": duration_minutes,
        "timezone": "UTC",

        # ------------------------
        # REGISTRATION REQUIRED
        # ------------------------
        "approval_type": 0,        # auto approve
        "registration_type": 1,    # each attendee registers

        "settings": {
            # ------------------------
            # FORCE LOGIN
            # ------------------------
            "meeting_authentication": True,

            # optional but recommended
            "waiting_room": True,
            "join_before_host": False,

            # collect email automatically
            "registrants_email_notification": True
        }
    }

    resp = requests.post(url, json=payload, headers=headers)

    if resp.status_code not in (200, 201):
        raise Exception(
            f"Zoom meeting error {resp.status_code}: {resp.text}"
        )

    data = resp.json()

    return {
        "meeting_id": str(data["id"]),
        "join_url": data["join_url"]
    }



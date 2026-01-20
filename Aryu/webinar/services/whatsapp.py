import requests
from celery import shared_task
from webinar.models import WebinarRegistration

WHATSAPP_TOKEN = "EAAvqXAq2IpoBQUpgy1ZBbFDCxK29lHzS3p0BL5N18wqXFZCq0eNVIFFlZA8Co2RO347i8tpwe0jpYRBGQUCXdO7OTcrZAimYVfI01fDkCcnOAv3UEQS5y6vnKg8qnEY1x8J3BY7Hxw62GWj2aWSvxKv4uez8WoLTHr5zHZBYziGtehJRjwaBGs2yc2v4yjrUY9hMEfYHQ0NBezB7O9wMqqcJWuq8GrhfJEAEEKc8iDrkuz1nMHQviRRqadaJmi0WIIwIPIFkTsKVxZBHrshCeZB9ZAuBCAZDZD"
PHONE_NUMBER_ID = "963430876847076"
WABA_ID="25956980047240783"

def send_whatsapp_message(phone, template_name, components):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en"},
            "components": components
        }
    }

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)
    return response.json()


def send_webinar_welcome_whatsapp(registration):
    webinar = registration.webinar

    return send_whatsapp_message(
        phone=registration.phone,
        template_name="webinar_welcome",
        components=[
            {
                "type": "header",
                "parameters": [
                    {
                        "type": "text",
                        "text": registration.name
                    }
                ]
            },

            {
                "type": "body",
                "parameters": [
                    {
                        "type": "text",
                        "text": webinar.title
                    },
                    {
                        "type": "text",
                        "text": webinar.start_date.strftime("%d %b %Y")
                    },
                    {
                        "type": "text",
                        "text": webinar.start_time.strftime("%I:%M %p")
                    }
                ]
            },
        ]
    )

@shared_task
def send_webinar_reminder(registration_id, time_left, instruction):
    reg = WebinarRegistration.objects.get(id=registration_id)
    webinar = reg.webinar

    send_whatsapp_message(
        phone=reg.phone,
        template_name="webinar_reminder",
        components=[
            # HEADER
            {
                "type": "header",
                "parameters": [
                    {
                        "type": "text",
                        "text": reg.name
                    }
                ]
            },

            # BODY
            {
                "type": "body",
                "parameters": [
                    {
                        "type": "text",
                        "text": webinar.title
                    },
                    {
                        "type": "text",
                        "text": time_left
                    },
                    {
                        "type": "text",
                        "text": webinar.start_date.strftime("%d %b %Y")
                    },
                    {
                        "type": "text",
                        "text": webinar.start_time.strftime("%I:%M %p")
                    },
                    {
                        "type": "text",
                        "text": instruction
                    }
                ]
            },

            # CTA BUTTONS (STATIC)
            {
                "type": "button",
                "sub_type": "url",
                "index": "0"
            },
            {
                "type": "button",
                "sub_type": "phone_number",
                "index": "1"
            }
        ]
    )


def send_webinar_joining_whatsapp(registration, join_url):
    webinar = registration.webinar

    return send_whatsapp_message(
        phone=registration.phone,  # format: 91XXXXXXXXXX
        template_name="webinar_joining",
        components=[
            # HEADER
            {
                "type": "header",
                "parameters": [
                    {
                        "type": "text",
                        "text": registration.name
                    }
                ]
            },

            # BODY
            {
                "type": "body",
                "parameters": [
                    {
                        "type": "text",
                        "text": webinar.title
                    },
                    {
                        "type": "text",
                        "text": webinar.start_date.strftime("%d %b %Y")
                    },
                    {
                        "type": "text",
                        "text": webinar.start_time.strftime("%I:%M %p")
                    },
                    {
                        "type": "text",
                        "text": join_url
                    }
                ]
            },

            # CTA BUTTONS (STATIC)
            {
                "type": "button",
                "sub_type": "url",
                "index": "0"
            },
            {
                "type": "button",
                "sub_type": "phone_number",
                "index": "1"
            }
        ]
    )



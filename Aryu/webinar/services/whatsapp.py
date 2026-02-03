import requests
from celery import shared_task
from webinar.models import WebinarRegistration

WHATSAPP_TOKEN = "EAAVj7xx32k0BQRgGkqV0vBAMoBm4m4sGkchg2BbZBoe7Ou6OdFopBYoNhipYqURs0HJTrxpAUIYdZBcItdZBZASwSmFYFQcVJyZApXDrZB6E2iVbZBOsV68hO7AcAbZBqZCDAaNRnZBGjvHuWcb7MSQVpnrMMReQT6XHicAtUMMSKcymZCPjwgdzty3iiRMtImuNQuqSGl4LHbFSrl2nyO28JsZCIZBCnAyFXKSZCYACNZBnV5CyFJ24RUDZCsWjQMTZBCqZAkjy6EnEbwduUdNcDUiT8nZADUZBohRj"
WHATSAPP_LIVE_TOKEN = "EAAVj7xx32k0BQsQqKdAz7cekGfckEZCSdEz6fL8YdVVSrTnRzjQnbWs78hRlqIxPJSb8r4uhjlI9crpNayZCV7VLLez2QNv5ZBljuDZBP3zWEZBOC1XNVk9FgqIamiKFZCFROV9s5Ycysj3NkNxBw5fqPyzkYMEFqOA3pgFHncOCYMkAeT5pc6m5azBcGZCafM44AZDZD"
PHONE_NUMBER_ID = "878484755357545" #"876623908875525" 
WABA_ID= "1430646228583413"  #"4298067283844773"

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
        "Authorization": f"Bearer {WHATSAPP_LIVE_TOKEN}",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)
    return response.json()


def send_webinar_welcome_whatsapp(registration):
    webinar = registration.webinar
    start_dt = webinar.scheduled_start
    print("Sending webinar welcome whatsapp to", registration.phone)
    return send_whatsapp_message(
        phone=f"91{registration.phone}",
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
                        "text": start_dt.strftime("%d %b %Y")
                    },
                    {
                        "type": "text",
                        "text": start_dt.strftime("%I:%M %p")
                    }
                ]
            }
            
        ]
        
    )

@shared_task
def send_webinar_reminder(registration_id, time_left, instruction):
    reg = WebinarRegistration.objects.get(id=registration_id)
    webinar = reg.webinar
    start_dt = webinar.scheduled_start

    # Ensure phone format: 91XXXXXXXXXX
    phone = reg.phone.strip()
    if phone.startswith("+"):
        phone = phone[1:]
    if not phone.startswith("91"):
        phone = "91" + phone

    print("Sending webinar reminder whatsapp to", phone)

    resp = send_whatsapp_message(
        phone=phone,
        template_name="webinar_reminder",
        components=[
            {
                "type": "header",
                "parameters": [
                    {"type": "text", "text": reg.name or ""}
                ]
            },
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": webinar.title},
                    {"type": "text", "text": time_left},
                    {"type": "text", "text": start_dt.strftime("%d %b %Y")},
                    {"type": "text", "text": start_dt.strftime("%I:%M %p")},
                    {"type": "text", "text": instruction},
                ]
            }
        ]
    )

    print("WhatsApp API response:", resp)
    return resp


def send_webinar_joining_whatsapp(registration, join_url):
    webinar = registration.webinar
    start_dt = webinar.scheduled_start
    return send_whatsapp_message(
        phone=f"91{registration.phone}",  # format: 91XXXXXXXXXX
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
                        "text": start_dt.strftime("%d %b %Y")
                    },
                    {
                        "type": "text",
                        "text": start_dt.strftime("%I:%M %p")
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
                "index": "0",
                "parameters": [
                    {"type": "text", "text": "something"}
                ]
            },
        ]
    )


def send_webinar_live_whatsapp(registration, join_url):
    webinar = registration.webinar
    start_dt = webinar.scheduled_start

    return send_whatsapp_message(
        phone=f"91{registration.phone}",
        template_name="webinar_live_now",
        components=[
            # HEADER
            {
                "type": "header",
                "parameters": [
                    
                ]
            },

            # BODY
            {
                "type": "body",
                "parameters": [
                    {"type": "text","text": registration.name},
                    {"type": "text", "text": webinar.title},
                    {"type": "text", "text": start_dt.strftime("%d %b %Y")},
                    {"type": "text", "text": start_dt.strftime("%I:%M %p")},
                    {"type": "text", "text": webinar.zoom_join_url},
                    
                ]
            }
        ]
    )


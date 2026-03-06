import requests
from celery import shared_task
from webinar.models import WebinarRegistration
import logging
from django.utils import timezone


logger = logging.getLogger(__name__)

WHATSAPP_TOKEN = "EAAWb62rlXVIBQth57cavJe1nEElv5fioVrCfThXRHnJDhOlNxriYZAI4Eq3y6QLNPtSac2ZAfHqNzqko27nQ22XSX87RUnsTr9PkqTOJod6dZAFswHUApOClZAMCWrhsZBsATaYtYCvvIs10dXDwjStSlvTCU59T3XrkuQ3VJBwIHf4VLHj7t9uTg8GLZAKPbxhhkIigctCGZC8hZAHBl9hEjy10h7IastzJ4cBCHN3JjAiqiIWZCgAndlTZChXGghK6JvGmD5DiZBuJKRvZA1qTusJOYCTzOQZDZD"
WHATSAPP_LIVE_TOKEN = "EAAVj7xx32k0BQtEwZBSDBuJZAkKReDvK4DJzlzoU8yoVC1WofQyF0OlGj74QizH7ml6mNWSk6FeH2ZAAq9ZCliZBiedxdFYPHJ8F9jddOShhtTFRZCR9NamcPYetv8k8BmGZA6Dd2qFdTtqWOr1Jqs5YtMSGSMmUZCFZC0dK98DgpZBLpkn2lYUwqAcv2KDh02egZDZD"
PHONE_NUMBER_ID = "878484755357545" #"878484755357545" #"876623908875525" 
WABA_ID= "1430646228583413"  #"4298067283844773"
"""
{
  "id": "26469123152676267",
  "name": "Yuvaraj T"
}
"""
AISENSY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY5ODlkMjRmYTA4M2Q2NWQ4NmUyNmRjNSIsIm5hbWUiOiJBcnl1IEFjYWRlbXkgUHJpdmF0ZSBMaW1pdGVkIiwiYXBwTmFtZSI6IkFpU2Vuc3kiLCJjbGllbnRJZCI6IjY5ODlkMjRmYTA4M2Q2NWQ4NmUyNmRjMCIsImFjdGl2ZVBsYW4iOiJGUkVFX0ZPUkVWRVIiLCJpYXQiOjE3NzA3MjQ0MjN9.kp-EwaczYRcTGAcsufhNO2XD-WVqqtKzQ7elQ4Bt35o"
AISENSY_API_URL = "https://backend.aisensy.com/campaign/t1/api/v2"

def normalize_phone(phone):
    """
    Converts phone to WhatsApp API format.
    Examples:
    +919876543210 -> 919876543210
    919876543210  -> 919876543210
    9876543210    -> 919876543210 (default India fallback)
    """

    phone = str(phone).strip().replace(" ", "")

    # remove +
    if phone.startswith("+"):
        phone = phone[1:]

    # fallback if only 10 digit number
    if len(phone) == 10:
        phone = f"91{phone}"

    return phone

def send_whatsapp_message(phone, template_name, parameters, media_url=None):
    payload = {
        "apiKey": AISENSY_API_KEY,
        "campaignName": template_name,
        "destination": phone,
        "userName": "Aryu Academy",
        "templateParams": parameters,
        "source": "webinar-system",
        "media": {},
        "buttons": [],
        "carouselCards": [],
        "location": {},
        "attributes": {},
        "paramsFallbackValue": {
            "FirstName": "User"
        }
    }

    if media_url:
        # Detect document vs image
        if media_url.lower().endswith(".pdf"):
            payload["media"] = {
                "url": media_url,
                "filename": "certificate.pdf"
            }
        else:
            payload["media"] = {
                "url": media_url,
                "filename": "media.jpg"
            }

    headers = {"Content-Type": "application/json"}

    response = requests.post(AISENSY_API_URL, json=payload, headers=headers)

    print("Status:", response.status_code)
    print("Response:", response.text)

    return response.json()


def send_webinar_welcome_whatsapp(registration):
    webinar = registration.webinar
    start_dt = timezone.localtime(webinar.scheduled_start)
    phone = normalize_phone(registration.phone)

    print("Sending webinar welcome whatsapp to", phone)

    res = send_whatsapp_message(
        phone=phone,
        template_name="Webinar Welcome Message",
        parameters=[
            webinar.title,
            start_dt.strftime("%d %b %Y"),
            start_dt.strftime("%I:%M %p"),
            webinar.waba_link
        ],
        media_url=webinar.get_image_url()  # header image
    )
    print("IST:", timezone.localtime(webinar.scheduled_start))
    print("WhatsApp API response:", res)
    return res

@shared_task
def send_webinar_reminder(registration_id, time_left):
    reg = WebinarRegistration.objects.get(id=registration_id)
    webinar = reg.webinar
    start_dt = timezone.localtime(webinar.scheduled_start)

    phone = reg.phone.strip()

    # Normalize phone
    if phone.startswith("+"):
        phone = phone[1:]
    if not phone.startswith("91"):
        phone = "91" + phone

    print("Sending webinar reminder whatsapp to", phone)

    resp = send_whatsapp_message(
        phone=phone,
        template_name="remainder",  # MUST match AiSensy campaign name exactly
        parameters=[
            webinar.title,                          # {{1}}
            time_left,                              # {{2}}
            start_dt.strftime("%d/%m/%Y"),          # {{3}}
            start_dt.strftime("%I:%M %p"),          # {{4}}
        ],
        media_url=webinar.get_image_url()          # Header Image
    )

    print("WhatsApp API response:", resp)
    return resp


def send_webinar_joining_whatsapp(registration, join_url):
    webinar = registration.webinar
    start_dt = timezone.localtime(webinar.scheduled_start)

    phone = normalize_phone(registration.phone)

    print("Sending webinar joining WhatsApp to", phone)

    response = send_whatsapp_message(
        phone=phone,
        template_name="webinar joining",
        parameters=[
            webinar.title,                   # {{1}}
            start_dt.strftime("%d/%m/%Y"),   # {{2}}
            start_dt.strftime("%I:%M %p"),   # {{3}}
            join_url                         # {{4}}
        ],
        media_url=webinar.get_image_url()
    )

    print("WhatsApp API response:", response)
    return response


def send_webinar_live_whatsapp(registration):
    webinar = registration.webinar
    start_dt = timezone.localtime(webinar.scheduled_start)

    phone = normalize_phone(registration.phone)

    print("Sending webinar live WhatsApp to", phone)

    response = send_whatsapp_message(
        phone=phone,
        template_name="Webinar Live Mess",
        parameters=[
            webinar.title,                         # {{1}}
            start_dt.strftime("%d/%m/%Y"),         # {{2}}
            start_dt.strftime("%I:%M %p"),         # {{3}}
        ],
        media_url=webinar.get_image_url()
    )

    print("WhatsApp API response:", response)
    return response


def send_webinar_certificate_whatsapp(certificate, phone):
    """
    Send certificate PDF via WhatsApp template (AiSensy)
    """

    logger.info("Sending webinar certificate WhatsApp to %s", phone)

    phone = normalize_phone(phone)

    pdf_url = certificate.certificate_file.url
    if not pdf_url.startswith("http"):
        pdf_url = f"https://portal.aryuacademy.com/api{pdf_url}"

    print(f"Certificate PDF URL: {pdf_url}")

    res = send_whatsapp_message(
        phone=phone,
        template_name="Webinar certificates",
        parameters=[
            certificate.student_name,   # {{1}}
            certificate.course_name     # {{2}}
        ],
        media_url=pdf_url
    )

    print("WhatsApp API response:", res)
    logger.info("WhatsApp API response: %s", res)

    return res


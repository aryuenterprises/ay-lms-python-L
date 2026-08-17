from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from datetime import datetime


def send_ebook_registration_email(registration):
    print("email is triggering")
    ebook = registration.ebook
    portal_link = "https://portal.aryuprojects.com/login"

    subject = f"Ebook Registration Successful - {ebook.title}"

    # Safely handle password if it doesn't exist on the registration model
    password_text = getattr(registration, "password", "N/A")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body>

      <p>Hello <strong>{registration.name}</strong>,</p>

      <p>Your ebook registration has been successfully completed.</p>

      <p><strong>Ebook:</strong> {ebook.title}</p>

      <h3>Your Login Details</h3>
      <p>Name: {registration.name}</p>
      <p>Email: {registration.email}</p>
      <p>Password: {password_text}</p>

      <p>
        Portal Link:
        <a href="{portal_link}">{portal_link}</a>
      </p>

      <p>Regards,<br>Aryu Academy</p>

    </body>
    </html>
    """

    email_msg = EmailMultiAlternatives(
        subject=subject,
        body="Your ebook registration is successful.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[registration.email],
    )

    email_msg.attach_alternative(html_content, "text/html")
    email_msg.send(fail_silently=False)
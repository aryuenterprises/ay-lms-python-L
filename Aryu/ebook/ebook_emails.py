from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from datetime import datetime


def send_ebook_registration_email(registration, password=None):
    print("email is triggering")
    ebook = registration.ebook
    portal_link = "https://portal.aryuprojects.com"

    subject = f"Ebook Registration Successful - {ebook.title}"

    if password:
        details_html = f"""
      <h3>Your Login Details</h3>
      <p>Name: {registration.name}</p>
      <p>Email: {registration.email}</p>
      <p>Password: {password}</p>
      <p>
        Portal Link:
        <a href="{portal_link}">{portal_link}</a>
      </p>
        """
    else:
        details_html = f"""
      <p>Your registration/purchase for <strong>{ebook.title}</strong> is completed!</p>
      <p>You can check your newly purchased ebook directly in the portal using your existing account credentials.</p>
      <p>
        Portal Link:
        <a href="{portal_link}">{portal_link}</a>
      </p>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body>

      <p>Hello <strong>{registration.name}</strong>,</p>

      <p>Your ebook registration has been successfully completed.</p>

      <p><strong>Ebook:</strong> {ebook.title}</p>

      {details_html}

      <p>Regards,<br>Aryu Academy</p>

    </body>
    </html>
    """

    email_msg = EmailMultiAlternatives(
        subject=subject,
        body=f"Your ebook registration for {ebook.title} is successful.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[registration.email],
    )

    email_msg.attach_alternative(html_content, "text/html")
    email_msg.send(fail_silently=False)
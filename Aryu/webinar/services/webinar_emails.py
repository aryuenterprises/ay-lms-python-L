from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from datetime import datetime


def send_webinar_registration_email(registration):
    webinar = registration.webinar

    subject = f"Registration Confirmed: {webinar.title}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0; padding:0; background-color:#f5f6fa; font-family:Arial, Helvetica, sans-serif;">

      <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f6fa; padding:40px 0;">
        <tr>
          <td align="center">
            <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,0.08);">

              <!-- Header -->
              <tr>
                <td style="background:#852121; padding:20px; border-radius:10px 10px 0 0; text-align:center;">
                  <h2 style="color:#ffffff; margin:0; font-size:20px;">
                    Webinar Registration Confirmed
                  </h2>
                </td>
              </tr>

              <!-- Body -->
              <tr>
                <td style="padding:30px; color:#333333; font-size:14px; line-height:1.6;">

                  <p style="margin:0 0 15px;">
                    Hello <strong>{registration.name}</strong>,
                  </p>

                  <p style="margin:0 0 15px;">
                    Thank you for registering for the following webinar:
                  </p>

                  <div style="background:#f8f9fa; padding:15px; border-radius:6px; margin-bottom:20px;">
                    <p style="margin:0 0 8px;"><strong>{webinar.title}</strong></p>
                    <p style="margin:0;">
                      <strong>Date:</strong> {webinar.scheduled_start.strftime('%d %b %Y')}<br>
                      <strong>Time:</strong> {webinar.scheduled_start.strftime('%I:%M %p')}
                    </p>
                  </div>

                  <p style="margin:0 0 10px; font-size:14px; color:#555;">
                    Join our WhatsApp group to receive important updates, reminders, and session materials related to the webinar.
                  </p>

                  <p style="word-break:break-all; color:#2b9627;">
                    <a href="{ webinar.waba_link }" style="color:#44a65c; text-decoration:none;">
                      { webinar.waba_link }
                    </a>
                  </p>

                  <p style="margin-top:25px;">
                    We look forward to your participation.
                  </p>

                  <p style="margin-top:30px; font-size:13px; color:#888888;">
                    Regards,<br>
                    Aryu Academy
                  </p>

                </td>
              </tr>

            </table>

            <!-- Footer -->
            <table width="520" cellpadding="0" cellspacing="0">
              <tr>
                <td align="center" style="padding:15px; font-size:12px; color:#999999;">
                  © {webinar.scheduled_start.year} Aryu Academy. All rights reserved.
                </td>

                <hr style="margin:25px 0; border:none; border-top:1px solid #eeeeee;">

                <p style="font-size:12px; color:#777777; line-height:1.5;">
                  By participating in this webinar, you agree to our
                  <a href="https://portal.aryuacademy.com/terms-and-conditions" style="color:#0d6efd; text-decoration:none;">
                    Terms & Conditions
                  </a>
                  and
                  <a href="https://portal.aryuacademy.com/privacy-policy" style="color:#0d6efd; text-decoration:none;">
                    Privacy Policy
                  </a>.
                </p>
              </tr>
            </table>

          </td>
        </tr>
      </table>

    </body>
    </html>
    """

    email_msg = EmailMultiAlternatives(
        subject=subject,
        body="Your webinar registration has been confirmed.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[registration.email],
    )
    email_msg.attach_alternative(html_content, "text/html")
    email_msg.send(fail_silently=False)


def send_webinar_certificate_email(registration, certificate_file):
    webinar = registration.webinar

    subject = f"Certificate of Completion - {webinar.title}"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [registration.email]

    # Plain text fallback (important for deliverability)
    text_content = f"""
Hi {registration.name or 'Participant'},

Thank you for attending the webinar "{webinar.title}".

Your Certificate of Completion is attached as a PDF.

We appreciate your participation.

Regards,
Aryu Academy
"""

    # HTML version
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0; padding:0; background-color:#f5f6fa; font-family:Arial, Helvetica, sans-serif;">

      <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f6fa; padding:40px 0;">
        <tr>
          <td align="center">

            <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,0.08);">
              <tr>
                <td height="20" style="font-size:0; line-height:0;">&nbsp;</td>
              </tr>
              <!-- Header -->
              <tr>
                <td style="background:#781b0d; padding:20px; border-radius:10px 10px 0 0; text-align:center;">
                  <h2 style="color:#ffffff; margin:0; font-size:20px;">
                    Certificate of Completion 
                  </h2>
                </td>
              </tr>

              <!-- Body -->
              <tr>
                <td style="padding:30px; color:#333333; font-size:14px; line-height:1.6;">

                  <p style="margin:0 0 15px;">
                    Hello <strong>{registration.name or 'Participant'}</strong>,
                  </p>

                  <p style="margin:0 0 15px;">
                    Thank you for successfully attending the webinar:
                  </p>

                  <div style="background:#f8f9fa; padding:15px; border-radius:6px; margin-bottom:20px;">
                    <p style="margin:0; font-weight:bold;">
                      {webinar.title}
                    </p>
                  </div>

                  <p style="margin:0 0 15px;">
                    Your Certificate of Completion is attached to this email as a PDF file.
                  </p>

                  <p style="margin:0 0 15px;">
                    We appreciate your participation and look forward to seeing you in future sessions.
                  </p>


                  <p style="margin-top:30px; font-size:13px; color:#888888;">
                    Regards,<br>
                    Aryu Academy
                  </p>

                </td>
              </tr>

            </table>

            <!-- Footer -->
            <table width="520" cellpadding="0" cellspacing="0">
              <tr>
                <td align="center" style="padding:15px; font-size:12px; color:#999999;">
                  © {webinar.scheduled_start.year if webinar.scheduled_start else ''} Aryu Academy. All rights reserved.
                </td>


                  <hr style="margin:25px 0; border:none; border-top:1px solid #eeeeee;">

                  <p style="font-size:12px; color:#777777; line-height:1.5;">
                    By accepting this certificate, you agree to our
                    <a href="https://portal.aryuacademy.com/terms-and-conditions" style="color:#781b0d; text-decoration:none;">
                      Terms & Conditions
                    </a>
                    and
                    <a href="https://portal.aryuacademy.com/privacy-policy" style="color:#781b0d; text-decoration:none;">
                      Privacy Policy
                    </a>.
                  </p>
              </tr>
            </table>

          </td>
        </tr>
      </table>

    </body>
    </html>
    """

    email_msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=from_email,
        to=to
    )

    email_msg.attach_alternative(html_content, "text/html")

    # Attach certificate PDF safely
    if certificate_file and hasattr(certificate_file, "path"):
        email_msg.attach_file(certificate_file.path)

    email_msg.send(fail_silently=False)


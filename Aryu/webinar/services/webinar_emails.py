from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from datetime import datetime


def send_webinar_registration_email(registration):
    webinar = registration.webinar

    subject = f"🎉 Welcome! You're Registered for {webinar.title}"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [registration.email]

    background_url = "https://aylms.aryuprojects.com/api/media/email/banner.svg"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0; padding:0; font-family:Arial, Helvetica, sans-serif;">

      <!-- FULL BACKGROUND -->
      <table width="100%" cellpadding="0" cellspacing="0"
        style="background:url('{background_url}') no-repeat center top;
               background-size:cover; padding:70px 0;">

        <tr>
          <td align="right" style="padding-right:10vw;">

            <!-- FLOATING CARD -->
            <table width="440" cellpadding="0" cellspacing="0"
              style="background:#0c0c0c;
                     border-radius:16px;
                     box-shadow:0 0 30px rgba(255,0,0,0.45);
                     overflow:hidden;">

              <!-- BODY -->
              <tr>
                <td style="padding:38px; text-align:center;">

                  <h2 style="margin:0; color:#ffffff; font-size:26px;">
                    🎉 Registration Confirmed
                  </h2>

                  <p style="color:#cccccc; margin-top:12px; font-size:14px;">
                    Welcome {registration.name}, you’re officially in!
                  </p>

                  <!-- WEBINAR TITLE -->
                  <div style="
                    margin-top:22px;
                    background:linear-gradient(135deg, #4a0000, #b30000);
                    padding:16px 22px;
                    border-radius:12px;
                    color:#ffffff;
                    font-size:18px;
                    font-weight:700;
                    box-shadow:0 0 14px rgba(255,0,0,0.6);
                  ">
                    {webinar.title}
                  </div>

                  <!-- DETAILS -->
                  <p style="margin-top:22px; font-size:14px; color:#dddddd; line-height:22px;">
                    📅 <b>Date:</b> {webinar.scheduled_start.strftime('%d %b %Y')}<br>
                    ⏰ <b>Time:</b> {webinar.scheduled_start.strftime('%I:%M %p')}
                  </p>

                  <!-- JOIN INFO -->
                  <p style="margin-top:18px; font-size:14px; color:#bbbbbb;">
                    🔗 <b>Join Link:</b><br>
                    {webinar.zoom_link or "Link will be shared before the session"}
                  </p>

                  <p style="margin-top:22px; font-size:13px; color:#aaaaaa;">
                    We’ll send you a reminder before the webinar starts ⏰
                  </p>

                </td>
              </tr>

              <!-- FOOTER -->
              <tr>
                <td style="background:#0c0c0c; padding:15px; text-align:center;
                           font-size:12px; color:#888;">
                  © {datetime.now().year} Aryu Academy. All rights reserved.
                </td>
              </tr>

            </table>

          </td>
        </tr>

      </table>

    </body>
    </html>
    """

    email_msg = EmailMultiAlternatives(
        subject,
        "",
        from_email,
        to
    )
    email_msg.attach_alternative(html_content, "text/html")
    return email_msg.send()


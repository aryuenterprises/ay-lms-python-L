from django.conf import settings
from django.core.mail import EmailMultiAlternatives


def send_bonus_email(reg, webinar, bonus_files):

    # 🔹 Build bonus links
    base_url = getattr(settings, "MEDIA_BASE_URL", "").rstrip("/")
    bonus_html = ""
    for file in bonus_files:
        if file.file and hasattr(file.file, "url"):
            file_path = file.file.url if file.file.url.startswith("/") else f"/{file.file.url}"
            file_url = f"{base_url}{file_path}"
            bonus_html += f"<li><a href='{file_url}'>Download PDF</a></li>"

    # 🔹 Email template
    html_content = f"""
    <div style="font-family: Arial; line-height:1.6;">
        <h2>🎉 Thank You for Attending!</h2>

        <p>Hi <b>{reg.name}</b>,</p>

        <p>
        Thank you for attending our webinar 
        <b>{webinar.title}</b>.
        </p>

        <p>
        We are happy to share the <b>recording</b> and <b>bonus materials</b>.
        </p>

        <h3>🎥 Webinar Recording</h3>
        <p>
            <a href="{webinar.video_url}" target="_blank">
                Watch Recording
            </a>
        </p>

        <h3>📂 Bonus Materials</h3>
        <ul>
            {bonus_html}
        </ul>

        <p>
        Keep learning and growing 🚀
        </p>

        <p>
        Regards,<br/>
        Team Aryu
        </p>
    </div>
    """

    email = EmailMultiAlternatives(
        subject=f"Bonus Materials - {webinar.title}",
        body="",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[reg.email],
    )

    email.attach_alternative(html_content, "text/html")
    email.send()
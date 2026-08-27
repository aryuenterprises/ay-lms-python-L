import logging
from django.core.mail import EmailMultiAlternatives
from django.conf import settings

logger = logging.getLogger(__name__)


def send_ebook_registration_email(registration, password=None):
    """
    Sends the Ebook registration success email formatted with the standardized
    brand design template used by the registration flows.
    """
    logger.info(f"Sending ebook registration success email for: {registration.email}")
    ebook = registration.ebook
    portal_link = getattr(settings, "PORTAL_URL", "https://portal.aryuacademy.com").rstrip("/")
    media_base_url = getattr(settings, "MEDIA_BASE_URL", "https://portal.aryuacademy.com").rstrip("/")

    subject = f"Ebook Registration Successful - {ebook.title}"

    if password:
        details_section = f"""
        <!-- CREDENTIALS BOX -->
        <table
            width="100%"
            cellpadding="0"
            cellspacing="0"
            border="0"
            style="
                margin-bottom: 30px;
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
            ">
            <tr>
                <td style="padding: 20px 24px">
                    <h3
                        style="
                            margin: 0 0 14px 0;
                            font-size: 18px;
                            color: #1e1b4b;
                            font-weight: 700;
                        ">
                        Your Account Login Credentials
                    </h3>
                    <p style="margin: 0 0 8px 0; font-size: 15px; color: #475569;">
                        <strong>Name:</strong> {registration.name}
                    </p>
                    <p style="margin: 0 0 8px 0; font-size: 15px; color: #475569;">
                        <strong>Email:</strong> {registration.email}
                    </p>
                    <p style="margin: 0 0 8px 0; font-size: 15px; color: #475569;">
                        <strong>Password:</strong>
                        <span
                            style="
                                font-family: monospace;
                                background: #e2e8f0;
                                padding: 3px 8px;
                                border-radius: 6px;
                                font-weight: 600;
                                color: #0f172a;
                            ">
                            {password}
                        </span>
                    </p>
                    <p style="margin: 0; font-size: 15px; color: #475569;">
                        <strong>Ebook:</strong> {ebook.title}
                    </p>
                </td>
            </tr>
        </table>
        """
    else:
        details_section = f"""
        <!-- DETAILS BOX -->
        <table
            width="100%"
            cellpadding="0"
            cellspacing="0"
            border="0"
            style="
                margin-bottom: 30px;
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
            ">
            <tr>
                <td style="padding: 20px 24px">
                    <h3
                        style="
                            margin: 0 0 14px 0;
                            font-size: 18px;
                            color: #1e1b4b;
                            font-weight: 700;
                        ">
                        Registration Details
                    </h3>
                    <p style="margin: 0 0 8px 0; font-size: 15px; color: #475569;">
                        <strong>Name:</strong> {registration.name}
                    </p>
                    <p style="margin: 0 0 8px 0; font-size: 15px; color: #475569;">
                        <strong>Email:</strong> {registration.email}
                    </p>
                    <p style="margin: 0 0 10px 0; font-size: 15px; color: #475569;">
                        <strong>Ebook:</strong> {ebook.title}
                    </p>
                    <p style="margin: 0; font-size: 14px; color: #64748b; line-height: 22px;">
                        You can access your newly registered ebook directly in the student portal using your existing account credentials.
                    </p>
                </td>
            </tr>
        </table>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">

    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ebook Registration Successful</title>
    </head>

    <body
        style="
        margin: 0;
        padding: 0;
        background-color: #f5f3ff;
        font-family: Arial, sans-serif;
        ">
        <table
        width="100%"
        cellpadding="0"
        cellspacing="0"
        border="0"
        style="background-color: #f5f3ff; padding: 40px 15px">
        <tr>
            <td align="center">
            <table
                width="620"
                cellpadding="0"
                cellspacing="0"
                border="0"
                style="
                background: #ffffff;
                border-radius: 18px;
                overflow: hidden;
                box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
                ">
                <!-- HEADER -->
                <tr>
                <td
                    align="center"
                    style="
                    background: linear-gradient(
                        135deg,
                        #090116 0%,
                        #090116 50%,
                        #7120e7 100%
                    );
                    padding: 45px 5px;
                    ">
                    <img
                    src="{media_base_url}/media/logos/passats.png"
                    alt="Aryu Academy"
                    style="
                        width: 200px;
                        max-width: 90%;
                        height: auto;
                        display: block;
                        margin: 0 auto;
                    " />

                    <p
                    style="
                        margin-top: 20px;
                        color: #996ae3;
                        font-size: 16px;
                        line-height: 26px;
                        font-weight: 600;
                    ">
                    Ebook Registration Successful
                    </p>
                </td>
                </tr>

                <!-- CONTENT -->
                <tr>
                <td style="padding: 45px 20px">
                    <h2
                    style="
                        margin: 0 0 20px 0;
                        font-size: 28px;
                        color: #1e1b4b;
                        font-weight: 700;
                    ">
                    Hello {registration.name},
                    </h2>

                    <p
                    style="
                        margin: 0 0 25px 0;
                        font-size: 16px;
                        line-height: 30px;
                        color: #475569;
                    ">
                    Thank you for your registration. Your access to <strong>{ebook.title}</strong> has been successfully confirmed.
                    </p>

                    {details_section}

                    <!-- BUTTON -->
                    <table
                    cellpadding="0"
                    cellspacing="0"
                    border="0"
                    align="center">
                    <tr>
                        <td
                        align="center"
                        style="
                            border-radius: 12px;
                            background: linear-gradient(135deg, #5c20e7, #7120e7);
                        ">
                        <a
                            href="{portal_link}"
                            target="_blank"
                            style="
                            display: inline-block;
                            padding: 16px 34px;
                            font-size: 16px;
                            font-weight: 700;
                            color: #ffffff;
                            text-decoration: none;
                            border-radius: 12px;
                            ">
                            Access Ebook Portal
                        </a>
                        </td>
                    </tr>
                    </table>

                    <!-- NOTICE -->
                    <table
                    width="100%"
                    cellpadding="0"
                    cellspacing="0"
                    border="0"
                    style="
                        margin-top: 40px;
                        background: #f5f3ff;
                        border-left: 4px solid #7c3aed;
                        border-radius: 10px;
                    ">
                    <tr>
                        <td style="padding: 18px 22px">
                        <p
                            style="
                            margin: 0;
                            font-size: 14px;
                            line-height: 24px;
                            color: #5b21b6;
                            ">
                            If you did not register for this ebook, please contact our support team immediately.
                        </p>
                        </td>
                    </tr>
                    </table>
                </td>
                </tr>

                <!-- FOOTER -->
                <tr>
                <td
                    align="center"
                    style="
                    background: #fafafa;
                    padding: 30px;
                    border-top: 1px solid #e5e7eb;
                    ">
                    <p style="margin: 0 0 10px 0; font-size: 14px; color: #475569">
                    Product of
                    <a
                        href="https://aryuacademy.com"
                        style="
                        color: #005aef;
                        text-decoration: none;
                        font-weight: 600;
                        ">
                        Aryu Academy Pvt.
                    </a>
                    </p>

                    <p
                    style="
                        margin: 0;
                        font-size: 13px;
                        color: #64748b;
                        line-height: 24px;
                    ">
                    <a
                        href="https://passats.aryuacademy.com/privacy-policy"
                        style="color: #005aef; text-decoration: none">
                        Privacy Policy
                    </a>

                    &nbsp; | &nbsp;

                    <a
                        href="https://passats.aryuacademy.com/terms-conditions"
                        style="color: #005aef; text-decoration: none">
                        Terms & Conditions
                    </a>
                    </p>

                    <p
                    style="
                        margin-top: 18px;
                        font-size: 12px;
                        line-height: 22px;
                        color: #9ca3af;
                    ">
                    © 2026 Aryu Academy Private Limited. All rights reserved.
                    </p>

                    <p
                    style="
                        margin-top: 8px;
                        font-size: 12px;
                        line-height: 22px;
                        color: #9ca3af;
                    ">
                    This is an automated confirmation email. Please do not reply.
                    </p>
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
        subject=subject,
        body=f"Your ebook registration for {ebook.title} is successful.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[registration.email],
    )

    email_msg.attach_alternative(html_content, "text/html")
    email_msg.send(fail_silently=False)
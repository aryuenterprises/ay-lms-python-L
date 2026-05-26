from django.core.management.base import BaseCommand

from django.utils import timezone

from datetime import timedelta

from resume.models import UserSubscription

from django.core.mail import EmailMultiAlternatives

from django.conf import settings


class Command(BaseCommand):

    help = "Send renewal reminders"

    def handle(self, *args, **kwargs):

        now = timezone.now()

        subscriptions = UserSubscription.objects.filter(
            status="active",
            end_date__isnull=False
        ).select_related(
            "user",
            "subscription"
        )

        for sub in subscriptions:

            days_left = (
                sub.end_date.date() -
                now.date()
            ).days

            # =====================================
            # 3 DAYS REMINDER
            # =====================================

            if (
                days_left == 3
                and not sub.renewal_mail_sent_3_days
            ):

                self.send_mail(
                    sub,
                    "3 days"
                )

                sub.renewal_mail_sent_3_days = True

                sub.save(
                    update_fields=[
                        "renewal_mail_sent_3_days"
                    ]
                )

            # =====================================
            # 1 DAY REMINDER
            # =====================================

            if (
                days_left == 1
                and not sub.renewal_mail_sent_1_day
            ):

                self.send_mail(
                    sub,
                    "1 day"
                )

                sub.renewal_mail_sent_1_day = True

                sub.save(
                    update_fields=[
                        "renewal_mail_sent_1_day"
                    ]
                )

    def send_mail(self, sub, reminder):

        html_message = f"""
<!DOCTYPE html>
<html lang="en">

<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Subscription Expired</title>
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
      box-shadow: 0 6px 20px rgba(0,0,0,0.08);
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
    src="https://portal.aryuacademy.com/api/media/logos/passats.png"
    alt="Pass ATS"
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

Subscription Expired

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

Hello {sub.user.first_name},

</h2>

<p
    style="
      margin: 0 0 20px 0;
      font-size: 16px;
      line-height: 30px;
      color: #475569;
    ">

Your Pass ATS subscription has expired.

</p>

<p
    style="
      margin: 0 0 25px 0;
      font-size: 16px;
      line-height: 30px;
      color: #475569;
    ">

Your premium features are currently unavailable.

Renew your subscription to continue accessing advanced ATS tools,
AI resume optimization, premium templates, and cover letter generation.

</p>

<!-- SUBSCRIPTION BOX -->

<table
    width="100%"
    cellpadding="0"
    cellspacing="0"
    border="0"
    style="
      margin-top: 30px;
      background: #f8fafc;
      border-radius: 14px;
    ">

<tr>
<td style="padding: 24px">

<p
    style="
      margin: 0 0 12px 0;
      font-size: 15px;
      color: #334155;
    ">

<strong>Expired Plan:</strong>
{sub.subscription.name}

</p>

<p
    style="
      margin: 0;
      font-size: 15px;
      color: #334155;
    ">

<strong>Expiry Date:</strong>
{sub.end_date.strftime("%d %B %Y")}

</p>

</td>
</tr>

</table>

<!-- BUTTON -->

<div
    style="
      text-align: center;
      margin-top: 40px;
    ">

<a
    href="https://passats.aryuacademy.com/pricing"
    target="_blank"
    style="
      display: inline-block;
      padding: 16px 34px;
      font-size: 16px;
      font-weight: 700;
      color: #ffffff;
      text-decoration: none;
      border-radius: 12px;
      background: linear-gradient(
        135deg,
        #5c20e7,
        #7120e7
      );
    ">

Renew Subscription

</a>

</div>

<!-- NOTICE -->

<table
    width="100%"
    cellpadding="0"
    cellspacing="0"
    border="0"
    style="
      margin-top: 40px;
      background: #fef2f2;
      border-left: 4px solid #dc2626;
      border-radius: 10px;
    ">

<tr>
<td style="padding: 18px 22px">

<p
    style="
      margin: 0;
      font-size: 14px;
      line-height: 24px;
      color: #991b1b;
    ">

Your premium access has been disabled until the subscription is renewed.

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

<p
    style="
      margin: 0 0 10px 0;
      font-size: 14px;
      color: #475569;
    ">

Product of

<a
    href="https://aryuacademy.com"
    style="
      color: #005aef;
      text-decoration: none;
      font-weight: 600;
    ">

Aryu Academy Pvt Ltd.

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
    style="
      color: #005aef;
      text-decoration: none;
    ">

Privacy Policy

</a>

&nbsp; | &nbsp;

<a
    href="https://passats.aryuacademy.com/terms-conditions"
    style="
      color: #005aef;
      text-decoration: none;
    ">

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

© 2026 Aryu Academy Private Limited.
All rights reserved.

</p>

<p
    style="
      margin-top: 8px;
      font-size: 12px;
      line-height: 22px;
      color: #9ca3af;
    ">

This is an automated subscription email.
Please do not reply.

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

        email = EmailMultiAlternatives(

            subject="Your Pass ATS Subscription is Expiring Soon",

            body=f"""
Hello {sub.user.first_name},

Your subscription expires in {reminder}.
            """,

            from_email=settings.DEFAULT_FROM_EMAIL,

            to=[sub.user.email]
        )

        email.attach_alternative(
            html_message,
            "text/html"
        )

        email.send(fail_silently=True)
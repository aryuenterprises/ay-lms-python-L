import os

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from django.conf import settings


class PaymentEmailService:

    @staticmethod
    def send_invoice_email(transaction):

        subject = f"Payment Invoice - {transaction.transaction_id}"

        html_content = render_to_string(
            "emails/invoice_email.html",
            {
                "student": transaction.student,
                "course": transaction.course,
                "transaction": transaction
            }
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body="Invoice Attached",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[transaction.student.email]
        )

        email.attach_alternative(
            html_content,
            "text/html"
        )

        if transaction.invoice:
            invoice_path = transaction.invoice.path

            if os.path.exists(invoice_path):
                with open(invoice_path, "rb") as f:
                    email.attach(
                        os.path.basename(invoice_path),
                        f.read(),
                        "application/pdf"
                    )

        email.send()
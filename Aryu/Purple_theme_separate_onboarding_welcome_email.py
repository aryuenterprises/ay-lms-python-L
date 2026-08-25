import os
import sys
import django

# Setup django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Aryu.settings")
django.setup()

from io import BytesIO
from xhtml2pdf import pisa
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from aryuapp.models import Student
from payments.models import PaymentTransaction
from num2words import num2words

def main():
    User = get_user_model()
    test_email = "tamilselvi12022004@gmail.com"
    raw_password = "AryuPassword@2026"

    # 1. Update/Sync Password for Live Login Authentication
    user = User.objects.filter(email__iexact=test_email).first() or User.objects.filter(username__iexact=test_email).first()
    if user:
        user.username = test_email
        user.set_password(raw_password)
        user.is_active = True
        user.save()
        print(f"[+] Password successfully synced for user: {user.username}")
    else:
        user = User.objects.create_user(
            username=test_email,
            email=test_email,
            password=raw_password,
            full_name="Tamil Selvi",
            is_active=True
        )
        print(f"[+] Created user: {user.username}")

    student = Student.objects.filter(email__iexact=test_email).first()
    if student:
        from django.contrib.auth.hashers import make_password
        student.password = make_password(raw_password)
        student.save()
        print(f"[+] Synced Student password to match user.")

    # 2. Extract / Calculate Invoice Details
    txn = PaymentTransaction.objects.filter(metadata__email=test_email).order_by("-id").first()
    txn_id = getattr(txn, "id", 926)
    total_amount = float(getattr(txn, "amount", 499.00))

    taxable_value = round(total_amount / 1.18, 2)
    cgst = round(taxable_value * 0.09, 2)
    sgst = round(taxable_value * 0.09, 2)
    invoice_no = f"AA{timezone.now().strftime('%y%m')}{txn_id}"

    student_name = f"{student.first_name} {student.last_name or ''}".strip() if student else "Tamil Selvi"

    context = {
        "student_name": student_name,
        "email": test_email,
        "username": test_email,
        "password": raw_password,
        "phone": "9876543210",
        "portal_url": "https://portal.aryuacademy.com",
        "login_url": "https://portal.aryuacademy.com",
        "course_name": "Python Full Stack Bootcamp Training",
        "invoice_no": invoice_no,
        "invoice_date": timezone.now().strftime("%d-%m-%Y"),
        "place_of_supply": "Tamil Nadu",
        "hsn_sac": "999293",
        "rate": f"{taxable_value:.2f}",
        "taxable_value": f"{taxable_value:.2f}",
        "cgst": f"{cgst:.2f}",
        "sgst": f"{sgst:.2f}",
        "total_amount": f"{total_amount:.2f}",
        "amount_in_words": num2words(total_amount, lang="en_IN").replace("-", " ").title() + " Only",
        "total_tax": f"{(cgst + sgst):.2f}",
        "tax_in_words": num2words(cgst + sgst, lang="en_IN").replace("-", " ").title() + " Only",
    }

    # 3. Clean Onboarding Welcome HTML Body
    email_html_body = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #F8FAFC; margin: 0; padding: 20px; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #E2E8F0; overflow: hidden; }}
    .header {{ background-color: #6B21A8; color: #ffffff; padding: 24px; text-align: center; }}
    .content {{ padding: 24px; color: #334155; line-height: 1.6; }}
    .cred-box {{ background-color: #FAF5FF; border: 1px solid #E9D5FF; border-radius: 6px; padding: 16px; margin: 20px 0; }}
    .cred-item {{ margin: 8px 0; font-size: 14px; }}
    .btn {{ display: inline-block; background-color: #6B21A8; color: #ffffff !important; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; margin-top: 10px; }}
    .footer {{ background-color: #F1F5F9; padding: 16px; text-align: center; font-size: 12px; color: #64748B; }}
</style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2 style="margin: 0;">Welcome to ARYU Academy</h2>
        </div>
        <div class="content">
            <p>Dear <strong>{context['student_name']}</strong>,</p>
            <p>Congratulations! Your registration for <strong>{context['course_name']}</strong> is confirmed.</p>
            
            <div class="cred-box">
                <h4 style="margin: 0 0 10px 0; color: #6B21A8;">Your Learning Portal Login Credentials</h4>
                <div class="cred-item"><strong>Portal URL:</strong> <a href="{context['portal_url']}">{context['portal_url']}</a></div>
                <div class="cred-item"><strong>Username:</strong> {test_email}</div>
                <div class="cred-item"><strong>Temporary Password:</strong> <code style="background: #E2E8F0; padding: 2px 6px; border-radius: 4px; color: #0F172A;">{raw_password}</code></div>
            </div>

            <div style="text-align: center; margin: 25px 0;">
                <a href="{context['portal_url']}" class="btn">Login to Learning Portal</a>
            </div>

            <p style="font-size: 13px; color: #64748B;">
                * Your official GST Tax Invoice (<code>{invoice_no}</code>) for the amount of <strong>INR {context['total_amount']}</strong> is attached to this email as a PDF.
            </p>
        </div>
        <div class="footer">
            &copy; 2026 ARYU Academy Private Limited. All rights reserved.<br/>
            For support: raj@aryuacademy.com | +91 7502149013
        </div>
    </div>
</body>
</html>
"""

    # 4. Render the PDF Tax Invoice from `invoice_pdf.html`
    invoice_pdf_html = render_to_string("invoices/invoice_pdf.html", context)
    pdf_buffer = BytesIO()
    pisa.CreatePDF(invoice_pdf_html, dest=pdf_buffer)
    pdf_bytes = pdf_buffer.getvalue()

    # 5. Dispatch Multipart Email
    email_msg = EmailMultiAlternatives(
        subject=f"Welcome to ARYU Academy - Login Credentials & Tax Invoice ({invoice_no})",
        body=f"""Hello {context['student_name']},

Welcome to ARYU Academy!

Your account details:
• Learning Portal: {context['portal_url']}
• Username: {test_email}
• Password: {raw_password}

Your official Tax Invoice ({invoice_no}) is attached as a PDF.

Best regards,
ARYU Academy Team
""",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[test_email],
    )
    email_msg.attach_alternative(email_html_body, "text/html")
    email_msg.attach(f"Tax_Invoice_{invoice_no}.pdf", pdf_bytes, "application/pdf")
    email_msg.send(fail_silently=False)

    print(f"[SUCCESS] Clean onboarding email with PDF Tax Invoice attachment dispatched to {test_email}")

if __name__ == "__main__":
    main()

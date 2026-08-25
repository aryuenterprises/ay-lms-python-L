import base64
import os
import sys
import django

# Setup django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Aryu.settings")
django.setup()

from django.conf import settings
from io import BytesIO
from xhtml2pdf import pisa
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from aryuapp.models import Student
from payments.models import PaymentTransaction

def run_test():
    User = get_user_model()
    test_email = "tamilselvi12022004@gmail.com"
    raw_password = "AryuPassword@2026"

    # 1. Verify / Sync Existing User
    user = User.objects.filter(email__iexact=test_email).first() or User.objects.filter(username__iexact=test_email).first()
    if user:
        user.username = test_email
        user.set_password(raw_password)
        user.is_active = True
        user.save()
        print(f"[INFO] Synced User password for {test_email}")
    else:
        print(f"[WARNING] User with email {test_email} not found in Django auth.")

    student = Student.objects.filter(email__iexact=test_email).first()
    student_name = getattr(student, "first_name", "Tamil Selvi") or "Tamil Selvi"
    if student:
        print(f"[INFO] Found Student: {student_name}, ID: {student.student_id}")
    else:
        print(f"[WARNING] Student with email {test_email} not found in Student model.")

    # 2. Financial Context & Tax Calculations
    txn = PaymentTransaction.objects.filter(metadata__email=test_email).order_by("-id").first()
    txn_id = getattr(txn, "id", 926)
    total_amount = float(getattr(txn, "amount", 499.00))

    taxable_value = round(total_amount / 1.18, 2)
    cgst = round(taxable_value * 0.09, 2)
    sgst = round(taxable_value * 0.09, 2)
    total_tax = round(cgst + sgst, 2)
    invoice_no = f"AA{timezone.now().strftime('%y%m')}{txn_id}"

    # 3. Locate & Encode Logo
    logo_base64 = ""
    logo_candidates = [
        os.path.join(settings.BASE_DIR, "static", "images", "logo.png"),
        os.path.join(settings.BASE_DIR, "media", "logos", "email_logo.png"),
        os.path.join(settings.BASE_DIR, "static", "logo.png"),
        os.path.join(settings.BASE_DIR, "aryuapp", "static", "images", "logo.png"),
    ]

    for path in logo_candidates:
        if os.path.exists(path):
            with open(path, "rb") as img:
                logo_base64 = base64.b64encode(img.read()).decode("utf-8")
            print(f"[INFO] Found logo at: {path}")
            break

    context = {
        "student_name": student_name,
        "email": test_email,
        "phone": getattr(student, "contact_no", "9876543210") or "9876543210",
        "invoice_no": invoice_no,
        "invoice_date": timezone.now().strftime("%d-%m-%Y"),
        "place_of_supply": "Tamil Nadu",
        "course_name": "Python Full Stack Bootcamp Training",
        "hsn_sac": "999293",
        "rate": f"{taxable_value:.2f}",
        "taxable_value": f"{taxable_value:.2f}",
        "cgst": f"{cgst:.2f}",
        "sgst": f"{sgst:.2f}",
        "total_tax": f"{total_tax:.2f}",
        "total_amount": f"{total_amount:.2f}",
        "amount_in_words": "Four Hundred And Ninety-Nine Only",
        "tax_in_words": "Seventy-Six Point One Two Only.",
        "logo_base64": logo_base64,
    }

    # 4. Generate PDF
    pdf_html = render_to_string("invoices/invoice_pdf.html", context)
    pdf_buffer = BytesIO()
    pisa.CreatePDF(pdf_html, dest=pdf_buffer)
    pdf_bytes = pdf_buffer.getvalue()

    # 5. Prepare HTML Email Body
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
            <p>Dear <strong>{student_name}</strong>,</p>
            <p>Your enrollment for <strong>{context['course_name']}</strong> has been confirmed.</p>
            
            <div class="cred-box">
                <h4 style="margin: 0 0 10px 0; color: #6B21A8;">Your Portal Access Credentials</h4>
                <div class="cred-item"><strong>Portal Link:</strong> <a href="https://portal.aryuacademy.com">https://portal.aryuacademy.com</a></div>
                <div class="cred-item"><strong>Username:</strong> {test_email}</div>
                <div class="cred-item"><strong>Password:</strong> <code style="background: #E2E8F0; padding: 2px 6px; border-radius: 4px; color: #0F172A;">{raw_password}</code></div>
            </div>

            <div style="text-align: center; margin: 25px 0;">
                <a href="https://portal.aryuacademy.com" class="btn">Access Learning Portal</a>
            </div>

            <p style="font-size: 13px; color: #64748B;">
                * Your official GST Tax Invoice (<code>{invoice_no}</code>) for <strong>INR {context['total_amount']}</strong> is attached as a PDF.
            </p>
        </div>
        <div class="footer">
            &copy; 2026 ARYU Academy Private Limited.<br/>
            Contact: raj@aryuacademy.com | +91 7502149013
        </div>
    </div>
</body>
</html>
"""

    # 6. Dispatch Email
    email_msg = EmailMultiAlternatives(
        subject=f"Welcome to ARYU Academy - Login Credentials & Tax Invoice ({invoice_no})",
        body=f"Hello {student_name},\n\nYour login credentials:\nPortal: https://portal.aryuacademy.com\nUsername: {test_email}\nPassword: {raw_password}\n\nInvoice attached.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[test_email]
    )
    email_msg.attach_alternative(email_html_body, "text/html")
    email_msg.attach(f"Tax_Invoice_{invoice_no}.pdf", pdf_bytes, "application/pdf")
    email_msg.send(fail_silently=False)

    print(f"[SUCCESS] Email test completed for {test_email}")

if __name__ == "__main__":
    run_test()

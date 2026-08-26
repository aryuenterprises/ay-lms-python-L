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

User = get_user_model()
test_email = "tamilselvi12022004@gmail.com"
raw_password = "AryuPassword@2026"

# 1. Sync User Password
user = User.objects.filter(email__iexact=test_email).first() or User.objects.filter(username__iexact=test_email).first()
if user:
    user.username = test_email
    user.set_password(raw_password)
    user.is_active = True
    user.save()

student = Student.objects.filter(email__iexact=test_email).first()
student_name = getattr(student, "name", "Tamil Selvi") or "Tamil Selvi"

# 2. Context & Tax Data
txn = PaymentTransaction.objects.filter(metadata__email=test_email).order_by("-id").first()
txn_id = getattr(txn, "id", 926)
total_amount = float(getattr(txn, "amount", 499.00))

taxable_value = round(total_amount / 1.18, 2)
cgst = round(taxable_value * 0.09, 2)
sgst = round(taxable_value * 0.09, 2)
total_tax = round(cgst + sgst, 2)
invoice_no = f"AA{timezone.now().strftime('%y%m')}{txn_id}"

# Locate logo (if available)
logo_base64 = ""
logo_candidates = [
    os.path.join(settings.BASE_DIR, "static", "images", "logo.png"),
    os.path.join(settings.BASE_DIR, "media", "logos", "email_logo.png"),
    os.path.join(settings.BASE_DIR, "static", "logo.png"),
    os.path.join(settings.BASE_DIR, "aryuapp", "static", "images", "logo.png"),
]
import base64
for path in logo_candidates:
    if os.path.exists(path):
        with open(path, "rb") as img:
            logo_base64 = base64.b64encode(img.read()).decode("utf-8")
        break

context = {
    "student_name": student_name,
    "email": test_email,
    "phone": getattr(student, "phone", "9876543210") or "9876543210",
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

# 3. Compile PDF
pdf_html = render_to_string("invoices/invoice_pdf.html", context)
pdf_buffer = BytesIO()
pisa_status = pisa.CreatePDF(pdf_html, dest=pdf_buffer)

if pisa_status.err:
    raise RuntimeError(f"PDF compilation failed: {pisa_status.err}")

pdf_bytes = pdf_buffer.getvalue()
print(f"[+] PDF generated successfully ({len(pdf_bytes)} bytes)")

# 4. Email Template Body
email_html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: Arial, sans-serif; background-color: #F8FAFC; margin: 0; padding: 20px; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #E2E8F0; overflow: hidden; }}
    .header {{ background-color: #6B21A8; color: #ffffff; padding: 20px; text-align: center; }}
    .content {{ padding: 20px; color: #334155; line-height: 1.5; }}
    .cred-box {{ background-color: #FAF5FF; border: 1px solid #E9D5FF; border-radius: 6px; padding: 14px; margin: 16px 0; }}
    .btn {{ display: inline-block; background-color: #6B21A8; color: #ffffff !important; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; margin-top: 8px; }}
    .footer {{ background-color: #F1F5F9; padding: 12px; text-align: center; font-size: 11px; color: #64748B; }}
</style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2 style="margin: 0;">Welcome to ARYU Academy</h2>
        </div>
        <div class="content">
            <p>Dear <strong>{student_name}</strong>,</p>
            <p>Your registration for <strong>{context['course_name']}</strong> has been confirmed.</p>
            
            <div class="cred-box">
                <h4 style="margin: 0 0 8px 0; color: #6B21A8;">Learning Portal Access Credentials</h4>
                <div><strong>Portal Link:</strong> <a href="https://aylms.aryuprojects.com">https://aylms.aryuprojects.com</a></div>
                <div style="margin-top: 4px;"><strong>Username:</strong> {test_email}</div>
                <div style="margin-top: 4px;"><strong>Password:</strong> <code style="background: #E2E8F0; padding: 2px 6px; border-radius: 4px;">{raw_password}</code></div>
            </div>

            <div style="text-align: center; margin: 20px 0;">
                <a href="https://aylms.aryuprojects.com" class="btn">Access Learning Portal</a>
            </div>

            <p style="font-size: 12px; color: #64748B;">
                * Your official GST Tax Invoice (<code>{invoice_no}</code>) is attached as a PDF document.
            </p>
        </div>
        <div class="footer">
            &copy; 2026 ARYU Academy Private Limited.<br/>
            Contact: raj@aryuacademy.com | +91 7502149013
        </div>
    </div>
</body>
</html>"""

# 5. Dispatch Message
msg = EmailMultiAlternatives(
    subject=f"Welcome to ARYU Academy - Login Credentials & Tax Invoice ({invoice_no})",
    body=f"Hello {student_name},\n\nPortal: https://aylms.aryuprojects.com\nUsername: {test_email}\nPassword: {raw_password}\n\nInvoice attached.",
    from_email=settings.DEFAULT_FROM_EMAIL,
    to=[test_email]
)
msg.attach_alternative(email_html_body, "text/html")
msg.attach(f"Tax_Invoice_{invoice_no}.pdf", pdf_bytes, "application/pdf")
msg.send(fail_silently=False)

print(f"[SUCCESS] Email dispatched with valid PDF invoice to {test_email}")

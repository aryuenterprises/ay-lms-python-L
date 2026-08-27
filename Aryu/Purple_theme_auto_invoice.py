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
    total_amount = float(getattr(txn, "amount", 1000.00))

    taxable_value = round(total_amount / 1.18, 2)
    cgst = round(taxable_value * 0.09, 2)
    sgst = round(taxable_value * 0.09, 2)
    invoice_no = f"AA{timezone.now().strftime('%y%m')}{txn_id}"

    student_name = f"{student.first_name} {student.last_name or ''}".strip() if student else "Tamil Selvi"

    context = {
        # Nested variables for template compatibility
        "transaction": {
            "invoice_no": invoice_no,
            "invoice_date": timezone.now().date(),
            "place_of_supply": "Tamil Nadu",
            "taxable_amount": f"{taxable_value:.2f}",
            "cgst_amount": f"{cgst:.2f}",
            "sgst_amount": f"{sgst:.2f}",
            "invoice_total": f"{total_amount:.2f}",
            "amount": f"{total_amount:.2f}",
            "hsn_code": "999293",
            "total_tax_amount": f"{(cgst + sgst):.2f}",
            "igst_amount": "",
        },
        "billing": {
            "name": student_name,
            "address": "Chennai, Tamil Nadu",
            "gst": "Unregistered",
            "email": test_email,
            "phone": "9876543210",
        },
        "company": {
            "company_name": "ARYU Academy Private Limited",
            "company_address": "No 33/14, Ground floor, Jayammal St, Ayyavoo Colony, Aminjikarai, Chennai, Tamil Nadu 600029",
            "gst_number": "45879933",
            "company_email": "raj@aryuacademy.com",
            "company_contact": "7502149013",
            "bank_name": "Federal Bank",
            "bank_account_no": "12330200034467",
            "bank_ifsc": "FDRL0001233",
            "upi_id": "aryuacademy8299@fbl",
            "pan_no": "ABECA6801B1",
            "declaration": "We declare that this invoice shows the actual price of the service described and all particulars are true and correct.",
        },
        "description": "Python Full Stack Bootcamp Training",
        "context_amount_words": num2words(total_amount, lang="en_IN"),
        "tax_amount_words": num2words(cgst + sgst, lang="en_IN"),
        "previous_invoice_details": [],
        "total_received": f"{total_amount:.2f}",
        "balance_due": "0.00",
        
        # Flat/Auth credentials
        "student_name": student_name,
        "portal_url": "https://portal.aryuacademy.com",
    }

    # 3. Render HTML Email Body from `invoice_email.html`
    email_html_content = render_to_string("emails/invoice_email.html", context)

    # 4. Render PDF Invoice Attachment from `invoice_pdf.html`
    invoice_pdf_html = render_to_string("invoices/invoice_pdf.html", context)
    pdf_buffer = BytesIO()
    pisa.CreatePDF(invoice_pdf_html, dest=pdf_buffer)
    pdf_bytes = pdf_buffer.getvalue()

    # 5. Dispatch Multipart Email
    plain_body = f"""Hello {student_name},

Welcome to ARYU Academy!

Your account details:
• Learning Portal: https://portal.aryuacademy.com
• Username: {test_email}
• Password: {raw_password}

Your official GST Tax Invoice ({invoice_no}) is attached to this email as a PDF.

Best regards,
ARYU Academy Team
"""

    email_msg = EmailMultiAlternatives(
        subject=f"Tax Invoice {invoice_no} & Login Credentials - ARYU Academy",
        body=plain_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[test_email],
    )
    email_msg.attach_alternative(email_html_content, "text/html")
    email_msg.attach(f"Tax_Invoice_{invoice_no}.pdf", pdf_bytes, "application/pdf")
    email_msg.send(fail_silently=False)

    print(f"[SUCCESS] Email dispatched using invoice_email.html and invoice_pdf.html to {test_email}")

if __name__ == "__main__":
    main()

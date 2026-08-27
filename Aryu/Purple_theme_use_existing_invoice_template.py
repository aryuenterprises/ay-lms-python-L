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
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone
from aryuapp.models import Student
from payments.models import PaymentTransaction
from num2words import num2words

def main():
    User = get_user_model()
    test_email = "tamilselvi12022004@gmail.com"
    raw_password = "AryuPassword@2026"

    # 1. Update/Synchronize Login Credentials
    user = User.objects.filter(email__iexact=test_email).first() or User.objects.filter(username__iexact=test_email).first()
    if user:
        user.username = test_email
        user.set_password(raw_password)
        user.is_active = True
        user.save()
        print(f"[+] Password synchronized for User: {user.username}")
    else:
        user = User.objects.create_user(
            username=test_email,
            email=test_email,
            password=raw_password,
            full_name="Tamil Selvi",
            is_active=True
        )
        print(f"[+] Created active User: {user.username}")

    # Sync/Update Student Record password
    from django.contrib.auth.hashers import make_password
    student = Student.objects.filter(email__iexact=test_email).first()
    if student:
        student.password = make_password(raw_password)
        student.save()
        print(f"[+] Password synchronized for Student: {student.email}")

    # 2. Prepare Context for existing `invoice_pdf.html`
    txn = PaymentTransaction.objects.filter(metadata__email=test_email).order_by("-id").first()
    txn_id = getattr(txn, "id", 926)
    total_amount = float(getattr(txn, "amount", 1000.00))

    taxable_value = round(total_amount / 1.18, 2)
    cgst = round(taxable_value * 0.09, 2)
    sgst = round(taxable_value * 0.09, 2)
    invoice_no = f"AA{timezone.now().strftime('%y%m')}{txn_id}"

    context = {
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
            "name": getattr(student, "name", "Tamil Selvi") or "Tamil Selvi",
            "address": "Chennai, Tamil Nadu",
            "gst": "Unregistered",
            "email": test_email,
            "phone": "9876543210",
        },
        "company": {
            "company_name": "ARYU Academy Private Limited",
            "company_address": "No 33/14, Ground floor, Jayammal St, Ayyavoo Colony, Aminjikarai, Chennai, Tamil Nadu 600029",
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
        "previous_transactions": [],
        "total_received": f"{total_amount:.2f}",
        "balance_due": "0.00",
    }

    # 3. Render PDF Using Existing Template
    rendered_html = render_to_string("invoices/invoice_pdf.html", context)
    pdf_buffer = BytesIO()
    pisa.CreatePDF(rendered_html, dest=pdf_buffer)
    pdf_bytes = pdf_buffer.getvalue()

    # 4. Send Email
    email_msg = EmailMessage(
        subject="Welcome to Aryu Academy - Login Credentials & Tax Invoice",
        body=f"""Hello Tamil Selvi,

Welcome to ARYU Academy!

Your account is ready. Log in to the learning portal using the credentials below:

• Portal URL: https://aylms.aryuprojects.com
• Username: {test_email}
• Password: {raw_password}

Your official GST Tax Invoice ({invoice_no}) is attached to this email as a PDF.

Best regards,
ARYU Academy Team
""",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[test_email],
    )
    email_msg.attach(f"Tax_Invoice_{invoice_no}.pdf", pdf_bytes, "application/pdf")
    email_msg.send(fail_silently=False)

    print(f"[SUCCESS] Email sent using existing template to {test_email}")

if __name__ == "__main__":
    main()

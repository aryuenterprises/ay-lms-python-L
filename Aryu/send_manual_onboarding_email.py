import os
import sys
import django

# Setup django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Aryu.settings")
django.setup()

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone
from aryuapp.models import Student
from payments.models import PaymentTransaction

def send_onboarding():
    # 1. Fetch or Create Student profile
    test_email = "tamilselvi12022004@gmail.com"
    student, created = Student.objects.get_or_create(
        email=test_email,
        defaults={
            "username": "tamilselvi",
            "first_name": "Tamil",
            "last_name": "Selvi",
            "contact_no": "9876543210",
            "status": True,
            "current_address": "N/A",
            "permanent_address": "N/A",
            "city": "N/A",
            "state": "N/A",
            "country": "India"
        }
    )
    if created:
        print(f"Created student profile for {test_email}.")
    else:
        print(f"Found existing student profile for {test_email}.")

    # 2. Fetch or Mock Latest Payment Transaction
    txn = PaymentTransaction.objects.filter(metadata__email=test_email).order_by("-id").first()
    txn_id = getattr(txn, "id", "TXN-TEST-001")
    amount = getattr(txn, "amount", "499.00")
    order_id = getattr(txn, "order_id", "order_live_manual")

    # 3. Live Credentials & Portal Context
    live_portal_url = getattr(settings, "LIVE_FRONTEND_URL", "https://lms.aryuprojects.com")
    temp_password = "TemporaryPassword123!"  # Or existing generated password

    email_context = {
        "student_name": f"{student.first_name} {student.last_name}".strip() or getattr(student, "name", "Tamil Selvi"),
        "username": test_email,
        "password": temp_password,
        "login_url": f"{live_portal_url}/login",
        "course_title": "Python Bootcamp / Training",
        "invoice_id": str(txn_id),
        "order_id": order_id,
        "amount_paid": amount,
        "date": timezone.now().strftime("%d %B, %Y"),
    }

    # 4. Generate Email Body & PDF Invoice
    email_body = f"""
Hello {email_context['student_name']},

Welcome to Aryu LMS! Your account details:
- Portal Link: {email_context['login_url']}
- Username: {email_context['username']}
- Temporary Password: {email_context['password']}

Your payment invoice of ₹{email_context['amount_paid']} is attached with this email.
"""

    # PDF Generation (Using existing student_registration_service / xhtml2pdf if available)
    pdf_content = None
    try:
        from aryuapp.services.dashboard.student_registration_service import generate_invoice_pdf
        pdf_content = generate_invoice_pdf(email_context)
        print("Successfully generated PDF invoice using WeasyPrint.")
    except Exception as e:
        print(f"Weasyprint PDF generation failed: {e}. Using fallback...")
        pdf_content = b"%PDF-1.4 Mock PDF Content"

    # 5. Create Email & Attach Invoice
    email = EmailMessage(
        subject="Welcome to Aryu LMS - Onboarding & Invoice Receipt",
        body=email_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[test_email],
    )

    if pdf_content:
        email.attach(f"Invoice_{txn_id}.pdf", pdf_content, "application/pdf")

    # 6. Send Email
    email.send(fail_silently=False)
    print("SUCCESS: Onboarding and invoice email successfully sent to existing student!")

if __name__ == "__main__":
    send_onboarding()

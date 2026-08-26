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
from django.core.mail import EmailMessage
from django.utils import timezone
from aryuapp.models import Student
from payments.models import PaymentTransaction

def main():
    test_email = "tamilselvi12022004@gmail.com"
    student = Student.objects.filter(email=test_email).first()
    if not student:
        # Guarantee student exists
        student, created = Student.objects.get_or_create(
            email=test_email,
            defaults={
                "username": "tamilselvi",
                "first_name": "Tamil",
                "last_name": "Selvi",
                "contact_no": "9876543210",
                "status": True,
                "current_address": "Chennai, Tamil Nadu",
                "permanent_address": "Chennai, Tamil Nadu",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "country": "India"
            }
        )
        print("Created student profile for testing.")
        
    student_name = f"{student.first_name} {student.last_name}".strip() or getattr(student, "name", "Tamil Selvi") or "Tamil Selvi"

    txn = PaymentTransaction.objects.filter(metadata__email=test_email).order_by("-id").first()
    txn_id = getattr(txn, "id", 926)
    total_amount = float(getattr(txn, "amount", 499.00))

    # 18% GST Calculations
    taxable_value = round(total_amount / 1.18, 2)
    cgst = round(taxable_value * 0.09, 2)
    sgst = round(taxable_value * 0.09, 2)
    invoice_no = f"AA{timezone.now().strftime('%y%m')}{txn_id}"

    invoice_html = f"""
<!DOCTYPE html>
<html>
<head>
<style>
    @page {{ size: a4 portrait; margin: 1.2cm; }}
    body {{ font-family: Helvetica, Arial, sans-serif; font-size: 11px; color: #2D3748; }}
    .header-table {{ width: 100%; border-bottom: 2px solid #6B21A8; padding-bottom: 8px; margin-bottom: 12px; }}
    .brand-title {{ font-size: 18px; font-weight: bold; color: #6B21A8; }}
    .invoice-title {{ font-size: 16px; font-weight: bold; color: #6B21A8; text-align: right; }}
    .section-table {{ width: 100%; margin-bottom: 12px; }}
    .table-box {{ width: 100%; border-collapse: collapse; margin-top: 8px; margin-bottom: 12px; }}
    .table-box th {{ background-color: #6B21A8; color: #ffffff; padding: 6px; font-size: 10px; text-align: left; }}
    .table-box td {{ padding: 6px; border: 0.5px solid #E2E8F0; font-size: 10px; }}
    .bank-table {{ width: 100%; border: 0.5px solid #CBD5E0; background-color: #FAF5FF; padding: 8px; margin-top: 10px; }}
    .declaration {{ font-size: 9px; color: #718096; margin-top: 15px; border-top: 0.5px solid #E2E8F0; padding-top: 6px; }}
</style>
</head>
<body>
    <table class="header-table">
        <tr>
            <td width="60%">
                <div class="brand-title">ARYU Academy Private Limited</div>
                <div>No 33/14, Ground floor, Jayammal St, Ayyavoo Colony,</div>
                <div>Aminjikarai, Chennai, Tamil Nadu 600029</div>
                <div><strong>GSTIN/UIN:</strong> 45879933 | <strong>PAN:</strong> ABECA6801B1</div>
                <div>Email: raj@aryuacademy.com | Phone: +91 7502149013</div>
            </td>
            <td width="40%" class="invoice-title">
                TAX INVOICE<br/>
                <span style="font-size: 11px; color: #4A5568;">Invoice No: <strong>{invoice_no}</strong></span><br/>
                <span style="font-size: 10px; color: #4A5568;">Date: {timezone.now().strftime('%d-%m-%Y')}</span><br/>
                <span style="font-size: 10px; color: #4A5568;">Place of Supply: Tamil Nadu</span>
            </td>
        </tr>
    </table>

    <table class="section-table">
        <tr>
            <td>
                <strong style="color: #6B21A8;">Buyer (Bill to):</strong><br/>
                <strong>{student_name}</strong><br/>
                Chennai, Tamil Nadu<br/>
                Email: {test_email} | Phone: 9876543210
            </td>
        </tr>
    </table>

    <table class="table-box">
        <thead>
            <tr>
                <th width="8%">SI NO</th>
                <th width="42%">Description of Service</th>
                <th width="15%">HSN/SAC</th>
                <th width="15%">Rate</th>
                <th width="10%">Tax %</th>
                <th width="10%">Amount (INR)</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>1</td>
                <td>Python Full Stack Bootcamp Training</td>
                <td>999293</td>
                <td>{taxable_value:.2f}</td>
                <td>18%</td>
                <td>{taxable_value:.2f}</td>
            </tr>
            <tr>
                <td colspan="5" align="right"><strong>Taxable Value</strong></td>
                <td>{taxable_value:.2f}</td>
            </tr>
            <tr>
                <td colspan="5" align="right">Output CGST (9%)</td>
                <td>{cgst:.2f}</td>
            </tr>
            <tr>
                <td colspan="5" align="right">Output SGST (9%)</td>
                <td>{sgst:.2f}</td>
            </tr>
            <tr style="background-color: #F7FAFC;">
                <td colspan="5" align="right"><strong style="color: #6B21A8;">Total Invoice Value</strong></td>
                <td><strong>{total_amount:.2f}</strong></td>
            </tr>
        </tbody>
    </table>

    <table class="bank-table">
        <tr>
            <td width="55%">
                <strong style="color: #6B21A8;">Company Bank Details:</strong><br/>
                <strong>A/c Name:</strong> ARYU ACADEMY PVT LTD<br/>
                <strong>Bank Name:</strong> Federal Bank<br/>
                <strong>A/c No:</strong> 12330200034467<br/>
                <strong>IFSC / Branch:</strong> FDRL0001233<br/>
                <strong>UPI ID:</strong> aryuacademy8299@fbl
            </td>
            <td width="45%" align="right">
                <div style="font-size: 13px; font-weight: bold; color: #16A34A;">PAID (ONLINE)</div>
                <div style="font-size: 9px; color: #718096;">Payment Txn ID: {txn_id}</div>
            </td>
        </tr>
    </table>

    <div class="declaration">
        <strong>Declaration:</strong> We declare that this invoice shows the actual price of the service described and that all particulars are true and correct.<br/>
        <em>Computer Generated Invoice - Signature Not Required</em>
    </div>
</body>
</html>
"""

    # Render PDF
    pdf_buffer = BytesIO()
    pisa.CreatePDF(invoice_html, dest=pdf_buffer)
    pdf_bytes = pdf_buffer.getvalue()

    # Send Email
    email_msg = EmailMessage(
        subject="Your Tax Invoice & Login Credentials - ARYU Academy",
        body=f"""Hello {student_name},

Welcome to ARYU Academy!

Your account details:
• Learning Portal: https://aylms.aryuprojects.com
• Username: {test_email}
• Password: TemporaryPassword123!

Your official GST Tax Invoice ({invoice_no}) is attached to this email as a PDF.

Best regards,
ARYU Academy Team
""",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[test_email]
    )
    email_msg.attach(f"Tax_Invoice_{invoice_no}.pdf", pdf_bytes, "application/pdf")
    email_msg.send(fail_silently=False)

    print(f"[SUCCESS] Tax invoice email sent to {test_email}")

if __name__ == "__main__":
    main()

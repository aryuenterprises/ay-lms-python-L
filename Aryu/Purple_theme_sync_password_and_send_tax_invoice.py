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
from django.utils import timezone
from aryuapp.models import Student
from payments.models import PaymentTransaction

def main():
    User = get_user_model()
    test_email = "tamilselvi12022004@gmail.com"
    raw_password = "AryuPassword@2026"

    # 1. Update / Synchronize Real User Password in Database
    user = User.objects.filter(email__iexact=test_email).first() or User.objects.filter(username__iexact=test_email).first()
    if user:
        user.username = test_email
        user.set_password(raw_password)
        user.is_active = True
        user.save()
        print(f"[+] Synced User password for {user.username}")
    else:
        user = User.objects.create_user(
            username=test_email,
            email=test_email,
            password=raw_password,
            full_name="Tamil Selvi",
            is_active=True
        )
        print(f"[+] Created active User: {user.username}")

    # Sync Student Record
    from django.contrib.auth.hashers import make_password
    student = Student.objects.filter(email__iexact=test_email).first()
    if student:
        student.password = make_password(raw_password)
        student.save()
        print(f"[+] Synced Student password to match user.")

    # 2. Transaction & Tax Invoice Calculations
    txn = PaymentTransaction.objects.filter(metadata__email=test_email).order_by("-id").first()
    txn_id = getattr(txn, "id", 926)
    total_amount = float(getattr(txn, "amount", 1000.00))

    taxable_value = round(total_amount / 1.18, 2)
    cgst = round(taxable_value * 0.09, 2)
    sgst = round(taxable_value * 0.09, 2)
    invoice_no = f"AA{timezone.now().strftime('%y%m')}{txn_id}"

    # 3. Official ARYU Academy Tax Invoice HTML Template
    invoice_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{ size: a4 portrait; margin: 1cm; }}
    body {{ font-family: Helvetica, Arial, sans-serif; font-size: 10px; color: #1F2937; line-height: 1.4; }}
    .main-table {{ width: 100%; border: 1.5px solid #6B21A8; border-collapse: collapse; }}
    .cell-pad {{ padding: 6px 8px; }}
    .brand-title {{ font-size: 14px; font-weight: bold; color: #6B21A8; }}
    .heading-title {{ font-size: 16px; font-weight: bold; color: #6B21A8; text-align: center; margin-bottom: 4px; }}
    .grid-table {{ width: 100%; border-collapse: collapse; }}
    .grid-table th {{ background-color: #6B21A8; color: #ffffff; padding: 5px; font-size: 9px; text-align: left; border: 0.5px solid #6B21A8; }}
    .grid-table td {{ padding: 5px; border: 0.5px solid #CBD5E1; font-size: 9px; }}
    .purple-bg {{ background-color: #FAF5FF; }}
    .b-top {{ border-top: 1px solid #6B21A8; }}
    .b-bottom {{ border-bottom: 1px solid #6B21A8; }}
    .b-right {{ border-right: 1px solid #6B21A8; }}
</style>
</head>
<body>
    <div class="heading-title">TAX INVOICE</div>
    <table class="main-table">
        <!-- Header Company & Invoice Details -->
        <tr>
            <td width="55%" class="cell-pad b-bottom b-right" valign="top">
                <div class="brand-title">ARYU Academy Private Limited</div>
                <div>No 33/14, Ground floor, Jayammal St,</div>
                <div>Ayyavoo Colony, Aminjikarai,</div>
                <div>Chennai, Tamil Nadu 600029</div>
                <div><strong>GSTIN/UIN:</strong> 45879933</div>
                <div><strong>Email:</strong> raj@aryuacademy.com | <strong>PH:</strong> 7502149013</div>
            </td>
            <td width="45%" class="cell-pad b-bottom" valign="top">
                <table width="100%">
                    <tr><td><strong>Invoice No</strong></td><td>: {invoice_no}</td></tr>
                    <tr><td><strong>Invoice Date</strong></td><td>: {timezone.now().strftime('%d-%m-%Y')}</td></tr>
                    <tr><td><strong>Place of Supply</strong></td><td>: Tamil Nadu</td></tr>
                </table>
            </td>
        </tr>

        <!-- Buyer Details -->
        <tr>
            <td colspan="2" class="cell-pad b-bottom purple-bg">
                <strong>Buyer (Bill to):</strong><br/>
                <strong>Tamil Selvi</strong><br/>
                Chennai, Tamil Nadu<br/>
                <strong>GSTIN/UIN:</strong> Unregistered<br/>
                <strong>Email:</strong> {test_email} | <strong>PH:</strong> 9876543210
            </td>
        </tr>

        <!-- Line Items -->
        <tr>
            <td colspan="2" style="padding: 0;">
                <table class="grid-table">
                    <thead>
                        <tr>
                            <th width="8%">SI NO</th>
                            <th width="42%">Description of Service</th>
                            <th width="15%">HSN/SAC</th>
                            <th width="15%">Rate</th>
                            <th width="10%">Tax %</th>
                            <th width="10%">Amount</th>
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
                            <td colspan="5" align="right">Output CGST 9%</td>
                            <td>{cgst:.2f}</td>
                        </tr>
                        <tr>
                            <td colspan="5" align="right">Output SGST 9%</td>
                            <td>{sgst:.2f}</td>
                        </tr>
                        <tr style="background-color: #FAF5FF; font-weight: bold;">
                            <td colspan="5" align="right" style="color: #6B21A8;">Invoice Value</td>
                            <td style="color: #6B21A8;">{total_amount:.2f}</td>
                        </tr>
                    </tbody>
                </table>
            </td>
        </tr>

        <!-- Bank Details & Declaration -->
        <tr>
            <td width="55%" class="cell-pad b-top b-right purple-bg" valign="top">
                <strong style="color: #6B21A8;">Company Bank Details:</strong><br/>
                <strong>A/c Name:</strong> ARYU ACADEMY PVT LTD<br/>
                <strong>Bank Name:</strong> Federal Bank<br/>
                <strong>A/c No:</strong> 12330200034467<br/>
                <strong>IFSC/BR:</strong> FDRL0001233<br/>
                <strong>UPI ID:</strong> aryuacademy8299@fbl<br/>
                <strong>Company PAN No:</strong> ABECA6801B1
            </td>
            <td width="45%" class="cell-pad b-top" valign="top" style="text-align: right;">
                <div style="font-size: 12px; font-weight: bold; color: #16A34A; margin-bottom: 5px;">PAID</div>
                <div style="font-size: 8px; color: #64748B; text-align: left;">
                    <strong>Declaration:</strong><br/>
                    We declare that this invoice shows the actual price of the service described and all particulars are true and correct.<br/><br/>
                    <em>Computer Generated Invoice - Signature Not Required</em>
                </div>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    # 4. Generate PDF
    pdf_buffer = BytesIO()
    pisa.CreatePDF(invoice_html, dest=pdf_buffer)
    pdf_data = pdf_buffer.getvalue()

    # 5. Send Email with Portal URL, Working Credentials & PDF Attachment
    email_message = EmailMessage(
        subject="Welcome to Aryu Academy - Login Credentials & Tax Invoice",
        body=f"""Hello Tamil Selvi,

Welcome to ARYU Academy!

Your account has been configured. You can log in to your learning portal using the credentials below:

• Portal URL: https://portal.aryuacademy.com
• Username: {test_email}
• Password: {raw_password}

Your official GST Tax Invoice ({invoice_no}) is attached to this email as a PDF document.

Best regards,
ARYU Academy Team
""",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[test_email]
    )
    email_message.attach(f"Tax_Invoice_{invoice_no}.pdf", pdf_data, "application/pdf")
    email_message.send(fail_silently=False)

    print(f"[SUCCESS] Email dispatched with working credentials and official Tax Invoice to {test_email}")

if __name__ == "__main__":
    main()

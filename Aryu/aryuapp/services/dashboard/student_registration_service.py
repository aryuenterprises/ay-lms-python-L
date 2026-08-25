import secrets
import logging
import re
from django.db import transaction
from django.conf import settings

logger = logging.getLogger(__name__)

def is_payment_successful(status: str) -> bool:
    """Helper to check if a transaction payment status indicates success."""
    return str(status).lower() in ["done", "paid", "success", "captured"]

def get_or_create_student_from_bootcamp(name: str, email: str, phone: str, profession: str = "", extra_data: dict = None):
    """
    Creates or fetches a Student record and queues welcome credentials & invoice email.
    """
    from aryuapp.models import Student, School_Student, College_Student, Employee, JobSeeker

    if extra_data is None:
        extra_data = {}

    email = email.strip().lower() if email else ""
    phone = phone.strip() if phone else ""

    # Look up by email first, fallback to contact_no
    student = None
    if email:
        student = Student.objects.filter(email=email).first()
    if not student and phone:
        student = Student.objects.filter(contact_no=phone).first()

    created = False
    random_password = None

    if not student:
        created = True
        random_password = secrets.token_urlsafe(8)
        
        name_clean = name.strip() if name else ""
        if name_clean:
            name_parts = name_clean.split(maxsplit=1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ""
        else:
            first_name = email.split("@")[0] if email else "student"
            last_name = ""

        # Generate unique username
        email_handle = email.split("@")[0] if email else "student"
        base_username = re.sub(r'[^a-zA-Z0-9_]', '', email_handle) or "student"
        base_username = base_username[:30]

        username = base_username
        counter = 1
        while Student.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        from django.contrib.auth.hashers import make_password
        student = Student(
            username=username,
            password=make_password(random_password),
            first_name=first_name,
            last_name=last_name,
            email=email,
            contact_no=phone,
            created_by_type="public",
            converter="campaign",
            status=True,
            current_address="N/A",
            permanent_address="N/A",
            city="N/A",
            state="N/A",
            country="India",
        )
        student.save()

        # Create profession-specific subprofile
        prof_lower = profession.lower()
        if "school" in prof_lower:
            School_Student.objects.get_or_create(student=student)
        elif "college" in prof_lower or "student" in prof_lower:
            College_Student.objects.get_or_create(student=student)
        elif "working" in prof_lower or "employee" in prof_lower or "professional" in prof_lower:
            Employee.objects.get_or_create(student=student)
        else:
            JobSeeker.objects.get_or_create(student=student)
    else:
        # If student exists, update status and contact info to ensure visibility
        updated_fields = []
        if not student.status:
            student.status = True
            updated_fields.append("status")
        
        name_clean = name.strip() if name else ""
        if name_clean and not student.first_name:
            name_parts = name_clean.split(maxsplit=1)
            student.first_name = name_parts[0]
            student.last_name = name_parts[1] if len(name_parts) > 1 else ""
            updated_fields.extend(["first_name", "last_name"])
            
        if email and not student.email:
            student.email = email
            updated_fields.append("email")
        if updated_fields:
            student.save(update_fields=updated_fields)

    # Queue post-commit welcome email and invoice
    txn_id = extra_data.get("transaction_id")
    transaction.on_commit(lambda: _safe_send_welcome_email(student, random_password, transaction_id=txn_id))

    return student, created

def _safe_send_welcome_email(student, password=None, transaction_id=None):
    """Internal helper to render template and send email with invoice attachment."""
    try:
        from webinar.services import send_student_credentials_email
        send_student_credentials_email(student=student, password=password, transaction_id=transaction_id)
    except Exception as e:
        logger.exception("Failed to send welcome credentials email to %s: %s", getattr(student, "email", ""), e)


def generate_invoice_pdf(context):
    """Generates PDF receipt using xhtml2pdf based on the official ARYU Academy GST Tax Invoice layout."""
    from io import BytesIO
    from xhtml2pdf import pisa
    
    student_name = context.get("student_name", "N/A")
    student_email = context.get("username", "N/A")
    student_phone = context.get("phone", "9876543210")
    
    invoice_id = context.get("invoice_id", "N/A")
    order_id = context.get("order_id", "N/A")
    course_title = context.get("course_title", "N/A")
    amount_paid = context.get("amount_paid", "0.00")
    date_str = context.get("date", "N/A")
    
    try:
        total_amount = float(amount_paid)
    except (ValueError, TypeError):
        total_amount = 499.00
        
    taxable_value = round(total_amount / 1.18, 2)
    cgst = round(taxable_value * 0.09, 2)
    sgst = round(taxable_value * 0.09, 2)
    
    # Generate Invoice No (dynamic or from context)
    invoice_no = context.get("invoice_no")
    if not invoice_no:
        from django.utils import timezone
        invoice_no = f"AA{timezone.now().strftime('%y%m')}{invoice_id}"
        
    invoice_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
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
                <span style="font-size: 10px; color: #4A5568;">Date: {date_str}</span><br/>
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
                Email: {student_email} | Phone: {student_phone}
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
                <td>{course_title}</td>
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
                <div style="font-size: 9px; color: #718096;">Payment Txn ID: {invoice_id}</div>
                <div style="font-size: 9px; color: #718096;">Order ID: {order_id}</div>
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
    pdf_buffer = BytesIO()
    pisa.CreatePDF(invoice_html, dest=pdf_buffer)
    return pdf_buffer.getvalue()
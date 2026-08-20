# services/student_registration_service.py
import secrets
import logging
from typing import Tuple, Optional
import os
from django.apps import apps
from django.db import transaction
from django.db.models import Q
from django.contrib.auth.hashers import make_password
from django.core.mail import EmailMessage
from django.utils import timezone
from django.conf import settings
# Import core student models from aryuapp
from aryuapp.models import (
    Student, 
    School_Student, 
    College_Student, 
    Employee, 
    JobSeeker, 
)
from email.mime.image import MIMEImage
logger = logging.getLogger(__name__)

# Fallback Portal URL using your domain
PORTAL_URL = getattr(settings, "PORTAL_URL", "https://portal.aryuacademy.com/")

# Valid payment statuses that confirm a paid transaction
SUCCESSFUL_PAYMENT_STATUSES = {"success", "done", "paid", "complete"}


def is_payment_successful(status_str: Optional[str]) -> bool:
    if not status_str:
        return False
    return status_str.strip().lower() in SUCCESSFUL_PAYMENT_STATUSES


@transaction.atomic
def get_or_create_student_from_bootcamp( 
    name: str,
    email: str,
    phone: str,
    profession: str = "",
    extra_data: dict = None
) -> Tuple[object, bool]:
    """
    Creates or fetches a Student instance upon verified Bootcamp/Webinar payment.
    Ensures created_by_type="public", converter="campaign", and status=True.
    """
    extra_data = extra_data or {}
    email = (email or "").strip().lower()
    phone = (phone or "").strip()

    # 1. Look up existing student by email or contact number
    lookup_query = Q()
    if email:
        lookup_query |= Q(email__iexact=email)
    if phone:
        lookup_query |= Q(contact_no=phone)

    student = Student.objects.select_for_update().filter(lookup_query).first()

    if student:
        # Update campaign converter if missing
        if not student.converter:
            student.converter = "campaign"
            student.save(update_fields=["converter"])
        return student, False

    # 2. Extract name components
    name_parts = name.strip().split(" ", 1) if name else ["Bootcamp", "User"]
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    # 3. Determine student sub-type
    prof_lower = (profession or "").strip().lower()
    if "school" in prof_lower:
        sub_type = "school_student"
    elif "college" in prof_lower or "student" in prof_lower:
        sub_type = "college_student"
    elif "working" in prof_lower or "employee" in prof_lower:
        sub_type = "employee"
    else:
        sub_type = "job_seeker"

    # 4. Auto-generate credentials and registration ID
    random_password = secrets.token_urlsafe(10)
    reg_id = f"REG-CAMP-{secrets.token_hex(4).upper()}"

    # 5. Create active Student profile
    student = Student.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        contact_no=phone,
        registration_id=reg_id,
        username=email or phone,
        password=make_password(random_password),
        status=True,                     # Active status
        converter="campaign",            # Set to campaign
        created_by_type="public",        # Crucial for StudentListAPIView filtering
        source_type="bootcamp",
        source_name="Bootcamp Registration",
        student_type=sub_type,
        is_archived=False,
    )

    # 6. Create corresponding sub-profile entry
    _create_student_sub_profile(student, sub_type, email, phone, profession, extra_data)

    # 7. Post-commit notification
    transaction.on_commit(lambda: _safe_send_welcome_email(student, random_password))

    return student, True


def _create_student_sub_profile(student, sub_type, email, phone, profession, extra_data):
    sub_table_data = {
        "student": student,
        "email": email,
        "phone_number": phone,
    }
    try:
        if sub_type == "school_student":
            School_Student.objects.create(
                school_name=extra_data.get("school_name", "Not Provided"),
                standard=extra_data.get("standard", ""),
                **sub_table_data
            )
        elif sub_type == "college_student":
            College_Student.objects.create(
                college_name=extra_data.get("college_name", "Not Provided"),
                degree=extra_data.get("degree", ""),
                **sub_table_data
            )
        elif sub_type == "employee":
            Employee.objects.create(
                designation=profession or "Employed",
                **sub_table_data
            )
        elif sub_type == "job_seeker":
            JobSeeker.objects.create(
                qualification=extra_data.get("qualification", ""),
                **sub_table_data
            )
    except Exception as exc:
        logger.error(f"Failed to create sub-profile for student {getattr(student, 'student_id', student.pk)}: {exc}")


def _safe_send_welcome_email(student, password, transaction_id=None):
    try:
        send_welcome_and_invoice_email(student, password, transaction_id)
    except Exception as exc:
        logger.error(f"Email failure for student {getattr(student, 'student_id', student.pk)}: {exc}")


def send_welcome_and_invoice_email(student, raw_password: str, transaction_id: Optional[str] = None):
    """
    Sends Welcome Email containing credentials, portal login link,
    embeds local logo image inline, and attaches the Payment Invoice PDF if available.
    """
    try:
        subject = "Welcome to Aryu Academy - Registration & Payment Receipt"
        recipient_email = getattr(student, "email", None) or getattr(student, "username", None)

        if not recipient_email:
            logger.warning(f"[Email Skipped] Student ID {getattr(student, 'student_id', student.pk)} has no email address.")
            return

        # 1. Fetch Invoice PDF attachment if transaction exists
        pdf_file = None
        pdf_name = "Invoice.pdf"

        if transaction_id:
            try:
                PaymentTransactionModel = None
                for app_config in apps.get_app_configs():
                    try:
                        PaymentTransactionModel = apps.get_model(app_config.label, 'PaymentTransaction')
                        if PaymentTransactionModel:
                            break
                    except LookupError:
                        continue

                if PaymentTransactionModel:
                    txn = PaymentTransactionModel.objects.filter(
                        Q(transaction_id=transaction_id) | Q(id=transaction_id) if str(transaction_id).isdigit() else Q(transaction_id=transaction_id)
                    ).first()

                    if txn and getattr(txn, 'invoice', None):
                        txn.invoice.open("rb")
                        pdf_file = txn.invoice.read()
                        txn.invoice.close()
                        pdf_name = f"Invoice_{getattr(txn, 'invoice_no', None) or txn.transaction_id}.pdf"
            except Exception as e:
                logger.error(f"[Email Invoice Attachment Error] Could not load PDF for transaction {transaction_id}: {str(e)}")

        # 2. Local Logo Path & Content-ID Setup
        logo_path = "/home/tamilselvi/Downloads/Clip_path_group_2026-03-23_12-07-28.png"
        logo_cid = "aryu_logo_cid"

        # 3. Construct HTML Body referencing cid:aryu_logo_cid
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 20px auto; padding: 0; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; }}
                .header {{ background-color: #501474; color: #ffffff; padding: 25px 20px; text-align: center; }}
                .logo {{ max-height: 60px; width: auto; margin-bottom: 10px; display: inline-block; }}
                .header h2 {{ margin: 0; font-size: 22px; font-weight: bold; color: #ffffff; }}
                .content {{ padding: 25px 20px; }}
                .credentials-box {{ background-color: #f8f9fa; border-left: 4px solid #501474; padding: 15px 20px; margin: 20px 0; border-radius: 0 6px 6px 0; }}
                .credentials-box h3 {{ margin-top: 0; color: #501474; }}
                .btn {{ display: inline-block; padding: 12px 24px; background-color: #501474; color: #ffffff !important; text-decoration: none; border-radius: 5px; font-weight: bold; margin-top: 15px; }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #777; text-align: center; padding: 15px 20px; border-top: 1px solid #eeeeee; }}
                a {{ color: #501474; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <img src="cid:{logo_cid}" alt="Aryu Academy Logo" class="logo" /><br/>
                    <h2>Welcome to Aryu Academy!</h2>
                </div>
                <div class="content">
                    <p>Dear <strong>{student.first_name} {getattr(student, 'last_name', '') or ''}</strong>,</p>
                    <p>Thank you for registering through our campaign. Your account registration and payment have been processed successfully.</p>
                    
                    <div class="credentials-box">
                        <h3>Your Student Portal Login Credentials:</h3>
                        <p><strong>Portal Link:</strong> <a href="{PORTAL_URL}">{PORTAL_URL}</a></p>
                        <p><strong>Username:</strong> {student.username}</p>
                        <p><strong>Password:</strong> {raw_password}</p>
                    </div>

                    <p>Please log in to access your course materials and batch information.</p>
                    <a href="{PORTAL_URL}" class="btn">Login to Student Portal</a>

                    <p style="margin-top: 25px;"><em>Note: Your payment invoice is attached to this email for your records.</em></p>
                </div>
                <div class="footer">
                    <p>&copy; {timezone.now().year} Aryu Academy. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        email = EmailMessage(
            subject=subject,
            body=html_content,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "support@aryuacademy.com"),
            to=[recipient_email],
        )
        email.content_subtype = "html"

        # 4. Attach Local Logo as Inline MIMEImage
        # 4. Attach Local Logo as Inline MIMEImage
        if os.path.exists(logo_path):
            try:
                with open(logo_path, "rb") as f:
                    logo_data = f.read()
                mime_image = MIMEImage(logo_data, _subtype="png")
                mime_image.add_header("Content-ID", f"<{logo_cid}>")
                mime_image.add_header("Content-Disposition", "inline", filename="logo.png")
                email.attach(mime_image)
            except Exception as img_err:
                logger.error(f"[Email Warning] Failed to attach logo image: {str(img_err)}")
        else:
            logger.warning(f"[Email Warning] Logo file not found at path: {logo_path}")

        # 5. Attach Invoice PDF if found
        if pdf_file:
            email.attach(pdf_name, pdf_file, "application/pdf")

        email.send(fail_silently=False)
        logger.info(f"[Email Sent] Welcome & Invoice email sent successfully to {recipient_email}")

    except Exception as exc:
        logger.error(f"[Email Error] Failed sending email to student {getattr(student, 'student_id', student.pk)}: {str(exc)}")
        raise
      
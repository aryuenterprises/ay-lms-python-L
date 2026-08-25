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
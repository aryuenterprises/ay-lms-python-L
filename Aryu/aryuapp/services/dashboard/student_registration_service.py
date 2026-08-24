import secrets
import logging
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
    from student.models import Student, School_Student, College_Student, Employee, JobSeeker

    if extra_data is None:
        extra_data = {}

    email = email.strip().lower() if email else ""
    phone = phone.strip() if phone else ""

    # Fetch existing student or build new student
    student = Student.objects.filter(email=email).first() if email else None
    if not student and phone:
        student = Student.objects.filter(phone=phone).first()

    created = False
    random_password = None

    if not student:
        created = True
        random_password = secrets.token_urlsafe(8)
        student = Student(
            full_name=name,
            email=email,
            phone=phone,
            created_by_type="public",
            converter="campaign",
            status=True,
        )
        student.set_password(random_password)
        student.save()

        # Handle profession sub-model creation
        prof_lower = profession.lower()
        if "school" in prof_lower:
            School_Student.objects.get_or_create(student=student)
        elif "college" in prof_lower or "student" in prof_lower:
            College_Student.objects.get_or_create(student=student)
        elif "working" in prof_lower or "employee" in prof_lower or "professional" in prof_lower:
            Employee.objects.get_or_create(student=student)
        else:
            JobSeeker.objects.get_or_create(student=student)

    # Post-commit welcome email trigger with transaction_id for invoice generation
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

def get_or_create_student_from_bootcamp(name: str, email: str, phone: str, profession: str = "", extra_data: dict = None):
    from student.models import Student, School_Student, College_Student, Employee, JobSeeker

    if extra_data is None:
        extra_data = {}

    email = email.strip().lower() if email else ""
    phone = phone.strip() if phone else ""

    # Look up by email first, fallback to phone
    student = None
    if email:
        student = Student.objects.filter(email=email).first()
    if not student and phone:
        student = Student.objects.filter(phone=phone).first()

    created = False
    random_password = None

    if not student:
        created = True
        random_password = secrets.token_urlsafe(8)
        student = Student(
            full_name=name,
            email=email,
            phone=phone,
            created_by_type="public",
            converter="campaign",
            status=True,  # Ensure active so it shows in the active list
        )
        student.set_password(random_password)
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
        if name and not student.full_name:
            student.full_name = name
            updated_fields.append("full_name")
        if email and not student.email:
            student.email = email
            updated_fields.append("email")
        if updated_fields:
            student.save(update_fields=updated_fields)

    # Queue post-commit welcome email and invoice
    txn_id = extra_data.get("transaction_id")
    transaction.on_commit(lambda: _safe_send_welcome_email(student, random_password, transaction_id=txn_id))

    return student, created

    
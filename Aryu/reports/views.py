import os
import math
import re
from datetime import datetime, date, time, timedelta
from collections import defaultdict
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.db.models import Q, Sum, Prefetch, Count, Max
from django.conf import settings
from django.db import transaction, models
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from aryuapp.auth import CustomJWTAuthentication
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
import logging
from aryuapp.models import Student, StudentCourse, Attendance, Trainer
from batches.models import NewBatch, ClassSchedule, BatchCourseTrainer
from payments.models import PaymentTransaction, TutorPayment
from payments.services.invoice_service import InvoiceService
from courses.models import Course, CourseCategory
from reports.models import GoogleReview
from reports.pagination import TutorPaymentReportPagination
from reports.serializers import GoogleReviewSerializer

logger = logging.getLogger(__name__)


def clean_and_extract_url(url_val):
    if not url_val:
        return None
    url_str = str(url_val).strip()
    if not url_str:
        return None
    # Un-wrap Markdown link format like [text](http://...) or <http://...>
    match = re.search(r'https?://[^\s\)\]"]+', url_str)
    if match:
        url_str = match.group(0)
    return url_str


def extract_filename_or_relative_path(input_val):
    if not input_val:
        return None
    if not isinstance(input_val, str):
        return None
    cleaned = clean_and_extract_url(input_val)
    if not cleaned:
        return None
    return cleaned.rstrip("/").split("/")[-1]


def parse_bool(val):
    """
    Safely coerce multipart/form-data string values to Python booleans.
    Returns None if value is absent/unrecognised so callers can skip the field.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if str(val).strip().lower() in ["true", "1", "yes"]:
        return True
    if str(val).strip().lower() in ["false", "0", "no"]:
        return False
    return None


def resolve_screenshot_url(review, request=None):
    if not review:
        return None
    screenshot = getattr(review, "screenshot", None) or getattr(review, "screenshot_url", None)
    if not screenshot:
        return None

    # Extract clean file name (e.g., "AYA0826066_review.png")
    if hasattr(screenshot, "name") and screenshot.name:
        filename = os.path.basename(screenshot.name)
    elif isinstance(screenshot, str) and screenshot.strip():
        clean_url = clean_and_extract_url(screenshot)
        filename = clean_url.rstrip("/").split("/")[-1] if clean_url else None
    else:
        return None

    if not filename:
        return None

    # Base URL without trailing slash
    base_url = getattr(settings, "MEDIA_BASE_URL", "").rstrip("/")

    # Ensure /media/ segment is present
    if not base_url.endswith("/media"):
        base_url = f"{base_url}/media"

    return f"{base_url}/{filename}"


def extract_batch_schedule(batch, course=None):
    """
    Extract and format schedule details from a NewBatch instance.
    Duration is resolved from Course metadata first, then batch.duration,
    then a date-span fallback.
    """
    if not batch:
        return {
            "batch_duration": "-",
            "start_time": None,
            "end_time": None,
            "start_date": None,
            "end_date": None,
        }

    s_date = batch.start_date.strftime("%Y-%m-%d") if getattr(batch, "start_date", None) else None
    e_date = batch.end_date.strftime("%Y-%m-%d") if getattr(batch, "end_date", None) else None
    s_time = batch.start_time.strftime("%I:%M %p") if getattr(batch, "start_time", None) else None
    e_time = batch.end_time.strftime("%I:%M %p") if getattr(batch, "end_time", None) else None

    duration = None
    target_course = course or getattr(batch, "course", None)
    if target_course and getattr(target_course, "duration", None):
        unit = f" {target_course.duration_type}" if getattr(target_course, "duration_type", None) else ""
        duration = f"{target_course.duration}{unit}".strip()
    elif getattr(batch, "duration", None):
        duration = str(batch.duration)
    elif s_date and e_date:
        duration = f"{s_date} to {e_date}"

    return {
        "batch_duration": duration or "-",
        "start_time": s_time or "-",
        "end_time": e_time or "-",
        "start_date": s_date or "-",
        "end_date": e_date or "-",
    }


def parse_date_bound_from(date_str):
    if not date_str:
        return None
    dt = parse_datetime(date_str)
    if dt is None:
        d = parse_date(date_str)
        if d:
            dt = datetime.combine(d, time.min)
    if dt:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt
    return None


def parse_date_bound_to(date_str):
    if not date_str:
        return None, "lte"
    dt = parse_datetime(date_str)
    if dt is not None:
        if dt.time() == time.min:
            dt = datetime.combine(dt.date() + timedelta(days=1), time.min)
            lookup = "lt"
        else:
            lookup = "lte"
    else:
        d = parse_date(date_str)
        if d:
            dt = datetime.combine(d + timedelta(days=1), time.min)
            lookup = "lt"
        else:
            return None, "lte"

    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt, lookup

class AryuReportView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    required_module = "Aryu Report"

    def get(self, request):
        try:
            search = request.GET.get("search", "").strip()
            tutor_id = request.GET.get("tutor_id", "").strip()
            course_id = request.GET.get("course_id", "").strip()

            # Ordered descending by creation date (-created_at)
            students = Student.objects.filter(
                is_archived=False,
                status=True
            ).filter(
                Q(student_courses__isnull=False) | Q(new_batches__isnull=False)
            ).order_by("-created_at").distinct()

            if search:
                students = students.filter(
                    Q(first_name__icontains=search) |
                    Q(last_name__icontains=search) |
                    Q(contact_no__icontains=search) |
                    Q(email__icontains=search) |
                    Q(registration_id__icontains=search)
                )

            if tutor_id:
                students = students.filter(
                    new_batches__trainer__trainer_id=tutor_id
                ).distinct()

            if course_id:
                students = students.filter(
                    new_batches__course__course_id=course_id,
                    new_batches__is_archived=False,
                    new_batches__status=True,
                ).distinct()

            courses = list(
                Course.objects.filter(is_archived=False)
                .values("course_id", "course_name")
                .order_by("course_name")
            )

            categories = list(
                CourseCategory.objects.filter(is_archived=False)
                .values("category_id", "category_name")
                .order_by("category_name")
            )

            data = []

            for student in students:
                full_name = (
                    f"{student.first_name or ''} "
                    f"{student.last_name or ''}"
                ).strip()

                student_data = {
                    "student_id": student.student_id,
                    "registration_id": student.registration_id,
                    "student_name": full_name,
                    "phone": student.contact_no,
                    "email": student.email,
                    "converter": student.converter,
                    "student_type": student.student_type,
                    "created_at": student.created_at,
                    "courses": []
                }

                batches = (
                    NewBatch.objects.filter(
                        students__student_id=student.student_id,
                        is_archived=False,
                        status=True,
                    )
                    .select_related("course")
                    .prefetch_related("trainers")
                    .distinct()
                )

                for batch in batches:
                    course = batch.course

                    transactions = (
                        PaymentTransaction.objects.filter(
                            student__student_id=student.student_id,
                            course=course,
                            is_archived=False
                        )
                        .order_by("-invoice_date", "-created_at")
                    )

                    totals = transactions.aggregate(
                        total_amount=Sum("amount"),
                        paid_amount=Sum("amount_received"),
                        balance_amount=Sum("balance_due"),
                        discount_amount=Sum("discount")
                    )

                    payment_history = []
                    trainer = batch.trainers.first()

                    for payment in transactions:
                        payment_history.append({
                            "id": payment.id,
                            "transaction_id": payment.transaction_id,
                            "invoice_date": payment.invoice_date,
                            "amount": float(payment.amount or 0),
                            "amount_received": float(payment.amount_received or 0),
                            "balance_due": float(payment.balance_due or 0),
                            "payment_status": payment.payment_status,
                            "payment_mode": (
                                payment.metadata.get("mode")
                                if payment.metadata
                                else None
                            ),
                            "invoice_url": (
                                request.build_absolute_uri(payment.invoice.url)
                                if payment.invoice
                                else None
                            )
                        })

                    student_data["courses"].append({
                        "course_id": course.course_id if course else None,
                        "course_name": course.course_name if course else None,
                        "course_type": course.mode_of_delivery if course else None,
                        "course_fee": course.fee,
                        "batch_id": batch.batch_id,
                        "batch_name": batch.title,
                        "duration": course.duration,
                        "duration_type": course.duration_type,
                        "batch_start_date": batch.start_date,
                        "batch_end_date": batch.end_date,
                        "trainer_name": trainer.full_name if trainer else "N/A",
                        "total_amount": float(totals["total_amount"] or 0),
                        "paid_amount": float(totals["paid_amount"] or 0),
                        "balance_amount": float(totals["balance_amount"] or 0),
                        "discount_amount": float(totals["discount_amount"] or 0),
                        "payment_history": payment_history
                    })

                if not student_data["courses"]:
                    transactions = (
                        PaymentTransaction.objects.filter(
                            student__student_id=student.student_id,
                            is_archived=False
                        )
                        .order_by("-created_at")
                    )

                    payment_history = []

                    for payment in transactions:
                        payment_history.append({
                            "id": payment.id,
                            "transaction_id": payment.transaction_id,
                            "invoice_date": payment.invoice_date,
                            "amount": float(payment.amount or 0),
                            "amount_received": float(payment.amount_received or 0),
                            "balance_due": float(payment.balance_due or 0),
                            "payment_status": payment.payment_status
                        })

                    student_data["payment_history"] = payment_history

                data.append(student_data)

            return Response({
                "success": True,
                "total_records": students.count(),
                "students": data,
                "data": data,
                "courses": courses,
                "categories": categories,
            })

        except Exception as e:
            logger.exception("Error in AryuReportView")
            return Response(
                {
                    "success": False,
                    "message": "An unexpected error occurred."
                },
                status=500
            )


class StudentEnrollmentReportView(APIView):
    """
    Production-grade API Endpoint for Student Enrollment Report.
    Supports role enforcement, input sanitization, batch lifecycle status filtering
    (current, completed, future), and database-level pagination.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    _VALID_BATCH_STATUSES = {"current", "ongoing", "completed", "past", "future", "upcoming"}

    @staticmethod
    def _build_batch_lifecycle_query(batch_status, now_dt):
        today = now_dt.date()
        current_time = now_dt.time()

        if batch_status in ("current", "ongoing"):
            cond = (
                (Q(start_date__lt=today) & Q(end_date__gt=today)) |
                Q(start_date=today, end_date__gt=today, start_time__lte=current_time) |
                Q(start_date__lt=today, end_date=today, end_time__gte=current_time) |
                Q(start_date=today, end_date=today, start_time__lte=current_time, end_time__gte=current_time)
            )
        elif batch_status in ("completed", "past"):
            cond = Q(end_date__lt=today) | Q(end_date=today, end_time__lt=current_time)
        elif batch_status in ("future", "upcoming"):
            cond = Q(start_date__gt=today) | Q(start_date=today, start_time__gt=current_time)
        else:
            return Q()

        matching = NewBatch.objects.filter(cond)
        return (
            Q(new_batches__is_archived=False, new_batches__in=matching) |
            Q(student_courses__batch__is_archived=False, student_courses__batch__in=matching)
        )

    def get(self, request):
        try:
            # 1. RBAC
            user = request.user
            if getattr(user, "user_type", "") not in ["super_admin", "admin"]:
                return Response({"success": False, "message": "Unauthorized access."}, status=status.HTTP_403_FORBIDDEN)

            # 2. Bounded Pagination (OWASP A04)
            try:
                page = max(1, int(request.GET.get("page", 1)))
            except (ValueError, TypeError):
                page = 1
            try:
                limit = min(100, max(1, int(request.GET.get("limit", 50))))
            except (ValueError, TypeError):
                limit = 50

            # 3. Input Sanitization
            search = request.GET.get("search", "").strip()
            course_id = request.GET.get("course_id", "").strip()
            batch_id = request.GET.get("batch_id", "").strip()
            batch_status = request.GET.get("batch_status", "").strip().lower()
            from_date_str = request.GET.get("from_date", "").strip()
            to_date_str = request.GET.get("to_date", "").strip()
            sort_by = request.GET.get("sort_by", "created_at").strip().lower()
            sort_order = request.GET.get("sort_order", "desc").strip().lower()

            # Whitelist batch_status
            if batch_status not in self._VALID_BATCH_STATUSES:
                batch_status = ""

            # Cascade check
            if course_id and batch_id:
                valid = (
                    NewBatch.objects.filter(batch_id=batch_id, course_id=course_id, is_archived=False).exists() or
                    StudentCourse.objects.filter(batch_id=batch_id, course_id=course_id).exists()
                )
                if not valid:
                    batch_id = ""

            # 4. Base QuerySet
            students_qs = Student.objects.filter(
                is_archived=False, status=True
            ).filter(Q(student_courses__isnull=False) | Q(new_batches__isnull=False))

            if search:
                students_qs = students_qs.filter(
                    Q(first_name__icontains=search) | Q(last_name__icontains=search) |
                    Q(email__icontains=search) | Q(registration_id__icontains=search) |
                    Q(student_courses__course__course_name__icontains=search) |
                    Q(student_courses__batch__title__icontains=search) |
                    Q(new_batches__course__course_name__icontains=search) |
                    Q(new_batches__title__icontains=search)
                )
            if course_id:
                students_qs = students_qs.filter(
                    Q(student_courses__course_id=course_id) | Q(new_batches__course_id=course_id)
                )
            if batch_id:
                students_qs = students_qs.filter(
                    Q(student_courses__batch_id=batch_id) | Q(new_batches__batch_id=batch_id)
                )

            # 5. Batch Lifecycle Filter
            now_dt = timezone.now()
            if batch_status:
                students_qs = students_qs.filter(
                    self._build_batch_lifecycle_query(batch_status, now_dt)
                )

            # 6. Date Filters
            if from_date_str:
                parsed_from = parse_date_bound_from(from_date_str)
                if parsed_from:
                    students_qs = students_qs.filter(created_at__gte=parsed_from)
            if to_date_str:
                parsed_to, lookup = parse_date_bound_to(to_date_str)
                if parsed_to:
                    if lookup == "lt":
                        students_qs = students_qs.filter(created_at__lt=parsed_to)
                    else:
                        students_qs = students_qs.filter(created_at__lte=parsed_to)

            # 7. Sorting
            sort_map = {
                "created_at": "created_at", "enrolled_at": "created_at",
                "student_name": "first_name", "name": "first_name",
                "first_name": "first_name", "last_name": "last_name",
                "registration_id": "registration_id", "student_id": "registration_id",
            }
            order_field = sort_map.get(sort_by, "created_at")
            order_expr = order_field if sort_order == "asc" else f"-{order_field}"

            students_qs = students_qs.distinct()
            total_count = students_qs.count()

            # 8. Slice & Prefetch
            offset = (page - 1) * limit
            sliced_students = students_qs.order_by(order_expr, "-student_id").prefetch_related(
                Prefetch("student_courses", queryset=StudentCourse.objects.select_related("course", "batch")),
                Prefetch("new_batches", queryset=NewBatch.objects.select_related("course"))
            )[offset:offset + limit]

            # 9. Active courses for filter options & validation
            active_courses = list(
                Course.objects.filter(is_archived=False)
                .exclude(status__iexact="Inactive")
                .values("course_id", "course_name").order_by("course_name")
            )
            valid_active_course_ids = {c["course_id"] for c in active_courses if c["course_name"]}

            # 6. Build Response Data List
            data = []
            for s in sliced_students:
                full_name = f"{s.first_name or ''} {s.last_name or ''}".strip()

                courses_map = {}  # course_id -> course_name
                batches_map = {}  # batch_id -> batch_title

                # A. Collect from StudentCourse
                for sc in s.student_courses.all():
                    c_obj = sc.course
                    if c_obj and c_obj.course_id in valid_active_course_ids:
                        c_name = c_obj.course_name
                        if c_name:
                            if not course_id or str(c_obj.course_id) == str(course_id):
                                courses_map[c_obj.course_id] = c_name
                    if sc.batch and not getattr(sc.batch, "is_archived", False):
                        if not batch_id or str(sc.batch.batch_id) == str(batch_id):
                            batch_title = sc.batch.title or getattr(sc.batch, "batch_name", None)
                            if batch_title:
                                batches_map[sc.batch.batch_id] = batch_title

                # B. Collect from NewBatch
                for nb in s.new_batches.all():
                    c_obj = nb.course
                    if c_obj and c_obj.course_id in valid_active_course_ids:
                        c_name = c_obj.course_name
                        if c_name:
                            if not course_id or str(c_obj.course_id) == str(course_id):
                                courses_map[c_obj.course_id] = c_name
                    if nb.title and not getattr(nb, "is_archived", False):
                        if not batch_id or str(nb.batch_id) == str(batch_id):
                            batches_map[nb.batch_id] = nb.title

                # Fallback to all assigned if empty maps
                if not courses_map and not course_id:
                    for sc in s.student_courses.all():
                        c_obj = sc.course
                        if c_obj and c_obj.course_id in valid_active_course_ids:
                            if c_obj.course_name:
                                courses_map[c_obj.course_id] = c_obj.course_name
                    for nb in s.new_batches.all():
                        c_obj = nb.course
                        if c_obj and c_obj.course_id in valid_active_course_ids:
                            if c_obj.course_name:
                                courses_map[c_obj.course_id] = c_obj.course_name

                if not batches_map and not batch_id:
                    for sc in s.student_courses.all():
                        if sc.batch and not getattr(sc.batch, "is_archived", False):
                            b_name = sc.batch.title or getattr(sc.batch, "batch_name", None)
                            if b_name:
                                batches_map[sc.batch.batch_id] = b_name
                    for nb in s.new_batches.all():
                        if nb.title and not getattr(nb, "is_archived", False):
                            batches_map[nb.batch_id] = nb.title

                course_names = list(courses_map.values())
                course_ids = list(courses_map.keys())
                batch_names = list(batches_map.values())
                batch_ids = list(batches_map.keys())

                course_val = ", ".join(course_names) if course_names else "-"
                batch_val = ", ".join(batch_names) if batch_names else "-"

                created_at_iso = s.created_at.strftime('%Y-%m-%d') if s.created_at else "-"

                # Resolve primary batch object for schedule extraction
                primary_batch = None
                primary_course = None
                for sc in s.student_courses.all():
                    if sc.batch:
                        primary_batch = sc.batch
                        primary_course = sc.course
                        break
                if not primary_batch:
                    for nb in s.new_batches.all():
                        primary_batch = nb
                        primary_course = nb.course
                        break

                schedule = extract_batch_schedule(primary_batch, primary_course)

                # Compute batch lifecycle badge
                computed_status = "N/A"
                if primary_batch and getattr(primary_batch, "start_date", None) and getattr(primary_batch, "end_date", None):
                    t_date = now_dt.date()
                    if primary_batch.end_date < t_date:
                        computed_status = "Completed"
                    elif primary_batch.start_date > t_date:
                        computed_status = "Future"
                    else:
                        computed_status = "Current"

                data.append({
                    "id": str(s.student_id),
                    "student_id": s.registration_id or f"std_{s.student_id}",
                    "registration_id": s.registration_id or f"std_{s.student_id}",
                    "first_name": s.first_name or "",
                    "last_name": s.last_name or "",
                    "student_name": full_name,
                    "email": s.email or "",
                    "contact_no": s.contact_no or "",
                    "created_at": created_at_iso,
                    "enrolled_at": created_at_iso,
                    "course_id": course_ids[0] if course_ids else None,
                    "course_ids": course_ids,
                    "course_name": course_names,
                    "course": course_val,
                    "batch_id": batch_ids[0] if batch_ids else None,
                    "batch_ids": batch_ids,
                    "batch_title": batch_names,
                    "batch": batch_val,
                    "batch_status": computed_status,
                    "batch_duration": schedule["batch_duration"],
                    "start_time": schedule["start_time"],
                    "end_time": schedule["end_time"],
                    "start_date": schedule["start_date"],
                    "end_date": schedule["end_date"],
                })

            # 7. Fetch Active Filter Options for Dropdowns
            courses_options = [
                {
                    "id": c["course_id"],
                    "course_id": c["course_id"],
                    "name": c["course_name"],
                    "course_name": c["course_name"]
                }
                for c in active_courses
            ]

            batches_qs = NewBatch.objects.filter(is_archived=False, status=True)
            if course_id:
                batches_qs = batches_qs.filter(course_id=course_id)

            active_batches = list(
                batches_qs.values("batch_id", "title", "course_id").order_by("title")
            )
            batches_options = [
                {
                    "id": b["batch_id"],
                    "batch_id": b["batch_id"],
                    "name": b["title"],
                    "title": b["title"],
                    "course_id": b["course_id"]
                }
                for b in active_batches
            ]

            active_categories = list(
                CourseCategory.objects.filter(is_archived=False)
                .values("category_id", "category_name")
                .order_by("category_name")
            )
            categories_options = [
                {
                    "id": cat["category_id"],
                    "category_id": cat["category_id"],
                    "name": cat["category_name"],
                    "category_name": cat["category_name"]
                }
                for cat in active_categories
            ]

            filter_options = {
                "courses": courses_options,
                "batches": batches_options,
                "categories": categories_options
            }

            total_pages = math.ceil(total_count / limit) if total_count > 0 else 0

            return Response({
                "success": True,
                "students": data,
                "data": data,
                "courses": courses_options,
                "batches": batches_options,
                "categories": categories_options,
                "pagination": {
                    "total_count": total_count,
                    "page": page,
                    "limit": limit,
                    "total_pages": total_pages
                },
                "filter_options": filter_options
            }, status=200)

        except Exception as e:
            logger.exception("Error in StudentEnrollmentReportView")
            return Response(
                {
                    "success": False,
                    "message": "An error occurred while fetching the student enrollment report."
                },
                status=500
            )


class AttendanceReportView(APIView):
    """
    Production-grade Attendance Report API endpoint.
    GET /api/v1/reports/attendance (or /api/reports/attendance)
    Strictly bases report on active students (is_archived=False, status=True).
    Follows OWASP security guidelines and DSA best practices ($O(1)$ lookups, 0 N+1 queries).
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get(self, request):
        try:
            # 1. Parse & Sanitize Pagination Parameters (OWASP Input Validation)
            try:
                page = int(request.GET.get("page", 1))
                if page < 1:
                    page = 1
            except (ValueError, TypeError):
                page = 1

            try:
                limit = int(request.GET.get("limit", 50))
                if limit < 1:
                    limit = 50
                elif limit > 200:
                    limit = 200
            except (ValueError, TypeError):
                limit = 50

            # 2. Parse & Sanitize Query Filters
            raw_search = request.GET.get("search", "")
            search = str(raw_search).strip()[:100]

            raw_course_id = request.GET.get("course_id", "")
            course_id = str(raw_course_id).strip()

            raw_batch_id = request.GET.get("batch_id", "")
            batch_id = str(raw_batch_id).strip()

            from_date_str = request.GET.get("from_date", "").strip()
            to_date_str = request.GET.get("to_date", "").strip()

            # Sanitize Sort Parameters (OWASP Parameter Whitelisting)
            sort_by = request.GET.get("sort_by", "created_at").strip().lower()
            sort_order = request.GET.get("sort_order", "desc").strip().lower()
            if sort_order not in ["asc", "desc"]:
                sort_order = "desc"

            SORT_FIELDS_WHITELIST = {
                "created_at": "created_at",
                "enrolled_at": "created_at",
                "student_name": "first_name",
                "name": "first_name",
                "first_name": "first_name",
                "last_name": "last_name",
                "registration_id": "registration_id",
                "student_id": "student_id",
                "email": "email",
            }
            db_sort_field = SORT_FIELDS_WHITELIST.get(sort_by, "created_at")
            order_expr = db_sort_field if sort_order == "asc" else f"-{db_sort_field}"

            # Batch validation & reset rule
            if course_id and batch_id:
                valid_batch_exists = NewBatch.objects.filter(
                    batch_id=batch_id,
                    course_id=course_id,
                    is_archived=False
                ).exists() or StudentCourse.objects.filter(
                    batch_id=batch_id,
                    course_id=course_id
                ).exists()
                if not valid_batch_exists:
                    batch_id = ""

            # Primary Base Queryset: Active Students Only (is_archived=False, status=True)
            students_qs = Student.objects.filter(is_archived=False, status=True)

            # Search filter (fuzzy on student name, email, registration_id)
            if search:
                students_qs = students_qs.filter(
                    Q(first_name__icontains=search) |
                    Q(last_name__icontains=search) |
                    Q(email__icontains=search) |
                    Q(registration_id__icontains=search)
                )

            # Course filter
            if course_id:
                students_qs = students_qs.filter(
                    Q(student_courses__course_id=course_id) |
                    Q(new_batches__course_id=course_id)
                )

            # Batch filter
            if batch_id:
                students_qs = students_qs.filter(
                    Q(student_courses__batch_id=batch_id) |
                    Q(new_batches__batch_id=batch_id)
                )

            # Date Range Filter on enrollment / created_at date
            if from_date_str:
                parsed_from = parse_date_bound_from(from_date_str)
                if parsed_from:
                    students_qs = students_qs.filter(created_at__gte=parsed_from)

            if to_date_str:
                parsed_to, lookup = parse_date_bound_to(to_date_str)
                if parsed_to:
                    if lookup == "lt":
                        students_qs = students_qs.filter(created_at__lt=parsed_to)
                    else:
                        students_qs = students_qs.filter(created_at__lte=parsed_to)

            students_qs = students_qs.distinct()
            total_count = students_qs.count()

            # Paginate with efficient Prefetching on the paginated slice only
            offset = (page - 1) * limit
            sliced_students = students_qs.order_by(order_expr, "-student_id").prefetch_related(
                Prefetch(
                    "student_courses",
                    queryset=StudentCourse.objects.select_related("course", "batch")
                ),
                Prefetch(
                    "new_batches",
                    queryset=NewBatch.objects.select_related("course")
                )
            )[offset:offset + limit]

            # 5. Fetch Active Courses matching Course Management criteria (/api/courses)
            active_courses = list(
                Course.objects.filter(is_archived=False)
                .exclude(status__iexact="Inactive")
                .values("course_id", "course_name")
                .order_by("course_name")
            )
            valid_active_course_map = {c["course_id"]: c["course_name"] for c in active_courses if c["course_name"]}
            valid_active_course_ids = set(valid_active_course_map.keys())

            # DSA Optimization: Hash Map Pre-Collection ($O(1)$ lookups, zero N+1 queries)
            student_meta = {}
            all_batch_ids = set()
            all_course_ids = set()

            for s in sliced_students:
                courses_map = {}
                batches_map = {}

                for sc in s.student_courses.all():
                    c_obj = sc.course
                    if c_obj and c_obj.course_id in valid_active_course_ids:
                        c_name = c_obj.course_name
                        if c_name:
                            if not course_id or str(c_obj.course_id) == str(course_id):
                                courses_map[c_obj.course_id] = c_name
                    if sc.batch and not getattr(sc.batch, "is_archived", False):
                        if not batch_id or str(sc.batch.batch_id) == str(batch_id):
                            b_title = sc.batch.title or getattr(sc.batch, "batch_name", None)
                            if b_title:
                                batches_map[sc.batch.batch_id] = b_title

                for nb in s.new_batches.all():
                    c_obj = nb.course
                    if c_obj and c_obj.course_id in valid_active_course_ids:
                        c_name = c_obj.course_name
                        if c_name:
                            if not course_id or str(c_obj.course_id) == str(course_id):
                                courses_map[c_obj.course_id] = c_name
                    if nb.title and not getattr(nb, "is_archived", False):
                        if not batch_id or str(nb.batch_id) == str(batch_id):
                            batches_map[nb.batch_id] = nb.title

                if not courses_map and not course_id:
                    for sc in s.student_courses.all():
                        c_obj = sc.course
                        if c_obj and c_obj.course_id in valid_active_course_ids:
                            if c_obj.course_name:
                                courses_map[c_obj.course_id] = c_obj.course_name
                    for nb in s.new_batches.all():
                        c_obj = nb.course
                        if c_obj and c_obj.course_id in valid_active_course_ids:
                            if c_obj.course_name:
                                courses_map[c_obj.course_id] = c_obj.course_name

                if not batches_map and not batch_id:
                    for sc in s.student_courses.all():
                        if sc.batch and not getattr(sc.batch, "is_archived", False):
                            b_title = sc.batch.title or getattr(sc.batch, "batch_name", None)
                            if b_title:
                                batches_map[sc.batch.batch_id] = b_title
                    for nb in s.new_batches.all():
                        if nb.title and not getattr(nb, "is_archived", False):
                            batches_map[nb.batch_id] = nb.title

                c_ids = list(courses_map.keys())
                b_ids = list(batches_map.keys())

                student_meta[s.student_id] = {
                    "courses_map": courses_map,
                    "batches_map": batches_map,
                    "batch_ids": b_ids,
                    "course_ids": c_ids,
                }
                all_batch_ids.update(b_ids)
                all_course_ids.update(c_ids)

            student_pks = [s.student_id for s in sliced_students]

            # Bulk query active scheduled classes (is_archived=False, is_class_cancelled=False)
            schedules_by_new_batch = defaultdict(list)
            schedules_by_old_batch = defaultdict(list)
            schedules_by_course = defaultdict(list)

            if all_batch_ids or all_course_ids:
                sched_filter = Q(is_archived=False, is_class_cancelled=False)
                sched_scope = Q()
                if all_batch_ids:
                    sched_scope |= Q(new_batch_id__in=all_batch_ids) | Q(batch_id__in=all_batch_ids)
                if all_course_ids:
                    sched_scope |= Q(course_id__in=all_course_ids)

                schedules_qs = ClassSchedule.objects.filter(
                    sched_filter & sched_scope
                ).values(
                    "schedule_id", "new_batch_id", "batch_id", "course_id", "scheduled_date"
                )

                for cs in schedules_qs:
                    if cs["new_batch_id"]:
                        schedules_by_new_batch[cs["new_batch_id"]].append(cs)
                    if cs["batch_id"]:
                        schedules_by_old_batch[cs["batch_id"]].append(cs)
                    if cs["course_id"]:
                        schedules_by_course[cs["course_id"]].append(cs)

            # Bulk query attendance / login records for student_pks
            attendance_by_student = defaultdict(list)
            if student_pks:
                att_qs = Attendance.objects.filter(
                    student_id__in=student_pks
                ).exclude(
                    status__iexact="ABSENT"
                ).values(
                    "id", "student_id", "schedule_id", "new_batch_id", "batch_id", "course_id", "date", "status"
                )

                for att in att_qs:
                    attendance_by_student[att["student_id"]].append(att)

            data = []
            for idx, s in enumerate(sliced_students):
                s_no = offset + idx + 1
                full_name = f"{s.first_name or ''} {s.last_name or ''}".strip()

                meta = student_meta.get(s.student_id, {})
                courses_map = meta.get("courses_map", {})
                batches_map = meta.get("batches_map", {})
                batch_ids = meta.get("batch_ids", [])
                course_ids = meta.get("course_ids", [])

                course_names = list(courses_map.values())
                batch_names = list(batches_map.values())

                course_val = ", ".join(course_names) if course_names else "-"
                course_id_val = course_ids[0] if course_ids else None
                batch_val = ", ".join(batch_names) if batch_names else "-"
                batch_id_val = batch_ids[0] if batch_ids else None

                # Gather applicable scheduled classes for student s
                student_schedules = {}
                if batch_ids:
                    for b_id in batch_ids:
                        for cs in schedules_by_new_batch.get(b_id, []):
                            student_schedules[cs["schedule_id"]] = cs
                        for cs in schedules_by_old_batch.get(b_id, []):
                            student_schedules[cs["schedule_id"]] = cs
                elif course_ids:
                    for c_id in course_ids:
                        for cs in schedules_by_course.get(c_id, []):
                            student_schedules[cs["schedule_id"]] = cs

                total_classes = len(student_schedules)

                # Process student attendance / login records
                student_atts = attendance_by_student.get(s.student_id, [])
                att_schedule_ids = set()
                unassigned_att_date_batch_course = set()
                unassigned_att_dates = set()

                for att in student_atts:
                    if att["schedule_id"]:
                        att_schedule_ids.add(att["schedule_id"])
                    else:
                        raw_dt = att["date"]
                        att_date = raw_dt.date() if hasattr(raw_dt, "date") else raw_dt
                        if att_date:
                            unassigned_att_dates.add(att_date)
                            if att["new_batch_id"]:
                                unassigned_att_date_batch_course.add((att_date, "nb", att["new_batch_id"]))
                            if att["batch_id"]:
                                unassigned_att_date_batch_course.add((att_date, "b", att["batch_id"]))
                            if att["course_id"]:
                                unassigned_att_date_batch_course.add((att_date, "c", att["course_id"]))

                attended_classes = 0
                for cs_id, cs in student_schedules.items():
                    cs_date = cs["scheduled_date"]
                    is_attended = False

                    if cs_id in att_schedule_ids:
                        is_attended = True
                    elif cs["new_batch_id"] and (cs_date, "nb", cs["new_batch_id"]) in unassigned_att_date_batch_course:
                        is_attended = True
                    elif cs["batch_id"] and (cs_date, "b", cs["batch_id"]) in unassigned_att_date_batch_course:
                        is_attended = True
                    elif cs["course_id"] and (cs_date, "c", cs["course_id"]) in unassigned_att_date_batch_course:
                        is_attended = True
                    elif cs_date in unassigned_att_dates:
                        is_attended = True

                    if is_attended:
                        attended_classes += 1

                not_attended_classes = max(0, total_classes - attended_classes)
                attendance_percentage = round((attended_classes / total_classes) * 100, 2) if total_classes > 0 else 0.0

                formatted_date = s.created_at.strftime('%Y-%m-%d') if s.created_at else None

                data.append({
                    "s_no": s_no,
                    "id": str(s.student_id),
                    "student_id": s.registration_id or f"std_{s.student_id}",
                    "registration_id": s.registration_id or f"std_{s.student_id}",
                    "student_name": full_name,
                    "email": s.email,
                    "course": course_val,
                    "course_id": course_id_val,
                    "batch": batch_val,
                    "batch_id": batch_id_val,
                    "total_classes": total_classes,
                    "attended_classes": attended_classes,
                    "not_attended_classes": not_attended_classes,
                    "attendance_percentage": attendance_percentage,
                    "created_at": formatted_date,
                    "enrolled_at": formatted_date,
                })

            # 6. Fetch Active Filter Options for Dropdowns
            courses_options = [
                {
                    "id": c["course_id"],
                    "course_id": c["course_id"],
                    "name": c["course_name"],
                    "course_name": c["course_name"]
                }
                for c in active_courses
            ]

            batches_qs = NewBatch.objects.filter(is_archived=False, status=True)
            if course_id:
                batches_qs = batches_qs.filter(course_id=course_id)

            active_batches = list(
                batches_qs.values("batch_id", "title", "course_id").order_by("title")
            )
            batches_options = [
                {
                    "id": b["batch_id"],
                    "batch_id": b["batch_id"],
                    "name": b["title"],
                    "title": b["title"],
                    "course_id": b["course_id"]
                }
                for b in active_batches
            ]

            active_categories = list(
                CourseCategory.objects.filter(is_archived=False)
                .values("category_id", "category_name")
                .order_by("category_name")
            )
            categories_options = [
                {
                    "id": cat["category_id"],
                    "category_id": cat["category_id"],
                    "name": cat["category_name"],
                    "category_name": cat["category_name"]
                }
                for cat in active_categories
            ]

            companies_options = []

            filter_options = {
                "courses": courses_options,
                "batches": batches_options,
                "categories": categories_options,
                "companies": companies_options,
            }

            total_pages = math.ceil(total_count / limit) if total_count > 0 else 0

            return Response({
                "success": True,
                "students": data,
                "data": data,
                "batches": batches_options,
                "courses": courses_options,
                "categories": categories_options,
                # "companies": companies_options,
                "pagination": {
                    "total_count": total_count,
                    "page": page,
                    "limit": limit,
                    "total_pages": total_pages
                },
                # "filter_options": filter_options
            }, status=200)

        except Exception as e:
            logger.exception("Error in AttendanceReportView")
            return Response(
                {
                    "success": False,
                    "message": "An unexpected error occurred while fetching the attendance report."
                },
                status=500
            )


def _parse_incoming_date(date_val):
    """Helper to parse raw date string or return None if empty/falsy."""
    if not date_val or str(date_val).strip().lower() in ['', 'null', 'undefined', 'none']:
        return None
    parsed = parse_date(str(date_val).strip()) or parse_datetime(str(date_val).strip())
    if parsed:
        return parsed.date() if isinstance(parsed, datetime) else parsed
    return None


def _clean_string(val):
    """Helper to sanitize text and URLs."""
    if not val or str(val).strip().lower() in ['', 'null', 'undefined', 'none']:
        return None
    return str(val).strip()


class GoogleReviewReportView(APIView):
    """
    Report 3 - Google Review API.
    GET /api/v1/reports/google-reviews
    POST /api/v1/reports/google-reviews
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        try:
            # 1. Pagination Parameters
            try:
                page = int(request.GET.get("page", 1))
                if page < 1:
                    page = 1
            except (ValueError, TypeError):
                page = 1

            try:
                limit = int(request.GET.get("limit", 50))
                if limit < 1:
                    limit = 50
                elif limit > 500:
                    limit = 500
            except (ValueError, TypeError):
                limit = 50

            # 2. Filters
            search = request.GET.get("search", "").strip()
            course_id = request.GET.get("course_id", "").strip()
            batch_id = request.GET.get("batch_id", "").strip()
            from_date_str = request.GET.get("from_date", "").strip()
            to_date_str = request.GET.get("to_date", "").strip()
            is_google_review_param = request.GET.get("is_google_review", "all").strip().lower()

            if course_id and batch_id:
                valid_batch_exists = NewBatch.objects.filter(
                    batch_id=batch_id, course_id=course_id, is_archived=False
                ).exists() or StudentCourse.objects.filter(
                    batch_id=batch_id, course_id=course_id
                ).exists()
                if not valid_batch_exists:
                    batch_id = ""

            students_qs = Student.objects.filter(is_archived=False)

            if search:
                students_qs = students_qs.filter(
                    Q(first_name__icontains=search) |
                    Q(last_name__icontains=search) |
                    Q(email__icontains=search) |
                    Q(registration_id__icontains=search)
                )

            if course_id:
                students_qs = students_qs.filter(
                    Q(student_courses__course_id=course_id) |
                    Q(new_batches__course_id=course_id)
                )

            if batch_id:
                students_qs = students_qs.filter(
                    Q(student_courses__batch_id=batch_id) |
                    Q(new_batches__batch_id=batch_id)
                )

            if is_google_review_param in ["yes", "true", "1"]:
                students_qs = students_qs.filter(google_reviews__is_google_review=True)
            elif is_google_review_param in ["no", "false", "0"]:
                students_qs = students_qs.filter(
                    Q(google_reviews__isnull=True) | Q(google_reviews__is_google_review=False)
                )

            if from_date_str:
                parsed_from = parse_date_bound_from(from_date_str)
                if parsed_from:
                    students_qs = students_qs.filter(
                        Q(google_reviews__review_date__gte=parsed_from.date()) |
                        Q(created_at__gte=parsed_from)
                    )

            if to_date_str:
                parsed_to, lookup = parse_date_bound_to(to_date_str)
                if parsed_to:
                    if lookup == "lt":
                        students_qs = students_qs.filter(
                            Q(google_reviews__review_date__lt=parsed_to.date()) |
                            Q(created_at__lt=parsed_to)
                        )
                    else:
                        students_qs = students_qs.filter(
                            Q(google_reviews__review_date__lte=parsed_to.date()) |
                            Q(created_at__lte=parsed_to)
                        )

            students_qs = students_qs.distinct()
            total_count = students_qs.count()

            # 3. Pagination & Prefetching
            offset = (page - 1) * limit
            sliced_students = students_qs.order_by("-created_at", "-student_id").prefetch_related(
                Prefetch(
                    "google_reviews",
                    queryset=GoogleReview.objects.select_related("course", "batch")
                ),
                Prefetch(
                    "student_courses",
                    queryset=StudentCourse.objects.select_related("course", "batch")
                ),
                Prefetch(
                    "new_batches",
                    queryset=NewBatch.objects.select_related("course")
                )
            )[offset:offset + limit]

            data = []
            for s in sliced_students:
                review = s.google_reviews.first()

                if review:
                    serialized = GoogleReviewSerializer(review, context={"request": request}).data
                else:
                    courses_map = {}
                    batches_map = {}

                    for sc in s.student_courses.all():
                        if sc.course and sc.course.course_name:
                            courses_map[sc.course.course_id] = sc.course.course_name
                        if sc.batch:
                            b_title = sc.batch.title or getattr(sc.batch, "batch_name", None)
                            if b_title:
                                batches_map[sc.batch.batch_id] = b_title

                    for nb in s.new_batches.all():
                        if nb.course and nb.course.course_name:
                            courses_map[nb.course.course_id] = nb.course.course_name
                        if nb.title:
                            batches_map[nb.batch_id] = nb.title

                    course_ids = list(courses_map.keys())
                    course_names = list(courses_map.values())
                    batch_ids = list(batches_map.keys())
                    batch_names = list(batches_map.values())

                    serialized = {
                        "id": None,
                        "review_id": None,
                        "student": s.student_id,
                        "student_id": s.registration_id or f"std_{s.student_id}",
                        "raw_student_id": s.student_id,
                        "student_name": f"{s.first_name or ''} {s.last_name or ''}".strip(),
                        "email": s.email,
                        "course": course_ids[0] if course_ids else None,
                        "course_id": course_ids[0] if course_ids else None,
                        "course_name": course_names[0] if course_names else "-",
                        "batch": batch_ids[0] if batch_ids else None,
                        "batch_id": batch_ids[0] if batch_ids else None,
                        "batch_name": batch_names[0] if batch_names else "-",
                        "is_google_review": False,
                        "review_date": None,
                        "screenshot_url": None,
                        "linkedin_review": False,
                        "linkedin_screenshot_url": None,
                        "linkedin_review_date": None,
                        "facebook_review": False,
                        "facebook_screenshot_url": None,
                        "facebook_review_date": None,
                        "trustpilot_review": False,
                        "trustpilot_screenshot_url": None,
                        "trustpilot_review_date": None,
                        "is_youtube_testimonial": False,
                        "youtube_testimonial_link": None,
                        "youtube_testimonial_date": None,
                        "created_at": s.created_at.isoformat() if s.created_at else None,
                        "updated_at": None,
                    }

                data.append(serialized)

            # 4. Filter Options
            active_courses = list(
                Course.objects.filter(is_archived=False)
                .exclude(status__iexact="Inactive")
                .values("course_id", "course_name")
                .order_by("course_name")
            )
            courses_options = [
                {
                    "id": c["course_id"],
                    "course_id": c["course_id"],
                    "name": c["course_name"],
                    "course_name": c["course_name"]
                }
                for c in active_courses
            ]

            batches_qs = NewBatch.objects.filter(is_archived=False, status=True)
            if course_id:
                batches_qs = batches_qs.filter(course_id=course_id)

            active_batches = list(
                batches_qs.values("batch_id", "title", "course_id").order_by("title")
            )
            batches_options = [
                {
                    "id": b["batch_id"],
                    "batch_id": b["batch_id"],
                    "name": b["title"],
                    "title": b["title"],
                    "course_id": b["course_id"]
                }
                for b in active_batches
            ]

            filter_options = {
                "courses": courses_options,
                "batches": batches_options
            }

            total_pages = math.ceil(total_count / limit) if total_count > 0 else 0

            return Response({
                "success": True,
                "data": data,
                "pagination": {
                    "total_count": total_count,
                    "page": page,
                    "limit": limit,
                    "total_pages": total_pages
                },
                "filter_options": filter_options
            }, status=200)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {"success": False, "message": str(e)},
                status=500
            )

    def post(self, request):
        """
        POST /api/reports/google-reviews
        Create or Upsert Google Review & multi-platform review records.
        """
        try:
            data = request.data
            raw_student_id = data.get("raw_student_id") or data.get("student_pk")
            student_id_str = data.get("student_id")
            course_id = data.get("course_id")
            batch_id = data.get("batch_id")

            if not raw_student_id and not student_id_str:
                return Response(
                    {"success": False, "message": "Field 'student_id' or 'raw_student_id' is required.", "error_code": "VALIDATION_ERROR"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            student = None
            if raw_student_id:
                student = Student.objects.filter(student_id=raw_student_id, is_archived=False).first()
            if not student and student_id_str:
                student = Student.objects.filter(
                    Q(registration_id=student_id_str) | Q(student_id=student_id_str),
                    is_archived=False
                ).first()

            if not student:
                return Response(
                    {"success": False, "message": f"Student '{raw_student_id or student_id_str}' not found.", "error_code": "NOT_FOUND"},
                    status=status.HTTP_404_NOT_FOUND
                )

            course = None
            batch = None

            if course_id:
                course = Course.objects.filter(course_id=course_id, is_archived=False).first()
            if batch_id:
                batch = NewBatch.objects.filter(batch_id=batch_id, is_archived=False).first()

            if not course:
                sc = student.student_courses.select_related("course").filter(course__isnull=False).first()
                if sc and sc.course:
                    course = sc.course
                else:
                    nb = student.new_batches.select_related("course").filter(course__isnull=False, is_archived=False).first()
                    if nb and nb.course:
                        course = nb.course

            if not batch:
                sc = student.student_courses.select_related("batch").filter(batch__isnull=False).first()
                if sc and sc.batch:
                    batch = sc.batch
                else:
                    batch = student.new_batches.filter(is_archived=False).first()

            # Date extraction
            is_google_review = parse_bool(data.get("is_google_review")) or False
            review_date_val = data.get("review_date")
            parsed_review_date = None

            if is_google_review and not review_date_val:
                parsed_review_date = timezone.now().date()
            elif review_date_val:
                parsed_review_date = _parse_incoming_date(review_date_val)

            parsed_linkedin_date = _parse_incoming_date(data.get("linkedin_review_date"))
            parsed_facebook_date = _parse_incoming_date(data.get("facebook_review_date"))
            parsed_trustpilot_date = _parse_incoming_date(data.get("trustpilot_review_date"))
            parsed_youtube_date = _parse_incoming_date(data.get("youtube_testimonial_date"))

            with transaction.atomic():
                review = GoogleReview.objects.select_for_update().filter(student=student).first()
                created = False

                if not review:
                    review = GoogleReview.objects.create(
                        student=student,
                        course=course,
                        batch=batch
                    )
                    created = True
                else:
                    if course and not review.course:
                        review.course = course
                    if batch and not review.batch:
                        review.batch = batch

                # Review Status Flags
                if "is_google_review" in data:
                    review.is_google_review = is_google_review
                if "review_date" in data:
                    review.review_date = parsed_review_date

                if "linkedin_review" in data:
                    review.linkedin_review = parse_bool(data.get("linkedin_review")) or False
                if "facebook_review" in data:
                    review.facebook_review = parse_bool(data.get("facebook_review")) or False
                if "trustpilot_review" in data:
                    review.trustpilot_review = parse_bool(data.get("trustpilot_review")) or False
                if "is_youtube_testimonial" in data:
                    review.is_youtube_testimonial = parse_bool(data.get("is_youtube_testimonial")) or False

                # Dates
                if "linkedin_review_date" in data:
                    review.linkedin_review_date = parsed_linkedin_date
                if "facebook_review_date" in data:
                    review.facebook_review_date = parsed_facebook_date
                if "trustpilot_review_date" in data:
                    review.trustpilot_review_date = parsed_trustpilot_date
                if "youtube_testimonial_date" in data:
                    review.youtube_testimonial_date = parsed_youtube_date

                # YouTube link
                if "youtube_testimonial_link" in data:
                    review.youtube_testimonial_link = _clean_string(data.get("youtube_testimonial_link"))

                # File uploads
                platform_file_keys = {
                    "screenshot":            ["screenshot", "screenshot_url"],
                    "linkedin_screenshot":   ["linkedin_screenshot", "linkedin_screenshot_url"],
                    "facebook_screenshot":   ["facebook_screenshot", "facebook_screenshot_url"],
                    "trustpilot_screenshot": ["trustpilot_screenshot", "trustpilot_screenshot_url"],
                }
                for model_field, possible_keys in platform_file_keys.items():
                    for key in possible_keys:
                        if key in request.FILES:
                            setattr(review, model_field, request.FILES[key])
                            break

                review.save()

            serializer = GoogleReviewSerializer(review, context={"request": request})
            resp_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            return Response({
                "success": True,
                "message": "Review created successfully." if created else "Review updated successfully.",
                "data": serializer.data
            }, status=resp_status)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class GoogleReviewDetailView(APIView):
    """
    PATCH / PUT /api/v1/reports/google-reviews/<id>
    DELETE /api/v1/reports/google-reviews/<id>
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def patch(self, request, pk=None):
        return self.update_review(request, pk)

    def put(self, request, pk=None):
        return self.update_review(request, pk)

    def update_review(self, request, pk=None):
        try:
            review = None
            student = None

            if str(pk).isdigit():
                review = GoogleReview.objects.filter(id=int(pk)).first()

            if not review:
                student = Student.objects.filter(
                    Q(student_id=pk) | Q(registration_id=pk)
                ).first()
                if student:
                    review = GoogleReview.objects.filter(student=student).first()

            if not review and not student:
                return Response(
                    {"success": False, "message": f"Review or Student with identifier '{pk}' not found.", "error_code": "NOT_FOUND"},
                    status=status.HTTP_404_NOT_FOUND
                )

            if not review and student:
                sc = StudentCourse.objects.filter(student=student).first()
                nb = NewBatch.objects.filter(student_courses__student=student).first()
                review = GoogleReview.objects.create(
                    student=student,
                    course=sc.course if sc else None,
                    batch=sc.batch if (sc and sc.batch) else nb
                )

            data = request.data
            files = request.FILES

            # Booleans
            is_google_review = parse_bool(data.get("is_google_review"))
            is_linkedin_review = parse_bool(data.get("linkedin_review"))
            is_facebook_review = parse_bool(data.get("facebook_review"))
            is_trustpilot_review = parse_bool(data.get("trustpilot_review"))
            is_youtube_testimonial = parse_bool(data.get("is_youtube_testimonial"))

            if is_google_review is not None:
                review.is_google_review = is_google_review
            if is_linkedin_review is not None:
                review.linkedin_review = is_linkedin_review
            if is_facebook_review is not None:
                review.facebook_review = is_facebook_review
            if is_trustpilot_review is not None:
                review.trustpilot_review = is_trustpilot_review
            if is_youtube_testimonial is not None:
                review.is_youtube_testimonial = is_youtube_testimonial

            # Dates
            if "review_date" in data:
                review.review_date = _parse_incoming_date(data.get("review_date"))
            if "linkedin_review_date" in data:
                review.linkedin_review_date = _parse_incoming_date(data.get("linkedin_review_date"))
            if "facebook_review_date" in data:
                review.facebook_review_date = _parse_incoming_date(data.get("facebook_review_date"))
            if "trustpilot_review_date" in data:
                review.trustpilot_review_date = _parse_incoming_date(data.get("trustpilot_review_date"))
            if "youtube_testimonial_date" in data:
                review.youtube_testimonial_date = _parse_incoming_date(data.get("youtube_testimonial_date"))

            # YouTube link
            if "youtube_testimonial_link" in data:
                review.youtube_testimonial_link = _clean_string(data.get("youtube_testimonial_link"))

            if review.is_google_review and not review.review_date:
                return Response(
                    {"success": False, "message": "Field 'review_date' is required when is_google_review is true.", "error_code": "UNPROCESSABLE_ENTITY"},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY
                )

            # Files
            platform_file_keys = {
                "screenshot":            ["screenshot", "screenshot_url"],
                "linkedin_screenshot":   ["linkedin_screenshot", "linkedin_screenshot_url"],
                "facebook_screenshot":   ["facebook_screenshot", "facebook_screenshot_url"],
                "trustpilot_screenshot": ["trustpilot_screenshot", "trustpilot_screenshot_url"],
            }

            for model_field, possible_keys in platform_file_keys.items():
                file_obj = None
                for key in possible_keys:
                    if key in files:
                        file_obj = files[key]
                        break
                if file_obj:
                    setattr(review, model_field, file_obj)

            if not files.get("screenshot") and not files.get("screenshot_url"):
                raw_screenshot_input = data.get("screenshot_url") or data.get("screenshot")
                if isinstance(raw_screenshot_input, str):
                    cleaned_url = clean_and_extract_url(raw_screenshot_input)
                    if cleaned_url:
                        url_validator = URLValidator()
                        try:
                            url_validator(cleaned_url)
                        except ValidationError:
                            return Response(
                                {"success": False, "message": "Field 'screenshot_url' must be a valid URI format.", "error_code": "VALIDATION_ERROR"},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        review.screenshot_url = extract_filename_or_relative_path(raw_screenshot_input) or cleaned_url

            review.save()

            serializer = GoogleReviewSerializer(review, context={"request": request})

            return Response({
                "success": True,
                "message": "Google review updated successfully.",
                "data": serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def delete(self, request, pk=None):
        try:
            review = None
            if str(pk).isdigit():
                review = GoogleReview.objects.filter(id=int(pk)).first()
            
            if not review:
                student = Student.objects.filter(
                    Q(student_id=pk) | Q(registration_id=pk)
                ).first()
                if student:
                    review = GoogleReview.objects.filter(student=student).first()

            if not review:
                return Response(
                    {"success": False, "message": f"Google review record with identifier '{pk}' not found.", "error_code": "NOT_FOUND"},
                    status=status.HTTP_404_NOT_FOUND
                )

            review_id = review.id
            student_id = review.student.registration_id or f"std_{review.student.student_id}"

            review.delete()

            return Response({
                "success": True,
                "message": f"Google review record #{review_id} for student {student_id} reset/deleted successfully.",
                "data": {
                    "id": review_id,
                    "student_id": student_id,
                    "is_google_review": False,
                    "review_date": None,
                    "screenshot_url": None
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            

class StudentPaymentHistoryReportPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'limit'
    max_page_size = 500

    def get_paginated_response(self, data):
        return Response({
            "success": True,
            "meta": {
                "total_records": self.page.paginator.count,
                "total_pages": self.page.paginator.num_pages,
                "current_page": self.page.number,
                "page_size": self.get_page_size(self.request)
            },
            "results": data
        })


class ReportFilterOptionsView(APIView):
    """
    Metadata endpoint to support UI filters for payment reports.
    Returns active courses and (cascaded) active batches.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get(self, request):
        try:
            user = request.user
            user_type = getattr(user, "user_type", "")
            if user_type not in ["super_admin", "admin"]:
                return Response(
                    {"success": False, "message": "Unauthorized"},
                    status=status.HTTP_403_FORBIDDEN
                )

            course_id = request.query_params.get("course_id")

            courses_qs = Course.objects.filter(is_archived=False).order_by("course_name")
            courses = [
                {
                    "course_id": c.course_id,
                    "course_name": c.course_name or ""
                }
                for c in courses_qs
            ]

            batches_qs = NewBatch.objects.filter(is_archived=False)
            if course_id:
                batches_qs = batches_qs.filter(course_id=course_id)

            batches = [
                {
                    "batch_id": b.batch_id,
                    "title": b.title or f"Batch {b.batch_id}",
                    "batch_title": b.title or f"Batch {b.batch_id}",
                    "course_id": b.course_id
                }
                for b in batches_qs.order_by("title")
            ]

            return Response({
                "success": True,
                "data": {
                    "courses": courses,
                    "batches": batches
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error in ReportFilterOptionsView")
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class StudentPaymentHistoryReportView(APIView):
    """
    GET report endpoint to serve detailed student payment summaries
    with server-side pagination and nested payment histories.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    pagination_class = StudentPaymentHistoryReportPagination

    def get(self, request):
        try:
            user = request.user
            user_type = getattr(user, "user_type", "")
            if user_type not in ["super_admin", "admin"]:
                return Response(
                    {"success": False, "message": "Unauthorized"},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Filter non-archived students
            all_students = Student.objects.filter(is_archived=False)

            # Include only students associated with courses/batches/transactions
            students_qs = all_students.filter(
                Q(student_courses__isnull=False) |
                Q(new_batches__course__isnull=False, new_batches__is_archived=False) |
                Q(batchcoursetrainer__course__isnull=False) |
                Q(transactions__course__isnull=False, transactions__is_archived=False)
            )

            # Extract query parameters for dynamic cascaded and date filtering
            course_id = request.query_params.get("course_id")
            batch_id = request.query_params.get("batch_id")
            from_date = request.query_params.get("from_date")
            to_date = request.query_params.get("to_date")
            search = request.query_params.get("search")

            # ---------------------------------------------------------
            # Metadata for Filters: Courses & Batches Separately
            # ---------------------------------------------------------
            all_courses = list(
                Course.objects.filter(is_archived=False)
                .values("course_id", "course_name")
                .order_by("course_name")
            )

            batches_qs = NewBatch.objects.filter(is_archived=False)
            if course_id:
                batches_qs = batches_qs.filter(course_id=course_id)

            all_batches = list(
                batches_qs.values(
                    "batch_id",
                    "title",
                    "course_id"
                ).order_by("title")
            )

            # Filter non-archived students
            all_students = Student.objects.filter(is_archived=False)

            # Include only students associated with courses/batches/transactions
            students_qs = all_students.filter(
                Q(student_courses__isnull=False) |
                Q(new_batches__course__isnull=False, new_batches__is_archived=False) |
                Q(batchcoursetrainer__course__isnull=False) |
                Q(transactions__course__isnull=False, transactions__is_archived=False)
            )

            # 1. Course Filter
            if course_id:
                students_qs = students_qs.filter(
                    Q(student_courses__course_id=course_id) |
                    Q(new_batches__course_id=course_id, new_batches__is_archived=False) |
                    Q(batchcoursetrainer__course_id=course_id) |
                    Q(transactions__course_id=course_id, transactions__is_archived=False)
                )

            # 2. Batch Filter
            if batch_id:
                students_qs = students_qs.filter(
                    Q(new_batches__batch_id=batch_id, new_batches__is_archived=False) |
                    Q(student_courses__batch_id=batch_id)
                )

            # 3. Date Range Filter (Applied on transaction created_at date)
            if from_date:
                students_qs = students_qs.filter(transactions__created_at__date__gte=from_date)
            if to_date:
                students_qs = students_qs.filter(transactions__created_at__date__lte=to_date)

            # 4. Search Filter
            if search:
                search_term = str(search).strip()
                if search_term:
                    students_qs = students_qs.filter(
                        Q(first_name__icontains=search_term) |
                        Q(last_name__icontains=search_term) |
                        Q(registration_id__icontains=search_term) |
                        Q(email__icontains=search_term) |
                        Q(contact_no__icontains=search_term)
                    )

            students_qs = students_qs.distinct()

            # Prefetch non-archived transactions ordered by -created_at with select_related('course', 'gateway')
            tx_filter = Q(is_archived=False)
            if from_date:
                tx_filter &= Q(created_at__date__gte=from_date)
            if to_date:
                tx_filter &= Q(created_at__date__lte=to_date)
            if course_id:
                tx_filter &= Q(course_id=course_id)

            transactions_prefetch = Prefetch(
                "transactions",
                queryset=PaymentTransaction.objects.filter(tx_filter).select_related("course", "gateway").order_by("-created_at")
            )

            # Prefetch related courses/batches and annotate/order by last payment
            students_qs = students_qs.prefetch_related(
                "new_batches__course",
                "student_courses__course",
                "batchcoursetrainer_set__course",
                transactions_prefetch
            ).annotate(
                last_payment=Max("transactions__created_at")
            ).order_by("-last_payment", "-student_id")

            paginator = self.pagination_class()
            page = paginator.paginate_queryset(students_qs, request, view=self)
            target_qs = page if page is not None else students_qs

            valid_statuses = {"success", "done", "paid", "complete", "captured", "partial", "advanced"}

            results = []
            for student in target_qs:
                # 1. Deduplicate & Collect Courses
                courses_dict = {}
                for sc in student.student_courses.all():
                    if sc.course and not getattr(sc.course, "is_archived", False):
                        courses_dict[sc.course.course_id] = sc.course
                for nb in student.new_batches.all():
                    if nb.course and not getattr(nb.course, "is_archived", False):
                        courses_dict[nb.course.course_id] = nb.course
                bct_manager = getattr(student, "batchcoursetrainer", None) or getattr(student, "batchcoursetrainer_set", None)
                if bct_manager is not None:
                    for bct in bct_manager.all():
                        if bct.course and not getattr(bct.course, "is_archived", False):
                            courses_dict[bct.course.course_id] = bct.course
                for tx in student.transactions.all():
                    if tx.course and not getattr(tx.course, "is_archived", False):
                        courses_dict[tx.course.course_id] = tx.course

                courses_list = [
                    {
                        "course_id": course.course_id,
                        "course_name": course.course_name or "",
                        "course_fee": float(course.fee or 0)
                    }
                    for course in courses_dict.values()
                ]

                # 2. Deduplicate & Collect Batches
                batches_dict = {}
                for nb in student.new_batches.all():
                    if not getattr(nb, "is_archived", False):
                        batches_dict[nb.batch_id] = nb
                for sc in student.student_courses.all():
                    if sc.batch and not getattr(sc.batch, "is_archived", False):
                        batches_dict[sc.batch.batch_id] = sc.batch

                batches_list = []
                for batch in batches_dict.values():
                    duration_str = None
                    if getattr(batch, "course", None) and getattr(batch.course, "duration", None):
                        dur_type = f" {batch.course.duration_type}" if getattr(batch.course, "duration_type", None) else ""
                        duration_str = f"{batch.course.duration}{dur_type}"
                    elif getattr(batch, "start_date", None) and getattr(batch, "end_date", None):
                        duration_str = f"{batch.start_date} to {batch.end_date}"

                    batches_list.append({
                        "batch_id": batch.batch_id,
                        "batch_title": getattr(batch, "title", None) or getattr(batch, "batch_name", None) or f"Batch {batch.batch_id}",
                        "duration": duration_str or "N/A"
                    })

                # 3. Financial Totals & Aggregations
                total_course_fee = sum(float(c.fee or 0) for c in courses_dict.values())
                discount = float(getattr(student, "discount", 0) or 0)
                total_after_discount = max(total_course_fee - discount, 0.0)

                all_txs = list(student.transactions.all())

                total_paid_amount = sum(
                    float(tx.amount or 0)
                    for tx in all_txs
                    if tx.payment_status and str(tx.payment_status).lower() in valid_statuses
                )

                total_pending_amount = max(total_after_discount - total_paid_amount, 0.0)

                if total_pending_amount <= 0 and total_paid_amount > 0:
                    status_str = "Completed"
                elif total_paid_amount > 0 and total_pending_amount > 0:
                    status_str = "Partial"
                else:
                    status_str = "Pending"

                # 4. Payment History Log per Student
                payment_history = []
                for tx in all_txs:
                    if not tx.invoice and str(tx.payment_status).lower() in ["success", "done", "paid", "complete", "captured"]:
                        try:
                            tx = InvoiceService.generate_invoice(tx.id)
                        except Exception as e:
                            logger.error(f"[Payment Report] Lazy invoice generation failed for transaction {tx.id}: {str(e)}")

                    invoice_url = None
                    if tx.invoice:
                        rel_path = tx.invoice.url if hasattr(tx.invoice, "url") else str(tx.invoice)
                        if rel_path:
                            if rel_path.startswith("http://") or rel_path.startswith("https://"):
                                invoice_url = rel_path
                            else:
                                try:
                                    invoice_url = request.build_absolute_uri(rel_path)
                                except Exception:
                                    base = getattr(settings, "MEDIA_BASE_URL", "http://localhost:8000")
                                    prefix = "" if rel_path.startswith("/") else "/"
                                    invoice_url = f"{base.rstrip('/')}{prefix}{rel_path}"

                    payment_history.append({
                        "transaction_id": tx.transaction_id or f"TXN{tx.id}",
                        "course_name": tx.course.course_name if tx.course else (tx.description or "General Payment"),
                        "amount": float(tx.amount or 0),
                        "payment_status": tx.payment_status,
                        "payment_mode": tx.payment_mode or (tx.metadata.get("mode") if tx.metadata else "Cash"),
                        "currency": tx.currency or "INR",
                        "gateway": tx.gateway.gatway_name if tx.gateway else None,
                        "invoice_no": tx.invoice_no,
                        "invoice_date": str(tx.invoice_date) if tx.invoice_date else None,
                        "invoice_url": invoice_url,
                        "created_at": tx.created_at.isoformat() if tx.created_at else None
                    })

                full_name = f"{student.first_name or ''} {student.last_name or ''}".strip()

                results.append({
                    "student_id": student.student_id,
                    "registration_id": student.registration_id or "",
                    "student_name": full_name,
                    "email": student.email or "",
                    "phone": student.contact_no or "",
                    "contact_no": student.contact_no or "",
                    "courses": courses_list,
                    "batches": batches_list,
                    "total_course_fee": total_course_fee,
                    "discount": discount,
                    "total_after_discount": total_after_discount,
                    "total_paid_amount": total_paid_amount,
                    "total_pending_amount": total_pending_amount,
                    "status": status_str,
                    "payment_history": payment_history
                })

            response_payload = {
                "success": True,
                "courses": all_courses,
                "batches": all_batches,
                "results": results
            }

            if page is not None:
                response_payload["meta"] = {
                    "total_records": paginator.page.paginator.count,
                    "total_pages": paginator.page.paginator.num_pages,
                    "current_page": paginator.page.number,
                    "page_size": paginator.get_page_size(request)
                }
                return Response(response_payload, status=status.HTTP_200_OK)

            response_payload["meta"] = {
                "total_records": len(results),
                "total_pages": 1,
                "current_page": 1,
                "page_size": len(results)
            }
            return Response(response_payload, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error in StudentPaymentHistoryReportView")
            return Response(
                {
                    "success": False,
                    "message": "An unexpected error occurred while generating student payment history report."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class TutorPaymentReportView(APIView):
    """
    Secure, production-grade report API endpoint for Tutor Payments.
    Enforces BOLA role verification, strict input sanitization/validation against SQLi,
    and database optimization using select_related and pagination.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    pagination_class = TutorPaymentReportPagination

    def get(self, request):
        try:
            # 1. BOLA & Access Control: Restricted to super_admin and admin
            user = request.user
            user_type = getattr(user, "user_type", "")
            if user_type not in ["super_admin", "admin"]:
                return Response(
                    {"success": False, "message": "Unauthorized access."},
                    status=status.HTTP_403_FORBIDDEN
                )

            # 2. Input Validation & Sanitization (OWASP)
            raw_course_id = request.query_params.get("course_id")
            raw_batch_id = request.query_params.get("batch_id")
            raw_tutor_id = request.query_params.get("tutor_id")
            raw_status = request.query_params.get("payment_status")
            raw_from_date = request.query_params.get("from_date")
            raw_to_date = request.query_params.get("to_date")
            search_term = request.query_params.get("search")

            course_id = None
            if raw_course_id is not None and str(raw_course_id).strip():
                try:
                    course_id = int(str(raw_course_id).strip())
                    if course_id <= 0:
                        raise ValueError
                except ValueError:
                    return Response(
                        {"success": False, "message": "Invalid course_id format. Must be a positive integer."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            batch_id = None
            if raw_batch_id is not None and str(raw_batch_id).strip():
                try:
                    batch_id = int(str(raw_batch_id).strip())
                    if batch_id <= 0:
                        raise ValueError
                except ValueError:
                    return Response(
                        {"success": False, "message": "Invalid batch_id format. Must be a positive integer."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            tutor_id = None
            if raw_tutor_id is not None and str(raw_tutor_id).strip():
                try:
                    tutor_id = int(str(raw_tutor_id).strip())
                    if tutor_id <= 0:
                        raise ValueError
                except ValueError:
                    return Response(
                        {"success": False, "message": "Invalid tutor_id format. Must be a positive integer."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            from_date = None
            if raw_from_date is not None and str(raw_from_date).strip():
                try:
                    from_date = datetime.strptime(str(raw_from_date).strip(), "%Y-%m-%d").date()
                except ValueError:
                    return Response(
                        {"success": False, "message": "Invalid from_date format. Must be YYYY-MM-DD."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            to_date = None
            if raw_to_date is not None and str(raw_to_date).strip():
                try:
                    to_date = datetime.strptime(str(raw_to_date).strip(), "%Y-%m-%d").date()
                except ValueError:
                    return Response(
                        {"success": False, "message": "Invalid to_date format. Must be YYYY-MM-DD."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            payment_status = None
            if raw_status is not None and str(raw_status).strip():
                payment_status = str(raw_status).strip().lower()

            # 3. Metadata Dropdowns (Optimized via .values())
            all_courses = list(
                Course.objects.filter(is_archived=False)
                .values("course_id", "course_name")
                .order_by("course_name")
            )

            batches_qs = NewBatch.objects.filter(is_archived=False)
            if course_id:
                batches_qs = batches_qs.filter(course_id=course_id)

            all_batches = list(
                batches_qs.values(
                    "batch_id",
                    "title",
                    "course_id"
                ).order_by("title")
            )

            all_tutors = list(
                Trainer.objects.all()
                .values("trainer_id", "full_name")
                .order_by("full_name")
            )

            # 4. Database Queryset Optimization (Avoid N+1 with select_related)
            payments_qs = TutorPayment.objects.select_related("tutor", "course", "batch")

            if course_id:
                payments_qs = payments_qs.filter(course_id=course_id)

            if batch_id:
                payments_qs = payments_qs.filter(batch_id=batch_id)

            if tutor_id:
                payments_qs = payments_qs.filter(tutor_id=tutor_id)

            if payment_status:
                payments_qs = payments_qs.filter(payment_status__iexact=payment_status)

            if from_date:
                payments_qs = payments_qs.filter(payment_date__gte=from_date)

            if to_date:
                payments_qs = payments_qs.filter(payment_date__lte=to_date)

            if search_term and str(search_term).strip():
                term = str(search_term).strip()
                payments_qs = payments_qs.filter(
                    Q(tutor__full_name__icontains=term) |
                    Q(tutor__username__icontains=term) |
                    Q(course__course_name__icontains=term) |
                    Q(batch__title__icontains=term)
                )

            # Indexed field sorting
            payments_qs = payments_qs.order_by("-payment_date", "-id")

            # 5. Pagination & Explicit Whitelisted Serialization
            paginator = self.pagination_class()
            page = paginator.paginate_queryset(payments_qs, request, view=self)
            target_qs = page if page is not None else payments_qs

            results = []
            for p in target_qs:
                tutor_name = p.tutor.full_name if p.tutor and p.tutor.full_name else (
                    getattr(p.tutor, "username", "") if p.tutor else "N/A"
                )
                course_name = p.course.course_name if p.course and p.course.course_name else "N/A"
                batch_title = (
                    p.batch.title if p.batch and getattr(p.batch, "title", None)
                    else (getattr(p.batch, "batch_name", None) or f"Batch {p.batch_id}" if p.batch else "N/A")
                )

                results.append({
                    "id": p.id,
                    "tutor_id": p.tutor_id,
                    "tutor_name": tutor_name,
                    "course_id": p.course_id,
                    "course_name": course_name,
                    "batch_id": p.batch_id,
                    "batch_title": batch_title,
                    "payment_type": p.payment_type or "N/A",
                    "payment_date": str(p.payment_date) if p.payment_date else None,
                    "amount": float(p.tutor_payment or 0),
                    "course_fee": float(p.course_fee or 0),
                    "payment_status": p.payment_status or "pending",
                    "notes": p.notes or ""
                })

            response_payload = {
                "success": True,
                "courses": all_courses,
                "batches": all_batches,
                # "tutors": all_tutors,
                "results": results
            }

            if page is not None:
                response_payload["meta"] = {
                    "total_records": paginator.page.paginator.count,
                    "total_pages": paginator.page.paginator.num_pages,
                    "current_page": paginator.page.number,
                    "page_size": paginator.get_page_size(request)
                }
                return Response(response_payload, status=status.HTTP_200_OK)

            response_payload["meta"] = {
                "total_records": len(results),
                "total_pages": 1,
                "current_page": 1,
                "page_size": len(results)
            }
            return Response(response_payload, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error in TutorPaymentReportView")
            return Response(
                {"success": False, "message": "An error occurred generating tutor payment report."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )




            
import os
import math
import re
from datetime import datetime, date, time, timedelta
from collections import defaultdict
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.db.models import Q, Sum, Prefetch, Count
from django.conf import settings
from django.db import transaction, models
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from aryuapp.auth import CustomJWTAuthentication
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
import logging
from aryuapp.models import Student, StudentCourse, Attendance
from batches.models import NewBatch, ClassSchedule
from payments.models import PaymentTransaction
from courses.models import Course, CourseCategory
from reports.models import GoogleReview

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
                is_archived=False
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
                "data": data,
                "courses": courses,
            })

        except Exception as e:
            import traceback
            traceback.print_exc()

            return Response(
                {
                    "success": False,
                    "message": str(e)
                },
                status=500
            )


class StudentEnrollmentReportView(APIView):
    """
    Performant API Endpoint for Student Enrollment Report Table.
    Supports pagination (page, limit), case-insensitive search on student name,
    course_id filter, batch_id filter, date filtering (from_date, to_date),
    sorting (sort_by, sort_order), batch hyphen fallback, and returns student_id.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get(self, request):
        try:
            # 1. Parse Pagination Parameters
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

            # 2. Parse Search & Filter Parameters
            search = request.GET.get("search", "").strip()
            course_id = request.GET.get("course_id", "").strip()
            batch_id = request.GET.get("batch_id", "").strip()
            from_date_str = request.GET.get("from_date", "").strip()
            to_date_str = request.GET.get("to_date", "").strip()
            sort_by = request.GET.get("sort_by", "created_at").strip().lower()
            sort_order = request.GET.get("sort_order", "desc").strip().lower()

            # Reset Rule for batch_id: If batch_id does not belong to course_id, discard batch_id
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

            # Base queryset: Active/non-archived students
            students_qs = Student.objects.filter(is_archived=False)

            # Case-insensitive search on student name (and registration_id/email)
            if search:
                students_qs = students_qs.filter(
                    Q(first_name__icontains=search) |
                    Q(last_name__icontains=search) |
                    Q(email__icontains=search) |
                    Q(registration_id__icontains=search) |
                    Q(student_courses__course__course_name__icontains=search) |
                    Q(student_courses__batch__title__icontains=search) |
                    Q(new_batches__course__course_name__icontains=search) |
                    Q(new_batches__title__icontains=search)
                )

            # Filter by course_id
            if course_id:
                students_qs = students_qs.filter(
                    Q(student_courses__course_id=course_id) |
                    Q(new_batches__course_id=course_id)
                )

            # Filter by batch_id
            if batch_id:
                students_qs = students_qs.filter(
                    Q(student_courses__batch_id=batch_id) |
                    Q(new_batches__batch_id=batch_id)
                )

            # Date Range Filter on student enrollment / created_at date
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

            # 3. Sorting Field Mapping
            sort_map = {
                "created_at": "created_at",
                "enrolled_at": "created_at",
                "student_name": "first_name",
                "name": "first_name",
                "first_name": "first_name",
                "last_name": "last_name",
                "registration_id": "registration_id",
                "student_id": "registration_id",
            }
            db_sort_field = sort_map.get(sort_by, "created_at")

            if sort_order == "asc":
                order_expr = db_sort_field
            else:
                order_expr = f"-{db_sort_field}"

            # Distinct before counting and slicing
            students_qs = students_qs.distinct()
            total_count = students_qs.count()

            # 4. Database-level Pagination Slicing with Prefetching
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

            # 5. Build Response Data List
            data = []
            for s in sliced_students:
                full_name = f"{s.first_name or ''} {s.last_name or ''}".strip()

                courses_map = {}  # course_id -> course_name
                batches_map = {}  # batch_id -> batch_title

                # A. Collect from StudentCourse
                for sc in s.student_courses.all():
                    if sc.course and sc.course.course_name:
                        if not course_id or str(sc.course.course_id) == str(course_id):
                            courses_map[sc.course.course_id] = sc.course.course_name
                    if sc.batch:
                        if not batch_id or str(sc.batch.batch_id) == str(batch_id):
                            batch_title = sc.batch.title or getattr(sc.batch, "batch_name", None)
                            if batch_title:
                                batches_map[sc.batch.batch_id] = batch_title

                # B. Collect from NewBatch
                for nb in s.new_batches.all():
                    if nb.course and nb.course.course_name:
                        if not course_id or str(nb.course.course_id) == str(course_id):
                            courses_map[nb.course.course_id] = nb.course.course_name
                    if nb.title:
                        if not batch_id or str(nb.batch_id) == str(batch_id):
                            batches_map[nb.batch_id] = nb.title

                # Fallback to all assigned if empty maps
                if not courses_map and not course_id:
                    for sc in s.student_courses.all():
                        if sc.course:
                            courses_map[sc.course.course_id] = sc.course.course_name
                    for nb in s.new_batches.all():
                        if nb.course:
                            courses_map[nb.course.course_id] = nb.course.course_name

                if not batches_map and not batch_id:
                    for sc in s.student_courses.all():
                        if sc.batch:
                            b_name = sc.batch.title or getattr(sc.batch, "batch_name", None)
                            if b_name:
                                batches_map[sc.batch.batch_id] = b_name
                    for nb in s.new_batches.all():
                        if nb.title:
                            batches_map[nb.batch_id] = nb.title

                course_names = list(courses_map.values())
                course_ids = list(courses_map.keys())
                batch_names = list(batches_map.values())
                batch_ids = list(batches_map.keys())

                course_val = ", ".join(course_names) if course_names else "-"
                course_id_val = course_ids[0] if course_ids else None
                batch_val = ", ".join(batch_names) if batch_names else "-"
                batch_id_val = batch_ids[0] if batch_ids else None

                created_at_iso = s.created_at.isoformat() if s.created_at else None

                data.append({
                    "id": str(s.student_id),
                    "student_id": s.registration_id or f"std_{s.student_id}",
                    "student_name": full_name,
                    "course": course_val,
                    "course_id": course_id_val,
                    "batch": batch_val,
                    "batch_id": batch_id_val,
                    "created_at": created_at_iso,
                    "enrolled_at": created_at_iso,
                })

            # 6. Fetch Active Filter Options for Dropdowns
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
                {
                    "success": False,
                    "message": str(e)
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


class GoogleReviewReportView(APIView):
    """
    Report 3 - Google Review API.
    GET /api/v1/reports/google-reviews (or /api/reports/google-reviews)
    POST /api/v1/reports/google-reviews (Create or Upsert Google Review)
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        try:
            # 1. Parse Pagination Parameters
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

            # 2. Parse Filters
            search = request.GET.get("search", "").strip()
            course_id = request.GET.get("course_id", "").strip()
            batch_id = request.GET.get("batch_id", "").strip()
            from_date_str = request.GET.get("from_date", "").strip()
            to_date_str = request.GET.get("to_date", "").strip()
            is_google_review_param = request.GET.get("is_google_review", "all").strip().lower()
            sort_by = request.GET.get("sort_by", "review_date").strip().lower()
            sort_order = request.GET.get("sort_order", "desc").strip().lower()

            # Reset Rule for batch_id if mismatched with course_id
            if course_id and batch_id:
                valid_batch_exists = NewBatch.objects.filter(
                    batch_id=batch_id, course_id=course_id, is_archived=False
                ).exists() or StudentCourse.objects.filter(
                    batch_id=batch_id, course_id=course_id
                ).exists()
                if not valid_batch_exists:
                    batch_id = ""

            # Base Queryset: Active students
            students_qs = Student.objects.filter(is_archived=False)

            # Search filter (name, email, registration_id)
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

            # Google Review status filter
            if is_google_review_param in ["yes", "true", "1"]:
                students_qs = students_qs.filter(google_reviews__is_google_review=True)
            elif is_google_review_param in ["no", "false", "0"]:
                students_qs = students_qs.filter(
                    Q(google_reviews__isnull=True) | Q(google_reviews__is_google_review=False)
                )

            # Date Range Filter against review_date or created_at
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
                full_name = f"{s.first_name or ''} {s.last_name or ''}".strip()
                review = s.google_reviews.first()

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

                course_names = list(courses_map.values())
                course_ids = list(courses_map.keys())
                batch_names = list(batches_map.values())
                batch_ids = list(batches_map.keys())

                course_val = course_names[0] if course_names else "-"
                course_id_val = course_ids[0] if course_ids else None
                batch_val = batch_names[0] if batch_names else "-"
                batch_id_val = batch_ids[0] if batch_ids else None

                review_id = review.id if review else None
                is_rev = review.is_google_review if review else False
                rev_date = review.review_date.strftime("%Y-%m-%d") if (review and review.review_date) else None
                screenshot_url = resolve_screenshot_url(review, request)

                data.append({
                    "id": review_id or str(s.student_id),
                    "review_id": review_id,
                    "student_id": s.registration_id or f"std_{s.student_id}",
                    "raw_student_id": s.student_id,
                    "student_name": full_name,
                    "email": s.email,
                    "is_google_review": is_rev,
                    "review_date": rev_date,
                    "screenshot_url": screenshot_url,
                    "course_name": course_val,
                    "course_id": course_id_val,
                    "batch_name": batch_val,
                    "batch_id": batch_id_val,
                    "created_at": s.created_at.isoformat() if s.created_at else None
                })

            # 4. Fetch Active Filter Options for Dropdowns
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
        POST /api/v1/reports/google-reviews
        Create or Upsert Google review record for (raw_student_id, course_id, batch_id).
        """
        try:
            data = request.data
            raw_student_id = data.get("raw_student_id") or data.get("student_pk")
            student_id_str = data.get("student_id")
            course_id = data.get("course_id")
            batch_id = data.get("batch_id")
            is_google_review_val = data.get("is_google_review")
            review_date_val = data.get("review_date")
            screenshot_file = request.FILES.get("screenshot")
            raw_screenshot_input = data.get("screenshot_url") or data.get("screenshot")
            cleaned_url = clean_and_extract_url(raw_screenshot_input) if isinstance(raw_screenshot_input, str) else None
            stored_file_name = extract_filename_or_relative_path(raw_screenshot_input) if isinstance(raw_screenshot_input, str) else None

            # Validation: raw_student_id or student_id, course_id, and batch_id are required
            if not raw_student_id and not student_id_str:
                return Response(
                    {"success": False, "message": "Field 'raw_student_id' or 'student_id' is required.", "error_code": "VALIDATION_ERROR"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if not course_id:
                return Response(
                    {"success": False, "message": "Field 'course_id' is required.", "error_code": "VALIDATION_ERROR"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if not batch_id:
                return Response(
                    {"success": False, "message": "Field 'batch_id' is required.", "error_code": "VALIDATION_ERROR"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Lookup Student
            student = None
            if raw_student_id:
                student = Student.objects.filter(student_id=raw_student_id).first()
            if not student and student_id_str:
                student = Student.objects.filter(
                    Q(registration_id=student_id_str) | Q(student_id=student_id_str)
                ).first()

            if not student:
                return Response(
                    {"success": False, "message": f"Student with identifier '{raw_student_id or student_id_str}' not found.", "error_code": "NOT_FOUND"},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Lookup Course & Batch
            course = Course.objects.filter(course_id=course_id).first()
            batch = NewBatch.objects.filter(batch_id=batch_id).first()

            if not course:
                return Response(
                    {"success": False, "message": f"Course with id '{course_id}' not found.", "error_code": "NOT_FOUND"},
                    status=status.HTTP_404_NOT_FOUND
                )
            if not batch:
                return Response(
                    {"success": False, "message": f"Batch with id '{batch_id}' not found.", "error_code": "NOT_FOUND"},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Parse boolean is_google_review
            is_google_review = False
            if is_google_review_val is not None:
                if isinstance(is_google_review_val, bool):
                    is_google_review = is_google_review_val
                elif str(is_google_review_val).lower() in ["true", "yes", "1"]:
                    is_google_review = True

            # Rule: If is_google_review is true, review_date is strictly mandatory
            if is_google_review and not review_date_val:
                return Response(
                    {"success": False, "message": "Field 'review_date' is strictly required when is_google_review is true.", "error_code": "UNPROCESSABLE_ENTITY"},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY
                )

            parsed_review_date = None
            if review_date_val:
                parsed_d = parse_date(str(review_date_val)) or parse_datetime(str(review_date_val))
                if parsed_d:
                    parsed_review_date = parsed_d.date() if isinstance(parsed_d, datetime) else parsed_d
                else:
                    return Response(
                        {"success": False, "message": "Invalid date format for 'review_date'. Expected YYYY-MM-DD.", "error_code": "VALIDATION_ERROR"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Validate screenshot_url format if passed as string URL
            if cleaned_url and not screenshot_file:
                url_validator = URLValidator()
                try:
                    url_validator(cleaned_url)
                except ValidationError:
                    return Response(
                        {"success": False, "message": "Field 'screenshot_url' must be a valid URI format.", "error_code": "VALIDATION_ERROR"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Atomic Upsert Database Logic
            with transaction.atomic():
                review, created = GoogleReview.objects.select_for_update().get_or_create(
                    student=student,
                    course=course,
                    batch=batch,
                    defaults={
                        "is_google_review": is_google_review,
                        "review_date": parsed_review_date,
                        "screenshot_url": stored_file_name or cleaned_url
                    }
                )

                review.is_google_review = is_google_review
                if parsed_review_date is not None:
                    review.review_date = parsed_review_date
                
                if screenshot_file:
                    review.screenshot = screenshot_file

                if stored_file_name or cleaned_url:
                    review.screenshot_url = stored_file_name or cleaned_url

                review.save()

            screenshot_url = resolve_screenshot_url(review, request)

            resp_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            return Response({
                "success": True,
                "message": "Google review created successfully." if created else "Google review updated successfully.",
                "data": {
                    "id": review.id,
                    "student_id": student.registration_id or f"std_{student.student_id}",
                    "raw_student_id": student.student_id,
                    "student_name": f"{student.first_name or ''} {student.last_name or ''}".strip(),
                    "email": student.email,
                    "is_google_review": review.is_google_review,
                    "review_date": review.review_date.strftime("%Y-%m-%d") if review.review_date else None,
                    "screenshot_url": screenshot_url,
                    "course_name": course.course_name,
                    "course_id": course.course_id,
                    "batch_name": batch.title,
                    "batch_id": batch.batch_id,
                    "created_at": review.created_at.isoformat() if review.created_at else None,
                    "updated_at": review.updated_at.isoformat() if review.updated_at else None
                }
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
    Update Google review status (is_google_review), review_date, and screenshot file upload.
    DELETE /api/v1/reports/google-reviews/<id>
    Delete / reset Google review record.
    <id> can be the GoogleReview PK or Student PK/registration_id.
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

            # 1. Look up by GoogleReview PK or Student PK/registration_id
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

            # If review doesn't exist yet for this student, create it
            if not review and student:
                sc = StudentCourse.objects.filter(student=student).first()
                nb = NewBatch.objects.filter(student_courses__student=student).first()
                review = GoogleReview.objects.create(
                    student=student,
                    course=sc.course if sc else None,
                    batch=sc.batch if (sc and sc.batch) else nb
                )

            # 2. Extract & Parse update data
            data = request.data
            is_google_review = data.get("is_google_review")
            review_date = data.get("review_date")
            screenshot = request.FILES.get("screenshot")
            raw_screenshot_input = data.get("screenshot_url") or data.get("screenshot")
            cleaned_url = clean_and_extract_url(raw_screenshot_input) if isinstance(raw_screenshot_input, str) else None
            stored_file_name = extract_filename_or_relative_path(raw_screenshot_input) if isinstance(raw_screenshot_input, str) else None

            if is_google_review is not None:
                if isinstance(is_google_review, bool):
                    review.is_google_review = is_google_review
                elif str(is_google_review).lower() in ["true", "yes", "1"]:
                    review.is_google_review = True
                elif str(is_google_review).lower() in ["false", "no", "0"]:
                    review.is_google_review = False

            # Validation Rule: If is_google_review is true and review_date is null/empty
            if review.is_google_review and not review.review_date and not review_date:
                return Response(
                    {"success": False, "message": "Field 'review_date' is required when is_google_review is true.", "error_code": "UNPROCESSABLE_ENTITY"},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY
                )

            if review_date:
                parsed_d = parse_date(str(review_date)) or parse_datetime(str(review_date))
                if parsed_d:
                    if isinstance(parsed_d, datetime):
                        review.review_date = parsed_d.date()
                    else:
                        review.review_date = parsed_d

            if screenshot and not isinstance(screenshot, str):
                review.screenshot = screenshot

            if cleaned_url and not screenshot:
                url_validator = URLValidator()
                try:
                    url_validator(cleaned_url)
                except ValidationError:
                    return Response(
                        {"success": False, "message": "Field 'screenshot_url' must be a valid URI format.", "error_code": "VALIDATION_ERROR"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                review.screenshot_url = stored_file_name or cleaned_url

            review.save()

            screenshot_url = resolve_screenshot_url(review, request)

            return Response({
                "success": True,
                "message": "Google review updated successfully.",
                "data": {
                    "id": review.id,
                    "student_id": review.student.registration_id or f"std_{review.student.student_id}",
                    "raw_student_id": review.student.student_id,
                    "student_name": f"{review.student.first_name or ''} {review.student.last_name or ''}".strip(),
                    "email": review.student.email,
                    "is_google_review": review.is_google_review,
                    "review_date": review.review_date.strftime("%Y-%m-%d") if review.review_date else None,
                    "screenshot_url": screenshot_url,
                    "course_name": review.course.course_name if review.course else "-",
                    "course_id": review.course.course_id if review.course else None,
                    "batch_name": review.batch.title if review.batch else "-",
                    "batch_id": review.batch.batch_id if review.batch else None,
                    "updated_at": review.updated_at.isoformat() if review.updated_at else None
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def delete(self, request, pk=None):
        """
        DELETE /api/v1/reports/google-reviews/{id}
        Delete review record or reset student review status.
        """
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

            # Delete the GoogleReview DB record (Soft Reset so student appears with is_google_review: false)
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



            
import math
from datetime import datetime, date, time, timedelta
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.db.models import Q, Sum, Prefetch, Count
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from aryuapp.auth import CustomJWTAuthentication
from aryuapp.models import Student, StudentCourse, Attendance
from batches.models import NewBatch, ClassSchedule
from payments.models import PaymentTransaction
from courses.models import Course


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
    Supports pagination (limit=50, page=1 default), sort (created_at DESC default),
    search (fuzzy on student name/email/reg_id), course_id, batch_id, date range filtering,
    dynamic S.No calculation, total_classes, attended_classes, not_attended_classes,
    attendance_percentage, and filter_options.
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

            # 2. Parse Query Filters
            search = request.GET.get("search", "").strip()
            course_id = request.GET.get("course_id", "").strip()
            batch_id = request.GET.get("batch_id", "").strip()
            from_date_str = request.GET.get("from_date", "").strip()
            to_date_str = request.GET.get("to_date", "").strip()
            sort_by = request.GET.get("sort_by", "created_at").strip().lower()
            sort_order = request.GET.get("sort_order", "desc").strip().lower()

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

            # Base Queryset: Active students
            students_qs = Student.objects.filter(is_archived=False)

            # Search filter (fuzzy on student name, email, reg_id)
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

            # 3. Sorting Mapping
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
            order_expr = db_sort_field if sort_order == "asc" else f"-{db_sort_field}"

            students_qs = students_qs.distinct()
            total_count = students_qs.count()

            # 4. Paginate with Prefetching
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

            # 5. Bulk Aggregations for Attendance Metrics
            student_pks = [s.student_id for s in sliced_students]

            # Attendance PRESENT counts per student
            attendance_counts = dict(
                Attendance.objects.filter(student_id__in=student_pks, status__iexact="PRESENT")
                .values("student_id")
                .annotate(cnt=Count("id"))
                .values_list("student_id", "cnt")
            )

            # ClassSchedule counts per batch
            batch_class_counts = dict(
                ClassSchedule.objects.filter(is_archived=False, is_class_cancelled=False)
                .filter(Q(new_batch_id__isnull=False) | Q(batch_id__isnull=False))
                .values("new_batch_id")
                .annotate(cnt=Count("schedule_id"))
                .values_list("new_batch_id", "cnt")
            )

            # ClassSchedule counts per course (as fallback)
            course_class_counts = dict(
                ClassSchedule.objects.filter(is_archived=False, is_class_cancelled=False)
                .values("course_id")
                .annotate(cnt=Count("schedule_id"))
                .values_list("course_id", "cnt")
            )

            data = []
            for idx, s in enumerate(sliced_students):
                s_no = offset + idx + 1
                full_name = f"{s.first_name or ''} {s.last_name or ''}".strip()

                courses_map = {}
                batches_map = {}

                for sc in s.student_courses.all():
                    if sc.course and sc.course.course_name:
                        if not course_id or str(sc.course.course_id) == str(course_id):
                            courses_map[sc.course.course_id] = sc.course.course_name
                    if sc.batch:
                        if not batch_id or str(sc.batch.batch_id) == str(batch_id):
                            b_title = sc.batch.title or getattr(sc.batch, "batch_name", None)
                            if b_title:
                                batches_map[sc.batch.batch_id] = b_title

                for nb in s.new_batches.all():
                    if nb.course and nb.course.course_name:
                        if not course_id or str(nb.course.course_id) == str(course_id):
                            courses_map[nb.course.course_id] = nb.course.course_name
                    if nb.title:
                        if not batch_id or str(nb.batch_id) == str(batch_id):
                            batches_map[nb.batch_id] = nb.title

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
                            b_title = sc.batch.title or getattr(sc.batch, "batch_name", None)
                            if b_title:
                                batches_map[sc.batch.batch_id] = b_title
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

                # Calculate total classes conducted for student's batches / courses
                total_classes = 0
                if batch_ids:
                    for b_id in batch_ids:
                        total_classes += batch_class_counts.get(b_id, 0)
                elif course_ids:
                    for c_id in course_ids:
                        total_classes += course_class_counts.get(c_id, 0)

                attended_classes = attendance_counts.get(s.student_id, 0)
                not_attended_classes = max(0, total_classes - attended_classes)
                attendance_percentage = round((attended_classes / total_classes) * 100, 2) if total_classes > 0 else 0.0

                created_at_iso = s.created_at.isoformat() if s.created_at else None

                data.append({
                    "s_no": s_no,
                    "id": str(s.student_id),
                    "student_id": s.registration_id or f"std_{s.student_id}",
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



            
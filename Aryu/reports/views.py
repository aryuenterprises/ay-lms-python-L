from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum, Q
from aryuapp.models import Student
from batches.models import BatchCourseTrainer
from payments.models import PaymentTransaction
from courses.models import Course


class AryuReportView(APIView):
    def get(self, request):
        try:
            search      = request.GET.get("search", "").strip()
            course_name = request.GET.get("course_name", "").strip()
            course_type = request.GET.get("course_type", "").strip()
            tutor_id    = request.GET.get("tutor_id", "").strip()
            start_date  = request.GET.get("start_date", "").strip()
            end_date    = request.GET.get("end_date", "").strip()
            page        = int(request.GET.get("page", 1))
            page_size   = int(request.GET.get("page_size", 10))

            # ── Base queryset: PaymentTransaction ──────────────────────
            qs = PaymentTransaction.objects.filter(
                billing_type="student",
                is_archived=False,
                student__isnull=False,
                course__isnull=False,
            ).select_related(
                "student",
                "course",
                "course__course_category",
            ).order_by("-created_at")

            # ── Filters ────────────────────────────────────────────────
            if search:
                qs = qs.filter(
                    Q(student__first_name__icontains=search) |
                    Q(student__last_name__icontains=search)  |
                    Q(student__contact_no__icontains=search) |
                    Q(student__email__icontains=search)
                )

            if course_name:
                qs = qs.filter(course__course_name__icontains=course_name)

            if course_type:
                qs = qs.filter(course__mode_of_delivery__iexact=course_type)

            # Filter by tutor via BatchCourseTrainer
            if tutor_id:
                student_ids = BatchCourseTrainer.objects.filter(
                    trainer__trainer_id=tutor_id
                ).values_list("student_id", flat=True).distinct()
                qs = qs.filter(student__student_id__in=student_ids)

            if start_date:
                qs = qs.filter(created_at__date__gte=start_date)
            if end_date:
                qs = qs.filter(created_at__date__lte=end_date)

            # ── Totals across ALL filtered records ─────────────────────
            totals = qs.aggregate(
                total_final_amount   = Sum("amount"),
                total_paid_amount    = Sum("amount_received"),
                total_balance_amount = Sum("balance_due"),
                total_discount       = Sum("discount"),
            )

            total_records = qs.count()

            # ── Pagination ─────────────────────────────────────────────
            start_index  = (page - 1) * page_size
            paginated_qs = qs[start_index: start_index + page_size]

            # ── Pre-fetch BatchCourseTrainer for all students in this page ──
            # Avoids N+1 queries — one query for all students on this page
            student_ids_page = [txn.student_id for txn in paginated_qs]

            bct_map = {}  # student_id → BatchCourseTrainer (latest)
            bct_qs = BatchCourseTrainer.objects.filter(
                student_id__in=student_ids_page
            ).select_related(
                "trainer",
                "batch",
                "course",
            )
            for bct in bct_qs:
                # If a student has multiple BCT records, match by course too
                key = (bct.student_id, bct.course_id)
                if key not in bct_map:
                    bct_map[key] = bct

            # ── Build rows ─────────────────────────────────────────────
            data = []
            for txn in paginated_qs:
                student = txn.student
                course  = txn.course

                full_name = f"{student.first_name or ''} {student.last_name or ''}".strip()

                # ✅ Get BatchCourseTrainer by (student, course) match
                bct = bct_map.get((student.student_id, course.course_id))

                # ✅ Tutor name from BatchCourseTrainer
                tutor_name = bct.trainer.full_name if bct and bct.trainer else "N/A"

                # ✅ Batch name from BatchCourseTrainer
                batch_id = getattr(bct.batch, "batch_id", "N/A") if bct and bct.batch else "N/A"
                batch_name = getattr(bct.batch, "batch_name", "N/A") if bct and bct.batch else "N/A"
                # Duration
                duration = "N/A"
                if course.duration and course.duration_type:
                    duration = f"{course.duration} {course.duration_type}"
                elif course.duration:
                    duration = str(course.duration)

                # Amount logic with fallbacks
                raw_amount     = float(txn.amount or 0)
                discount       = float(txn.discount or 0)
                after_discount = float(txn.total_after_discount or 0)
                final_amount   = after_discount if after_discount > 0 else max(raw_amount - discount, 0)
                paid_amount    = float(txn.amount_received or 0)
                balance_due    = float(txn.balance_due or 0)
                if balance_due == 0 and paid_amount > 0:
                    balance_due = max(final_amount - paid_amount, 0)

                # Course type fallback
                course_type_val = (
                    course.mode_of_delivery
                    or student.student_type
                    or "N/A"
                )

                data.append({
                    "student_name"   : full_name or "N/A",
                    "phone"          : student.contact_no or "N/A",
                    "email"          : student.email or "N/A",
                    "registration_id": student.registration_id or "N/A",
                    "student_id"     : student.student_id,
                    "discount"       : student.discount or "N/A",
                    "course_type"    : course_type_val,
                    "course_name"    : course.course_name or "N/A",
                    "course_id"      : course.course_id,
                    "batch_name"     : batch_name,           # ✅ from BatchCourseTrainer
                    "batch_id"       : batch_id,
                    "tutor_name"     : tutor_name,           # ✅ from BatchCourseTrainer
                    "total_amount"   : raw_amount,
                    "discount_amount": discount,
                    "final_amount"   : final_amount,
                    "paid_amount"    : paid_amount,
                    "balance_amount" : balance_due,
                    "duration"       : duration,
                    "start_date"     : str(course.start_date) if course.start_date else "N/A",
                    "end_date"       : str(course.end_date)   if course.end_date   else "N/A",
                    "transaction_id" : txn.transaction_id or "N/A",
                    "payment_status" : txn.payment_status or "N/A",
                    "payment_mode"   : txn.payment_mode or "N/A",
                    "created_at"     : txn.created_at.strftime("%d %b %Y") if txn.created_at else "N/A",
                })

            return Response({
                "success"       : True,
                "page"          : page,
                "page_size"     : page_size,
                "total_records" : total_records,
                "totals": {
                    "total_final_amount"  : float(totals["total_final_amount"]   or 0),
                    "total_paid_amount"   : float(totals["total_paid_amount"]    or 0),
                    "total_balance_amount": float(totals["total_balance_amount"] or 0),
                    "total_discount"      : float(totals["total_discount"]       or 0),
                },
                "data": data
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({"success": False, "message": str(e)}, status=500)
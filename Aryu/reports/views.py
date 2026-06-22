from django.db.models import Q, Sum
from rest_framework.views import APIView
from rest_framework.response import Response

from aryuapp.models import Student
from batches.models import NewBatch
from payments.models import PaymentTransaction


class AryuReportView(APIView):

    def get(self, request):
        try:
            search      = request.GET.get("search", "").strip()
            course_name = request.GET.get("course_name", "").strip()
            course_type = request.GET.get("course_type", "").strip()
            tutor_id    = request.GET.get("tutor_id", "").strip()
            start_date  = request.GET.get("start_date", "").strip()
            end_date    = request.GET.get("end_date", "").strip()
            # page        = int(request.GET.get("page", 1))
            # page_size   = int(request.GET.get("page_size", 10))

            search = request.GET.get("search", "").strip()
            tutor_id = request.GET.get("tutor_id", "").strip()

            students = Student.objects.filter(
                is_archived=False
            ).distinct()

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

            data = []

            for student in students:

            unique_student_ids = list(
            qs.values_list(
                    "student__student_id",
                    flat=True
                ).distinct()
            )

            total_records = len(unique_student_ids)

            # start_index = (page - 1) * page_size
            # student_ids_page = unique_student_ids[
            #     start_index:start_index + page_size
            # ]

            # No pagination
            paginated_qs = qs

            total_records = qs.values(
                "student__student_id"
            ).distinct().count()

            student_ids_page = (
                qs.values_list(
                    "student_id",
                    flat=True
                )
                .distinct()
            )

            bct_map = {}

            bct_qs = NewBatch.objects.filter(
                students__student_id__in=student_ids_page
            ).select_related(
                "trainer",
                "course"
            ).prefetch_related(
                "students"
            ).distinct()

            for bct in bct_qs:
                for student in bct.students.all():
                    key = (
                        student.student_id,
                        bct.course_id
                    )

                    totals = transactions.aggregate(
                        total_amount=Sum("amount"),
                        paid_amount=Sum("amount_received"),
                        balance_amount=Sum("balance_due"),
                        discount_amount=Sum("discount")
                    )

            data = []
            processed_students = set()

            for txn in paginated_qs:

                if txn.student_id in processed_students:
                    continue

                processed_students.add(txn.student_id)

                student = txn.student
                course = txn.course

                full_name = (
                    f"{student.first_name or ''} "
                    f"{student.last_name or ''}"
                ).strip()

                bct = bct_map.get(
                    (student.student_id, course.course_id)
                )

                tutor_name = (
                    bct.trainer.full_name
                    if bct and bct.trainer
                    else "N/A"
                )

                batch_id = bct.batch_id if bct else "N/A"
                batch_name = bct.title if bct else "N/A"
                batch_start_date = bct.start_date if bct else "N/A"
                batch_end_date = bct.end_date if bct else "N/A"

                duration = "N/A"
                if course.duration and course.duration_type:
                    duration = (
                        f"{course.duration} "
                        f"{course.duration_type}"
                    )
                elif course.duration:
                    duration = str(course.duration)

                raw_amount = float(txn.amount or 0)
                discount = float(txn.discount or 0)

                after_discount = float(
                    txn.total_after_discount or 0
                )

                final_amount = (
                    after_discount
                    if after_discount > 0
                    else max(raw_amount - discount, 0)
                )

                paid_amount = float(
                    txn.amount_received or 0
                )

                balance_due = float(
                    txn.balance_due or 0
                )

                course_type_val = (
                    course.mode_of_delivery
                    or student.student_type
                    or "N/A"
                )

                student_transactions = (
                    PaymentTransaction.objects.filter(
                        student__student_id=student.student_id,
                        is_archived=False
                    )
                    .select_related("course")
                    .order_by(
                        "-invoice_date",
                        "-created_at"
                    )
                )

                payment_history = []

                for payment in student_transactions:

                    payment_history.append({
                        "id": payment.id,
                        "course_name": (
                            payment.course.course_name
                            if payment.course
                            else None
                        ),
                        "course_type": (
                            course.mode_of_delivery
                            if course else None
                        ),
                        "course_fee":course.fee,
                        "batch_id": batch.batch_id,
                        "batch_name": batch.title,
                        "duration":course.duration,
                        "batch_start_date": batch.start_date,
                        "batch_end_date": batch.end_date,
                        "trainer_name": (
                            batch.trainer.full_name
                            if batch.trainer
                            else "N/A"
                        ),
                        "payment_status": payment.payment_status,
                        "payment_mode": (
                            payment.metadata.get("mode")
                            if payment.metadata
                            else None
                        ),
                        "invoice_url": (
                            "https://aylms.aryuprojects.com/api"
                            + payment.invoice.url
                        )
                        if payment.invoice
                        and hasattr(payment.invoice, "url")
                        else None,
                    })

                data.append({
                    "student_name": full_name or "N/A",
                    "phone": student.contact_no or "N/A",
                    "email": student.email or "N/A",
                    "registration_id": (
                        student.registration_id
                        or "N/A"
                    ),
                    "student_id": student.student_id,
                    "discount": student.discount or "N/A",
                    "converter": student.converter or "N/A",

                    "course_type": course_type_val,
                    "course_name": course.course_name or "N/A",
                    "course_id": course.course_id,

                    "batch_name": batch_name,
                    "batch_id": batch_id,

                    "batch_start_date": (
                        str(batch_start_date)
                        if batch_start_date != "N/A"
                        else "N/A"
                    ),

                    "batch_end_date": (
                        str(batch_end_date)
                        if batch_end_date != "N/A"
                        else "N/A"
                    ),

                    student_data["payment_history"] = payment_history

                    "total_amount": raw_amount,
                    "discount_amount": discount,
                    "final_amount": final_amount,
                    "paid_amount": paid_amount,
                    "balance_amount": balance_due,

                    "duration": duration,

                    "start_date": (
                        str(course.start_date)
                        if course.start_date
                        else "N/A"
                    ),

                    "end_date": (
                        str(course.end_date)
                        if course.end_date
                        else "N/A"
                    ),

                    "created_at": (
                        txn.created_at.strftime(
                            "%d %b %Y"
                        )
                        if txn.created_at
                        else "N/A"
                    ),

                    "payment_history": payment_history
                })
            return Response({
                "success"       : True,
                # "page"          : page,
                # "page_size"     : page_size,
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

            return Response(
                {
                    "success": False,
                    "message": str(e)
                },
                status=500
            )
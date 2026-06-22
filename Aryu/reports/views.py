from django.db.models import Q, Sum
from rest_framework.views import APIView
from rest_framework.response import Response

from aryuapp.models import Student
from batches.models import NewBatch
from payments.models import PaymentTransaction


class AryuReportView(APIView):

    def get(self, request):
        try:

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
                    "courses": []
                }

                batches = (
                    NewBatch.objects.filter(
                        students__student_id=student.student_id
                    )
                    .select_related(
                        "course",
                        "trainer"
                    )
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
                        .order_by(
                            "-invoice_date",
                            "-created_at"
                        )
                    )

                    totals = transactions.aggregate(
                        total_amount=Sum("amount"),
                        paid_amount=Sum("amount_received"),
                        balance_amount=Sum("balance_due"),
                        discount_amount=Sum("discount")
                    )

                    payment_history = []

                    for payment in transactions:

                        payment_history.append({
                            "id": payment.id,
                            "transaction_id": payment.transaction_id,
                            "invoice_date": payment.invoice_date,
                            "amount": float(payment.amount or 0),
                            "amount_received": float(
                                payment.amount_received or 0
                            ),
                            "balance_due": float(
                                payment.balance_due or 0
                            ),
                            "payment_status": payment.payment_status,
                            "payment_mode": (
                                payment.metadata.get("mode")
                                if payment.metadata
                                else None
                            ),
                            "invoice_url": (
                                request.build_absolute_uri(
                                    payment.invoice.url
                                )
                                if payment.invoice
                                else None
                            )
                        })

                    student_data["courses"].append({
                        "course_id": (
                            course.course_id
                            if course else None
                        ),
                        "course_name": (
                            course.course_name
                            if course else None
                        ),
                        "course_type": (
                            course.mode_of_delivery
                            if course else None
                        ),
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
                        "total_amount": float(
                            totals["total_amount"] or 0
                        ),
                        "paid_amount": float(
                            totals["paid_amount"] or 0
                        ),
                        "balance_amount": float(
                            totals["balance_amount"] or 0
                        ),
                        "discount_amount": float(
                            totals["discount_amount"] or 0
                        ),
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
                            "amount_received": float(
                                payment.amount_received or 0
                            ),
                            "balance_due": float(
                                payment.balance_due or 0
                            ),
                            "payment_status": payment.payment_status
                        })

                    student_data["payment_history"] = payment_history

                data.append(student_data)

            return Response({
                "success": True,
                "total_records": students.count(),
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
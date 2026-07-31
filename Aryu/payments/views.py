from .models import *
from .serializers import *
from aryuapp.auth import CustomJWTAuthentication
from django.core.mail import EmailMessage
from num2words import num2words
from rest_framework.response import Response
import io
import razorpay
from django.views.decorators.csrf import csrf_exempt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
import stripe
from rest_framework.decorators import action, api_view
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import OuterRef, Subquery, F, Value, DecimalField,Prefetch,Q
from django.db.models.functions import Coalesce
from payments.services.invoice_service import (
    InvoiceService
)
from decimal import Decimal, InvalidOperation
from aryuapp.utils import *
from aryuapp.mixins import *
from aryuapp.models import Settings
from aryuapp.views import flatten_errors
from collections import defaultdict
import pytz
import json
import logging
from datetime import datetime
logger = logging.getLogger(__name__)
import requests
from requests.auth import HTTPBasicAuth
from zoneinfo import ZoneInfo
from datetime import timedelta
import traceback
from webinar.models import Webinar
from django.db.models import Max
# Create your views here.


class PaymentGatewayViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        """
        Return gateways depending on the user's role.
        Super admin sees all, admin/trainer sees their own.
        """
        user = self.request.user
        role = getattr(user, "user_type", None)

        qs = PaymentGateway.objects.all()

        if role in ["trainer", "admin"]:
            trainer_id = getattr(user, "trainer_id", None)
            qs = qs.filter(created_by=trainer_id, created_by_type=role)
        elif role == "super_admin":
            user_id = getattr(user, "user_id", None)
            qs = qs.filter(created_by=user_id, created_by_type=role)
        # students normally should not see gateways
        elif role == "student":
            qs = PaymentGateway.objects.none()

        return qs.order_by("-created_at")

    def list(self, request):

        user = request.user

        if getattr(user, "user_type", "") != "super_admin":

            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )
        
        queryset = self.get_queryset()
        serializer = PaymentGatewaySerializer(queryset, many=True)
        return Response({"success": True, "data": serializer.data})

    def create(self, request):

        user = request.user

        if getattr(user, "user_type", "") != "super_admin":

            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )
        
        serializer = PaymentGatewaySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "message": "Payment gateway created successfully.", "data": serializer.data}, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):

        user = request.user

        if getattr(user, "user_type", "") != "super_admin":

            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )
        
        try:
            queryset = self.get_queryset()  # <-- no arguments here
            gateway = queryset.filter(pk=pk).first()
            if not gateway:
                return Response({"success": False, "message": "Payment gateway not found."}, status=200)

            serializer = PaymentGatewaySerializer(gateway)
            return Response({"success": True, "data": serializer.data}, status=200)
        except Exception as e:
            return Response({"success": False, "message": f"Error retrieving data: {str(e)}"}, status=200)


    def update(self, request, pk=None):

        user = request.user

        if getattr(user, "user_type", "") != "super_admin":

            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )
        
        try:
            queryset = self.get_queryset()  # <-- no arguments here
            instance = queryset.filter(pk=pk).first()
            if not instance:
                return Response({"success": False, "message": "Payment gateway not found."}, status=200)

            partial = request.method == "PATCH"
            serializer = PaymentGatewaySerializer(instance, data=request.data, partial=partial, context={"request": request})
            if serializer.is_valid():
                serializer.save()
                return Response({
                    "success": True,
                    "message": "Payment gateway updated successfully.",
                    "data": serializer.data
                }, status=200)
            else:
                return Response({"success": False, "message": serializer.errors}, status=200)
        except Exception as e:
            return Response({"success": False, "message": f"Error updating gateway: {str(e)}"}, status=200)

    def destroy(self, request, pk=None):

        user = request.user

        if getattr(user, "user_type", "") != "super_admin":

            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )
        """
        Soft delete (archive) instead of actual deletion.
        """
        try:
            gateway = PaymentGateway.objects.filter(pk=pk).first()
            if not gateway:
                return Response({"success": False, "message": "Payment gateway not found."}, status=status.HTTP_200_OK)

            gateway.is_archived = True
            gateway.save(update_fields=["is_archived"])
            return Response({"success": True, "message": "Payment gateway archived successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": f"Error archiving gateway: {str(e)}"}, status=status.HTTP_200_OK)

import math

def safe_float(value, default=0):
    try:
        if value in [None, "", "undefined", "null"]:
            return default

        value = float(value)

        # 🚨 Handle NaN / Infinity
        if math.isnan(value) or math.isinf(value):
            return default

        return value

    except (ValueError, TypeError):
        return default
class PaymentTransactionViewSet(viewsets.ViewSet):
    
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return PaymentTransaction.objects.filter(is_archived=False)
    

    def list(self, request):
        user = request.user
        user_type = getattr(user, "user_type", "")
        user_created_id = getattr(user, "trainer_id", None)

        if getattr(user, "user_type", "") != "super_admin":
            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )

        if user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)

        # ================================================================
        # OPTIMIZATION 1: Global queries pulled OUTSIDE the loop (Runs only 1 time)
        # ================================================================
        companies = list(
            Employer.objects.filter(is_archived=False).values("company_id", "company_name")
        )

        courses_list = list(
            Course.objects.filter(is_archived=False, status="Active").values("course_id", "course_name")
        )

        settings = Settings.objects.filter(is_archived=False).only(
            "stripe_enabled", "paypal_enabled", "razorpay_enabled"
        ).order_by("-created_at").first()

        # ================================================================
        # STEP 1 & 2: Base queryset & Hierarchy filter (FIXED: Removed select_related)
        # ================================================================
        # ALL STUDENTS
        all_students = Student.objects.filter(is_archived=False)

        if user_type == "admin" and user_created_id:
            all_students = all_students.filter(created_by=user_created_id)

        elif user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

            all_students = all_students.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )

        # ONLY STUDENTS WITH TRANSACTIONS
        students_qs = all_students.filter(
            transactions__is_archived=False
        ).distinct()

        # ================================================================
        # STEP 3: Prefetch (Prefetching relationships cleanly)
        # ================================================================
        all_students = all_students.prefetch_related(
            "new_batches__course"
        )
        students_qs = students_qs.prefetch_related(
            "new_batches__course",  
            Prefetch(
                "transactions",
                queryset=PaymentTransaction.objects.filter(
                    is_archived=False
                ).select_related(
                    "course", "gateway"
                ).order_by("-created_at")
            )
        )

        # ================================================================
        # STEP 4: Build response using the OPTIMIZED students_qs
        # ================================================================
        students = []

        for student in all_students:

            employer = getattr(student, "employer", None)

            courses = []

            for batch in student.new_batches.all():
                if not batch.course:
                    continue

                course = batch.course

                # Get all transactions for this student & course
                txs = PaymentTransaction.objects.filter(
                    student=student,
                    course=course,
                    is_archived=False
                )

                paid_amount = sum(
                    float(tx.amount)
                    for tx in txs
                    if tx.payment_status
                    and tx.payment_status.lower() in [
                        "success",
                        "done",
                        "paid",
                        "partial",
                        "advanced",
                        "complete",
                    ]
                )

                course_fee = float(course.fee or 0)
                discount = float(getattr(student, "discount", 0) or 0)

                total_after_discount = course_fee - discount
                due_amount = max(total_after_discount - paid_amount, 0)

                courses.append({
                    "course_id": course.course_id,
                    "course_name": course.course_name,
                    "course_fee": course_fee,
                    "discount": discount,
                    "total_after_discount": total_after_discount,
                    "paid_amount": paid_amount,
                    "due_amount": due_amount,
                })

            students.append({
                "student_id": student.student_id,
                "registration_id": student.registration_id,
                "student_name": student.first_name,
                "email": student.email,
                "phone": student.contact_no,
                "company_id": getattr(employer, "company_id", None) if employer else None,
                "company_name": getattr(employer, "company_name", None) if employer else None,
                "courses": courses,
            })
        student_list = []

        for student in students_qs:
            try:
                courses_data = []

                # Reads from memory cache now (0 database hits)
                batches = student.new_batches.all()
                all_transactions = student.transactions.all()

                for batch in batches:
                    course = batch.course
                    if not course:
                        continue

                    # Filter in Python memory instead of hitting the DB
                    txs = sorted(
                        [
                            tx for tx in student.transactions.all()
                            if tx.course_id == course.course_id
                        ],
                        key=lambda x: x.created_at,
                        reverse=True
                    )

                    discount = float(getattr(student, "discount", None) or 0)
                    paid_amount = sum(
                        float(tx.amount or 0)
                        for tx in txs
                        if tx.payment_status and tx.payment_status.lower() in [
                            "success",
                            "done",
                            "paid",
                            "partial",
                            "advanced",
                            "complete"
                        ]
                    )

                    course_fee = float(getattr(course, "fee", None) or 0)
                    discount = float(getattr(discount, "discount", None) or 0)

                    total_after_discount = course_fee - discount
                    due_amount = max(total_after_discount - paid_amount, 0.0)

                    courses_data.append({
                        "course_id": course.course_id,
                        "course_name": course.course_name,
                        "course_fee": course_fee,
                        "discount": discount,
                        "total_after_discount": total_after_discount,   
                        "paid_amount": paid_amount,                     
                        "due_amount": due_amount,                       
                        "transactions": [
                            {
                                "transaction_id": tx.transaction_id,
                                "amount": float(tx.amount),
                                "payment_status": tx.payment_status,
                                "payment_mode": tx.metadata.get("mode") if tx.metadata else None, 
                                "currency": tx.currency,
                                "created_at": tx.created_at,
                            } for tx in txs
                        ]
                    })

                # Safe evaluation for employer matching your original code strategy
                employer = getattr(student, "employer", None) if hasattr(student, "employer") else None

                student_list.append({
                    "student_id": student.student_id,
                    "registration_id": student.registration_id,
                    "student_name": f"{student.first_name}".strip(),
                    "email": student.email,
                    "phone": student.contact_no,
                    "courses": courses_data,  
                    "company_id": getattr(employer, "company_id", None) if employer else None,
                    "company_name": getattr(employer, "company_name", None) if employer else None,
                })

            except Exception as e:
                print(f"Error processing student {student.student_id}: {e}")

        # ================================================================
        # STEP 5: Serializer & Gateways
        # ================================================================

        students_qs = (
            students_qs
            .annotate(last_payment=Max("transactions__created_at"))
            .order_by("-last_payment")
        )

        serializer = StudentPaymentSummarySerializer(students_qs, many=True)

        enabled_gateways = []
        if settings:
            if settings.stripe_enabled:
                enabled_gateways.append("Stripe test")
            if settings.paypal_enabled:
                enabled_gateways.append("paypal")
            if settings.razorpay_enabled:
                enabled_gateways.append("razorpay")

        # ================================================================
        # FINAL RESPONSE
        # ================================================================
        return Response({
            "success": True,

            # Students who have payment transactions
            "student_payment_summaries": serializer.data,

            # All students
            "students": students,

            "students_count": len(students),

            "companies": companies,
            "courses_list": courses_list,
            "enabled_gateways": enabled_gateways,

            "meta": {
                "total_students": len(students),
                "students_with_transactions": len(student_list),
                "user_type": user_type
            }
        })  


    def create(self, request):

        user = request.user

        if getattr(user, "user_type", "") != "super_admin":

            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )

        serializer = (
            PaymentTransactionCreateSerializer(
                data=request.data,
                context={"request": request}
            )
        )

        serializer.is_valid(
            raise_exception=True
        )

        transaction = serializer.save()

        return Response({
            "success": True,
            "message":
            "Payment transaction created successfully",
            "data":
            PaymentTransactionDetailSerializer(
                transaction,
                context={"request": request}
            ).data
        })
     
    def retrieve(self, request, pk=None):

        user = request.user

        if getattr(user, "user_type", "") != "super_admin":

            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )
        """
        Retrieve detailed payment information for a single student
        
        Args:
            pk: student_id
        """
        student = Student.objects.filter(student_id=pk,is_archived=False).prefetch_related(
            Prefetch(
                "transactions",
                queryset=PaymentTransaction.objects.select_related("course", "gateway")
            ),
            Prefetch(
                "emi_plans",
                queryset=PaymentEMI.objects.prefetch_related("installments")
            ),
            Prefetch(
                "new_batches",  # batches student is enrolled in
                queryset=NewBatch.objects.select_related("course")
            )
        ).first()

        if not student:
            return Response({
                "success": False,
                "message": "Student not found"
            }, status=status.HTTP_404_NOT_FOUND)

        # ================================================================
        # Build courses with transactions
        # ================================================================
        courses_list = []
        seen_course_ids = set()

        for batch in student.new_batches.all():
            course = batch.course
            
            # Skip if already processed (student in multiple batches of same course)
            if course.course_id in seen_course_ids:
                continue
            seen_course_ids.add(course.course_id)

            # Get transactions for this course
            txs = [
                    tx for tx in student.transactions.all()
                    if tx.course_id == course.course_id and not tx.is_archived
                ]


            # Calculate paid amount (only successful payments)
            paid_amount = sum(
                float(tx.amount) 
                for tx in txs 
                if tx.payment_status.lower() == "success"
            )

            courses_list.append({
                "course_id": course.course_id,
                "course_name": course.course_name,
                "total_course_fee": float(course.fee),
                "paid_amount": paid_amount,
                "balance": float(course.fee) - paid_amount,
                "discount": float(getattr(student, 'discount', 0)),
                # "date": course.date,  # Uncomment if needed
                "transactions": [
                    {
                        "transaction_id": tx.transaction_id,
                        "amount": float(tx.amount),
                        "payment_status": tx.payment_status,
                        "payment_mode": tx.payment_mode, 
                        "discount": (
                            tx.discount if tx.discount 
                            else (student.discount if batch else 0)
                        ),
                        "currency": tx.currency,
                        "created_at": tx.created_at,
                        "gateway": tx.gateway.gatway_name if tx.gateway else None,
                    } for tx in txs
                ],
                "batches": [
                    {
                        "batch_id": batch.batch_id,
                        "batch_title": batch.title,
                        "discount": getattr(student, 'discount', 0)
                    }
                ]
            })

        # ================================================================
        # Build the student payment summary
        # ================================================================
        student_summary = {
            "student_id": student.student_id,
            "registration_id": student.registration_id,
            "student_name": f"{student.first_name} ".strip(),
            "email": student.email,
            "contact_no": student.contact_no,
            "courses": courses_list,
            "emi_plans": [
                {
                    "emi_id": emi.emi_id,
                    "total_amount": float(emi.total_amount),
                    "installments": [
                        {
                            "installment_id": ins.installment_id,
                            "amount": float(ins.amount),
                            "status": ins.status
                        } for ins in emi.installments.all()
                    ]
                } for emi in student.emi_plans.all()
            ]
        }

        # ================================================================
        # Get enabled gateways
        # ================================================================
        settings = Settings.objects.filter(is_archived=False).only(
            "stripe_enabled", "paypal_enabled", "razorpay_enabled"
        ).order_by("-created_at").first()

        enabled_gateways = []
        if settings:
            if settings.stripe_enabled:
                enabled_gateways.append("Stripe test")
            if settings.paypal_enabled:
                enabled_gateways.append("paypal")
            if settings.razorpay_enabled:
                enabled_gateways.append("razorpay")

        gateway_list = list(
            PaymentGateway.objects
            .filter(
                is_archived=False,
                gatway_name__in=enabled_gateways
            )
            .only("id", "gatway_name")
            .values("id", "gatway_name")
        )

        return Response({
            "success": True,
            "student_payment_summary": student_summary,
            "gatway": gateway_list  # Note: typo in original, keeping for compatibility
        })
    
    def update(self, request, pk=None):

        user = request.user

        if getattr(user, "user_type", "") != "super_admin":
            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )

        transaction = PaymentTransaction.objects.filter(
            pk=pk,
            is_archived=False
        ).first()

        if not transaction:
            return Response(
                {
                    "success": False,
                    "message": "Transaction not found"
                },
                status = 200
            )

        # ---------- Check if course fee is already completed ----------
        if "amount" in request.data:

            student = transaction.student
            course = transaction.course

            if student and course:

                final_fee = Decimal(str(course.fee or 0))

                if hasattr(student, "course_fee") and student.course_fee:
                    try:
                        new_amount = Decimal(str(request.data["amount"]))
                    except (InvalidOperation, KeyError, TypeError):
                        return Response(
                            {
                                "success": False,
                                "message": "Invalid payment amount."
                            },
                            status=400
                        )

                already_paid = Decimal(
                    str(
                        PaymentTransaction.objects.filter(
                            student=student,
                            course=course,
                            is_archived=False
                        )
                        .exclude(pk=transaction.pk)
                        .aggregate(total=Sum("amount"))["total"] or 0
                    )
                )

                new_amount = Decimal(str(request.data["amount"]))

                total_paid = already_paid + new_amount

                if total_paid > final_fee:
                    remaining = final_fee - already_paid

                    return Response(
                        {
                            "success": False,
                            "message": (
                                f"Payment exceeds the remaining course fee. "
                                f"Course Fee: ₹{final_fee}, "
                                f"Already Paid: ₹{already_paid}, "
                                f"Remaining Balance: ₹{remaining}."
                            )
                        },
                        status = 200
                    )
               

        serializer = PaymentTransactionUpdateSerializer(
            transaction,
            data=request.data,
            partial=True,
            context={"request": request}
        )

        if not serializer.is_valid():
            first_error = next(iter(serializer.errors.values()))[0]

            return Response(
                {   
                    "success": False,
                    "message": str(first_error),
                    "errors": serializer.errors,
                },
                status=200,
            )

        serializer.save()

        return Response(
            {
                "success": True,
                "message": "Transaction updated successfully",
                "data": serializer.data
            }
        )
    
    def destroy(self, request, pk=None):

        user = request.user

        if getattr(user, "user_type", "") != "super_admin":

            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )
        
        try:
            transaction = PaymentTransaction.objects.get(pk=pk)

            transaction.is_archived = True
            transaction.save()

            return Response({
                "success": True,
                "message": "Transaction deleted successfully"
            })

        except PaymentTransaction.DoesNotExist:
            return Response({
                "success": False,
                "message": "Transaction not found"
            }, status=200)

    def student_payment_history(self, request, student_id=None):

        user = request.user

        if user.user_type not in ["student", "super_admin"]:
            return Response(
                {
                    "success": False,
                    "message": "Unauthorized access"
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # Restrict students to their own records
        if user.user_type == "student":

            logged_student_id = str(user.student_id)

            if str(student_id) != logged_student_id:

                logger.warning(
                    f"Student ID tampering attempt | "
                    f"user={user.id} | "
                    f"requested={student_id} | "
                    f"actual={logged_student_id}"
                )

                return Response(
                    {
                        "success": False,
                        "message": "You are not allowed to access other student payment records"
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

        transactions = (
            PaymentTransaction.objects
            .filter(
                student__student_id=student_id,
                is_archived=False
            )
            .select_related("course", "gateway")
            .order_by("-invoice_date", "-created_at")
        )

        student = Student.objects.get(student_id=student_id)

        serializer = StudentPaymentSummarySerializer(
            student,
            context={"request": request}
        )

        payment_logs = [
            {
                "course_name": tx.course.course_name if tx.course else None,
                "student_payment_summaries": serializer.data,
                "invoice_date": tx.invoice_date,
                "transaction_id": tx.transaction_id,
                "amount": float(tx.amount or 0),
                "payment_status": tx.payment_status,
                "payment_mode":tx.payment_mode,
                "discount": float(tx.discount or 0),
                "currency": tx.currency,
                "gateway": tx.gateway.gatway_name if tx.gateway else None,
                "invoice_url": (
                    request.build_absolute_uri(tx.invoice.url)
                    if tx.invoice else None
                ),
                "created_at": tx.created_at,
            }
            for tx in transactions
        ]

        return Response(
            {
                "success": True,
                "count": len(payment_logs),
                "payment_logs": payment_logs,
            }
        )
    # 2. Delete FULL student + all transactions
    @action(detail=True, methods=['delete'], url_path='delete-student')
    def delete_student(self, request, pk=None):
        user = request.user

        if getattr(user, "user_type", "") != "super_admin":

            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )
        
        try:
            student = Student.objects.get(student_id=pk)

            # delete all transactions
            PaymentTransaction.objects.filter(
                student_id=pk,
                is_archived=False
            ).update(is_archived=True)

            return Response({
                "success": True,
                "message": "Student and all transactions deleted"
            })

        except Student.DoesNotExist:
            return Response({
                "success": False,
                "message": "Student not found"
            }, status=404)

    @action(detail=False,methods=["post"],)
    def generate_invoice(self, request):

        user = request.user

        if getattr(user, "user_type", "") != "super_admin":

            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )

        serializer = GenerateInvoiceSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        transaction = serializer.transaction

        regenerate = serializer.validated_data.get(
            "regenerate",
            False
        )

        try:

            transaction = (
                InvoiceService.generate_invoice(
                    transaction.id,
                    regenerate=regenerate
                )
            )

            invoice_url = None

            if (
                transaction.invoice
                and hasattr(
                    transaction.invoice,
                    "url"
                )
            ):

                invoice_url = (
                    request.build_absolute_uri(
                        transaction.invoice.url
                    )
                )

            return Response(
                {
                    "success": True,
                    "message": (
                        "Invoice generated successfully"
                    ),
                    "data": {
                        "transaction_id":
                            transaction.id,

                        "invoice_no":
                            transaction.invoice_no,

                        "invoice_url":
                            invoice_url,

                        "invoice_date":
                            transaction.invoice_date,
                    }
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:

            return Response(
                {
                    "success": False,
                    "message": str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False,methods=["post"])
    def send_invoice_email(self, request):

        user = request.user

        if getattr(user, "user_type", "") != "super_admin":

            return Response(
                {
                    "success": False,
                    "message": "Unauthorized"
                },
                status=403
            )

        transaction_id = request.data.get(
            "transaction_id"
        )

        if not transaction_id:

            return Response(
                {
                    "success": False,
                    "message":
                    "transaction_id is required"
                },
                status=400
            )

        transaction = (
            PaymentTransaction.objects
            .select_related(
                "student",
                "employer",
                "course"
            )
            .filter(
                id=transaction_id,
                is_archived=False
            )
            .first()
        )

        if not transaction:

            return Response(
                {
                    "success": False,
                    "message":
                    "Transaction not found"
                },
                status=200
            )

        # =====================================================
        # CHECK INVOICE
        # =====================================================

        if not transaction.invoice:

            return Response(
                {
                    "success": False,
                    "message":
                    "Invoice not generated"
                },
                status=400
            )

        # =====================================================
        # GET EMAIL + NAME
        # =====================================================

        recipient_email = None
        customer_name = None

        # STUDENT BILLING
        if (
            transaction.billing_type == "student"
            and transaction.student
        ):

            recipient_email = (
                transaction.student.email
            )

            customer_name = (
                transaction.student.first_name
            )

        # COMPANY BILLING
        elif (
            transaction.billing_type == "company"
            and transaction.employer
        ):

            recipient_email = (
                transaction.employer.email
            )

            customer_name = (
                transaction.employer.company_name
            )

        if not recipient_email:

            return Response(
                {
                    "success": False,
                    "message":
                    "Recipient email not found"
                },
                status=400
            )

        # =====================================================
        # EMAIL BODY
        # =====================================================

        subject = (
            f"Aryu Academy Pvt Ltd - Invoice - "
            f"{transaction.invoice_no}"
        )

        body = f"""
<!DOCTYPE html>
<html>

<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Invoice Email</title>
</head>

<body style="
    margin:0;
    padding:0;
    background-color:#eef1f7;
    font-family:Arial, Helvetica, sans-serif;
">

<table width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:#eef1f7;padding:30px 15px;">

<tr>
<td align="center">

<table width="650" cellpadding="0" cellspacing="0" border="0"
       style="
            width:100%;
            max-width:650px;
            background:#ffffff;
            border-radius:14px;
            overflow:hidden;
            border:1px solid #e5e7eb;
       ">

    <!-- HEADER -->
    <tr>
        <td align="center"
            style="
                background:linear-gradient(135deg,#200A38,#430080);
                padding:35px 25px;
            ">

            <!-- LOGO -->
            <img
                src="https://portal.aryuacademy.com/api/media/logos/email_logo.png"
                alt="Aryu Academy Private Limited"
                style="
                    width:320px;
                    max-width:90%;
                    height:auto;
                    display:block;
                    margin:0 auto;
                    object-fit:contain;
                "
            />

            <p style="
                margin:10px 0 0 0;
                color:#d8c9ff;
                font-size:14px;
                line-height:22px;
            ">
                Invoice & Payment Confirmation
            </p>

        </td>
    </tr>

    <!-- BODY -->
    <tr>
        <td style="padding:40px 35px;">

            <p style="
                margin:0 0 18px 0;
                color:#111827;
                font-size:16px;
                line-height:28px;
            ">
                Dear <strong>{customer_name}</strong>,
            </p>

            <p style="
                margin:0 0 25px 0;
                color:#4b5563;
                font-size:15px;
                line-height:28px;
            ">
                Thank you for choosing
                <strong style="color:#430080;">
                    Aryu Academy
                </strong>.

                Your payment has been successfully received.
                Please find your invoice attached with this email
                for your reference and records.
            </p>

            <!-- HIGHLIGHT BOX -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="
                        background:#faf7ff;
                        border:1px solid #e9d8fd;
                        border-radius:12px;
                        margin-bottom:30px;
                   ">

                <tr>
                    <td style="padding:28px;">

                        <table width="100%" cellpadding="0" cellspacing="0">

                            <tr>
                                <td style="
                                    padding-bottom:16px;
                                    color:#6b7280;
                                    font-size:14px;
                                    width:42%;
                                ">
                                    Invoice Number
                                </td>

                                <td style="
                                    padding-bottom:16px;
                                    color:#111827;
                                    font-size:15px;
                                    font-weight:700;
                                ">
                                    {transaction.invoice_no}
                                </td>
                            </tr>

                            <tr>
                                <td style="
                                    padding-bottom:16px;
                                    color:#6b7280;
                                    font-size:14px;
                                ">
                                    Course
                                </td>

                                <td style="
                                    padding-bottom:16px;
                                    color:#111827;
                                    font-size:15px;
                                    font-weight:600;
                                ">
                                    {transaction.course.course_name if transaction.course else '-'}
                                </td>
                            </tr>

                            <tr>
                                <td style="
                                    padding-bottom:16px;
                                    color:#6b7280;
                                    font-size:14px;
                                ">
                                    Billing Type
                                </td>

                                <td style="
                                    padding-bottom:16px;
                                    color:#111827;
                                    font-size:15px;
                                    font-weight:600;
                                    text-transform:capitalize;
                                ">
                                    {transaction.billing_type}
                                </td>
                            </tr>

                            <tr>
                                <td style="
                                    color:#6b7280;
                                    font-size:14px;
                                ">
                                    Payment Amount
                                </td>

                                <td style="
                                    color:#430080;
                                    font-size:22px;
                                    font-weight:700;
                                ">
                                    ₹{transaction.amount}
                                </td>
                            </tr>

                        </table>

                    </td>
                </tr>

            </table>

            <p style="
                margin:0 0 25px 0;
                color:#4b5563;
                font-size:14px;
                line-height:26px;
            ">
                If you have any questions regarding this payment or invoice,
                feel free to contact our support team.
            </p>

            <!-- BUTTON -->
            <table cellpadding="0" cellspacing="0" border="0"
                   style="margin:30px 0;">

                <tr>
                    <td align="center"
                        style="
                            border-radius:8px;
                            background:#430080;
                        ">

                        <a href="https://aryuacademy.com/"
                           target="_blank"
                           style="
                                display:inline-block;
                                padding:14px 28px;
                                color:#ffffff;
                                font-size:14px;
                                font-weight:600;
                                text-decoration:none;
                           ">
                            Visit Our Website
                        </a>

                    </td>
                </tr>

            </table>

            <!-- FOOTER -->
            <hr style="
                border:none;
                border-top:1px solid #e5e7eb;
                margin:35px 0 25px 0;
            ">

            <p style="
                margin:0 0 15px 0;
                color:#6b7280;
                font-size:13px;
                line-height:24px;
            ">
                This email and its attachments are confidential and intended
                solely for the recipient.
            </p>

            <!-- SOCIAL LINKS -->
            <table width="100%" cellpadding="0" cellspacing="0">

                <tr>
                    <td align="center">

                        <a href="https://aryuacademy.com/"
                           style="
                                color:#430080;
                                text-decoration:none;
                                font-size:13px;
                                margin:0 8px;
                                font-weight:600;
                           ">
                           Website
                        </a>

                        <span style="color:#c4b5fd;">|</span>

                        <a href="https://www.instagram.com/aryuacademyofficial/"
                           style="
                                color:#430080;
                                text-decoration:none;
                                font-size:13px;
                                margin:0 8px;
                                font-weight:600;
                           ">
                           Instagram
                        </a>

                        <span style="color:#c4b5fd;">|</span>

                        <a href="https://www.facebook.com/aryuacademyofficial/"
                           style="
                                color:#430080;
                                text-decoration:none;
                                font-size:13px;
                                margin:0 8px;
                                font-weight:600;
                           ">
                           Facebook
                        </a>

                        <span style="color:#c4b5fd;">|</span>

                        <a href="https://www.linkedin.com/company/aryuacademyofficial"
                           style="
                                color:#430080;
                                text-decoration:none;
                                font-size:13px;
                                margin:0 8px;
                                font-weight:600;
                           ">
                           LinkedIn
                        </a>

                    </td>
                </tr>

            </table>

            <p style="
                margin:25px 0 0 0;
                text-align:center;
                color:#9ca3af;
                font-size:12px;
                line-height:22px;
            ">
                © 2026 Aryu Academy. All rights reserved.
            </p>

        </td>
    </tr>

</table>

</td>
</tr>

</table>

</body>
</html>
"""

        # =====================================================
        # SEND EMAIL
        # =====================================================

        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email]
        )
        email.content_subtype = "html"
        # ATTACH PDF
        email.attach_file(
            transaction.invoice.path
        )
        logger.warning(
            f"EMAIL TRIGGERED FOR: {recipient_email}"
        )
        email.send(
            fail_silently=False
        )

        return Response(
            {
                "success": True,
                "message":
                "Invoice email sent successfully",

                "data": {
                    "invoice_no":
                        transaction.invoice_no,

                    "sent_to":
                        recipient_email
                }
            },
            status=200
        )

class StripePaymentViewSet(viewsets.ViewSet):

    @action(detail=False, methods=['post'])
    def create_payment(self, request):
        serializer = StripePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        student_id = getattr(request.user, "student_id", None)
        try:
            student = Student.objects.get(student_id=student_id)
        except Student.DoesNotExist:
            return Response({"success": False, "message": "Student does not exist."}, status=200)

        # Fetch Stripe gateway from DB
        stripe_gateway = PaymentGateway.objects.filter(gatway_name__icontains="stripe").first()
        # if not stripe_gateway:
        #     return Response({"success": False, "message": "Stripe is disabled or not configured"}, status=200)

        stripe.api_key = stripe_gateway.secret_key
        amount_in_paise = int(data['amount'] * 100)

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': stripe_gateway.currency or 'INR',
                        'product_data': {'name': 'Course Payment'},
                        'unit_amount': amount_in_paise,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=data['success_url'],
                cancel_url=data['cancel_url'],
            )
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

        PaymentTransaction.objects.create(
            student=student,
            gateway=stripe_gateway,
            amount=data['amount'],
            currency=stripe_gateway.currency or 'INR',
            payment_status='pending',
            order_id=session.id,
            description="Payment via Stripe",
        )

        return Response({"success": True, "checkout_url": session.url})

    @csrf_exempt
    @action(detail=False, methods=['post'], url_path='webhook')
    def stripe_webhook(self, request):
        # Fetch Stripe gateway credentials
        stripe_gateway = PaymentGateway.objects.filter(gatway_name__icontains="stripe", is_enabled=True).first()
        if not stripe_gateway or not stripe_gateway.webhook_secret:
            return HttpResponse(status=400)

        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, stripe_gateway.webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError):
            return HttpResponse(status=200)

        # --------------- Handle Stripe Events ----------------
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            transaction = PaymentTransaction.objects.filter(order_id=session.get('id')).first()
            if transaction:
                transaction.payment_status = "done"
                transaction.transaction_id = session.get('payment_intent')
                transaction.save()

        elif event['type'] == 'checkout.session.expired':
            session = event['data']['object']
            transaction = PaymentTransaction.objects.filter(order_id=session.get('id')).first()
            if transaction:
                transaction.payment_status = "failed"
                transaction.save()

        elif event['type'] == 'payment_intent.payment_failed':
            intent = event['data']['object']
            transaction = PaymentTransaction.objects.filter(transaction_id=intent.get('id')).first()
            if transaction:
                transaction.payment_status = "failed"
                transaction.save()

        return HttpResponse(status=200)


import paypalrestsdk

class PayPalPaymentViewSet(viewsets.ViewSet):

    @action(detail=False, methods=['post'])
    def create_payment(self, request):
        serializer = PayPalPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        student_id = getattr(request.user, "student_id", None)
        try:
            student = Student.objects.get(student_id=student_id)
        except Student.DoesNotExist:
            return Response({"success": False, "message": "Student does not exist."}, status=200)

        settings_obj = Settings.objects.first()
        if not settings_obj or not getattr(settings_obj, "paypal_enabled", False):
            return Response({"success": False, "message": "PayPal is disabled in settings."}, status=200)

        # Fetch PayPal keys from PaymentGateway
        paypal_gateway = PaymentGateway.objects.filter(gatway_name__icontains="paypal").first()
        if not paypal_gateway:
            return Response({"success": False, "message": "PayPal keys not configured."}, status=200)

        paypalrestsdk.configure({
            "mode": "sandbox",  # or "live"
            "client_id": paypal_gateway.public_key,
            "client_secret": paypal_gateway.secret_key
        })

        payment = paypalrestsdk.Payment({
            "intent": "sale",
            "payer": {"payment_method": "paypal"},
            "redirect_urls": {
                "return_url": data['success_url'],
                "cancel_url": data['cancel_url'],
            },
            "transactions": [{
                "amount": {
                    "total": str(data['amount']),
                    "currency": "USD"
                },
                "description": "Course Payment"
            }]
        })

        if payment.create():
            PaymentTransaction.objects.create(
                student=student,
                gateway=paypal_gateway,
                amount=data['amount'],
                currency=paypal_gateway.currency or "USD",
                payment_status="pending",
                order_id=payment.id,
                description="Payment via PayPal",
            )

            for link in payment.links:
                if link.rel == "approval_url":
                    return Response({"success": True, "approval_url": str(link.href)})

            return Response({"success": False, "message": "No approval URL found."}, status=200)
        else:
            return Response({"success": False, "message": payment.error}, status=200)

    @csrf_exempt
    @action(detail=False, methods=['post'], url_path='webhook')
    def paypal_webhook(self, request):
        settings_obj = Settings.objects.first()
        if not settings_obj or not getattr(settings_obj, "paypal_enabled", False):
            return HttpResponse(status=400)

        paypal_gateway = PaymentGateway.objects.filter(gatway_name__icontains="paypal").first()
        if not paypal_gateway:
            return HttpResponse(status=400)

        event = request.data
        event_type = event.get('event_type')
        resource = event.get('resource', {})

        if event_type in ["PAYMENT.SALE.COMPLETED", "CHECKOUT.ORDER.APPROVED"]:
            order_id = resource.get('id') or resource.get('invoice_id')
            transaction = PaymentTransaction.objects.filter(order_id=order_id).first()
            if transaction:
                transaction.payment_status = "done"
                transaction.transaction_id = resource.get('id')
                transaction.save()
                # Reuse your existing invoice generator
                InvoiceService.generate_invoice(
                    transaction.id
                )

        return HttpResponse(status=200)

class RazorpayPaymentViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    required_module = "Transcation History"
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_client(self):
        gateway = PaymentGateway.objects.filter(gatway_name__icontains="razorpay_test").first()
        if not gateway:
            return None, None
        client = razorpay.Client(auth=(gateway.public_key, gateway.secret_key))
        return client, gateway

    # -------------------------
    # Create Razorpay Payment Link
    # -------------------------
    @action(detail=False, methods=['post'])
    def create(self, request, webinar):
        amount = float(request.data.get("amount", 0))
        currency = request.data.get("currency", "INR")
        success_url = request.data.get("success_url")
        cancel_url = request.data.get("failure_url")
        data = request.data.copy()
        data["webinar_name"] = webinar.title
        data["name"] = request.data.get("name")
        data["email"] = request.data.get("email")
        data["phone"] = request.data.get("phone")

        if not amount or not success_url or not cancel_url:
            return Response({"success": False, "message": "Amount, success_url, and cancel_url are required"}, status=400)

        student_id = getattr(request.user, "student_id", None)
        student = Student.objects.filter(student_id=student_id).first()
        if not student:
            return Response({"success": False, "message": "Student not found"}, status=404)

        client, gateway = self._get_client()
        if not client:
            return Response({"success": False, "message": "Razorpay not configured"}, status=400)

        try:
            payment_link_data = {
                "amount": int(amount * 100),
                "currency": currency,
                "accept_partial": False,
                "description": webinar.title,
                "customer": {
                    "name": data.get("name"),
                    "email": data.get("email"),
                    "contact": data.get("phone")
                },
                # Attach metadata inside notes so Razorpay returns it on payment objects
                "notes": {
                    "webinar_name": webinar.title,
                    "webinar_id": str(getattr(webinar, "uuid", getattr(webinar, "id", ""))),
                    "name": data.get("name"),
                    "email": data.get("email"),
                    "phone": data.get("phone")
                },
                "notify": {"sms": True, "email": True},
                "reminder_enable": True,
                "callback_url": success_url,
                "callback_method": "get"
            }

            payment_link = client.payment_link.create(payment_link_data)

            # Save transaction as pending
            PaymentTransaction.objects.create(
                student=student,
                gateway=gateway,
                amount=amount,
                currency=currency,
                payment_status="pending",
                order_id=payment_link.get("id"),
                description=webinar.title,
                created_at=timezone.now()
            )

            return Response({
                "success": True,
                "payment_url": payment_link.get("short_url"),
                "order_id": payment_link.get("id")
            })

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=500)

    def get(self, request):
        try:
            status_filter = request.GET.get("status", "all")
            course_filter = request.GET.get("course", "all").strip().lower()
            search = request.GET.get("search", "").strip().lower()
            start_date = request.GET.get("start_date")
            end_date = request.GET.get("end_date")
            page = int(request.GET.get("page", 1))
            page_size = int(request.GET.get("page_size", 50))

            client = razorpay.Client(
                auth=(
                    "rzp_live_SKfiZYRJEe8WuU",
                    "Du4L7ebKchXQSOMcgzx5wE3h"
                )
            )

            params = {}

            if start_date:
                params["from"] = int(
                    datetime.strptime(start_date, "%Y-%m-%d").timestamp()
                )

            if end_date:
                params["to"] = int(
                    datetime.strptime(end_date, "%Y-%m-%d")
                    .replace(hour=23, minute=59, second=59)
                    .timestamp()
                )

            has_filter = search or (status_filter.lower() != "all") or (course_filter != "all")

            all_payments = []
            batch_size = 100
            skip = 0

            while True:
                result = client.payment.all({
                    **params,
                    "count": batch_size,
                    "skip": skip
                })

                if isinstance(result, dict):
                    batch = result.get("items", [])
                elif isinstance(result, list):
                    batch = result
                else:
                    batch = []

                if not batch:
                    break

                all_payments.extend(batch)

                if len(batch) < batch_size:
                    break

                skip += batch_size

            # ── 1. Fetch active courses directly from your Course model ──
            # Exclude archived/empty names and extract course_name
            db_courses = (
                Course.objects.filter(is_archived=False)
                .exclude(course_name__isnull=True)
                .exclude(course_name__exact="")
                .values_list('course_name', flat=True)
            )
            courses_set = set(db_courses)

            # ── 2. Match payment notes to Course IDs / Webinar IDs ──
            course_ids = set()
            for payment in all_payments:
                if isinstance(payment, dict):
                    notes = payment.get("notes") if isinstance(payment.get("notes"), dict) else {}
                    c_id = notes.get("course_id") or notes.get("webinar_id")
                    if c_id:
                        course_ids.add(c_id)

            # Map IDs to course names
            course_map = {}
            if course_ids:
                # Search by course_id in Course model
                matched_courses = Course.objects.filter(course_id__in=[c for c in course_ids if str(c).isdigit()])
                course_map.update({str(c.course_id): c.course_name for c in matched_courses})

                # Fallback check for Webinar model if applicable
                try:
                    webinars = Webinar.objects.filter(uuid__in=course_ids)
                    course_map.update({str(w.uuid): w.title for w in webinars})
                except Exception:
                    pass

            all_rows = []

            for payment in all_payments:
                if not isinstance(payment, dict):
                    continue

                notes = payment.get("notes", {})
                if not isinstance(notes, dict):
                    notes = {}

                # Priority order to resolve course name
                webinar_name = notes.get("course_name") or notes.get("webinar_name") or notes.get("title")
                
                if not webinar_name:
                    c_id = notes.get("course_id") or notes.get("webinar_id")
                    if c_id:
                        webinar_name = course_map.get(str(c_id))

                if not webinar_name:
                    webinar_name = payment.get("description")

                desc_str = str(webinar_name or "N/A").strip()

                # Add to set if valid title
                if desc_str and desc_str.upper() != "N/A" and not desc_str.startswith("#"):
                    courses_set.add(desc_str)

                row = {
                    "payment_id": payment.get("id"),
                    "customer": notes.get("name") or notes.get("customer_name") or "N/A",
                    "email": notes.get("email") or payment.get("email"),
                    "phone": notes.get("phone") or notes.get("contact") or payment.get("contact"),
                    "description": desc_str,
                    "amount": round(payment.get("amount", 0) / 100, 2),
                    "status": payment.get("status"),
                    "method": payment.get("method"),
                    "upi_id": payment.get("vpa"),
                    "razorpay_fee": round((payment.get("fee") or 0) / 100, 2),
                    "created_at": datetime.fromtimestamp(
                        payment.get("created_at", 0)
                    ).strftime("%d %b %Y %I:%M:%S %p"),
                }

                all_rows.append(row)

            # Sorted list of clean course names
            courses_list = sorted([c for c in courses_set if c and not str(c).startswith("#")])

            # ── 3. Apply Filters ──
            if has_filter:
                if course_filter != "all":
                    all_rows = [
                        r for r in all_rows
                        if r["description"].lower() == course_filter
                    ]

                if status_filter.lower() != "all":
                    all_rows = [
                        r for r in all_rows
                        if str(r["status"]).lower() == status_filter.lower()
                    ]

                if search:
                    filtered = []
                    for r in all_rows:
                        searchable = (
                            f"{r['payment_id']} "
                            f"{r['customer']} "
                            f"{r['email']} "
                            f"{r['phone']} "
                            f"{r['description']}"
                        ).lower()

                        try:
                            amount_match = float(search) == float(r["amount"])
                        except ValueError:
                            amount_match = False

                        if search in searchable or amount_match:
                            filtered.append(r)

                    all_rows = filtered

            total_records = len(all_rows)

            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_data = all_rows[start_index:end_index]
            
            for idx, row in enumerate(paginated_data, start=start_index + 1):
                row["sno"] = idx

            success_amount = sum(
                float(row.get("amount", 0))
                for row in all_rows
                if str(row.get("status", "")).lower() == "captured"
            )

            failed_amount = sum(
                float(row.get("amount", 0))
                for row in all_rows
                if str(row.get("status", "")).lower() == "failed"
            )

            refunded_amount = sum(
                float(row.get("amount", 0))
                for row in all_rows
                if str(row.get("status", "")).lower() == "refunded"
            )

            return Response({
                "success": True,
                "page": page,
                "page_size": page_size,
                "total_records": total_records,
                "success_amount": round(success_amount, 2),
                "failed_amount": round(failed_amount, 2),
                "refunded_amount": round(refunded_amount, 2),
                "courses": courses_list,
                "data": paginated_data
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {"success": False, "message": str(e)},
                status=500
            )
         
    # -------------------------
    # Verify Razorpay Payment
    # -------------------------
    @csrf_exempt
    @action(detail=False, methods=['post'], url_path="verify")
    def verify_payment(self, request):
        payment_id = request.data.get("razorpay_payment_id")
        order_id = request.data.get("razorpay_order_id")
        signature = request.data.get("razorpay_signature")

        if not payment_id or not order_id or not signature:
            return Response({"success": False, "message": "Required parameters missing"}, status=400)

        client, _ = self._get_client()
        if not client:
            return Response({"success": False, "message": "Razorpay not configured"}, status=400)

        # Verify signature
        try:
            params = {
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature
            }
            client.utility.verify_payment_signature(params)

            transaction = PaymentTransaction.objects.filter(order_id=order_id).first()
            if transaction:
                transaction.payment_status = "done"
                transaction.transaction_id = payment_id
                transaction.save()

                # Generate invoice
                InvoiceService.generate_invoice(
                    transaction.id
                )

            return Response({"success": True, "message": "Payment verified successfully"})
        except razorpay.errors.SignatureVerificationError:
            return Response({"success": False, "message": "Payment verification failed"}, status=200)

class RazorpaySettlementViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    required_module = "Transcation History"

    def list(self, request):
        try:
            count = request.query_params.get("count", 50)
            skip = request.query_params.get("skip", 0)

            response = requests.get(
                "https://api.razorpay.com/v1/settlements",
                params={
                    "count": count,
                    "skip": skip
                },
                auth=HTTPBasicAuth(
                   "rzp_live_SKfiZYRJEe8WuU",
                    "Du4L7ebKchXQSOMcgzx5wE3h"
                ),
                timeout=30
            )

            data = response.json()

            ist = ZoneInfo("Asia/Kolkata")

            for item in data.get("items", []):
                item["amount"] = float(
                    round(Decimal(item["amount"]) / Decimal("100"), 2)
                )

                item["created_at"] = datetime.fromtimestamp(
                    item["created_at"],
                    tz=ist
                ).strftime("%d %b %Y %I:%M:%S %p")

            return Response({
                "success": True,
                "status_code": response.status_code,
                "data": data
            })

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def balance(self, request):
        try:
            auth = HTTPBasicAuth(
                "rzp_live_SKfiZYRJEe8WuU",
                "Du4L7ebKchXQSOMcgzx5wE3h"
            )

            balance_response = requests.get(
                "https://api.razorpay.com/v1/balance",
                auth=auth
            )

            balance_data = balance_response.json()

            available_balance = balance_data.get("balance", 0) / 100

            settlement_response = requests.get(
                "https://api.razorpay.com/v1/settlements?count=100",
                auth=auth
            )

            settlement_data = settlement_response.json()

            today = datetime.now().date()
            yesterday = today - timedelta(days=1)

            today_settlement = 0
            yesterday_settlement = 0

            for settlement in settlement_data.get("items", []):
                settlement_date = datetime.fromtimestamp(
                    settlement["created_at"]
                ).date()

                amount = settlement.get("amount", 0)

                if settlement_date == today:
                    today_settlement += amount
                elif settlement_date == yesterday:
                    yesterday_settlement += amount

            return Response({
                "success": True,
                "data": {
                    "available_balance": round(available_balance, 2),
                    "today_settlement": round(today_settlement / 100, 2),
                    "yesterday_settlement": round(yesterday_settlement / 100, 2),
                }
            })

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)    
        
@api_view(['GET'])
def stripe_success(request):
    return Response({"success": True, "message": "Payment successful!"})

@api_view(['GET'])
def stripe_cancel(request):
    return Response({"success": False, "message": "Payment canceled!"})


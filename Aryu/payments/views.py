from payments.serializers import TutorPaymentReadSerializer
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
from rest_framework import generics
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
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

    def list(self, request):
        user = request.user
        user_type = getattr(user, "user_type", "")
        user_created_id = getattr(user, "trainer_id", None)

        # Allowed roles: super_admin and admin
        if user_type not in ["super_admin", "admin"]:
            return Response(
                {"success": False, "message": "Unauthorized"},
                status=status.HTTP_403_FORBIDDEN
            )

        if user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)

        # -------------------------------------------------------------
        # 1. Global Metadata Queries
        # -------------------------------------------------------------
        companies = list(
            Employer.objects.filter(is_archived=False).values("company_id", "company_name")
        )
        courses_list = list(
            Course.objects.filter(is_archived=False, status="Active").values("course_id", "course_name")
        )
        settings = Settings.objects.filter(is_archived=False).only(
            "stripe_enabled", "paypal_enabled", "razorpay_enabled"
        ).order_by("-created_at").first()

        # -------------------------------------------------------------
        # 2. Base Queryset Filtering
        # -------------------------------------------------------------
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

        # Prefetch transactions with invoices & gateways for ALL active students
        students_qs = all_students.distinct().prefetch_related(
            "new_batches__course",
            Prefetch(
                "transactions",
                queryset=PaymentTransaction.objects.filter(
                    is_archived=False
                ).select_related("course", "gateway").order_by("-created_at")
            )
        )

        students_response_data = []

        # -------------------------------------------------------------
        # 3. Process Student Transactions & Build Payment History
        # -------------------------------------------------------------
        for student in students_qs:
            employer = getattr(student, "employer", None)
            all_txs = list(student.transactions.all())

            student_payment_history = []
            course_map = defaultdict(list)

            for tx in all_txs:
                # Lazy-generate missing invoice if status is completed/done
                if not tx.invoice and str(tx.payment_status).lower() in ["success", "done", "paid", "complete"]:
                    try:
                        tx = InvoiceService.generate_invoice(tx.id)
                    except Exception as e:
                        logger.error(f"[Payment List] Lazy invoice generation failed for transaction {tx.id}: {str(e)}")

                invoice_url = None
                if tx.invoice and hasattr(tx.invoice, "url"):
                    invoice_url = request.build_absolute_uri(tx.invoice.url)

                payment_mode = tx.payment_mode or (tx.metadata.get("mode") if tx.metadata else "Cash")
                course_name = tx.course.course_name if tx.course else (tx.description or "General Payment")

                # Build full detailed payment log entry
                tx_history_entry = {
                    "transaction_id": tx.transaction_id,
                    "course_id": tx.course.course_id if tx.course else None,
                    "course_name": course_name,
                    "amount": float(tx.amount or 0),
                    "discount": float(getattr(tx, "discount", 0) or 0),
                    "payment_status": tx.payment_status,
                    "payment_mode": payment_mode,
                    "currency": tx.currency or "INR",
                    "gateway": tx.gateway.gatway_name if tx.gateway else None,
                    "invoice_no": tx.invoice_no,
                    "invoice_date": tx.invoice_date,
                    "invoice_url": invoice_url,
                    "created_at": tx.created_at,
                }

                student_payment_history.append(tx_history_entry)

                if tx.course:
                    course_map[tx.course].append(tx_history_entry)

            # Include batch courses with zero transactions if present
            for batch in student.new_batches.all():
                if batch.course and batch.course not in course_map:
                    course_map[batch.course] = []

            courses_summary = []
            for course_obj, tx_logs in course_map.items():
                txs_sorted = sorted(tx_logs, key=lambda x: x["created_at"], reverse=True)

                paid_amount = sum(
                    tx_log["amount"]
                    for tx_log in txs_sorted
                    if tx_log["payment_status"] and str(tx_log["payment_status"]).lower() in [
                        "success", "done", "paid", "partial", "advanced", "complete", "captured"
                    ]
                )

                course_fee = float(getattr(course_obj, "fee", 0) or 0)
                discount = float(getattr(student, "discount", 0) or 0)
                total_after_discount = max(course_fee - discount, 0.0)
                due_amount = max(total_after_discount - paid_amount, 0.0)

                courses_summary.append({
                    "course_id": course_obj.course_id,
                    "course_name": course_obj.course_name,
                    "course_fee": course_fee,
                    "discount": discount,
                    "total_after_discount": total_after_discount,
                    "paid_amount": paid_amount,
                    "due_amount": due_amount,
                    "transactions": txs_sorted
                })

            students_response_data.append({
                "student_id": student.student_id,
                "registration_id": student.registration_id,
                "student_name": f"{student.first_name} {getattr(student, 'last_name', '') or ''}".strip(),
                "email": student.email,
                "phone": student.contact_no,
                "company_id": getattr(employer, "company_id", None) if employer else None,
                "company_name": getattr(employer, "company_name", None) if employer else None,
                "payment_history": student_payment_history,
                "courses": courses_summary,
            })

        # Sort queryset by most recent payment
        students_qs = students_qs.annotate(
            last_payment=Max("transactions__created_at")
        ).order_by("-last_payment")

        serializer = StudentPaymentSummarySerializer(students_qs, many=True, context={"request": request})

        enabled_gateways = []
        if settings:
            if settings.stripe_enabled:
                enabled_gateways.append("Stripe test")
            if settings.paypal_enabled:
                enabled_gateways.append("paypal")
            if settings.razorpay_enabled:
                enabled_gateways.append("razorpay")

        return Response({
            "success": True,
            "student_payment_summaries": serializer.data,
            "students": students_response_data,
            "students_count": len(students_response_data),
            "companies": companies,
            "courses_list": courses_list,
            "enabled_gateways": enabled_gateways,
            "meta": {
                "total_students": len(students_response_data),
                "students_with_transactions": len(students_response_data),
                "user_type": user_type
            }
        }, status=status.HTTP_200_OK)

    def create(self, request):
        user = request.user
        if getattr(user, "user_type", "") != "super_admin":
            return Response({"success": False, "message": "Unauthorized"}, status=403)

        serializer = PaymentTransactionCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        transaction = serializer.save()

        return Response({
            "success": True,
            "message": "Payment transaction created successfully",
            "data": PaymentTransactionDetailSerializer(
                transaction, context={"request": request}
            ).data
        })

    def retrieve(self, request, pk=None):
        user = request.user
        if getattr(user, "user_type", "") != "super_admin":
            return Response({"success": False, "message": "Unauthorized"}, status=403)

        student = Student.objects.filter(student_id=pk, is_archived=False).prefetch_related(
            Prefetch(
                "transactions",
                queryset=PaymentTransaction.objects.select_related("course", "gateway")
            ),
            Prefetch(
                "emi_plans",
                queryset=PaymentEMI.objects.prefetch_related("installments")
            ),
            Prefetch(
                "new_batches",
                queryset=NewBatch.objects.select_related("course")
            )
        ).first()

        if not student:
            return Response({"success": False, "message": "Student not found"}, status=status.HTTP_404_NOT_FOUND)

        courses_list = []
        seen_course_ids = set()

        for batch in student.new_batches.all():
            course = batch.course
            if course.course_id in seen_course_ids:
                continue
            seen_course_ids.add(course.course_id)

            txs = [
                tx for tx in student.transactions.all()
                if tx.course_id == course.course_id and not tx.is_archived
            ]

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
            "gatway": gateway_list
        })

    def update(self, request, pk=None):
        user = request.user
        if getattr(user, "user_type", "") != "super_admin":
            return Response({"success": False, "message": "Unauthorized"}, status=403)

        transaction = PaymentTransaction.objects.filter(pk=pk, is_archived=False).first()
        if not transaction:
            return Response({"success": False, "message": "Transaction not found"}, status=200)

        if "amount" in request.data:
            student = transaction.student
            course = transaction.course

            if student and course:
                final_fee = Decimal(str(course.fee or 0))

                if hasattr(student, "course_fee") and student.course_fee:
                    try:
                        new_amount = Decimal(str(request.data["amount"]))
                    except (InvalidOperation, KeyError, TypeError):
                        return Response({"success": False, "message": "Invalid payment amount."}, status=400)

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
                    return Response({
                        "success": False,
                        "message": (
                            f"Payment exceeds the remaining course fee. "
                            f"Course Fee: ₹{final_fee}, "
                            f"Already Paid: ₹{already_paid}, "
                            f"Remaining Balance: ₹{remaining}."
                        )
                    }, status=200)

        serializer = PaymentTransactionUpdateSerializer(
            transaction,
            data=request.data,
            partial=True,
            context={"request": request}
        )

        if not serializer.is_valid():
            first_error = next(iter(serializer.errors.values()))[0]
            return Response({   
                "success": False,
                "message": str(first_error),
                "errors": serializer.errors,
            }, status=200)

        serializer.save()
        return Response({
            "success": True,
            "message": "Transaction updated successfully",
            "data": serializer.data
        })

    def destroy(self, request, pk=None):
        user = request.user
        if getattr(user, "user_type", "") != "super_admin":
            return Response({"success": False, "message": "Unauthorized"}, status=403)
        
        try:
            transaction = PaymentTransaction.objects.get(pk=pk)
            transaction.is_archived = True
            transaction.save()
            return Response({"success": True, "message": "Transaction deleted successfully"})
        except PaymentTransaction.DoesNotExist:
            return Response({"success": False, "message": "Transaction not found"}, status=200)

    def student_payment_history(self, request, student_id=None):
        user = request.user
        if user.user_type not in ["student", "super_admin"]:
            return Response({"success": False, "message": "Unauthorized access"}, status=status.HTTP_403_FORBIDDEN)

        if user.user_type == "student" and str(student_id) != str(user.student_id):
            return Response({"success": False, "message": "Unauthorized access to student record"}, status=status.HTTP_403_FORBIDDEN)

        student = Student.objects.filter(student_id=student_id).first()
        if not student:
            return Response({"success": False, "message": "Student not found"}, status=status.HTTP_404_NOT_FOUND)

        transactions = (
            PaymentTransaction.objects
            .filter(student=student, is_archived=False)
            .select_related("course", "gateway")
            .order_by("-created_at")
        )

        serializer = StudentPaymentSummarySerializer(student, context={"request": request})

        payment_logs = []
        for tx in transactions:
            if not tx.invoice and str(tx.payment_status).lower() in ["success", "done", "paid", "complete"]:
                try:
                    tx = InvoiceService.generate_invoice(tx.id)
                except Exception as e:
                    logger.error(f"Lazy invoice generation failed for transaction {tx.id}: {str(e)}")

            invoice_url = None
            if tx.invoice and hasattr(tx.invoice, "url"):
                invoice_url = request.build_absolute_uri(tx.invoice.url)

            payment_logs.append({
                "course_name": tx.course.course_name if tx.course else (tx.description or "N/A"),
                "student_payment_summaries": serializer.data,
                "invoice_date": tx.invoice_date,
                "transaction_id": tx.transaction_id,
                "amount": float(tx.amount or 0),
                "payment_status": tx.payment_status,
                "payment_mode": tx.payment_mode or (tx.metadata.get("mode") if tx.metadata else "Cash"),
                "discount": float(tx.discount or 0),
                "currency": tx.currency,
                "gateway": tx.gateway.gatway_name if tx.gateway else None,
                "invoice_no": tx.invoice_no,
                "invoice_url": invoice_url,
                "created_at": tx.created_at,
            })

        return Response({
            "success": True,
            "count": len(payment_logs),
            "payment_logs": payment_logs,
        })

    @action(detail=True, methods=['delete'], url_path='delete-student')
    def delete_student(self, request, pk=None):
        user = request.user
        if getattr(user, "user_type", "") != "super_admin":
            return Response({"success": False, "message": "Unauthorized"}, status=403)
        
        try:
            student = Student.objects.get(student_id=pk)
            PaymentTransaction.objects.filter(student_id=pk, is_archived=False).update(is_archived=True)
            return Response({"success": True, "message": "Student and all transactions deleted"})
        except Student.DoesNotExist:
            return Response({"success": False, "message": "Student not found"}, status=404)

    @action(detail=False, methods=["post"])
    def generate_invoice(self, request):
        user = request.user
        if getattr(user, "user_type", "") != "super_admin":
            return Response({"success": False, "message": "Unauthorized"}, status=403)

        serializer = GenerateInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        transaction = serializer.transaction
        regenerate = serializer.validated_data.get("regenerate", False)

        try:
            transaction = InvoiceService.generate_invoice(transaction.id, regenerate=regenerate)
            invoice_url = None
            if transaction.invoice and hasattr(transaction.invoice, "url"):
                invoice_url = request.build_absolute_uri(transaction.invoice.url)

            return Response({
                "success": True,
                "message": "Invoice generated successfully",
                "data": {
                    "transaction_id": transaction.id,
                    "invoice_no": transaction.invoice_no,
                    "invoice_url": invoice_url,
                    "invoice_date": transaction.invoice_date,
                }
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def send_invoice_email(self, request):
        user = request.user
        if getattr(user, "user_type", "") != "super_admin":
            return Response({"success": False, "message": "Unauthorized"}, status=403)

        transaction_id = request.data.get("transaction_id")
        if not transaction_id:
            return Response({"success": False, "message": "transaction_id is required"}, status=400)

        transaction = (
            PaymentTransaction.objects
            .select_related("student", "employer", "course")
            .filter(id=transaction_id, is_archived=False)
            .first()
        )

        if not transaction:
            return Response({"success": False, "message": "Transaction not found"}, status=200)

        if not transaction.invoice:
            return Response({"success": False, "message": "Invoice not generated"}, status=400)

        recipient_email = None
        customer_name = None

        if transaction.billing_type == "student" and transaction.student:
            recipient_email = transaction.student.email
            customer_name = transaction.student.first_name
        elif transaction.billing_type == "company" and transaction.employer:
            recipient_email = transaction.employer.email
            customer_name = transaction.employer.company_name

        if not recipient_email:
            return Response({"success": False, "message": "Recipient email not found"}, status=400)

        subject = f"Aryu Academy Pvt Ltd - Invoice - {transaction.invoice_no}"
        body = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Invoice Email</title>
</head>
<body style="margin:0;padding:0;background-color:#eef1f7;font-family:Arial, Helvetica, sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#eef1f7;padding:30px 15px;">
<tr>
<td align="center">
<table width="650" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:650px;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb;">
    <tr>
        <td align="center"
            style="
                background:linear-gradient(135deg,#200A38,#430080);
                padding:35px 25px;
            ">

            <!-- LOGO -->
            <img
                src="https://aylms.aryuprojects.com/api/media/logos/email_logo.png"
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
    <tr>
        <td style="padding:40px 35px;">
            <p style="margin:0 0 18px 0;color:#111827;font-size:16px;line-height:28px;">Dear <strong>{customer_name}</strong>,</p>
            <p style="margin:0 0 25px 0;color:#4b5563;font-size:15px;line-height:28px;">Thank you for choosing <strong style="color:#430080;">Aryu Academy</strong>. Your payment has been successfully received. Please find your invoice attached with this email for your reference and records.</p>
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#faf7ff;border:1px solid #e9d8fd;border-radius:12px;margin-bottom:30px;">
                <tr>
                    <td style="padding:28px;">
                        <table width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                                <td style="padding-bottom:16px;color:#6b7280;font-size:14px;width:42%;">Invoice Number</td>
                                <td style="padding-bottom:16px;color:#111827;font-size:15px;font-weight:700;">{transaction.invoice_no}</td>
                            </tr>
                            <tr>
                                <td style="padding-bottom:16px;color:#6b7280;font-size:14px;">Course</td>
                                <td style="padding-bottom:16px;color:#111827;font-size:15px;font-weight:600;">{transaction.course.course_name if transaction.course else '-'}</td>
                            </tr>
                            <tr>
                                <td style="padding-bottom:16px;color:#6b7280;font-size:14px;">Billing Type</td>
                                <td style="padding-bottom:16px;color:#111827;font-size:15px;font-weight:600;text-transform:capitalize;">{transaction.billing_type}</td>
                            </tr>
                            <tr>
                                <td style="color:#6b7280;font-size:14px;">Payment Amount</td>
                                <td style="color:#430080;font-size:22px;font-weight:700;">₹{transaction.amount}</td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
            <p style="margin:0 0 25px 0;color:#4b5563;font-size:14px;line-height:26px;">If you have any questions regarding this payment or invoice, feel free to contact our support team.</p>
            <table cellpadding="0" cellspacing="0" border="0" style="margin:30px 0;">
                <tr>
                    <td align="center" style="border-radius:8px;background:#430080;">
                        <a href="https://aryuacademy.com/" target="_blank" style="display:inline-block;padding:14px 28px;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;">Visit Our Website</a>
                    </td>
                </tr>
            </table>
            <hr style="border:none;border-top:1px solid #e5e7eb;margin:35px 0 25px 0;">
            <p style="margin:0 0 15px 0;color:#6b7280;font-size:13px;line-height:24px;">This email and its attachments are confidential and intended solely for the recipient.</p>
            <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                    <td align="center">
                        <a href="https://aryuacademy.com/" style="color:#430080;text-decoration:none;font-size:13px;margin:0 8px;font-weight:600;">Website</a>
                        <span style="color:#c4b5fd;">|</span>
                        <a href="https://www.instagram.com/aryuacademyofficial/" style="color:#430080;text-decoration:none;font-size:13px;margin:0 8px;font-weight:600;">Instagram</a>
                        <span style="color:#c4b5fd;">|</span>
                        <a href="https://www.facebook.com/aryuacademyofficial/" style="color:#430080;text-decoration:none;font-size:13px;margin:0 8px;font-weight:600;">Facebook</a>
                        <span style="color:#c4b5fd;">|</span>
                        <a href="https://www.linkedin.com/company/aryuacademyofficial" style="color:#430080;text-decoration:none;font-size:13px;margin:0 8px;font-weight:600;">LinkedIn</a>
                    </td>
                </tr>
            </table>
            <p style="margin:25px 0 0 0;text-align:center;color:#9ca3af;font-size:12px;line-height:22px;">© 2026 Aryu Academy. All rights reserved.</p>
        </td>
    </tr>
</table>
</td>
</tr>
</table>
</body>
</html>
"""

        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email]
        )
        email.content_subtype = "html"
        email.attach_file(transaction.invoice.path)
        logger.warning(f"EMAIL TRIGGERED FOR: {recipient_email}")
        email.send(fail_silently=False)

        return Response({
            "success": True,
            "message": "Invoice email sent successfully",
            "data": {
                "invoice_no": transaction.invoice_no,
                "sent_to": recipient_email
            }
        }, status=200)


        
class TutorPaymentViewSet(viewsets.ModelViewSet):
    queryset = TutorPayment.objects.all().select_related('tutor', 'course', 'batch')

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return TutorPaymentReadSerializer
        return TutorPaymentWriteSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        trainer_id = request.query_params.get('trainer_id') or request.query_params.get('tutor_id')
        from_date = request.query_params.get('from_date')
        to_date = request.query_params.get('to_date')
        course_id = request.query_params.get('course')
        batch_id = request.query_params.get('batch')
        payment_status = request.query_params.get('payment_status')
        search_query = request.query_params.get('search')

        # Filters
        if trainer_id:
            queryset = queryset.filter(tutor_id=trainer_id)

        if from_date:
            queryset = queryset.filter(payment_date__gte=from_date)
        if to_date:
            queryset = queryset.filter(payment_date__lte=to_date)

        if course_id:
            queryset = queryset.filter(course_id=course_id)
        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)
        if payment_status and payment_status.lower() != 'all':
            queryset = queryset.filter(payment_status__iexact=payment_status)

        if search_query:
            queryset = queryset.filter(
                Q(course__course_name__icontains=search_query) |
                Q(batch__title__icontains=search_query) |
                Q(notes__icontains=search_query) |
                Q(payment_type__icontains=search_query)
            )

        queryset = queryset.order_by('-payment_date', '-created_at')

        # Trainer Header Details
        trainer_details = None
        if trainer_id:
            try:
                trainer_obj = Trainer.objects.get(trainer_id=trainer_id)
                trainer_details = TrainerHeaderSerializer(trainer_obj).data
            except Trainer.DoesNotExist:
                trainer_details = None

        # Fetch Active Courses
        active_courses = Course.objects.filter(is_archived=False).exclude(status__iexact='inactive')
        courses_data = CourseOptionSerializer(active_courses, many=True).data

        # --- NEW: Build Course-Grouped Batches ---
        # Prefetch active batches to prevent N+1 query overhead
        active_courses_with_batches = active_courses.prefetch_related(
            Prefetch(
                'batches',  # Related name from Course to NewBatch (adjust if different e.g., 'newbatch_set')
                queryset=NewBatch.objects.filter(status=True, is_archived=False),
                to_attr='active_batches_list'
            )
        )

        batches_by_course = [
            {
                "course_id": course.course_id,  # Changed from course.id to course.course_id
                "course_name": course.course_name,
                "batches": [
                    {
                        "batch_id": getattr(batch, 'batch_id', getattr(batch, 'id', None)),
                        "title": batch.title
                    }
                    for batch in getattr(course, 'active_batches_list', [])
                ]
            }
            for course in active_courses_with_batches
        ]

        # Paginated Response
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['trainer_details'] = trainer_details
            response.data['active_courses'] = courses_data
            response.data['all_batches'] = batches_by_course
            return response

        # Non-paginated Response
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'trainer_details': trainer_details,
            'active_courses': courses_data,
            'all_batches': batches_by_course,
            'results': serializer.data
        }, status=status.HTTP_200_OK)
        

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
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_client(self):
        gateway = PaymentGateway.objects.filter(gatway_name__icontains="razorpay_test").first()
        if not gateway:
            return None, None
        client = razorpay.Client(auth=(gateway.public_key, gateway.secret_key))
        return client, gateway

    # ---------------------------------------------------------
    # Helper: Fetch, Map & Filter Payments (Shared Logic)
    # ---------------------------------------------------------
    def _get_filtered_payments_data(self, request):
        status_filter = request.GET.get("status", "all")
        course_filter = request.GET.get("course", "all").strip().lower()
        search = request.GET.get("search", "").strip().lower()
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        client = razorpay.Client(
            auth=(
                "rzp_live_SKfiZYRJEe8WuU",
                "Du4L7ebKchXQSOMcgzx5wE3h"
            )
        )

        params = {}
        if start_date:
            params["from"] = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
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

        # 1. Fetch active courses directly from Course model
        db_courses = (
            Course.objects.filter(is_archived=False)
            .exclude(course_name__isnull=True)
            .exclude(course_name__exact="")
            .values_list('course_name', flat=True)
        )
        courses_set = set(db_courses)

        # 2. Match payment notes to Course IDs / Webinar IDs
        course_ids = set()
        for payment in all_payments:
            if isinstance(payment, dict):
                notes = payment.get("notes") if isinstance(payment.get("notes"), dict) else {}
                c_id = notes.get("course_id") or notes.get("webinar_id")
                if c_id:
                    course_ids.add(c_id)

        course_map = {}
        if course_ids:
            matched_courses = Course.objects.filter(course_id__in=[c for c in course_ids if str(c).isdigit()])
            course_map.update({str(c.course_id): c.course_name for c in matched_courses})

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

            webinar_name = notes.get("course_name") or notes.get("webinar_name") or notes.get("title")
            
            if not webinar_name:
                c_id = notes.get("course_id") or notes.get("webinar_id")
                if c_id:
                    webinar_name = course_map.get(str(c_id))

            if not webinar_name:
                webinar_name = payment.get("description")

            desc_str = str(webinar_name or "N/A").strip()

            if desc_str and desc_str.upper() != "N/A" and not desc_str.startswith("#"):
                courses_set.add(desc_str)

            row = {
                "payment_id": payment.get("id"),
                "customer": notes.get("name") or notes.get("customer_name") or "N/A",
                "email": notes.get("email") or payment.get("email") or "N/A",
                "phone": notes.get("phone") or notes.get("contact") or payment.get("contact") or "N/A",
                "description": desc_str,
                "amount": round(payment.get("amount", 0) / 100, 2),
                "status": payment.get("status"),
                "method": payment.get("method"),
                "upi_id": payment.get("vpa") or "N/A",
                "razorpay_fee": round((payment.get("fee") or 0) / 100, 2),
                "created_at": datetime.fromtimestamp(
                    payment.get("created_at", 0)
                ).strftime("%d %b %Y %I:%M:%S %p"),
            }
            all_rows.append(row)

        courses_list = sorted([c for c in courses_set if c and not str(c).startswith("#")])

        # 3. Apply Filters
        if has_filter:
            if course_filter != "all":
                all_rows = [r for r in all_rows if r["description"].lower() == course_filter]

            if status_filter.lower() != "all":
                all_rows = [r for r in all_rows if str(r["status"]).lower() == status_filter.lower()]

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

        # Add S.No
        for idx, row in enumerate(all_rows, start=1):
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

        return {
            "all_rows": all_rows,
            "courses_list": courses_list,
            "success_amount": success_amount,
            "failed_amount": failed_amount,
            "refunded_amount": refunded_amount
        }

    # -------------------------
    # Get Payments List API
    # -------------------------
    def get(self, request):
        try:
            page = int(request.GET.get("page", 1))
            page_size = int(request.GET.get("page_size", 50))

            data_dict = self._get_filtered_payments_data(request)
            all_rows = data_dict["all_rows"]
            total_records = len(all_rows)

            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_data = all_rows[start_index:end_index]

            return Response({
                "success": True,
                "page": page,
                "page_size": page_size,
                "total_records": total_records,
                "success_amount": round(data_dict["success_amount"], 2),
                "failed_amount": round(data_dict["failed_amount"], 2),
                "refunded_amount": round(data_dict["refunded_amount"], 2),
                "courses": data_dict["courses_list"],
                "data": paginated_data
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({"success": False, "message": str(e)}, status=500)

    # ---------------------------------------------------------
    # Export PDF Action Endpoint
    # GET /api/razorpay-payments/export-pdf/
    # ---------------------------------------------------------
    @action(detail=False, methods=['get'], url_path="export-pdf")
    def export_pdf(self, request):
        try:
            data_dict = self._get_filtered_payments_data(request)
            all_rows = data_dict["all_rows"]

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=landscape(A4),
                rightMargin=20,
                leftMargin=20,
                topMargin=20,
                bottomMargin=20
            )

            elements = []
            styles = getSampleStyleSheet()

            # Dynamic Styles
            title_style = ParagraphStyle(
                'ReportTitle',
                parent=styles['Heading1'],
                fontSize=18,
                leading=22,
                textColor=colors.HexColor("#1E293B"),
                spaceAfter=10
            )

            cell_style = ParagraphStyle(
                'CellText',
                parent=styles['Normal'],
                fontSize=8,
                leading=10,
                textColor=colors.HexColor("#334155")
            )

            header_style = ParagraphStyle(
                'HeaderText',
                parent=styles['Normal'],
                fontSize=9,
                leading=11,
                fontName="Helvetica-Bold",
                textColor=colors.white
            )

            # Title
            elements.append(Paragraph("Razorpay Payment Transactions Report", title_style))
            elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%d %b %Y %I:%M %p')}", cell_style))
            elements.append(Spacer(1, 12))

            # Summary Table
            summary_data = [
                [
                    Paragraph("<b>Total Transactions</b>", cell_style),
                    Paragraph("<b>Captured Amount</b>", cell_style),
                    Paragraph("<b>Failed Amount</b>", cell_style),
                    Paragraph("<b>Refunded Amount</b>", cell_style),
                ],
                [
                    Paragraph(str(len(all_rows)), cell_style),
                    Paragraph(f"₹ {data_dict['success_amount']:,.2f}", cell_style),
                    Paragraph(f"₹ {data_dict['failed_amount']:,.2f}", cell_style),
                    Paragraph(f"₹ {data_dict['refunded_amount']:,.2f}", cell_style),
                ]
            ]
            summary_table = Table(summary_data, colWidths=[180, 180, 180, 180])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(summary_table)
            elements.append(Spacer(1, 15))

            # Main Data Table Header
            table_data = [[
                Paragraph("S.No", header_style),
                Paragraph("Payment ID", header_style),
                Paragraph("Customer", header_style),
                Paragraph("Email / Phone", header_style),
                Paragraph("Course / Webinar", header_style),
                Paragraph("Amount", header_style),
                Paragraph("Method", header_style),
                Paragraph("Status", header_style),
                Paragraph("Date", header_style),
            ]]

            # Rows
            for r in all_rows:
                table_data.append([
                    Paragraph(str(r["sno"]), cell_style),
                    Paragraph(str(r["payment_id"]), cell_style),
                    Paragraph(str(r["customer"]), cell_style),
                    Paragraph(f"{r['email']}<br/>{r['phone']}", cell_style),
                    Paragraph(str(r["description"]), cell_style),
                    Paragraph(f"₹ {r['amount']:,.2f}", cell_style),
                    Paragraph(str(r["method"]).upper(), cell_style),
                    Paragraph(str(r["status"]).capitalize(), cell_style),
                    Paragraph(str(r["created_at"]), cell_style),
                ])

            # Column Widths total = 802pt (Fits Landscape A4 printable width)
            col_widths = [35, 110, 95, 120, 130, 65, 55, 60, 132]
            
            data_table = Table(table_data, colWidths=col_widths, repeatRows=1)
            data_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ]))

            elements.append(data_table)

            doc.build(elements)
            buffer.seek(0)

            response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="Razorpay_Payments_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
            return response

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({"success": False, "message": str(e)}, status=500)

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

                InvoiceService.generate_invoice(transaction.id)

            return Response({"success": True, "message": "Payment verified successfully"})
        except razorpay.errors.SignatureVerificationError:
            return Response({"success": False, "message": "Payment verification failed"}, status=200)

class RazorpaySettlementViewSet(viewsets.ViewSet):

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


class PaymentStudentDropdownView(generics.ListAPIView):
    """
    Dropdown API for Payment Report Student Search.
    Queries and returns ALL active, non-archived students from the primary Student model table.
    """
    serializer_class = StudentMinimalSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        return Student.objects.filter(status=True, is_archived=False).order_by('first_name')


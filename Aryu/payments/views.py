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
from aryuapp.utils import *
from aryuapp.mixins import *
from aryuapp.models import Settings, Employer
from aryuapp.views import flatten_errors
from collections import defaultdict

import json
import logging

logger = logging.getLogger(__name__)

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
        queryset = self.get_queryset()
        serializer = PaymentGatewaySerializer(queryset, many=True)
        return Response({"success": True, "data": serializer.data})

    def create(self, request):
        serializer = PaymentGatewaySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "message": "Payment gateway created successfully.", "data": serializer.data}, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
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

        if user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)

        # ================================================================
        # STEP 1: Base queryset
        # ================================================================
        students_qs = Student.objects.filter(is_archived=False)

        

        # ================================================================
        # STEP 2: Hierarchy filter
        # ================================================================
        if user_type == "admin" and user_created_id:
            students_qs = students_qs.filter(created_by=user_created_id)

        elif user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

            students_qs = students_qs.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )

        students_qs = students_qs.filter(transactions__is_archived=False).distinct()

        # ================================================================
        # STEP 3: Prefetch (IMPORTANT)
        # ================================================================
        students_qs = students_qs.prefetch_related(
            "new_batches__course",  # for courses
            Prefetch(
                "transactions",
                queryset=PaymentTransaction.objects.filter(is_archived=False)
                .select_related("course", "gateway")
                .order_by("-created_at")
            )
        )

        # ================================================================
        # STEP 4: Build response properly
        # ================================================================
        student_list = []
        students = Student.objects.filter(is_archived=False)

        

        # ================================================================
        # STEP 2: Hierarchy filter
        # ================================================================
        if user_type == "admin" and user_created_id:
            students = students.filter(created_by=user_created_id)

        elif user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

            students = students.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )

        

        for student in students:
            try:
                
                courses_data = []

                # Get student courses via batches
                batches = student.new_batches.all()

                for batch in batches:
                    course = batch.course

                    # Get transactions for this course
                    txs = [
                        tx for tx in student.transactions.all()
                        if tx.course_id == course.course_id
                    ]

                    total_paid = sum(
                        float(tx.amount)
                        for tx in txs
                        if tx.payment_status and tx.payment_status.lower() == "success"
                    )

                    course_fee = float(course.fee) if course and course.fee else 0
                    discount = float(getattr(student, "discount", 0))
                    final_fee = course_fee - discount
                    balance = final_fee - total_paid

                    courses_data.append({
                        "course_id": course.course_id,
                        "course_name": course.course_name,
                        "course_fee": course_fee,
                        "discount": discount,
                        "final_fee": final_fee,
                        "paid_amount": total_paid,
                        "balance": balance,
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

                companies = list(
                    Employer.objects.filter(
                        is_archived=False
                    ).values(
                        "company_id",
                        "company_name"
                    )
                )

                courses_list = list(
                    Course.objects.filter(
                        is_archived=False,
                        status="Active"
                    ).values(
                        "course_id",
                        "course_name"
                    )
                )

                # ✅ FINAL STUDENT OBJECT
                student_list.append({
                    "student_id": student.student_id,
                    "registration_id": student.registration_id,
                    "student_name": f"{student.first_name}".strip(),
                    "email": student.email,
                    "phone": student.contact_no,
                    "courses": courses_data,  # ✅ correct structure
                    "company_id": (
                        getattr(student.employer, "company_id", None)
                        if hasattr(student, "employer")
                        else None
                    ),

                    "company_name": (
                        getattr(student.employer, "company_name", None)
                        if hasattr(student, "employer")
                        else None
                    ),
                })

               

            except Exception as e:
                print(f"Error processing student {student.student_id}: {e}")

        # ================================================================
        # STEP 5: Serializer (optional)
        # ================================================================
        serializer = StudentPaymentSummarySerializer(students_qs, many=True)

        # ================================================================
        # STEP 6: Gateways
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

        # ================================================================
        # FINAL RESPONSE
        # ================================================================
        return Response({
            "success": True,
            "student_payment_summaries": serializer.data,
            "students_count": len(student_list),
            "students": student_list,
            "companies": companies,
            "courses_list": courses_list,
            "enabled_gateways": enabled_gateways,
            "meta": {
                "total_students": len(student_list),
                "user_type": user_type
            }
        })

    def retrieve(self, request, pk=None):
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
                        "payment_mode": tx.metadata.get("mode") if tx.metadata else None, 
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
    

    def create(self, request):

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
    

    def update(self, request, pk=None):

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
                status=404
            )

        serializer = PaymentTransactionUpdateSerializer(
            transaction,
            data=request.data,
            partial=True,
            context={"request": request}
        )

        if not serializer.is_valid():

            return Response(
                {
                    "success": False,
                    "errors": serializer.errors
                },
                status=400
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
            }, status=404)


    # 2. Delete FULL student + all transactions
    @action(detail=True, methods=['delete'], url_path='delete-student')
    def delete_student(self, request, pk=None):
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
                status=404
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
    def create(self, request):
        amount = float(request.data.get("amount", 0))
        currency = request.data.get("currency", "INR")
        success_url = request.data.get("success_url")
        cancel_url = request.data.get("failure_url")

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
                "amount": int(amount * 100),  # in paise
                "currency": currency,
                "accept_partial": False,
                "description": f"Payment by {student.student_id}",
                "customer": {
                    "name": student.first_name ,
                    "email": student.email,
                    "contact": student.contact_no
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
                gateway=gateway,  # link your PaymentGateway if needed
                amount=amount,
                currency=currency,
                payment_status="pending",
                order_id=payment_link.get("id"),
                description="Payment via Razorpay Link",
                created_at=timezone.now()
            )

            return Response({
                "success": True,
                "payment_url": payment_link.get("short_url"),  # direct payment link
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

@api_view(['GET'])
def stripe_success(request):
    return Response({"success": True, "message": "Payment successful!"})

@api_view(['GET'])
def stripe_cancel(request):
    return Response({"success": False, "message": "Payment canceled!"})


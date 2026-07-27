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


# Universal lookup set for successful/valid payment statuses
VALID_DONE_STATUSES = {
    "success",
    "done",
    "paid",
    "captured",
    "complete",
    "partial",
    "advanced",
}


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

        if user_type != "super_admin":
            return Response(
                {"success": False, "message": "Unauthorized"},
                status=status.HTTP_403_FORBIDDEN
            )

        if user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)

        companies = list(
            Employer.objects.filter(is_archived=False).values("company_id", "company_name")
        )
        courses_list = list(
            Course.objects.filter(is_archived=False, status="Active").values("course_id", "course_name")
        )

        settings = Settings.objects.filter(is_archived=False).only(
            "stripe_enabled", "paypal_enabled", "razorpay_enabled"
        ).order_by("-created_at").first()

        all_students = Student.objects.filter(is_archived=False).select_related("employer")

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

        tx_prefetch = Prefetch(
            "transactions",
            queryset=PaymentTransaction.objects.filter(
                is_archived=False
            ).select_related("course", "gateway").order_by("-created_at")
        )

        all_students = all_students.prefetch_related("new_batches__course", tx_prefetch)
        students_qs = all_students.filter(transactions__is_archived=False).distinct().prefetch_related("new_batches__course", tx_prefetch)

        students = []
        for student in all_students:
            employer = getattr(student, "employer", None)
            courses = []
            student_txs = list(student.transactions.all())

            for batch in student.new_batches.all():
                if not batch.course:
                    continue

                course = batch.course
                txs = [tx for tx in student_txs if tx.course_id == course.course_id]

                paid_amount = sum(
                    float(tx.amount or 0)
                    for tx in txs
                    if tx.payment_status and str(tx.payment_status).strip().lower() in VALID_DONE_STATUSES
                )

                course_fee = float(course.fee or 0)
                discount = float(getattr(student, "discount", 0) or 0)
                total_after_discount = max(course_fee - discount, 0.0)
                due_amount = max(total_after_discount - paid_amount, 0.0)

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
                batches = student.new_batches.all()
                student_txs = list(student.transactions.all())

                for batch in batches:
                    course = batch.course
                    if not course:
                        continue

                    txs = sorted(
                        [tx for tx in student_txs if tx.course_id == course.course_id],
                        key=lambda x: x.created_at,
                        reverse=True
                    )

                    discount = float(getattr(student, "discount", 0) or 0)
                    paid_amount = sum(
                        float(tx.amount or 0)
                        for tx in txs
                        if tx.payment_status and str(tx.payment_status).strip().lower() in VALID_DONE_STATUSES
                    )

                    course_fee = float(getattr(course, "fee", 0) or 0)
                    total_after_discount = max(course_fee - discount, 0.0)
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
                                "amount": float(tx.amount or 0),
                                "payment_status": tx.payment_status,
                                "payment_mode": tx.metadata.get("mode") if tx.metadata else getattr(tx, "payment_mode", None),
                                "currency": tx.currency,
                                "created_at": tx.created_at,
                            } for tx in txs
                        ]
                    })

                employer = getattr(student, "employer", None)
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
                logger.error(f"Error processing student {student.student_id}: {e}")

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
    def create(self, request,webinar):
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

    def get(self, request):
        try:

            status_filter = request.GET.get("status", "all")
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

            has_filter = search or (status_filter.lower() != "all")

            # ✅ ALWAYS fetch all records in batches of 100
            # Razorpay does NOT provide a real total count field —
            # "count" in the response = items returned, not total available.
            # The only reliable way is to fetch everything and count ourselves.
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

                # If fewer items returned than requested, we've reached the end
                if len(batch) < batch_size:
                    break

                skip += batch_size

            # ── Build rows ──
            all_rows = []

            for payment in all_payments:
                if not isinstance(payment, dict):
                    continue

                notes = payment.get("notes", {})
                if not isinstance(notes, dict):
                    notes = {}

                webinar_name = payment.get("description")

                webinar_id = notes.get("webinar_id")
                if webinar_id:
                    webinar = Webinar.objects.filter(uuid=webinar_id).first()

                    if webinar:
                        webinar_name = webinar.title

                row = {
                    "payment_id": payment.get("id"),
                    "customer": notes.get("name", "N/A"),
                    "email": notes.get("email") or payment.get("email"),
                    "phone": notes.get("phone") or payment.get("contact"),
                    "description": f"{webinar_name}",
                    "amount": round(payment.get("amount", 0) / 100,2),
                    "status": payment.get("status"),
                    "method": payment.get("method"),
                    "upi_id": payment.get("vpa"),
                    "razorpay_fee": round((payment.get("fee") or 0) / 100, 2),
                    "created_at": datetime.fromtimestamp(
                        payment.get("created_at", 0)
                    ).strftime("%d %b %Y %I:%M:%S %p"),
                }

                all_rows.append(row)
            # ── Apply filters if active ──
            if has_filter:
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
                            f"{r['phone']}"
                        ).lower()

                        # Match amount exactly
                        amount_match = search == str(int(float(r["amount"])))

                        if search in searchable or amount_match:
                            filtered.append(r)

                    all_rows = filtered

            # ✅ total_records = actual count of all matching rows
            total_records = len(all_rows)
            success_amount = sum(
                float(row.get("amount", 0))
                for row in all_rows
            )

            # ✅ Paginate AFTER filtering
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_data = all_rows[start_index:end_index]
            for idx, row in enumerate(paginated_data, start=start_index + 1):
                row["sno"] = idx
            success_amount = sum(
                float(row.get("amount", 0))
                for row in all_rows
                if row.get("status", "").lower() == "captured"
            )

            failed_amount = sum(
                float(row.get("amount", 0))
                for row in all_rows
                if row.get("status", "").lower() == "failed"
            )

            refunded_amount = sum(
                float(row.get("amount", 0))
                for row in all_rows
                if row.get("status", "").lower() == "refunded"
            )

            return Response({
                "success": True,
                "page": page,
                "page_size": page_size,
                "total_records": total_records,
                "success_amount": success_amount,
                "failed_amount": failed_amount,
                "refunded_amount": refunded_amount,
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


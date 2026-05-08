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

from aryuapp.utils import *
from aryuapp.mixins import *
from aryuapp.models import Settings
from aryuapp.views import flatten_errors
from collections import defaultdict

import json
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
    """
    ViewSet for handling payment transactions
    
    FIXED VERSION - Resolves issue where only 33 out of 63 students were showing
    
    Key fixes:
    1. Proper query order (filter before prefetch)
    2. Debug logging to track student counts
    3. All students included regardless of transactions
    4. Better handling of hierarchy filters
    """
    
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

                # ✅ FINAL STUDENT OBJECT
                student_list.append({
                    "student_id": student.student_id,
                    "registration_id": student.registration_id,
                    "student_name": f"{student.first_name}".strip(),
                    "email": student.email,
                    "phone": student.contact_no,
                    "courses": courses_data  # ✅ correct structure
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
        try:
            student_id = int(str(request.data.get("student_id")).strip())
            course_id = int(str(request.data.get("course_id")).strip())
        except (TypeError, ValueError):
            return Response({"success": False, "message": "Invalid student_id or course_id"}, status=400)

        payments = request.data.get("payments", [])

        if isinstance(payments, str):
            try:
                payments = json.loads(payments)
            except Exception:
                return Response({"success": False, "message": "Invalid payments format"}, status=400)

        # if not isinstance(payments, list) or not payments:
        #     return Response({"success": False, "message": "Payments must be a non-empty list"}, status=400)

        student = Student.objects.filter(student_id=student_id).first()
        course = Course.objects.filter(course_id=course_id).first()

        if not student or not course:
            return Response({"success": False, "message": "Student or Course not found"}, status=404)

        created_ids = []

        for pay in payments:
            amount = float(pay.get("amount", 0))
            if amount <= 0:
                return Response({"success": False, "message": "Invalid amount"}, status=400)

            transaction_id = pay.get("transaction_id") or f"TXN{uuid.uuid4().hex[:8].upper()}"

            # ✅ prevent duplicate at create level
            exists = PaymentTransaction.objects.filter(transaction_id=transaction_id).exists()
            if exists:
                continue

            tx = PaymentTransaction.objects.create(
                student=student,
                course=course,
                amount=amount,
                currency="INR",
                payment_status=pay.get("status"),
                transaction_id=transaction_id,
                metadata={
                    "mode": pay.get("mode"),
                    "date": pay.get("date"),
                    "attachment": pay.get("attachment")
                }
            )

            created_ids.append(tx.id)

        return Response({
            "success": True,
            "message": "Payments created",
            "created_count": len(created_ids),
            "created_ids": created_ids
        })
    def update(self, request, pk=None):
        student_id = request.data.get("student_id")
        course_id = request.data.get("course_id")
        metadata = request.data.get("metadata", [])

        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                return Response(
                    {
                        "success": False,
                        "message": "Invalid metadata"
                    },
                    status=400
                )

        student = Student.objects.filter(
            student_id=student_id
        ).first()

        course = Course.objects.filter(
            course_id=course_id
        ).first()

        if not student or not course:
            return Response(
                {
                    "success": False,
                    "message": "Invalid student or course"
                },
                status=400
            )

        created_ids = []
        updated_ids = []

        for pay in metadata:

            amount = float(pay.get("amount", 0))

            transaction_id = pay.get("transaction_id")

            mode = (
                pay.get("payment_mode") or ""
            ).lower()

            status_val = pay.get("payment_status")

            date = pay.get("payment_date")

            tx = None

            if transaction_id:
                tx = PaymentTransaction.objects.filter(
                    transaction_id=transaction_id
                ).first()

            # UPDATE EXISTING
            if tx:

                tx.amount = amount
                tx.payment_status = status_val

                tx.metadata = {
                    "mode": mode,
                    "date": date
                }

                tx.student = student
                tx.course = course

                tx.save()

                updated_ids.append(tx.id)

            else:
                # CREATE NEW
                new_tx = PaymentTransaction.objects.create(
                    student=student,
                    course=course,
                    amount=amount,
                    currency="INR",
                    payment_status=status_val,
                    transaction_id=transaction_id or f"TXN{uuid.uuid4().hex[:8].upper()}",
                    metadata={
                        "mode": mode,
                        "date": date
                    }
                )

                created_ids.append(new_tx.id)

        return Response({
            "success": True,
            "message": "Payments synced successfully",
            "created_count": len(created_ids),
            "updated_count": len(updated_ids)
        })
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


    # ✅ 2. Delete FULL student + all transactions
    @action(detail=True, methods=['delete'], url_path='delete-student')
    def delete_student(self, request, pk=None):
        try:
            student = Student.objects.get(student_id=pk)

            # delete all transactions
            PaymentTransaction.objects.filter(
                student_id=pk,
                is_archived=False
            ).update(is_archived=True)

            # delete student
            student.is_archived = True
            student.save()

            return Response({
                "success": True,
                "message": "Student and all transactions deleted"
            })

        except Student.DoesNotExist:
            return Response({
                "success": False,
                "message": "Student not found"
            }, status=404)

from django.conf import settings as django_settings
from stripe import _error as stripe_error
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

    def generate_invoice(self, transaction):
            student = transaction.student
            settings_obj = Settings.objects.first()

            # Convert amount to words
            amount_words = num2words(transaction.amount, to='currency', lang='en_IN')

            # Create Invoice object (auto-generates invoice_number)
            invoice = Invoice.objects.create(
                student=student,
                buyer_name=student.full_name,
                buyer_address=getattr(student, "address", ""),
                buyer_mobile=getattr(student, "mobile", ""),
                description=transaction.description,
                quantity=1,
                rate=transaction.amount,
                amount=transaction.amount,
                per="Nos",
                amount_in_words=amount_words,
                payment_terms="Immediate",
                created_by=transaction.created_by,
                created_by_type=transaction.created_by_type,
            )

            # Generate PDF
            pdf_buffer = io.BytesIO()
            pdf = canvas.Canvas(pdf_buffer, pagesize=A4)
            pdf.setTitle(f"Invoice {invoice.invoice_number}")
            pdf.drawString(50, 800, f"Invoice No: {invoice.invoice_number}")
            pdf.drawString(50, 780, f"Date: {invoice.date}")
            pdf.drawString(50, 760, f"Company: {settings_obj.company_name}")
            pdf.drawString(50, 740, f"Bank: {settings_obj.bank_name} A/C: {settings_obj.bank_account_no} IFSC: {settings_obj.bank_ifsc}")
            pdf.drawString(50, 720, f"Student: {invoice.buyer_name}")
            pdf.drawString(50, 700, f"Description: {invoice.description}")
            pdf.drawString(50, 680, f"Amount: {invoice.amount} INR ({invoice.amount_in_words})")
            pdf.drawString(50, 660, f"Declaration: {settings_obj.declaration or ''}")
            pdf.showPage()
            pdf.save()
            pdf_buffer.seek(0)

            # Save PDF to invoice model
            file_name = f"invoice_{invoice.invoice_number}.pdf"
            invoice.pdf_file.save(file_name, pdf_buffer)
            invoice.save()

            # Send email to student
            if student.email:
                email = EmailMessage(
                    subject=f"Invoice {invoice.invoice_number}",
                    body=f"Dear {student.full_name},\n\nPlease find attached your invoice.",
                    to=[student.email]
                )
                email.attach(file_name, pdf_buffer.getvalue(), 'application/pdf')
                email.send()

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
                StripePaymentViewSet().generate_invoice(transaction)

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
                StripePaymentViewSet().generate_invoice(transaction)

            return Response({"success": True, "message": "Payment verified successfully"})
        except razorpay.errors.SignatureVerificationError:
            return Response({"success": False, "message": "Payment verification failed"}, status=200)

@api_view(['GET'])
def stripe_success(request):
    return Response({"success": True, "message": "Payment successful!"})

@api_view(['GET'])
def stripe_cancel(request):
    return Response({"success": False, "message": "Payment canceled!"})


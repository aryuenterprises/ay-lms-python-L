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
from django.contrib.auth.hashers import *
from django.db.models import Q, F, Prefetch,  DecimalField,  Sum, Value, OuterRef, Subquery
from django.db.models.functions import Coalesce
from aryuapp.utils import *
from aryuapp.mixins import *
from aryuapp.views import flatten_errors
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

        # ---------------- Latest successful transaction ----------------
        latest_tx = PaymentTransaction.objects.filter(
            student=OuterRef("pk"),
            payment_status="Success",
             is_archived=False
        ).order_by("-created_at")

        # ---------------- Paid amount aggregation ----------------
        paid_amount_subquery = PaymentTransaction.objects.filter(
            student=OuterRef("pk"),
            payment_status="Success",
             is_archived=False
        ).values("student").annotate(
            total=Sum("amount")
        ).values("total")

        students_qs = (
            Student.objects
            .filter(transactions__isnull=False, is_archived=False)
            .select_related()
            .prefetch_related(
                Prefetch(
                    "transactions",
                    queryset=PaymentTransaction.objects
                    .filter(
        is_archived=False
    ).select_related(
                        "gateway",
                        "course"
                    ).only(
                        "id",
                        "transaction_id",
                        "amount",
                        "currency",
                        "payment_status",
                        "gateway__gatway_name",
                        "course__course_name",
                        "created_at"
                    ).order_by("-created_at")
                ),
                Prefetch(
                    "emi_plans",
                    queryset=PaymentEMI.objects.prefetch_related("installments")
                )
            )
            .annotate(
                course_name=Subquery(latest_tx.values("course__course_name")[:1]),
                total_course_fee=Subquery(latest_tx.values("course__fee")[:1]),
                paid_amount=Coalesce(
                    Subquery(paid_amount_subquery[:1]),
                    Value(0),
                    output_field=DecimalField()
                )
            )
        )
        # ---------------- Hierarchy filters ----------------
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
        else:
            students_qs = Student.objects.none()

        # ---------------- Serializer ----------------
        serializer = StudentPaymentSummarySerializer(
            students_qs,
            many=True
        )

        # ---------------- Students List (Ultra Optimized) ----------------

        student_queryset = Student.objects.filter(
            is_archived=False, status=True
        )

        if user_type == "admin" and user_created_id:

            student_queryset = student_queryset.filter(
                created_by=str(user_created_id)
            )

        elif user_type == "super_admin" and user_created_id:

            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

            admin_ids = [str(i) for i in admin_ids]

            student_queryset = student_queryset.filter(
                Q(created_by_type="super_admin", created_by=str(user_created_id)) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )

        else:
            student_queryset = Student.objects.none()


        student_list = list(
            student_queryset.values(
                "student_id",
                "registration_id",
                "first_name",
                "last_name",
                "email",
                "contact_no"
            )
        )

        # Rename fields for response format
        student_list = [
            {
                "student_id": s["student_id"],
                "registration_id": s["registration_id"],
                "student_name": f"{s['first_name']} {s['last_name']}".strip(),
                "email": s["email"],
                "phone": s["contact_no"]
            }
            for s in student_list
        ]

        settings = (
            Settings.objects
            .filter(is_archived=False)
            .only("stripe_enabled", "paypal_enabled", "razorpay_enabled")
            .order_by("-created_at")
            .first()
        )

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

        course_list = list(
            Course.objects
            .filter(is_archived=False, status="Active")
            .values(
                id=F("course_id"),
                name=F("course_name")
            ).order_by("-course_id")
        )
        
        return Response({
            "success": True,
            "student_payment_summaries": serializer.data,
            "students": student_list,
            "gatway": gateway_list,
            "courses": course_list
        })
   
    def retrieve(self, request, pk=None):

        latest_tx = PaymentTransaction.objects.filter(
            student=OuterRef("pk"),
            payment_status="Success"
        ).order_by("-created_at")

        paid_amount_subquery = PaymentTransaction.objects.filter(
            student=OuterRef("pk"),
            payment_status="Success"

        ).values("student").annotate(
            total=Sum("amount")
        ).values("total")

        student = (
            Student.objects
            .filter(student_id=pk)
            .prefetch_related(
                Prefetch(
                    "transactions",
                    queryset=PaymentTransaction.objects.select_related(
                        "gateway",
                        "course"
                    )
                ),
                Prefetch(
                    "emi_plans",
                    queryset=PaymentEMI.objects.prefetch_related("installments")
                )
            )
            .annotate(
                course_name=Subquery(latest_tx.values("course__course_name")[:1]),
                total_course_fee=Subquery(latest_tx.values("course__fee")[:1]),
                paid_amount=Coalesce(Subquery(paid_amount_subquery[:1]), Value(0))
            )
            .first()
        )

        if not student:
            return Response({
                "success": False,
                "message": "Student not found"
            })

        serializer = StudentPaymentSummarySerializer(student)
        settings = (
            Settings.objects
            .filter(is_archived=False)
            .only("stripe_enabled", "paypal_enabled", "razorpay_enabled")
            .order_by("-created_at")
            .first()
        )

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
            "student_payment_summary": serializer.data,
            "gatway":gateway_list,
        })
    
    def create(self, request):
        serializer = PaymentTransactionCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        transaction = serializer.save()

        # Return full details
        return Response({
            "success": True,
            'message': "Payment created successfully",
        })
        
    def update(self, request, pk=None):
        try:
            transaction = PaymentTransaction.objects.select_related(
                "course", "gateway", "student"
            ).get(pk=pk)
        except PaymentTransaction.DoesNotExist:
            return Response({
                "success": False,
                "message": "Transaction not found"
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = PaymentTransactionUpdateSerializer(
            transaction,
            data=request.data,
            partial=True,
            context={"request": request}
        )

        # Validate safely (same as student logic)
        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "success": False,
                "message": error_message
            }, status=status.HTTP_200_OK)

        # Save transaction
        serializer.save()
        transaction.refresh_from_db()

        # ----------------------------------
        # Save notes (NEW)
        # ----------------------------------
        notes_text = request.data.get("notes")

        if notes_text:
            mixin = NotesMixin()
            mixin.save_notes(transaction, notes_text, request=request)

        return Response({
            "success": True,
            "message": "Payment updated successfully"
        })


    def destroy(self, request, pk=None):
        try:
            transaction = PaymentTransaction.objects.get(pk=pk)
            transaction.is_archived = True   # soft delete
            transaction.save()
            return Response({"success": True, "message": "Payment deleted successfully"})
        except PaymentTransaction.DoesNotExist:
            return Response({"success": False, "message": "Transaction not found"}, status=404)


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
                    "name": student.first_name + " " + student.last_name,
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


import io
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from django.template.loader import render_to_string
from django.utils import timezone
from django.db.models import Sum
from num2words import num2words

from aryuapp.models import Settings
from payments.models import PaymentTransaction

logger = logging.getLogger(__name__)


def render_pdf(html_string, base_url=None):
    try:
        from weasyprint import HTML
        return HTML(string=html_string, base_url=base_url or settings.BASE_DIR).write_pdf()
    except Exception as e:
        logger.warning(f"WeasyPrint PDF rendering failed, attempting xhtml2pdf fallback: {e}")
        try:
            from xhtml2pdf import pisa
            result = io.BytesIO()
            pisa_status = pisa.CreatePDF(io.BytesIO(html_string.encode("UTF-8")), dest=result)
            if pisa_status.err:
                raise Exception(f"xhtml2pdf error code: {pisa_status.err}")
            return result.getvalue()
        except Exception as fallback_err:
            logger.error(f"Both WeasyPrint and xhtml2pdf failed: {fallback_err}")
            raise fallback_err


class InvoiceService:

    HSN_CODE = "999293"

    @classmethod
    def get_invoice_url(cls, transaction_or_file, request=None):
        if not transaction_or_file:
            return None

        file_obj = getattr(transaction_or_file, "invoice", transaction_or_file)
        invoice_no = getattr(transaction_or_file, "invoice_no", "")

        if file_obj and hasattr(file_obj, "url") and file_obj.url:
            if hasattr(file_obj, "name") and not file_obj.name:
                return None
            invoice_path = file_obj.url
        elif isinstance(file_obj, str) and file_obj:
            if file_obj.startswith("http://") or file_obj.startswith("https://"):
                return file_obj
            invoice_path = file_obj
        elif invoice_no:
            invoice_path = f"/media/invoices/{invoice_no}.pdf"
        else:
            return None

        if not invoice_path.startswith("/"):
            invoice_path = f"/{invoice_path}"

        base_url = (
            getattr(settings, "MEDIA_BASE_URL", "").rstrip("/")
            or getattr(settings, "FRONTEND_URL", "").rstrip("/")
            or getattr(settings, "BACKEND_URL", "").rstrip("/")
        )

        if base_url:
            return f"{base_url}{invoice_path}"

        if request:
            return request.build_absolute_uri(invoice_path)

        return invoice_path

    @classmethod
    def round_amount(cls, value):
        return Decimal(value).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

    @classmethod
    def calculate_tax(cls, amount, company):

        # =====================================
        # GST INCLUSIVE CALCULATION
        # =====================================

        amount = Decimal(str(amount))

        cgst_percentage = Decimal(
            str(company.cgst_percentage or 9)
        )

        sgst_percentage = Decimal(
            str(company.sgst_percentage or 9)
        )

        total_gst_percentage = (
            cgst_percentage + sgst_percentage
        )

        # =====================================
        # TAXABLE AMOUNT
        # Example:
        # 2999 / 1.18 = 2541.53
        # =====================================

        taxable_amount = (
            amount * Decimal("100")
        ) / (
            Decimal("100") + total_gst_percentage
        )

        taxable_amount = cls.round_amount(
            taxable_amount
        )

        # =====================================
        # CGST
        # =====================================

        cgst_amount = (
            taxable_amount *
            cgst_percentage
        ) / Decimal("100")

        cgst_amount = cls.round_amount(
            cgst_amount
        )

        # =====================================
        # SGST
        # =====================================

        sgst_amount = (
            taxable_amount *
            sgst_percentage
        ) / Decimal("100")

        sgst_amount = cls.round_amount(
            sgst_amount
        )

        # =====================================
        # TOTAL TAX
        # =====================================

        total_tax_amount = (
            cgst_amount + sgst_amount
        )

        total_tax_amount = cls.round_amount(
            total_tax_amount
        )

        # =====================================
        # FINAL TOTAL
        # =====================================

        invoice_total = (
            taxable_amount +
            total_tax_amount
        )

        invoice_total = cls.round_amount(
            invoice_total
        )

        return {
            "taxable_amount":
                taxable_amount,

            "cgst_amount":
                cgst_amount,

            "sgst_amount":
                sgst_amount,

            "igst_amount":
                Decimal("0.00"),

            "total_tax_amount":
                total_tax_amount,

            "invoice_total":
                invoice_total,
        }

    @classmethod
    def get_billing_details(cls, transaction):

        # =========================================
        # COMPANY BILLING
        # =========================================

        if (
            transaction.billing_type == "company"
            and transaction.employer
        ):

            employer = transaction.employer

            return {
                "name": (
                    employer.company_name or "-"
                ),
                "address": (
                    employer.address or "-"
                ),
                "gst": (
                    employer.org_gst_number
                    or "Unregistered"
                ),
                "email": (
                    employer.email or "-"
                ),
                "phone": (
                    employer.phone or "-"
                ),
                "type": "company"
            }

        # =========================================
        # WEBINAR BILLING
        # =========================================

        if (
            transaction.billing_type == "webinar"
            and transaction.webinar_registration
        ):

            webinar = (
                transaction.webinar_registration
            )

            return {
                "name": (
                    webinar.name
                    or "Webinar Participant"
                ),
                "address": "-",
                "gst": "Unregistered",
                "email": (
                    webinar.email or "-"
                ),
                "phone": (
                    webinar.phone or "-"
                ),
                "type": "webinar"
            }

        # =========================================
        # STUDENT BILLING
        # =========================================

        student = transaction.student

        if not student:
            return {
                "name": "Customer",
                "address": "-",
                "gst": "Unregistered",
                "email": "-",
                "phone": "-",
                "type": "customer"
            }

        return {
            "name": (
                f"{student.first_name} "
                f"{student.last_name or ''}"
            ).strip(),
            "address": (
                student.current_address or "-"
            ),
            "gst": (
                student.stu_gst_number
                or "Unregistered"
            ),
            "email": (
                student.email or "-"
            ),
            "phone": (
                student.contact_no or "-"
            ),
            "type": "student"
        }

    @classmethod
    def get_description(cls, transaction):

        # =========================================
        # COURSE PAYMENT
        # =========================================

        if transaction.course:
            return (
                transaction.course.course_name
            )

        # =========================================
        # WEBINAR PAYMENT
        # =========================================

        if (
            transaction.webinar_registration
            and transaction.webinar_registration.webinar
        ):

            return (
                transaction
                .webinar_registration
                .webinar
                .title
            )

        # =========================================
        # EBOOK PAYMENT
        # =========================================

        if transaction.ebookregistration:
            return "Ebook Purchase"

        return "Payment"

    @classmethod
    def get_previous_transactions(cls, transaction):

        queryset = (
            PaymentTransaction.objects.filter(
                payment_status__in=[
                    "success",
                    "paid",
                    "done",
                    "partial",
                    "advanced",
                ],
                is_archived=False,
                invoice_no__isnull=False,
            )
        )

        if transaction.student:
            queryset = queryset.filter(student=transaction.student)

            if transaction.course:
                queryset = queryset.filter(course=transaction.course)

        elif transaction.webinar_registration:
            queryset = queryset.filter(
                webinar_registration=transaction.webinar_registration
            )

        # Exclude current transaction
        queryset = queryset.exclude(id=transaction.id)

        return queryset.order_by("created_at")
    @classmethod
    def get_previous_invoice_details(
        cls,
        previous_transactions,
        current_transaction
    ):

        invoice_list = []

        for index, txn in enumerate(previous_transactions, start=1):
            invoice_list.append({
                "sno": index,
                "invoice_no": txn.invoice_no,
                "date": txn.invoice_date,
                "amount": cls.round_amount(txn.amount),
            })

        invoice_list.append({
            "sno": len(invoice_list) + 1,
            "invoice_no": current_transaction.invoice_no,
            "date": current_transaction.invoice_date,
            "amount": cls.round_amount(current_transaction.amount),
        })

        return invoice_list
    @classmethod
    def get_total_received(
        cls,
        previous_transactions,
        current_transaction
    ):

        total = (
            previous_transactions.aggregate(
                total=models.Sum("amount")
            )["total"]
            or Decimal("0")
        )

        total += Decimal(
            current_transaction.amount
        )

        return cls.round_amount(total)

    @classmethod
    def get_balance_due(cls, transaction):

        if transaction.course:

            course_fee = Decimal(transaction.course.fee or 0)

            total_received = (
                PaymentTransaction.objects.filter(
                    student=transaction.student,
                    course=transaction.course,
                    is_archived=False,
                    payment_status__in=[
                        "success",
                        "paid",
                        "done",
                        "partial",
                        "advanced"
                    ]
                ).aggregate(
                    total=Sum("amount")
                )["total"] or Decimal("0")
            )

            due = course_fee - total_received

            return max(
                cls.round_amount(due),
                Decimal("0")
            )

        if (
            transaction.webinar_registration
            and transaction.webinar_registration.webinar
        ):

            webinar_price = Decimal(
                transaction.webinar_registration.webinar.price or 0
            )

            total_received = (
                PaymentTransaction.objects.filter(
                    webinar_registration=transaction.webinar_registration,
                    is_archived=False,
                    payment_status__in=[
                        "success",
                        "paid",
                        "done",
                        "partial",
                        "advanced"
                    ]
                ).aggregate(
                    total=Sum("amount")
                )["total"] or Decimal("0")
            )

            due = webinar_price - total_received

            return max(
                cls.round_amount(due),
                Decimal("0")
            )

        return Decimal("0.00")
    @classmethod
    def update_transaction_tax_fields(
        cls,
        transaction,
        tax_data,
        balance_due
    ):

        transaction.taxable_amount = (
            tax_data["taxable_amount"]
        )

        transaction.cgst_amount = (
            tax_data["cgst_amount"]
        )

        transaction.sgst_amount = (
            tax_data["sgst_amount"]
        )

        transaction.igst_amount = (
            tax_data["igst_amount"]
        )

        transaction.total_tax_amount = (
            tax_data["total_tax_amount"]
        )

        transaction.invoice_total = (
            tax_data["invoice_total"]
        )

        transaction.amount_received = (
            transaction.amount
        )

        transaction.balance_due = (
            balance_due
        )

        transaction.invoice_date = (
            transaction.invoice_date
            or timezone.now().date()
        )

        if not transaction.place_of_supply:

            transaction.place_of_supply = (
                "Tamil Nadu"
            )

        transaction.save(
            update_fields=[
                "taxable_amount",
                "cgst_amount",
                "sgst_amount",
                "igst_amount",
                "total_tax_amount",
                "invoice_total",
                "amount_received",
                "balance_due",
                "invoice_date",
                "place_of_supply",
            ]
        )

    @classmethod
    def generate_invoice(
        cls,
        transaction_id,
        regenerate=False,
        request=None
    ):

        transaction = (
            PaymentTransaction.objects
            .select_related(
                "student",
                "course",
                "employer",
                "webinar_registration",
                "webinar_registration__webinar"
            )
            .get(id=transaction_id)
        )

        # =========================================
        # PREVENT DUPLICATE
        # =========================================

        if (
            transaction.invoice
            and not regenerate
        ):
            transaction.invoice_url = cls.get_invoice_url(transaction, request=request)
            return transaction

        # =========================================
        # COMPANY SETTINGS
        # =========================================

        company = (
            Settings.objects
            .filter(is_archived=False)
            .last()
        )

        if not company:
            raise Exception(
                "Company settings not configured"
            )

        # =========================================
        # TAX CALCULATION
        # =========================================

        tax_data = cls.calculate_tax(
            transaction.amount,
            company
        )

        # =========================================
        # PREVIOUS PAYMENTS
        # =========================================

        previous_transactions = cls.get_previous_transactions(transaction)

        previous_invoice_details = cls.get_previous_invoice_details(
            previous_transactions,
            transaction
        )

        previous_paid_amount = (
            previous_transactions.aggregate(
                total=models.Sum("amount")
            )["total"] or Decimal("0")
        )

        current_payment = cls.round_amount(transaction.amount)

        total_received = cls.round_amount(
            previous_paid_amount + current_payment
        )


        balance_due = cls.get_balance_due(transaction)

        # =========================================
        # UPDATE TRANSACTION
        # =========================================

        cls.update_transaction_tax_fields(
            transaction,
            tax_data,
            balance_due
        )

        # =========================================
        # BILLING DETAILS
        # =========================================

        billing = (
            cls.get_billing_details(
                transaction
            )
        )

        # =========================================
        # DESCRIPTION
        # =========================================

        description = (
            cls.get_description(
                transaction
            )
        )

        # =========================================
        # AMOUNT WORDS
        # =========================================

        invoice_total_words = (
            num2words(
                transaction.invoice_total,
                lang="en_IN"
            )
        )

        tax_amount_words = (
            num2words(
                transaction.total_tax_amount,
                lang="en_IN"
            )
        )

        # =========================================
        # TEMPLATE CONTEXT
        # =========================================

        context = {
            # Core Objects
            "transaction": transaction,
            "company": company,
            "billing": billing,

            # Direct Identifiers & Header
            "invoice_no": transaction.invoice_no,
            "invoice_date": transaction.invoice_date,
            "place_of_supply": transaction.place_of_supply or "Tamil Nadu",

            # Buyer / Student Info
            "student_name": billing.get("name", "Customer"),
            "student_address": billing.get("address", "-"),
            "email": billing.get("email", "-"),
            "phone": billing.get("phone", "-"),
            "gst": billing.get("gst", "Unregistered"),

            # Line Item & Tax Breakdown
            "course_name": description,
            "hsn_sac": cls.HSN_CODE,
            "rate": transaction.amount,
            "taxable_value": transaction.taxable_amount,
            "cgst": transaction.cgst_amount,
            "sgst": transaction.sgst_amount,
            "total_tax": transaction.total_tax_amount,
            "total_amount": transaction.invoice_total,

            # Word Representations
            "amount_in_words": invoice_total_words,
            "tax_in_words": tax_amount_words,

            # Ledger & Payment History
            "previous_transactions": previous_transactions,
            "previous_invoice_details": previous_invoice_details,
            "previous_paid_amount": previous_paid_amount,
            "current_payment": current_payment,
            "total_received": total_received,
            "balance_due": balance_due,
        }

        # =========================================
        # RENDER HTML
        # =========================================

        html_string = render_to_string(
            "invoices/invoice_pdf.html",
            context
        )

        # =========================================
        # GENERATE PDF
        # =========================================

        pdf_bytes = render_pdf(
            html_string,
            base_url=settings.BASE_DIR
        )

        # =========================================
        # SAVE PDF
        # =========================================

        file_name = (
            f"{transaction.invoice_no}.pdf"
        )

        if transaction.invoice:
            transaction.invoice.delete(
                save=False
            )

        transaction.invoice.save(
            file_name,
            ContentFile(pdf_bytes),
            save=True
        )

        transaction.invoice_url = cls.get_invoice_url(transaction, request=request)
        return transaction
    
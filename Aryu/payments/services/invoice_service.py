import io
import ipaddress
import logging
import os
import shutil
import socket
import subprocess
import tempfile
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse, unquote

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import models, transaction as db_transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.db.models import Sum
from num2words import num2words

from aryuapp.models import Settings
from payments.models import PaymentTransaction

logger = logging.getLogger("payments")


def _safe_weasyprint_url_fetcher(url, timeout=5, ssl_context=None):
    """
    Security-hardened URL fetcher for WeasyPrint.
    - Blocks arbitrary local file read by constraining paths strictly to MEDIA_ROOT, STATIC_ROOT, BASE_DIR.
    - Blocks SSRF by refusing requests to loopback, link-local, private RFC1918, and multicast IP ranges.
    - Permits valid data: URIs and public media URLs.
    """
    from weasyprint import default_url_fetcher

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme == "data":
        return default_url_fetcher(url, timeout=timeout, ssl_context=ssl_context)

    if scheme in ("file", ""):
        path = unquote(parsed.path or url)
        real_path = os.path.realpath(path)
        allowed_dirs = [
            os.path.realpath(settings.MEDIA_ROOT),
            os.path.realpath(settings.BASE_DIR),
        ]
        static_root = getattr(settings, "STATIC_ROOT", None)
        if static_root:
            allowed_dirs.append(os.path.realpath(static_root))

        is_allowed = any(
            real_path == allowed_dir or real_path.startswith(allowed_dir + os.sep)
            for allowed_dir in allowed_dirs
        )
        if not is_allowed:
            logger.warning(
                "Blocked unauthorized local file access during PDF rendering: %s",
                os.path.basename(real_path)
            )
            raise PermissionError("Access to unauthorized file path is forbidden.")

        return default_url_fetcher(f"file://{real_path}", timeout=timeout, ssl_context=ssl_context)

    if scheme in ("http", "https"):
        hostname = parsed.hostname
        if not hostname:
            raise PermissionError("Invalid URL hostname in PDF rendering.")

        # Block localhost / link-local / private IPs (SSRF protection)
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                ip_str = socket.gethostbyname(hostname)
                ip = ipaddress.ip_address(ip_str)
            except Exception:
                ip = None

        if ip and (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast):
            logger.warning("Blocked SSRF attempt to internal network during PDF generation.")
            raise PermissionError("Network access to private/internal addresses is forbidden.")

        return default_url_fetcher(url, timeout=min(timeout or 5, 5), ssl_context=ssl_context)

    raise PermissionError(f"URL scheme '{scheme}' is forbidden in PDF rendering.")


def _find_browser_binary():
    """
    Locates an existing headless Chromium / Chrome browser binary in the deployment environment.
    Priority:
    1. Environment variables CHROME_BIN, CHROMIUM_PATH
    2. System PATH (chrome-headless-shell, chromium, chromium-browser, google-chrome-stable, google-chrome)
    3. Playwright browser cache (~/.cache/ms-playwright, PLAYWRIGHT_BROWSERS_PATH)
    4. Playwright Python executable_path if available
    """
    env_bin = os.environ.get("CHROME_BIN") or os.environ.get("CHROMIUM_PATH")
    if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
        return env_bin

    for name in ("chrome-headless-shell", "chromium", "chromium-browser", "google-chrome-stable", "google-chrome"):
        bin_path = shutil.which(name)
        if bin_path:
            try:
                resolved = os.path.realpath(bin_path)
                if os.path.isfile(resolved) and os.access(resolved, os.X_OK):
                    return resolved
            except OSError:
                continue

    cache_dirs = [
        os.path.expanduser("~/.cache/ms-playwright"),
        "/root/.cache/ms-playwright",
    ]
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        cache_dirs.insert(0, os.environ["PLAYWRIGHT_BROWSERS_PATH"])

    candidates = []
    for cache_dir in cache_dirs:
        if os.path.isdir(cache_dir):
            for root, _, files in os.walk(cache_dir):
                for f in files:
                    if f in ("chrome-headless-shell", "chrome"):
                        full_path = os.path.join(root, f)
                        if os.access(full_path, os.X_OK):
                            priority = 0 if f == "chrome-headless-shell" else 1
                            candidates.append((priority, full_path))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            pw_path = p.chromium.executable_path
            if pw_path and os.path.isfile(pw_path) and os.access(pw_path, os.X_OK):
                return pw_path
    except Exception:
        pass

    return None


def _render_with_browser(html_string, timeout=30):
    """
    Renders HTML to PDF using a headless Chromium subprocess.
    Production requirements:
    - Safe subprocess: shell=False, strict argument list.
    - Script execution disabled (--disable-javascript) for security.
    - No GPU, isolated memory (--disable-dev-shm-usage, --disable-gpu).
    - Resource timeout to prevent hangs.
    - Strict tempfile management with cleanup in finally block.
    """
    browser_bin = _find_browser_binary()
    if not browser_bin:
        raise RuntimeError(
            "Headless browser binary not found in deployment environment. "
            "Please configure CHROME_BIN or install chromium / playwright."
        )

    temp_dir = tempfile.mkdtemp(prefix="invoice_pdf_")
    html_path = os.path.join(temp_dir, "input.html")
    pdf_path = os.path.join(temp_dir, "output.pdf")

    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_string)

        cmd = [
            browser_bin,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-crash-reporter",
            "--disable-javascript",
            "--disable-background-networking",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            "--mute-audio",
            "--hide-scrollbars",
            f"--print-to-pdf={pdf_path}",
            html_path,
        ]

        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            shell=False,
            check=False,
        )

        if proc.returncode != 0:
            err_msg = proc.stderr.decode("utf-8", errors="replace")[:300] if proc.stderr else ""
            raise RuntimeError(
                f"Headless browser exited with code {proc.returncode}: {err_msg.strip()}"
            )

        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
            raise RuntimeError("Headless browser finished without generating a valid PDF file.")

        with open(pdf_path, "rb") as f:
            return f.read()

    finally:
        try:
            if os.path.exists(html_path):
                os.unlink(html_path)
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except OSError as cleanup_err:
            logger.warning(f"Error cleaning up temporary PDF resources: {cleanup_err}")


def render_pdf(html_string, base_url=None):
    """
    Renders HTML to PDF using WeasyPrint with secure headless browser fallback.
    xhtml2pdf / pisa has been completely eliminated.
    """
    if not html_string or not html_string.strip():
        raise ValueError("HTML content must not be empty.")

    max_bytes = getattr(settings, "PDF_MAX_HTML_BYTES", 10 * 1024 * 1024)
    if len(html_string.encode("utf-8")) > max_bytes:
        raise ValueError(f"HTML payload exceeds maximum allowed size ({max_bytes // (1024 * 1024)} MB).")

    # Primary: WeasyPrint with security-hardened URL fetcher
    try:
        from weasyprint import HTML
        return HTML(
            string=html_string,
            base_url=base_url or settings.BASE_DIR,
            url_fetcher=_safe_weasyprint_url_fetcher,
        ).write_pdf()
    except Exception as wp_err:
        logger.warning(
            "Primary WeasyPrint PDF rendering failed, attempting headless browser fallback: %s",
            wp_err.__class__.__name__
        )

    # Fallback: Headless Chromium browser renderer
    try:
        return _render_with_browser(html_string, timeout=30)
    except Exception as browser_err:
        logger.error(
            "Both WeasyPrint and headless browser fallback failed for PDF rendering: %s",
            browser_err.__class__.__name__
        )
        raise RuntimeError(f"PDF rendering failed across all engines: {browser_err}") from browser_err


class InvoiceService:

    HSN_CODE = "999293"

    @classmethod
    def get_invoice_url(cls, transaction_or_file, request=None):
        if not transaction_or_file:
            return None

        file_obj = getattr(transaction_or_file, "invoice", transaction_or_file)
        invoice_no = getattr(transaction_or_file, "invoice_no", "")

        file_path = None
        url_path = None

        if file_obj and hasattr(file_obj, "path") and file_obj.path:
            file_path = file_obj.path
            url_path = file_obj.url if hasattr(file_obj, "url") else None
        elif isinstance(file_obj, str) and file_obj:
            if file_obj.startswith("http://") or file_obj.startswith("https://"):
                return file_obj
            rel_path = file_obj.lstrip("/")
            if rel_path.startswith("media/"):
                rel_path = rel_path[6:]
            file_path = os.path.join(settings.MEDIA_ROOT, rel_path)
            url_path = f"/media/{rel_path}"
        elif invoice_no:
            file_path = os.path.join(settings.MEDIA_ROOT, "invoices", f"{invoice_no}.pdf")
            url_path = f"/media/invoices/{invoice_no}.pdf"

        # Verify physical existence on disk
        if not file_path or not os.path.exists(file_path):
            return None

        if not url_path:
            url_path = f"/media/invoices/{invoice_no}.pdf" if invoice_no else None

        if not url_path:
            return None

        if not url_path.startswith("/"):
            url_path = f"/{url_path}"

        if url_path.startswith("/media/"):
            api_url_path = "/api" + url_path
        elif url_path.startswith("/api/media/"):
            api_url_path = url_path
        else:
            api_url_path = "/api/media/" + url_path.lstrip("/")

        if request:
            return request.build_absolute_uri(api_url_path)

        base_url = (
            getattr(settings, "MEDIA_BASE_URL", "").rstrip("/")
            or getattr(settings, "FRONTEND_URL", "").rstrip("/")
            or getattr(settings, "BACKEND_URL", "").rstrip("/")
        )

        if base_url:
            return f"{base_url}{api_url_path}"

        return api_url_path

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
            txn_date = txn.invoice_date or (txn.created_at.strftime("%Y-%m-%d") if hasattr(txn, "created_at") and txn.created_at else "")
            invoice_list.append({
                "sno": index,
                "invoice_no": txn.invoice_no,
                "date": txn_date,
                "invoice_date": txn_date,
                "amount": cls.round_amount(txn.amount),
            })

        curr_date = current_transaction.invoice_date or (current_transaction.created_at.strftime("%Y-%m-%d") if hasattr(current_transaction, "created_at") and current_transaction.created_at else "")
        invoice_list.append({
            "sno": len(invoice_list) + 1,
            "invoice_no": current_transaction.invoice_no,
            "date": curr_date,
            "invoice_date": curr_date,
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

    ELIGIBLE_STATUSES = ["success", "done", "paid", "complete", "advanced"]

    @classmethod
    def generate_invoice(
        cls,
        transaction_id,
        regenerate=False,
        request=None
    ):
        with db_transaction.atomic():
            transaction = (
                PaymentTransaction.objects
                .select_for_update(of=('self',))
                .select_related(
                    "student",
                    "course",
                    "employer",
                    "webinar_registration",
                    "webinar_registration__webinar"
                )
                .get(id=transaction_id)
            )

            # Check status eligibility unless manually triggered with regenerate
            status_str = str(transaction.payment_status or "").strip().lower()
            if status_str not in cls.ELIGIBLE_STATUSES and not regenerate:
                logger.warning(
                    f"Transaction {transaction_id} status '{transaction.payment_status}' is not eligible for invoice generation."
                )

            # =========================================
            # PREVENT DUPLICATE (VERIFY PHYSICAL DISK EXISTENCE)
            # =========================================

            file_exists = False
            if transaction.invoice:
                try:
                    file_name = str(transaction.invoice)
                    if default_storage.exists(file_name):
                        file_exists = True
                    elif hasattr(transaction.invoice, "path") and transaction.invoice.path:
                        file_exists = os.path.exists(transaction.invoice.path)
                except Exception as check_err:
                    logger.warning(f"Error checking invoice storage existence for transaction {transaction_id}: {check_err}")
                    file_exists = False

            if transaction.invoice and file_exists and not regenerate:
                logger.info(f"Invoice already exists for transaction {transaction_id} at {transaction.invoice}")
                transaction.invoice_url = cls.get_invoice_url(transaction, request=request)
                return transaction

        if not transaction.invoice_no:
            transaction.invoice_no = transaction.generate_invoice_no()
            transaction.save(update_fields=["invoice_no"])

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

        try:
            html_string = render_to_string(
                "invoices/invoice_pdf.html",
                context
            )
        except Exception as tpl_err:
            logger.error(f"Invoice template rendering failed for transaction {transaction_id}: {tpl_err}", exc_info=True)
            raise Exception(f"Failed to render invoice template: {tpl_err}")

        # =========================================
        # GENERATE PDF
        # =========================================

        try:
            pdf_bytes = render_pdf(
                html_string,
                base_url=settings.BASE_DIR
            )
        except Exception as pdf_err:
            logger.error(f"PDF rendering failed for transaction {transaction_id}: {pdf_err}", exc_info=True)
            raise Exception(f"Failed to render PDF: {pdf_err}")

        if not pdf_bytes:
            raise Exception("Generated PDF output is empty.")

        # =========================================
        # ENSURE TARGET DIRECTORY & SAVE PDF
        # =========================================

        try:
            invoices_dir = os.path.join(settings.MEDIA_ROOT, "invoices")
            os.makedirs(invoices_dir, exist_ok=True)

            file_name = f"{transaction.invoice_no}.pdf"
            relative_path = f"invoices/{file_name}"

            if transaction.invoice:
                try:
                    transaction.invoice.delete(save=False)
                except Exception as del_err:
                    logger.warning(f"Could not delete old invoice file for transaction {transaction_id}: {del_err}")

            transaction.invoice.save(
                file_name,
                ContentFile(pdf_bytes),
                save=False
            )
            transaction.save(update_fields=["invoice"])

            full_file_path = os.path.join(invoices_dir, file_name)
            if not os.path.exists(full_file_path):
                with open(full_file_path, "wb") as f:
                    f.write(pdf_bytes)

            logger.info(f"Successfully generated and saved invoice for transaction {transaction_id} at {relative_path}")

        except Exception as save_err:
            logger.error(f"Saving invoice PDF failed for transaction {transaction_id}: {save_err}", exc_info=True)
            raise Exception(f"Failed to save invoice PDF: {save_err}")

        transaction.invoice_url = cls.get_invoice_url(transaction, request=request)
        return transaction
    
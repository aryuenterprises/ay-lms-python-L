"""
PDFGeneratorService — Production-grade HTML → PDF using Playwright (Chromium)
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from rest_framework import serializers, permissions, status
from rest_framework.parsers import JSONParser
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

_MAX_HTML_BYTES: int = getattr(settings, "PDF_MAX_HTML_BYTES", 10 * 1024 * 1024)  # 10 MB
_MIN_HTML_LENGTH: int = 10  # anything shorter cannot be a valid HTML document


class GeneratePDFSerializer(serializers.Serializer):
    """
    Validates the POST /api/resume/candidates/generate-pdf request body.
    """
    html = serializers.CharField(
        required=True,
        allow_blank=False,
        help_text="A complete HTML document string to render as a PDF.",
    )

    def validate_html(self, value: str) -> str:
        value = value.strip()

        if len(value) < _MIN_HTML_LENGTH:
            raise serializers.ValidationError(
                "The html field is too short to be a valid HTML document."
            )

        byte_size = len(value.encode("utf-8"))
        max_mb = _MAX_HTML_BYTES / (1024 * 1024)
        if byte_size > _MAX_HTML_BYTES:
            raise serializers.ValidationError(
                f"HTML payload size ({byte_size / (1024 * 1024):.1f} MB) "
                f"exceeds the maximum allowed size ({max_mb:.0f} MB)."
            )

        return value


# ---------------------------------------------------------------------------
# Print-optimisation CSS injected into every document before rendering
# FIXED: Removed `@page { margin: 0; }` to allow standard print boundaries.
# ---------------------------------------------------------------------------
_PRINT_CSS = """
<style id="__pdf_print_inject__">
  @page {
    size: A4;
  }

  /* Force exact colour reproduction — no browser-imposed "ink-save" */
  html, body {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
    color-adjust: exact !important;
  }

  /* Prevent stray page-break artefacts */
  * {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  /* Sensible page-break defaults; callers can override with utility classes */
  .page-break-before { page-break-before: always; }
  .page-break-after  { page-break-after:  always; }
  .avoid-break       { page-break-inside: avoid; }

  /* Remove browser-default link decoration that shows URLs in print */
  @media print {
    a[href]::after { content: none !important; }
  }
</style>
"""

# ---------------------------------------------------------------------------
# Basic HTML sanitisation — block dangerous resource schemes
# ---------------------------------------------------------------------------
_DANGEROUS_PATTERNS = [
    (re.compile(r'(?i)(src|href|action|data)\s*=\s*["\']?\s*file://', re.I), ""),
    (re.compile(r'<script[^>]*>[\s\S]*?</script>', re.I), ""),
    (re.compile(r'<script\b[^>]*>', re.I), ""),
    (re.compile(r'<meta[^>]+http-equiv\s*=\s*["\']?refresh["\']?[^>]*>', re.I), ""),
]


class PDFGenerationError(Exception):
    """Raised when PDF rendering fails for any reason."""


class PDFGeneratorService:
    _BROWSER_LAUNCH_ARGS: list[str] = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--font-render-hinting=none",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--metrics-recording-only",
        "--mute-audio",
        "--no-first-run",
        "--safebrowsing-disable-auto-update",
    ]

    _ALLOWED_RESOURCE_TYPES: frozenset[str] = frozenset({
        "document",
        "stylesheet",
        "font",
        "image",
        "fetch",
    })

    _ALLOWED_URL_PREFIXES: tuple[str, ...] = (
        "https://fonts.googleapis.com",
        "https://fonts.gstatic.com",
        "https://cdn.jsdelivr.net",
        "https://cdnjs.cloudflare.com",
        "https://unpkg.com",
        "data:",
        "blob:",
    )

    def generate_pdf(self, html_content: str) -> bytes:
        try:
            return asyncio.run(self._generate_pdf_async(html_content))
        except PDFGenerationError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error during PDF generation")
            raise PDFGenerationError(f"PDF generation failed: {exc}") from exc

    def _sanitize_html(self, html: str) -> str:
        for pattern, replacement in _DANGEROUS_PATTERNS:
            html = pattern.sub(replacement, html)
        return html

    def _inject_print_css(self, html: str) -> str:
        head_close = re.search(r'</head>', html, re.IGNORECASE)
        if head_close:
            pos = head_close.start()
            return html[:pos] + _PRINT_CSS + html[pos:]
        html_open = re.search(r'<html[^>]*>', html, re.IGNORECASE)
        if html_open:
            pos = html_open.end()
            return html[:pos] + _PRINT_CSS + html[pos:]
        return _PRINT_CSS + html

    def _validate_html(self, html: str) -> None:
        if not html or not html.strip():
            raise PDFGenerationError("HTML content must not be empty.")
        if len(html.encode("utf-8")) > _MAX_HTML_BYTES:
            raise PDFGenerationError(
                f"HTML payload exceeds the maximum allowed size "
                f"({_MAX_HTML_BYTES // (1024 * 1024)} MB)."
            )

    async def _route_handler(self, route, request):
        resource_type = request.resource_type
        url: str = request.url

        if url.startswith("data:") or url.startswith("blob:"):
            await route.continue_()
            return

        if resource_type not in self._ALLOWED_RESOURCE_TYPES:
            await route.abort()
            return

        if url.startswith("http://") or url.startswith("https://"):
            if not any(url.startswith(prefix) for prefix in self._ALLOWED_URL_PREFIXES):
                logger.debug("PDF renderer blocked resource: %s (%s)", url, resource_type)
                await route.abort()
                return

        await route.continue_()

    async def _generate_pdf_async(self, html_content: str) -> bytes:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise PDFGenerationError(
                "Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            ) from exc

        self._validate_html(html_content)
        html_content = self._sanitize_html(html_content)
        html_content = self._inject_print_css(html_content)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=self._BROWSER_LAUNCH_ARGS,
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 794, "height": 1123},  
                    java_script_enabled=False,   
                    bypass_csp=True,             
                )
                page = await context.new_page()

                await page.route("**/*", self._route_handler)

                with tempfile.NamedTemporaryFile(
                    suffix=".html",
                    mode="w",
                    encoding="utf-8",
                    delete=False,
                ) as tmp:
                    tmp.write(html_content)
                    tmp_path = Path(tmp.name)

                try:
                    await page.goto(
                        f"file://{tmp_path.as_posix()}",
                        wait_until="networkidle",
                        timeout=30_000,
                    )

                    await page.wait_for_timeout(500)

                    # FIXED: Added default 10mm margins so text doesn't hit the absolute edge.
                    pdf_bytes: bytes = await page.pdf(
                        format="A4",
                        print_background=True,
                        margin={
                            "top": "10mm",
                            "right": "10mm",
                            "bottom": "10mm",
                            "left": "10mm",
                        },
                        prefer_css_page_size=True,
                    )
                finally:
                    tmp_path.unlink(missing_ok=True)

                await context.close()
                return pdf_bytes

            finally:
                await browser.close()


class GenerateResumePDFView(APIView):
    """
    POST /api/resume/candidates/generate-pdf
    """
    parser_classes = [JSONParser]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request) -> HttpResponse:
        serializer = GeneratePDFSerializer(data=request.data)
        if not serializer.is_valid():
            return HttpResponse(
                content=serializer.errors,
                content_type="application/json",
                status=status.HTTP_400_BAD_REQUEST,
            )

        html_content: str = serializer.validated_data["html"]

        t_start = time.perf_counter()
        try:
            service = PDFGeneratorService()
            pdf_bytes = service.generate_pdf(html_content)
        except PDFGenerationError as exc:
            logger.error(
                "PDF generation error for user %s: %s",
                getattr(request.user, "pk", "anonymous"),
                exc,
            )
            return HttpResponse(
                content={"detail": str(exc)},
                content_type="application/json",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.exception(
                "Unexpected PDF generation failure for user %s",
                getattr(request.user, "pk", "anonymous"),
            )
            return HttpResponse(
                content={"detail": "An unexpected error occurred while generating the PDF."},
                content_type="application/json",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        finally:
            elapsed = time.perf_counter() - t_start
            logger.info(
                "PDF generation completed in %.2fs for user %s",
                elapsed,
                getattr(request.user, "pk", "anonymous"),
            )

        response = HttpResponse(
            content=pdf_bytes,
            content_type="application/pdf",
            status=status.HTTP_200_OK,
        )
        response["Content-Disposition"] = 'attachment; filename="resume.pdf"'
        response["Content-Length"] = len(pdf_bytes)
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    
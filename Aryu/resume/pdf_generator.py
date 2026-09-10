"""
PDFGeneratorService — Production-grade, secure HTML → PDF conversion using WeasyPrint.
Includes extended diagnostic logging for detailed debugging.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import time
import traceback
import urllib.parse
from typing import Optional

import bleach
from bleach.css_sanitizer import CSSSanitizer
from django.conf import settings
from django.http import HttpResponse
from rest_framework import permissions, serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from weasyprint import HTML, default_url_fetcher

logger = logging.getLogger(__name__)

# Re-enable WeasyPrint warnings temporarily during debugging to capture layout/CSS issues
logging.getLogger("weasyprint").setLevel(logging.WARNING)

_MAX_HTML_BYTES: int = getattr(settings, "PDF_MAX_HTML_BYTES", 10 * 1024 * 1024)  # 10 MB
_MIN_HTML_LENGTH: int = 10
_MAX_RESOURCE_BYTES: int = 5 * 1024 * 1024  # 5 MB per resource
_RESOURCE_FETCH_TIMEOUT: int = 5  # 5 seconds socket timeout

# Allowed external domains for fonts and assets in resumes
_DEFAULT_ALLOWED_DOMAINS: frozenset[str] = frozenset({
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdnjs.cloudflare.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "ka-f.fontawesome.com",
})

# Elements to strip entirely along with their inner content
_DANGEROUS_BLOCK_ELEMENTS_REGEX = re.compile(
    r"<(script|noscript|template|object|embed|iframe|frame|frameset|canvas|audio|video|form|button|select|textarea|applet|base)\b[^>]*>[\s\S]*?</\1>",
    re.IGNORECASE,
)
_DANGEROUS_EMPTY_ELEMENTS_REGEX = re.compile(
    r"<(script|noscript|template|object|embed|iframe|frame|frameset|canvas|audio|video|form|input|button|select|textarea|applet|base|meta\s+http-equiv)\b[^>]*>",
    re.IGNORECASE,
)

# Inline event handlers like onclick=, onerror=, onload=
_EVENT_HANDLER_REGEX = re.compile(r"\s+on\w+\s*=\s*(?:'[^']*'|\"[^\"]*\"|[^\s>]+)", re.IGNORECASE)

# Dangerous protocols in attributes
_JAVASCRIPT_PROTOCOL_REGEX = re.compile(r"""(?:href|src|action|data)\s*=\s*['"]?\s*(?:javascript|vbscript):""", re.IGNORECASE)

# Dangerous CSS directives in style blocks or attributes
_DANGEROUS_CSS_IMPORT_REGEX = re.compile(r"""@import\s+(?:url\(['"]?|['"])(?:file:|javascript:|data:text/html)""", re.IGNORECASE)
_DANGEROUS_CSS_EXPRESSION_REGEX = re.compile(r"""expression\s*\(|-moz-binding|behavior\s*:""", re.IGNORECASE)

# Allowed tags for resume HTML rendering
_ALLOWED_HTML_TAGS = [
    "html", "head", "body", "style", "title", "meta", "link",
    "div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "b", "strong", "i", "em", "u", "s", "strike", "small", "sub", "sup",
    "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
    "hr", "br", "img", "a", "section", "header", "footer", "main", "article",
    "aside", "nav", "blockquote", "pre", "code", "font", "center", "abbr", "address",
    "svg", "path", "g", "circle", "rect", "line", "polyline", "polygon",
]

_ALLOWED_HTML_ATTRIBUTES = {
    "*": ["class", "id", "style", "dir", "lang", "title", "data-*"],
    "img": ["src", "alt", "title", "width", "height", "align", "valign", "border"],
    "a": ["href", "title", "target", "rel"],
    "link": ["rel", "href", "type", "media", "crossorigin"],
    "meta": ["charset", "name", "content"],
    "table": ["border", "cellpadding", "cellspacing", "width", "height", "align", "bgcolor", "summary"],
    "tr": ["align", "valign", "bgcolor"],
    "td": ["colspan", "rowspan", "align", "valign", "width", "height", "bgcolor"],
    "th": ["colspan", "rowspan", "align", "valign", "width", "height", "bgcolor"],
    "col": ["span", "width", "align"],
    "colgroup": ["span", "width"],
    "font": ["color", "size", "face"],
    "ol": ["type", "start", "reversed"],
    "ul": ["type"],
    "li": ["value", "type"],
    "svg": ["viewbox", "width", "height", "fill", "stroke", "xmlns"],
    "path": ["d", "fill", "stroke", "stroke-width"],
    "circle": ["cx", "cy", "r", "fill", "stroke"],
    "rect": ["x", "y", "width", "height", "rx", "ry", "fill", "stroke"],
}

_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "tel", "data"]

_CSS_SANITIZER = CSSSanitizer(
    allowed_css_properties=[
        "color", "background", "background-color", "background-image", "background-position",
        "background-repeat", "background-size", "background-attachment", "background-clip",
        "background-origin", "border", "border-top", "border-right", "border-bottom", "border-left",
        "border-color", "border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
        "border-style", "border-top-style", "border-right-style", "border-bottom-style", "border-left-style",
        "border-width", "border-top-width", "border-right-width", "border-bottom-width", "border-left-width",
        "border-radius", "border-top-left-radius", "border-top-right-radius", "border-bottom-left-radius", "border-bottom-right-radius",
        "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
        "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
        "width", "min-width", "max-width", "height", "min-height", "max-height",
        "box-sizing", "aspect-ratio", "font", "font-family", "font-size", "font-weight", "font-style", "font-variant", "font-stretch",
        "line-height", "letter-spacing", "word-spacing", "text-align", "text-decoration",
        "text-decoration-color", "text-decoration-line", "text-decoration-style",
        "text-transform", "text-indent", "text-overflow", "text-shadow", "vertical-align",
        "white-space", "word-break", "word-wrap", "overflow-wrap", "hyphens",
        "display", "flex", "flex-direction", "flex-wrap", "flex-flow", "justify-content",
        "align-items", "align-content", "align-self", "flex-grow", "flex-shrink", "flex-basis", "order",
        "gap", "row-gap", "column-gap", "grid", "grid-template-columns", "grid-template-rows", "grid-template-areas",
        "grid-auto-columns", "grid-auto-rows", "grid-auto-flow", "grid-column",
        "grid-column-start", "grid-column-end", "grid-row", "grid-row-start", "grid-row-end",
        "grid-area", "grid-gap", "position", "top", "right", "bottom", "left", "float", "clear", "z-index",
        "overflow", "overflow-x", "overflow-y", "visibility", "opacity", "clip-path", "transform", "transform-origin",
        "columns", "column-gap", "column-count", "column-fill", "column-rule", "column-span", "column-width",
        "table-layout", "border-collapse", "border-spacing", "caption-side", "empty-cells",
        "list-style", "list-style-type", "list-style-position", "list-style-image",
        "page-break-before", "page-break-after", "page-break-inside", "break-before",
        "break-after", "break-inside", "size", "orphans", "widows",
        "-webkit-print-color-adjust", "print-color-adjust", "color-adjust",
        "box-shadow", "filter", "backdrop-filter"
    ]
)


def safe_weasyprint_url_fetcher(url: str, timeout: int = _RESOURCE_FETCH_TIMEOUT, ssl_context=None):
    logger.debug("[PDF URL Fetcher] Requesting URL: %s", url[:150])
    if not url or not isinstance(url, str):
        logger.error("[PDF URL Fetcher Error] Invalid or empty URL.")
        raise PermissionError("Invalid or empty URL in PDF rendering.")

    parsed = urllib.parse.urlparse(url.strip())
    scheme = parsed.scheme.lower()

    if scheme in ("file", ""):
        logger.warning("[PDF URL Fetcher Blocked] Local file access attempt: %s", url[:100])
        raise PermissionError("Direct local file access is forbidden in PDF rendering.")

    if scheme == "data":
        allowed_data_prefixes = (
            "data:image/png;", "data:image/jpeg;", "data:image/jpg;",
            "data:image/webp;", "data:image/gif;", "data:image/svg+xml;",
            "data:font/woff2;", "data:font/woff;", "data:font/ttf;",
            "data:application/font-woff;", "data:application/x-font-ttf;",
        )
        url_lower = url.lower()
        if not any(url_lower.startswith(p) for p in allowed_data_prefixes):
            logger.warning("[PDF URL Fetcher Blocked] Disallowed data URI MIME type: %s", url[:50])
            raise PermissionError("Disallowed data URI format.")
        if len(url) > _MAX_RESOURCE_BYTES:
            logger.warning("[PDF URL Fetcher Blocked] Oversized data URI (%d bytes).", len(url))
            raise PermissionError("Data URI payload exceeds maximum allowed size.")
        return default_url_fetcher(url, timeout=timeout, ssl_context=ssl_context)

    if scheme in ("http", "https"):
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            raise PermissionError("Invalid URL hostname in PDF rendering.")

        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal") or \
           hostname.endswith((".localhost", ".local", ".internal", ".corp", ".lan", ".home")):
            logger.warning("[PDF URL Fetcher Blocked] Local/internal hostname SSRF attempt: %s", hostname)
            raise PermissionError("Access to internal hostnames is forbidden.")

        allowed_domains = _DEFAULT_ALLOWED_DOMAINS
        custom_domains = getattr(settings, "PDF_ALLOWED_DOMAINS", None)
        if custom_domains:
            allowed_domains = allowed_domains | frozenset(d.lower() for d in custom_domains)

        is_domain_allowed = (
            hostname in allowed_domains or
            any(hostname.endswith("." + d) for d in allowed_domains)
        )
        if not is_domain_allowed:
            logger.warning("[PDF URL Fetcher Blocked] Unapproved external domain: %s", hostname)
            raise PermissionError(f"External domain '{hostname}' is not in the allowed resources list.")

        try:
            port = parsed.port or (443 if scheme == "https" else 80)
            addr_info = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for family, socktype, proto, canonname, sockaddr in addr_info:
                ip_str = sockaddr[0]
                ip = ipaddress.ip_address(ip_str)
                if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                    logger.warning("[PDF URL Fetcher Blocked] SSRF attempt to internal IP %s for host %s", ip_str, hostname)
                    raise PermissionError(f"Access to internal IP address {ip_str} is forbidden.")
        except socket.gaierror:
            logger.warning("[PDF URL Fetcher Warning] Failed to resolve hostname: %s", hostname)
            if "fonts.googleapis.com" in hostname or "fonts.gstatic.com" in hostname:
                return {"string": b"/* font fallback */", "mime_type": "text/css"}
            raise PermissionError(f"Failed to resolve host '{hostname}'.")

        try:
            return default_url_fetcher(
                url,
                timeout=min(timeout or _RESOURCE_FETCH_TIMEOUT, _RESOURCE_FETCH_TIMEOUT),
                ssl_context=ssl_context,
            )
        except Exception as fetch_err:
            logger.warning("[PDF URL Fetcher Failed] Resource fetch error %s: %s", url[:100], fetch_err)
            if "fonts.googleapis.com" in hostname or "fonts.gstatic.com" in hostname:
                return {"string": b"/* font fallback */", "mime_type": "text/css"}
            raise PermissionError(f"Resource fetch failed: {fetch_err}") from fetch_err

    raise PermissionError(f"URL scheme '{scheme}' is forbidden in PDF rendering.")


_PRINT_CSS = """
<style id="__pdf_print_inject__">
  @page {
    size: A4;
    margin: 8mm;
  }
  html, body {
    margin: 0;
    padding: 0;
  }
  * {
    box-sizing: border-box;
  }
  .page-break-before { page-break-before: always; break-before: page; }
  .page-break-after  { page-break-after:  always; break-after: page; }
  .avoid-break       { page-break-inside: avoid; break-inside: avoid; }
  @media print {
    a[href]::after { content: none !important; }
  }
</style>
"""


class GeneratePDFSerializer(serializers.Serializer):
    html = serializers.CharField(
        required=True,
        allow_blank=False,
        help_text="A complete HTML document string to render as a PDF.",
    )
    filename = serializers.CharField(
        required=False,
        allow_blank=True,
        default="resume.pdf",
        max_length=120,
        help_text="Optional custom filename for the downloaded PDF.",
    )

    def validate_html(self, value: str) -> str:
        if not isinstance(value, str):
            raise serializers.ValidationError("The html field must be a valid string.")

        value = value.strip()

        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, str):
                    value = parsed.strip()
            except (ValueError, TypeError, json.JSONDecodeError):
                pass

        if r'\"' in value or r'\n' in value or r'\r' in value or r'\t' in value:
            value = (
                value.replace(r'\"', '"')
                     .replace(r'\n', '\n')
                     .replace(r'\r', '\r')
                     .replace(r'\t', '\t')
            )

        if len(value) < _MIN_HTML_LENGTH:
            raise serializers.ValidationError("The html field is too short to be a valid HTML document.")

        byte_size = len(value.encode("utf-8"))
        if byte_size > _MAX_HTML_BYTES:
            max_mb = _MAX_HTML_BYTES / (1024 * 1024)
            raise serializers.ValidationError(
                f"HTML payload size ({byte_size / (1024 * 1024):.1f} MB) "
                f"exceeds the maximum allowed size ({max_mb:.0f} MB)."
            )

        return value


class PDFGenerationError(Exception):
    """Raised when PDF rendering fails."""


class PDFGeneratorService:
    def generate_pdf(self, html_content: str) -> bytes:
        t0 = time.perf_counter()
        logger.info("[PDFGeneratorService] Step 1: Starting PDF generation process...")

        if not html_content or not isinstance(html_content, str):
            raise PDFGenerationError("HTML content must be a non-empty string.")

        self._validate_html(html_content)
        t_val = time.perf_counter()
        logger.info("[PDFGeneratorService] Step 2: HTML validation passed (%.3fs)", t_val - t0)

        clean_html = self._sanitize_html(html_content)
        t_san = time.perf_counter()
        logger.info("[PDFGeneratorService] Step 3: HTML sanitization passed (%.3fs)", t_san - t_val)

        final_html = self._inject_print_css(clean_html)

        try:
            logger.info("[PDFGeneratorService] Step 4: Invoking Weasyprint engine...")
            pdf_bytes = HTML(
                string=final_html,
                base_url=None,
                url_fetcher=safe_weasyprint_url_fetcher,
            ).write_pdf()
            
            t_render = time.perf_counter()
            logger.info("[PDFGeneratorService] Step 5: WeasyPrint output generated (%d bytes in %.3fs)", len(pdf_bytes), t_render - t_san)
            return pdf_bytes
        except Exception as exc:
            logger.error("[PDFGeneratorService Error] Exception during write_pdf: %s", exc)
            logger.error("[PDFGeneratorService Traceback]\n%s", traceback.format_exc())
            raise PDFGenerationError(f"PDF rendering failed: {exc}") from exc

    def _validate_html(self, html: str) -> None:
        if not html or not html.strip():
            raise PDFGenerationError("HTML content must not be empty.")
        byte_size = len(html.encode("utf-8"))
        if byte_size > _MAX_HTML_BYTES:
            max_mb = _MAX_HTML_BYTES // (1024 * 1024)
            raise PDFGenerationError(f"HTML payload exceeds maximum size ({max_mb} MB).")

    def _sanitize_html(self, html: str) -> str:
        try:
            html = _DANGEROUS_BLOCK_ELEMENTS_REGEX.sub("", html)
            html = _DANGEROUS_EMPTY_ELEMENTS_REGEX.sub("", html)
            html = _EVENT_HANDLER_REGEX.sub("", html)
            html = _JAVASCRIPT_PROTOCOL_REGEX.sub('src=""', html)
            html = _DANGEROUS_CSS_IMPORT_REGEX.sub("/* blocked import */", html)
            html = _DANGEROUS_CSS_EXPRESSION_REGEX.sub("/* blocked expr */", html)

            styles = []

            def _extract_style(match):
                styles.append(match.group(1))
                return f"<!--__STYLE_PLACEHOLDER_{len(styles) - 1}__-->"

            style_pattern = re.compile(r"<style\b[^>]*>([\s\S]*?)</style>", re.IGNORECASE)
            html_without_styles = style_pattern.sub(_extract_style, html)

            cleaned = bleach.clean(
                html_without_styles,
                tags=_ALLOWED_HTML_TAGS,
                attributes=_ALLOWED_HTML_ATTRIBUTES,
                protocols=_ALLOWED_PROTOCOLS,
                css_sanitizer=_CSS_SANITIZER,
                strip=True,
                strip_comments=False,
            )

            for idx, raw_css in enumerate(styles):
                cleaned = cleaned.replace(
                    f"<!--__STYLE_PLACEHOLDER_{idx}__-->",
                    f"<style>{raw_css}</style>"
                )

            return cleaned
        except Exception as e:
            logger.error("[PDFGeneratorService Sanitization Error]: %s\n%s", e, traceback.format_exc())
            raise PDFGenerationError(f"Failed to sanitize HTML payload: {e}")

    def _inject_print_css(self, html: str) -> str:
        head_close = re.search(r"</head>", html, re.IGNORECASE)
        if head_close:
            pos = head_close.start()
            return html[:pos] + _PRINT_CSS + html[pos:]
        
        html_open = re.search(r"<html[^>]*>", html, re.IGNORECASE)
        if html_open:
            pos = html_open.end()
            return html[:pos] + _PRINT_CSS + html[pos:]

        return _PRINT_CSS + html


class GenerateResumePDFView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = []

    def post(self, request) -> HttpResponse:
        user_identifier = getattr(request.user, "pk", "anonymous")
        logger.info("[GenerateResumePDFView] Processing incoming request for user: %s", user_identifier)

        serializer = GeneratePDFSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("[GenerateResumePDFView] Validation failed for user %s: %s", user_identifier, serializer.errors)
            return Response(
                {"error": "Invalid request parameters", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        html_content: str = serializer.validated_data["html"]
        filename: str = serializer.validated_data.get("filename") or "resume.pdf"

        t_start = time.perf_counter()

        try:
            service = PDFGeneratorService()
            pdf_bytes = service.generate_pdf(html_content)
        except PDFGenerationError as exc:
            logger.error("[GenerateResumePDFView Error] PDFGenerationError for user %s: %s", user_identifier, exc)
            return Response(
                {"error": f"Failed to generate PDF: {str(exc)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.exception("[GenerateResumePDFView Exception] Unexpected error for user %s: %s", user_identifier, exc)
            return Response(
                {"error": f"An unexpected error occurred while generating the PDF: {str(exc)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        finally:
            elapsed = time.perf_counter() - t_start
            logger.info("[GenerateResumePDFView] Execution completed in %.2fs for user %s", elapsed, user_identifier)

        response = HttpResponse(
            content=pdf_bytes,
            content_type="application/pdf",
            status=status.HTTP_200_OK,
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Content-Length"] = len(pdf_bytes)
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["X-Content-Type-Options"] = "nosniff"
        return response
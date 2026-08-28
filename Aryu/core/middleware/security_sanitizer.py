# aryuapp/middleware/security_sanitizer.py
import html
import json
import logging
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied, ValidationError
try:
    import bleach
except ImportError:
    bleach = None

logger = logging.getLogger(__name__)

# Standard allowed tags for rich-text descriptions (e.g. Resume descriptions, summaries, Quill lists)
RICH_TEXT_ALLOWED_TAGS = [
    "p", "br", "strong", "b", "em", "i", "u", "s", "strike",
    "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "a", "span", "div", "blockquote", "code", "pre", "sub", "sup",
    "table", "thead", "tbody", "tr", "th", "td",
    "hr",
]

RICH_TEXT_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "span": ["class", "contenteditable"],
    "li": ["class", "data-list"],
    "p": ["class"],
    "div": ["class"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
    "*": ["class", "data-list", "contenteditable"],
}

RICH_TEXT_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]

RICH_TEXT_KEYS = {
    "description",
    "content",
    "body",
    "notes",
    "message",
    "html",
    "html_markup",
    "summary",
    "responsibilities",
    "achievements",
    "details",
    "bio",
    "profile",
    "about",
    "cover_letter",
    "custom_section",
    "text",
    "statement",
    "resume_data",
    "section_payload",
}

PASS_THROUGH_KEYS = {
    "password",
    "new_password",
    "confirm_password",
    "old_password",
    "current_password",
}


class InputSanitizationMiddleware(MiddlewareMixin):
    """
    Enterprise-grade input sanitization, type-hardening, and fallback exception handling.
    Protects against:
      - Denial of Service (DoS) from nested query payload injections (e.g. {"$ne": null}).
      - Unexpected Type/Value database casting crashes (translates 500s into clean 400s).
      - XSS script injections on string endpoints while preserving safe rich-text HTML for authorized fields.
    """

    def process_request(self, request):
        # Skip sanitization for HTML -> PDF endpoint and Webhooks (preserves exact raw request bytes for HMAC)
        if request.path.startswith("/api/resume/candidates/generate-pdf") or "webhook" in request.path.lower():
            return None

        if request.method in ["POST", "PUT", "PATCH"]:
            if request.content_type == "application/json":
                try:
                    if not request.body:
                        return None

                    is_resume_request = (
                        request.path.startswith("/api/resume/user-resumes") or
                        request.path.startswith("/api/resume/templates") or
                        request.path.startswith("/api/resumes")
                    )

                    raw_data = json.loads(request.body)
                    sanitized_data = self.sanitize_data(raw_data, is_rich_text=is_resume_request)
                    encoded_data = json.dumps(sanitized_data).encode("utf-8")
                    request._body = encoded_data

                except json.JSONDecodeError:
                    return JsonResponse(
                        {"error": "Malformed JSON payload format."},
                        status=400
                    )

                except Exception as e:
                    logger.error(f"Request sanitization failed: {str(e)}")
                    return JsonResponse(
                        {"error": "Invalid request parameters detected."},
                        status=400
                    )

        return None

    def sanitize_rich_text(self, text: str) -> str:
        """
        Sanitizes rich-text strings by preserving valid formatting tags and stripping unsafe XSS vectors.
        """
        if bleach:
            return bleach.clean(
                text.strip(),
                tags=RICH_TEXT_ALLOWED_TAGS,
                attributes=RICH_TEXT_ALLOWED_ATTRIBUTES,
                protocols=RICH_TEXT_ALLOWED_PROTOCOLS,
                strip=True,
                strip_comments=True,
            )
        return text.strip()

    def sanitize_plain_text(self, text: str) -> str:
        """
        Strips all HTML tags from plain text inputs to prevent XSS.
        """
        if bleach:
            return bleach.clean(
                text.strip(),
                tags=[],
                attributes={},
                protocols=["http", "https"],
                strip=True,
                strip_comments=True,
            )
        return html.escape(text.strip())

    def sanitize_data(self, data, depth=0, is_rich_text=False):
        if depth > 10:
            raise PermissionDenied("Payload nesting depth threshold exceeded.")

        if isinstance(data, dict):
            cleaned_dict = {}

            for key, value in data.items():
                # Block MongoDB operators
                if isinstance(key, str) and key.startswith("$"):
                    logger.warning(
                        f"NoSQL injection pattern key '{key}' detected and blocked."
                    )
                    continue

                # Preserve sensitive password fields untouched
                if key in PASS_THROUGH_KEYS:
                    cleaned_dict[key] = value
                    continue

                # Determine whether this field or child context should preserve safe rich-text HTML
                field_is_rich = is_rich_text or (isinstance(key, str) and key.lower() in RICH_TEXT_KEYS)

                if isinstance(value, str):
                    if field_is_rich:
                        cleaned_dict[key] = self.sanitize_rich_text(value)
                    else:
                        cleaned_dict[key] = self.sanitize_plain_text(value)
                else:
                    cleaned_dict[key] = self.sanitize_data(value, depth + 1, is_rich_text=field_is_rich)

            return cleaned_dict

        elif isinstance(data, list):
            cleaned_list = []
            for item in data:
                if isinstance(item, str):
                    if is_rich_text:
                        cleaned_list.append(self.sanitize_rich_text(item))
                    else:
                        cleaned_list.append(self.sanitize_plain_text(item))
                else:
                    cleaned_list.append(self.sanitize_data(item, depth + 1, is_rich_text=is_rich_text))
            return cleaned_list

        elif isinstance(data, str):
            if is_rich_text:
                return self.sanitize_rich_text(data)
            return self.sanitize_plain_text(data)

        return data

    def process_exception(self, request, exception):
        """
        Catches database lookup casting failures (like a dictionary passed to an Integer PK field lookup)
        globally and gracefully translates them to a standard HTTP 400 Bad Request instead of an HTTP 500 crash.
        """
        if isinstance(exception, (ValueError, TypeError, ValidationError)):
            logger.warning(f"Prevented view crash from malformed database input query lookup: {str(exception)}")
            return JsonResponse(
                {
                    "success": False,
                    "message": "Invalid argument types provided for parameter lookup queries."
                }, 
                status=400
            )
        return None
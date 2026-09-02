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

# Rich-text fields specifically recognized within the resume builder app
RESUME_RICH_TEXT_FIELDS = {
    "text",
    "description",
    "summary",
    "html_markup",
    "html",
    "responsibilities",
    "achievements",
    "cover_letter",
    "bio",
    "content",
    "body",
}

PASS_THROUGH_KEYS = {
    "password",
    "new_password",
    "confirm_password",
    "old_password",
    "current_password",
    "description",
}


class InputSanitizationMiddleware(MiddlewareMixin):
    """
    Enterprise-grade input sanitization, type-hardening, and fallback exception handling.
    Protects against:
      - Denial of Service (DoS) from nested query payload injections (e.g. {"$ne": null}).
      - Unexpected Type/Value database casting crashes (translates 500s into clean 400s).
      - XSS script injections on string endpoints while preserving safe rich-text HTML for authorized fields.
    """

    def is_resume_builder_request(self, request) -> bool:
        """
        Determines whether the incoming request is targeting the resume builder APIs.
        """
        path = getattr(request, "path", "")
        return (
            path.startswith("/api/resume/user-resumes") or
            path.startswith("/api/resume/templates") or
            path.startswith("/api/resumes")
        )

    def process_request(self, request):
        # Skip sanitization for HTML -> PDF endpoint and Webhooks (preserves exact raw request bytes for HMAC)
        if request.path.startswith("/api/resume/candidates/generate-pdf") or "webhook" in request.path.lower():
            return None

        if request.method in ["POST", "PUT", "PATCH"]:
            if request.content_type == "application/json":
                try:
                    if not request.body:
                        return None

                    is_resume_context = self.is_resume_builder_request(request)

                    raw_data = json.loads(request.body)
                    sanitized_data = self.sanitize_data(raw_data, is_resume_context=is_resume_context)
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

    def sanitize_data(self, data, depth=0, is_resume_context=False, current_field_is_rich=False):
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
                field_is_rich = (
                    is_resume_context and
                    isinstance(key, str) and
                    key.lower() in RESUME_RICH_TEXT_FIELDS
                )

                if isinstance(value, str):
                    if field_is_rich:
                        cleaned_dict[key] = self.sanitize_rich_text(value)
                    else:
                        cleaned_dict[key] = self.sanitize_plain_text(value)
                else:
                    cleaned_dict[key] = self.sanitize_data(
                        value,
                        depth=depth + 1,
                        is_resume_context=is_resume_context,
                        current_field_is_rich=field_is_rich,
                    )

            return cleaned_dict

        elif isinstance(data, list):
            cleaned_list = []
            for item in data:
                if isinstance(item, str):
                    if current_field_is_rich:
                        cleaned_list.append(self.sanitize_rich_text(item))
                    else:
                        cleaned_list.append(self.sanitize_plain_text(item))
                else:
                    cleaned_list.append(
                        self.sanitize_data(
                            item,
                            depth=depth + 1,
                            is_resume_context=is_resume_context,
                            current_field_is_rich=current_field_is_rich,
                        )
                    )
            return cleaned_list

        elif isinstance(data, str):
            if current_field_is_rich:
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
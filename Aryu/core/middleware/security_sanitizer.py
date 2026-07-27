# aryuapp/middleware/security_sanitizer.py
import html
import json
import logging
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied, ValidationError

logger = logging.getLogger(__name__)

class InputSanitizationMiddleware(MiddlewareMixin):
    """
    Enterprise-grade input sanitization, type-hardening, and fallback exception handling.
    Protects against:
      - Denial of Service (DoS) from nested query payload injections (e.g. {"$ne": null}).
      - Unexpected Type/Value database casting crashes (translates 500s into clean 400s).
      - XSS script injections on string endpoints.
    """

    def process_request(self, request):

        # Skip sanitization for HTML → PDF endpoint
        if request.path.startswith("/api/resume/candidates/generate-pdf"):
            return None

        if request.method in ["POST", "PUT", "PATCH"]:
            if request.content_type == "application/json":
                try:
                    if not request.body:
                        return None

                    raw_data = json.loads(request.body)

                    sanitized_data = self.sanitize_data(raw_data)

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

    def sanitize_data(self, data, depth=0):

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

                # Allow HTML for rich text fields
                if key in [
                    "description",
                    "content",
                    "body",
                    "notes",
                    "message",
                    "html"
                ]:
                    if isinstance(value, str):
                        cleaned_dict[key] = value.strip()
                    else:
                        cleaned_dict[key] = self.sanitize_data(value, depth + 1)

                else:
                    cleaned_dict[key] = self.sanitize_data(value, depth + 1)

            return cleaned_dict

        elif isinstance(data, list):
            return [self.sanitize_data(item, depth + 1) for item in data]

        elif isinstance(data, str):
            print("ESCAPING STRING:", data)
            return html.escape(data.strip())
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
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

    HTML_ALLOWED_PATHS = [
        "/api/resume/candidates/generate-pdf",
        "/api/resume/user-resumes",
        "/api/resume/create-plan/",
        "/api/resume/update-plan/",
    ]

    def process_request(self, request):

        # Skip sanitization for HTML → PDF endpoint
        if self.is_html_allowed(request.path):
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
        """
        Recursively clean and escape inputs. 
        Enforces defensive max depth bounds to block deep recursive stack-exhaustion payloads.
        """
        if depth > 10:
            raise PermissionDenied("Payload nesting depth threshold exceeded.")

        if isinstance(data, dict):
            # Block MongoDB NoSQL style operators completely (e.g. keys starting with $)
            cleaned_dict = {}
            for k, v in data.items():
                if isinstance(k, str) and k.startswith("$"):
                    logger.warning(f"NoSQL injection pattern key '{k}' detected and blocked.")
                    continue
                cleaned_dict[k] = self.sanitize_data(v, depth + 1)
            return cleaned_dict

        elif isinstance(data, list):
            return [self.sanitize_data(item, depth + 1) for item in data]

        elif isinstance(data, str):
            # Escapes <script> tag blocks to safe equivalents and strip trailing spaces
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
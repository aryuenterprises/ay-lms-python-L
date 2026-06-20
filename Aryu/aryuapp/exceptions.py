from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)

def extract_first_error_message(errors):
    """
    Recursively extracts the first error message from a nested DRF error dict or list.
    """
    if isinstance(errors, list) and errors:
        # Handles cases where the error message might be a nested dict or list inside a list
        return extract_first_error_message(errors[0])
    elif isinstance(errors, dict):
        # Extract messages from common DRF fields first if available
        for key in ['detail', 'non_field_errors', 'error']:
            if key in errors:
                return extract_first_error_message(errors[key])
        # Fallback to the first available key's value
        for value in errors.values():
            return extract_first_error_message(value)
    return str(errors)

def custom_exception_handler(exc, context):
    # 1. Call DRF's default exception handler to catch known API exceptions (like ValidationError)
    response = exception_handler(exc, context)

    if response is not None:
        # --- CASE A: KNOWN DRF EXCEPTION (Validation Errors, 401 Unauthorized, 403 Forbidden, etc.) ---
        message = extract_first_error_message(response.data)
        
        response.data = {
            "success": False,
            "message": message
        }
    else:
        # --- CASE B: UNHANDLED PYTHON RUNTIME CRASH (The P1 Security Vulnerability Fix) ---
        # Log the full stack trace securely to your server logs so you can find and debug it
        logger.error(f"CRITICAL SYSTEM UNHANDLED EXCEPTION: {str(exc)}", exc_info=True)

        # Build a safe response back to the client to gracefully prevent Nginx from collapsing into a 502
        response = Response(
            {
                "success": False,
                "message": "An unexpected server error occurred. Please try again later."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return response
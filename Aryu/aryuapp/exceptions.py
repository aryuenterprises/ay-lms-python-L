from rest_framework.views import exception_handler
from rest_framework.response import Response

def extract_first_error_message(errors):
    """
    Recursively extracts the first error message from a nested DRF error dict.
    """
    if isinstance(errors, list) and errors:
        return str(errors[0])
    elif isinstance(errors, dict):
        for value in errors.values():
            return extract_first_error_message(value)
    return str(errors)

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        if isinstance(response.data, dict):
            if 'detail' in response.data:
                message = str(response.data['detail'])
            else:
                message = extract_first_error_message(response.data)
            response.data = {
                "success": False,
                "message": message
            }
        else:
            response.data = {
                "success": False,
                "message": str(response.data)
            }

    return response

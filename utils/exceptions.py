from rest_framework.views import exception_handler
from rest_framework.response import Response
from django.utils import timezone

def custom_exception_handler(exc, context):
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)
    
    if response is not None:
        # Extract error details
        error_data = response.data
        
        # Determine message and errors
        if isinstance(error_data, dict):
            message = error_data.get('detail', 'An error occurred')
            # Remove 'detail' from errors if it exists
            errors = {k: v for k, v in error_data.items() if k != 'detail'}
            if not errors:
                errors = None
        else:
            message = 'An error occurred'
            errors = error_data if error_data else None
        
        custom_response = {
            "success": False,
            "statusCode": response.status_code,
            "message": message,
            "timestamp": timezone.now().isoformat(),
            "data": None,
            "errors": errors
        }
        response.data = custom_response
    
    return response
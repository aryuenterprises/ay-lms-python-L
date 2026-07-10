from django.shortcuts import render

# Create your views here.
import time
from functools import wraps
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework import status

def get_client_ip(request):
    """Safely extracts the true client IP, even behind Nginx/Cloudflare proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def apply_custom_throttle(request, rate_limit=5, period=60):
    """
    Common Rate Limiting Gateway.
    Default: Max 5 requests per 60 seconds (1 minute).
    Returns (True, None) if allowed, or (False, Response) if throttled.
    """
    ip_address = get_client_ip(request)
    user_id = request.user.user_id if request.user and request.user.is_authenticated else "anonymous"
    
    # Create a unique cache key combining user context and IP address
    cache_key = f"throttle_{user_id}_{ip_address}_{request.path}"
    
    # Fetch timestamps of previous requests
    request_history = cache.get(cache_key, [])
    current_time = time.time()
    
    # Keep only the requests that happened within the valid sliding window period
    request_history = [timestamp for timestamp in request_history if current_time - timestamp < period]
    
    if len(request_history) >= rate_limit:
        # Calculate how many seconds they must wait before trying again
        retry_after = int(period - (current_time - request_history[0]))
        
        return False, Response({
            "success": False,
            "message": "Too many requests. Please slow down.",
            "retry_after_seconds": max(1, retry_after)
        }, status=status.HTTP_429_TOO_MANY_REQUESTS) # 429 is the standard HTTP code for rate limits
        
    # Record the current request timestamp and save back to fast cache memory
    request_history.append(current_time)
    cache.set(cache_key, request_history, timeout=period)
    
    return True, None


def secure_throttle(rate_limit=5, period=60):
    """Decorator to easily wrap any class method action."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(self, request, *args, **kwargs):
            is_allowed, throttle_response = apply_custom_throttle(request, rate_limit, period)
            if not is_allowed:
                return throttle_response
            return view_func(self, request, *args, **kwargs)
        return _wrapped_view
    return decorator
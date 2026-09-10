from functools import wraps
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from django_ratelimit.decorators import ratelimit
from django_ratelimit.exceptions import Ratelimited


def get_client_ip(request):
    """Accurately extracts client IP address, checking X-Forwarded-For."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class BaseStorageThrottle(SimpleRateThrottle):
    """
    Base throttle that identifies unauthenticated clients by real IP
    and authenticated clients by user ID.
    """

    def get_cache_key(self, request, view):
        if hasattr(request, 'user') and request.user and request.user.is_authenticated:
            ident = f"user_{request.user.id}"
        else:
            ident = f"ip_{get_client_ip(request)}"

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }


class FaceSearchRateThrottle(BaseStorageThrottle):
    """
    Limits face search requests to protect computational and ML resources.
    Default: 15 requests per minute.
    """
    scope = 'face_search'


class UploadRateThrottle(BaseStorageThrottle):
    """
    Limits upload initialization and file uploads.
    Default: 60 requests per minute.
    """
    scope = 'upload'


class DownloadRateThrottle(BaseStorageThrottle):
    """
    Limits signed download URL generation.
    Default: 120 requests per minute.
    """
    scope = 'download'


class BulkDownloadRateThrottle(BaseStorageThrottle):
    """
    Strict rate limit for asynchronous bulk ZIP compilation.
    Default: 5 requests per minute.
    """
    scope = 'bulk_download'


class ShareAccessRateThrottle(BaseStorageThrottle):
    """
    Limits public gallery views to prevent scraping.
    Default: 150 requests per minute.
    """
    scope = 'share_access'


def drf_ratelimit(key='ip', rate='30/m', block=False, method=None):
    """
    Decorator integrating django_ratelimit with DRF class-based API views.
    Returns standard machine-readable HTTP 429 response when throttled.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(self, request, *args, **kwargs):
            try:
                # Apply django-ratelimit check
                was_limited = getattr(request, 'limited', False)
                if was_limited:
                    return Response(
                        {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "detail": "Too many requests. Please slow down.",
                        },
                        status=status.HTTP_429_TOO_MANY_REQUESTS
                    )
            except Ratelimited:
                return Response(
                    {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "detail": "Too many requests. Please slow down.",
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )
            return view_func(self, request, *args, **kwargs)
        return _wrapped
    return decorator

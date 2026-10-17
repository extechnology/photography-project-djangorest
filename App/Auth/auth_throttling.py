import logging
from rest_framework.throttling import SimpleRateThrottle

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Accurately extracts client IP address, checking proxy headers."""
    if not request:
        return '127.0.0.1'
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    x_real_ip = request.META.get('HTTP_X_REAL_IP')
    if x_real_ip:
        return x_real_ip.strip()
    return request.META.get('REMOTE_ADDR') or '127.0.0.1'


class BaseAuthThrottle(SimpleRateThrottle):
    """
    Base throttle for authentication and security endpoints.
    Tracks unauthenticated requests by IP and authenticated users by user ID.
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


class LoginRateThrottle(SimpleRateThrottle):
    """
    Strict rate limit on login attempts to prevent credential brute-forcing.
    Tracks by combination of client IP and targeted username/identifier.
    Default: 10 requests per minute.
    """
    scope = 'login'

    def get_cache_key(self, request, view):
        ip = get_client_ip(request)
        identifier = ''
        if hasattr(request, 'data') and isinstance(request.data, dict):
            identifier = (
                request.data.get('username')
                or request.data.get('email')
                or request.data.get('identifier')
                or ''
            ).strip().lower()

        ident = f"{ip}_{identifier}" if identifier else f"ip_{ip}"
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }


class RegisterRateThrottle(SimpleRateThrottle):
    """
    Limits account registrations to prevent automated bot signups.
    Tracks by client IP.
    Default: 10 requests per minute.
    """
    scope = 'register'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': f"ip_{get_client_ip(request)}"
        }


class OTPSendRateThrottle(SimpleRateThrottle):
    """
    Strictly throttles OTP generation and resend calls to prevent email/SMS bombing.
    Tracks by IP and the recipient's email/phone/identifier.
    Default: 5 requests per minute.
    """
    scope = 'otp_send'

    def get_cache_key(self, request, view):
        ip = get_client_ip(request)
        target = ''
        if hasattr(request, 'data') and isinstance(request.data, dict):
            target = (
                request.data.get('email')
                or request.data.get('phone')
                or request.data.get('identifier')
                or request.data.get('username')
                or ''
            ).strip().lower()

        ident = f"{ip}_{target}" if target else f"ip_{ip}"
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }


class OTPVerifyRateThrottle(SimpleRateThrottle):
    """
    Strictly throttles OTP verification attempts to prevent brute-forcing 6-digit codes.
    Tracks by IP and the identifier being verified.
    Default: 10 requests per minute.
    """
    scope = 'otp_verify'

    def get_cache_key(self, request, view):
        ip = get_client_ip(request)
        target = ''
        if hasattr(request, 'data') and isinstance(request.data, dict):
            target = (
                request.data.get('email')
                or request.data.get('phone')
                or request.data.get('identifier')
                or request.data.get('username')
                or ''
            ).strip().lower()

        ident = f"{ip}_{target}" if target else f"ip_{ip}"
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }


class PasswordResetRateThrottle(SimpleRateThrottle):
    """
    Limits password change and reset requests.
    Default: 5 requests per minute.
    """
    scope = 'password_reset'

    def get_cache_key(self, request, view):
        if hasattr(request, 'user') and request.user and request.user.is_authenticated:
            ident = f"user_{request.user.id}"
        else:
            ident = f"ip_{get_client_ip(request)}"

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }


class OAuthRateThrottle(SimpleRateThrottle):
    """
    Limits Google / social OAuth verification attempts.
    Default: 20 requests per minute.
    """
    scope = 'oauth'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': f"ip_{get_client_ip(request)}"
        }


class TokenRefreshRateThrottle(SimpleRateThrottle):
    """
    Limits JWT token refresh calls.
    Default: 60 requests per minute.
    """
    scope = 'token_refresh'

    def get_cache_key(self, request, view):
        if hasattr(request, 'user') and request.user and request.user.is_authenticated:
            ident = f"user_{request.user.id}"
        else:
            ident = f"ip_{get_client_ip(request)}"

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }


class AvailabilityCheckRateThrottle(SimpleRateThrottle):
    """
    Limits real-time username and identifier availability checks to prevent user enumeration.
    Default: 45 requests per minute.
    """
    scope = 'availability_check'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': f"ip_{get_client_ip(request)}"
        }

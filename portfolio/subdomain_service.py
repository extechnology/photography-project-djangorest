import re
from typing import Optional, Tuple, Dict, Any
from django.conf import settings
from .models import PortfolioConfig, ReservedSubdomain

DEFAULT_RESERVED_SUBDOMAINS = {
    'www', 'app', 'api', 'admin', 'auth', 'mail', 'smtp', 'pop', 'imap',
    'ftp', 'static', 'media', 'cdn', 'support', 'staging', 'dev', 'stage',
    'test', 'status', 'dashboard', 'billing', 'assets', 'culling', 'gallery',
    'galleries', 'events', 'storage', 'login', 'signup', 'register', 'root',
    'exshare', 'atelier', 'help', 'docs', 'ws', 'socket', 'portal', 'internal',
    'public', 'private', 'secure', 'ssl', 'vpn', 'ns', 'ns1', 'ns2', 'mx',
    'smtp1', 'smtp2', 'autodiscover', 'autoconfig', 'webmail', 'demo', 'blog',
    'shop', 'store', 'checkout', 'pay', 'payments', 'webhook', 'webhooks',
    'account', 'accounts', 'server', 'srv', 'node', 'edge', 'origin'
}

SUBDOMAIN_REGEX = re.compile(r'^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$')


def get_reserved_subdomains() -> set[str]:
    """Returns the set of all reserved infrastructure and service names."""
    configured = getattr(settings, 'RESERVED_SUBDOMAINS', []) or []
    return DEFAULT_RESERVED_SUBDOMAINS.union(set(str(c).strip().lower() for c in configured if c))


def normalize_subdomain(name: Optional[str]) -> str:
    """Normalizes a subdomain label to lowercase stripped string."""
    return (name or '').strip().lower()


def validate_subdomain_label(label: str) -> Tuple[bool, Optional[str]]:
    """
    Validates a subdomain label against RFC 1035 / DNS rules:
    - 3 to 63 ASCII characters
    - Lowercase letters, digits, and internal hyphens
    - No leading/trailing hyphens, dots, underscores, or spaces
    - Not a reserved infrastructure/service name

    Returns (is_valid, error_reason)
    """
    if not label:
        return False, "Subdomain cannot be empty."

    norm = normalize_subdomain(label)
    if len(norm) < 3:
        return False, "Subdomain must be at least 3 characters long."
    if len(norm) > 63:
        return False, "Subdomain cannot exceed 63 characters."

    if norm.startswith('-') or norm.endswith('-'):
        return False, "Subdomain cannot begin or end with a hyphen."

    if not SUBDOMAIN_REGEX.match(norm):
        return False, "Subdomain may only contain lowercase letters, numbers, and internal hyphens."

    reserved = get_reserved_subdomains()
    if norm in reserved:
        return False, f"The name '{norm}' is reserved for platform infrastructure."

    if ReservedSubdomain.objects.filter(name=norm).exists():
        return False, f"The subdomain '{norm}' is reserved and unavailable."

    return True, None


def check_subdomain_availability(name: str, current_user=None) -> Dict[str, Any]:
    """
    Checks if a normalized subdomain name is available for registration.
    Returns:
      {
        "name": str,
        "available": bool,
        "reason": Optional[str],
        "is_current_owner": bool
      }
    """
    norm = normalize_subdomain(name)
    is_valid, validation_error = validate_subdomain_label(norm)
    if not is_valid:
        return {
            "name": norm,
            "available": False,
            "reason": validation_error,
            "is_current_owner": False
        }

    existing = PortfolioConfig.objects.filter(subdomain=norm).first()
    if existing:
        if current_user and existing.user_id == getattr(current_user, 'id', None):
            return {
                "name": norm,
                "available": True,
                "reason": "already_owned",
                "is_current_owner": True
            }
        return {
            "name": norm,
            "available": False,
            "reason": "already_taken",
            "is_current_owner": False
        }

    return {
        "name": norm,
        "available": True,
        "reason": None,
        "is_current_owner": False
    }


def resolve_portfolio_from_request(request) -> Optional[PortfolioConfig]:
    """
    Resolves PortfolioConfig from the HTTP Host header.
    Requires request.get_host() to be a single tenant subdomain under PORTFOLIO_BASE_DOMAIN (default: exshare.ai)
    or a configured custom_domain.
    Excludes reserved service hosts and multi-level subdomains.
    Only returns published portfolios (is_published=True).
    """
    raw_host = request.get_host()
    # Strip port number if present (e.g. 'mridhul.exshare.ai:8000' -> 'mridhul.exshare.ai')
    host = raw_host.split(':')[0].strip().lower()

    base_domain = getattr(settings, 'PORTFOLIO_BASE_DOMAIN', 'exshare.ai').strip().lower()

    # 1. Exact match on base domain or local dev root host -> Not a tenant host
    if host == base_domain or host in ('localhost', '127.0.0.1', 'testserver'):
        # In test mode or local debug, support explicit testing header if provided
        test_subdomain = request.headers.get('X-Tenant-Subdomain')
        if test_subdomain:
            norm_test = normalize_subdomain(test_subdomain)
            return PortfolioConfig.objects.select_related('user').filter(
                subdomain=norm_test,
                is_published=True
            ).first()
        return None

    # 2. Check if host ends with '.<base_domain>'
    label = None
    if host.endswith('.' + base_domain):
        label = host[:-len('.' + base_domain)]
    elif host.endswith('.localhost'):
        label = host[:-len('.localhost')]

    if label:
        # Require exactly one valid label under base domain (no multi-level nesting like 'a.b.exshare.ai')
        if '.' in label:
            return None

        norm_label = normalize_subdomain(label)
        # Disallow reserved infrastructure hostnames (api, app, admin, www, etc.)
        if norm_label in get_reserved_subdomains():
            return None

        return PortfolioConfig.objects.select_related('user').filter(
            subdomain=norm_label,
            is_published=True
        ).first()

    # 3. Check if host matches an independent custom_domain (e.g. photographer.com)
    return PortfolioConfig.objects.select_related('user').filter(
        custom_domain=host,
        is_published=True
    ).first()

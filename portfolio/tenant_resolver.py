import re
from typing import Optional
from django.http import HttpRequest
from django.conf import settings
from .models import PortfolioConfig, RESERVED_SUBDOMAINS
from .subdomain_service import get_reserved_subdomains, normalize_subdomain

try:
    from App.Photographers.photo_models import PhotographerProfile
except ImportError:
    PhotographerProfile = None


def resolve_tenant_subdomain(request: HttpRequest) -> Optional[str]:
    """
    Extracts the tenant subdomain from:
    1. HTTP header 'X-Tenant-Subdomain' (used during development / tunnels / testing)
    2. 'Host' or 'X-Forwarded-Host' HTTP header (used in production Nginx wildcard routing)
    3. Query parameter '?subdomain=' (fallback override)
    """
    reserved = get_reserved_subdomains().union(RESERVED_SUBDOMAINS)

    # 1. Direct explicit header (works across dev tunnels and proxies)
    header_sub = request.headers.get('x-tenant-subdomain') or request.headers.get('X-Tenant-Subdomain')
    if header_sub:
        clean = header_sub.strip().lower()
        if clean not in reserved and '.' not in clean:
            return clean

    # 2. Host extraction
    host = request.headers.get('x-forwarded-host') or request.get_host().split(':')[0].lower()

    # Handle *.localhost in local dev
    if host.endswith('.localhost'):
        sub = host.replace('.localhost', '').strip().lower()
        if sub and sub not in reserved and '.' not in sub:
            return sub

    # Handle *.exshare.ai (or configured base domain) in production
    base_domain = getattr(settings, 'PORTFOLIO_BASE_DOMAIN', 'exshare.ai').strip().lower()
    if host.endswith(f'.{base_domain}'):
        sub = host[:-len(base_domain) - 1].strip().lower()
        if sub and sub not in reserved and '.' not in sub:
            return sub

    # 3. Query parameter fallback
    query_sub = request.GET.get('subdomain')
    if query_sub:
        clean = query_sub.strip().lower()
        if clean not in reserved and '.' not in clean:
            return clean

    return None


def get_tenant_profile(request: HttpRequest) -> Optional[PortfolioConfig]:
    """
    Returns the portfolio configuration / photographer profile bound to the incoming tenant host.
    """
    subdomain = resolve_tenant_subdomain(request)
    if not subdomain:
        return None
    return PortfolioConfig.objects.filter(subdomain__iexact=subdomain).first()

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
        if '.' in sub:
            # Multi-level / nested subdomains (e.g. foo.bar.exshare.ai) are strictly rejected
            return None
        if sub and sub not in reserved:
            return sub
        return None

    # Handle dynamic base domain (e.g. *.example.com)
    from .subdomain_service import extract_base_domain_from_host
    dynamic_base = extract_base_domain_from_host(host)
    if dynamic_base and dynamic_base != base_domain and host.endswith(f'.{dynamic_base}'):
        sub = host[:-len(dynamic_base) - 1].strip().lower()
        if '.' in sub:
            return None
        if sub and sub not in reserved:
            return sub

    # Check if first label matches an active registered subdomain
    if '.' in host:
        candidate = host.split('.')[0].strip().lower()
        if candidate and len(candidate) >= 3 and candidate not in reserved:
            from .subdomain_service import SUBDOMAIN_REGEX
            if SUBDOMAIN_REGEX.match(candidate) and PortfolioConfig.objects.filter(subdomain__iexact=candidate).exists():
                return candidate

    # 3. Query parameter fallback
    query_sub = request.GET.get('subdomain')
    if query_sub:
        clean = query_sub.strip().lower()
        if clean not in reserved and '.' not in clean:
            return clean

    return None


def get_tenant_profile(request: HttpRequest, only_active: bool = True, prefetch_works: bool = False) -> Optional[PortfolioConfig]:
    """
    Returns the portfolio configuration / photographer profile bound to the incoming tenant host.
    Ensures:
    - Only published portfolios (is_published=True) are resolved for public traffic.
    - Only active, provisioned subdomains (subdomain_status='active') are accessible.
    """
    subdomain = resolve_tenant_subdomain(request)
    if not subdomain:
        return None
    qs = PortfolioConfig.objects.select_related('user').filter(subdomain__iexact=subdomain)
    if only_active:
        qs = qs.filter(
            is_published=True,
            subdomain_status=PortfolioConfig.SubdomainStatus.ACTIVE
        )
    if prefetch_works:
        from .models import PortfolioWork
        from django.db.models import Prefetch
        qs = qs.prefetch_related(
            Prefetch(
                'works',
                queryset=PortfolioWork.objects.filter(is_published=True).order_by('order', 'id').prefetch_related('photos')
            )
        )
    return qs.first()


import logging
from django.utils import timezone
from django.db import transaction, IntegrityError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.core.exceptions import ValidationError
from django.conf import settings

from .models import (
    PortfolioConfig,
    ReservedSubdomain,
    validate_subdomain,
)
from .subdomain_service import (
    get_reserved_subdomains,
    normalize_subdomain,
    build_subdomain_full_domain,
    build_subdomain_live_url,
    build_direct_portfolio_url,
)
from .tasks import provision_subdomain_dns_task

logger = logging.getLogger(__name__)


def get_user_portfolio_config(user) -> PortfolioConfig:
    """Helper to retrieve or create the PortfolioConfig for the authenticated user."""
    profile = getattr(user, 'portfolio_config', None)
    if not profile and hasattr(user, 'photographer_profile'):
        profile = getattr(user.photographer_profile, 'portfolio_config', None)
    if not profile:
        profile, _ = PortfolioConfig.objects.get_or_create(
            user=user,
            defaults={'studio_name': user.username}
        )
    return profile


class SubdomainAvailabilityView(APIView):
    """
    GET /api/portfolio/subdomain/availability/?name={name}
    Debounced endpoint to check if a subdomain name is available for registration.
    Note: An availability check does not reserve the name.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        name = request.query_params.get('name', '').strip().lower()
        if not name:
            return Response(
                {
                    "name": "",
                    "available": False,
                    "reason": "Subdomain name is required.",
                    "code": "MISSING_NAME_PARAMETER"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1. Format & length validation
        try:
            validate_subdomain(name)
        except ValidationError as e:
            err_msg = str(e.messages[0]) if hasattr(e, 'messages') else str(e)
            is_reserved = 'reserved' in err_msg.lower()
            return Response(
                {
                    "name": name,
                    "available": False,
                    "reason": "reserved" if is_reserved else "invalid_format",
                    "error": err_msg,
                    "is_current_owner": False,
                },
                status=status.HTTP_200_OK
            )

        # 2. Check ownership
        current_profile = get_user_portfolio_config(request.user)
        if current_profile.subdomain and current_profile.subdomain.lower() == name:
            return Response(
                {
                    "name": name,
                    "available": True,
                    "reason": None,
                    "is_current_owner": True,
                    "status": current_profile.subdomain_status,
                },
                status=status.HTTP_200_OK
            )

        # 3. Check dynamic reserved table & static list
        reserved_set = get_reserved_subdomains()
        if name in reserved_set or ReservedSubdomain.objects.filter(name=name).exists():
            return Response(
                {
                    "name": name,
                    "available": False,
                    "reason": "reserved",
                    "error": "This name is reserved for platform infrastructure.",
                    "is_current_owner": False,
                },
                status=status.HTTP_200_OK
            )

        # 4. Check if already claimed by another portfolio
        if PortfolioConfig.objects.filter(subdomain__iexact=name).exists():
            return Response(
                {
                    "name": name,
                    "available": False,
                    "reason": "already_taken",
                    "is_current_owner": False,
                },
                status=status.HTTP_200_OK
            )

        full_domain = build_subdomain_full_domain(name, request=request)
        live_url = build_subdomain_live_url(name, request=request)
        return Response(
            {
                "name": name,
                "available": True,
                "reason": None,
                "is_current_owner": False,
                "domain": full_domain,
                "url": live_url,
                "live_url": live_url,
            },
            status=status.HTTP_200_OK
        )


class ClaimSubdomainView(APIView):
    """
    PUT /api/portfolio/subdomain/
    POST /api/portfolio/subdomain/
    Atomically claims a subdomain for the authenticated photographer.
    - Validates name and checks database locks (select_for_update).
    - Reserves the record as 'pending'.
    - Dispatches async GoDaddy DNS provisioning via Celery on transaction commit.
    - Returns HTTP 202 Accepted while provisioning is pending.
    """
    permission_classes = [permissions.IsAuthenticated]

    def put(self, request):
        return self._handle_claim(request)

    def post(self, request):
        return self._handle_claim(request)

    def _handle_claim(self, request):
        subdomain = request.data.get('subdomain', '').strip().lower()
        if not subdomain:
            return Response(
                {
                    "error": "Subdomain is required.",
                    "code": "INVALID_SUBDOMAIN"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate format
        try:
            validate_subdomain(subdomain)
        except ValidationError as e:
            return Response(
                {
                    "error": str(e.messages[0]) if hasattr(e, 'messages') else str(e),
                    "code": "INVALID_SUBDOMAIN"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check reserved
        if ReservedSubdomain.objects.filter(name=subdomain).exists():
            return Response(
                {
                    "error": f"The subdomain '{subdomain}' is reserved and unavailable.",
                    "code": "INVALID_SUBDOMAIN"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        current_profile = get_user_portfolio_config(request.user)

        # Idempotent repeat: if already assigned to current user and active
        if current_profile.subdomain and current_profile.subdomain.lower() == subdomain:
            if current_profile.subdomain_status == PortfolioConfig.SubdomainStatus.ACTIVE:
                full_domain = current_profile.get_full_domain(request=request)
                full_url = current_profile.get_public_url(request=request)
                return Response(
                    {
                        "status": "active",
                        "subdomain": subdomain,
                        "domain": full_domain,
                        "url": full_url,
                        "message": "Subdomain is already active and assigned to your portfolio."
                    },
                    status=status.HTTP_200_OK
                )
            elif current_profile.subdomain_status == PortfolioConfig.SubdomainStatus.PENDING:
                full_domain = current_profile.get_full_domain(request=request)
                full_url = current_profile.get_public_url(request=request)
                return Response(
                    {
                        "status": "pending",
                        "subdomain": subdomain,
                        "domain": full_domain,
                        "url": full_url,
                        "message": "Subdomain is already assigned to your portfolio and provisioning is currently pending."
                    },
                    status=status.HTTP_202_ACCEPTED
                )

        # In version 1: prohibit self-service renames if already active to prevent link hijacking
        if current_profile.subdomain and current_profile.subdomain.lower() != subdomain:
            if current_profile.subdomain_status == PortfolioConfig.SubdomainStatus.ACTIVE:
                return Response(
                    {
                        "error": f"Self-service subdomain renaming is not permitted. Your portfolio is currently active at '{current_profile.subdomain}'. Please contact support to request a domain modification.",
                        "code": "RENAME_PROHIBITED",
                        "current_subdomain": current_profile.subdomain
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Atomic reservation
        try:
            with transaction.atomic():
                existing_holder = (
                    PortfolioConfig.objects
                    .select_for_update()
                    .filter(subdomain__iexact=subdomain)
                    .first()
                )

                if existing_holder and existing_holder.id != current_profile.id:
                    return Response(
                        {
                            "error": "This subdomain was just claimed by another photographer.",
                            "code": "SUBDOMAIN_ALREADY_TAKEN"
                        },
                        status=status.HTTP_409_CONFLICT
                    )

                dns_provider = getattr(settings, 'PORTFOLIO_DNS_PROVIDER', 'wildcard').strip().lower()
                now = timezone.now()
                effective_ip = getattr(settings, 'PORTFOLIO_SERVER_IP', '31.97.232.245')

                if dns_provider == 'wildcard':
                    # Instant activation via Wildcard DNS record (*.exshare.ai)
                    current_profile.subdomain = subdomain
                    current_profile.subdomain_status = PortfolioConfig.SubdomainStatus.ACTIVE
                    current_profile.subdomain_provisioned_at = now
                    current_profile.subdomain_dns_checked_at = now
                    current_profile.subdomain_dns_record_type = 'A'
                    current_profile.subdomain_dns_record_data = effective_ip
                    current_profile.subdomain_dns_provider = 'wildcard'
                    current_profile.subdomain_dns_managed = True
                    current_profile.subdomain_error = ''
                    current_profile.subdomain_retry_count = 0
                    current_profile.save(update_fields=[
                        'subdomain',
                        'subdomain_status',
                        'subdomain_provisioned_at',
                        'subdomain_dns_checked_at',
                        'subdomain_dns_record_type',
                        'subdomain_dns_record_data',
                        'subdomain_dns_provider',
                        'subdomain_dns_managed',
                        'subdomain_error',
                        'subdomain_retry_count',
                        'updated_at'
                    ])
                else:
                    # Reserve state in DB
                    current_profile.subdomain = subdomain
                    current_profile.subdomain_status = PortfolioConfig.SubdomainStatus.PENDING
                    current_profile.subdomain_error = ''
                    current_profile.subdomain_retry_count = 0
                    current_profile.save(update_fields=[
                        'subdomain',
                        'subdomain_status',
                        'subdomain_error',
                        'subdomain_retry_count',
                        'updated_at'
                    ])

                    # Enqueue Celery task after commit
                    profile_id = current_profile.id
                    transaction.on_commit(lambda: provision_subdomain_dns_task.delay(profile_id, subdomain))

        except IntegrityError:
            return Response(
                {
                    "error": "This subdomain was just claimed by another photographer.",
                    "code": "SUBDOMAIN_ALREADY_TAKEN"
                },
                status=status.HTTP_409_CONFLICT
            )

        full_domain = current_profile.get_full_domain(request=request)
        full_url = current_profile.get_public_url(request=request)
        direct_url = build_direct_portfolio_url(subdomain, request=request)

        if dns_provider == 'wildcard':
            return Response(
                {
                    "status": "active",
                    "subdomain": subdomain,
                    "domain": full_domain,
                    "url": full_url,
                    "live_url": full_url,
                    "direct_url": direct_url,
                    "message": f"Subdomain '{subdomain}' claimed and active immediately via Wildcard DNS."
                },
                status=status.HTTP_200_OK
            )

        return Response(
            {
                "status": "pending",
                "subdomain": subdomain,
                "domain": full_domain,
                "url": full_url,
                "live_url": full_url,
                "direct_url": direct_url,
                "message": f"Subdomain '{subdomain}' claimed successfully. DNS record provisioning has been scheduled."
            },
            status=status.HTTP_202_ACCEPTED
        )


class SubdomainStatusView(APIView):
    """
    GET /api/portfolio/subdomain/status/
    Reads the current provisioning status and health for the authenticated user's portfolio.
    States: 'pending', 'provisioning', 'active', 'failed'.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = get_user_portfolio_config(request.user)
        if not profile.subdomain:
            return Response(
                {
                    "subdomain": None,
                    "status": None,
                    "domain": None,
                    "url": None,
                    "message": "No subdomain assigned to this portfolio."
                },
                status=status.HTTP_200_OK
            )

        full_domain = profile.get_full_domain(request=request)
        full_url = profile.get_public_url(request=request)

        return Response(
            {
                "subdomain": profile.subdomain,
                "status": profile.subdomain_status,
                "domain": full_domain,
                "url": full_url,
                "live_url": full_url,
                "provisioned_at": profile.subdomain_provisioned_at,
                "dns_checked_at": profile.subdomain_dns_checked_at,
                "error": profile.subdomain_error or None,
                "retry_allowed": profile.subdomain_status == PortfolioConfig.SubdomainStatus.FAILED,
                "retry_count": profile.subdomain_retry_count,
            },
            status=status.HTTP_200_OK
        )


class SubdomainRetryProvisioningView(APIView):
    """
    POST /api/portfolio/subdomain/retry/
    Allows the authenticated user to retry a failed DNS provisioning operation.
    - Enforces ownership: only operates on the authenticated user's portfolio.
    - Throttled: rejects requests if last retry was within 30 seconds.
    - Returns HTTP 202 Accepted.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        profile = get_user_portfolio_config(request.user)
        if not profile.subdomain:
            return Response(
                {
                    "error": "No subdomain is associated with your portfolio.",
                    "code": "NO_SUBDOMAIN"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if profile.subdomain_status == PortfolioConfig.SubdomainStatus.ACTIVE:
            return Response(
                {
                    "message": "Subdomain is already active and verified.",
                    "status": "active"
                },
                status=status.HTTP_200_OK
            )

        if profile.subdomain_status == PortfolioConfig.SubdomainStatus.PROVISIONING:
            return Response(
                {
                    "message": "Provisioning is currently in progress. Please allow a few seconds.",
                    "status": "provisioning"
                },
                status=status.HTTP_202_ACCEPTED
            )

        # Throttling check: maximum 1 retry per 30 seconds
        if profile.subdomain_last_retry_at:
            elapsed = (timezone.now() - profile.subdomain_last_retry_at).total_seconds()
            if elapsed < 30:
                retry_after = int(30 - elapsed)
                return Response(
                    {
                        "error": "Please wait before retrying.",
                        "code": "RETRY_THROTTLED",
                        "retry_after_seconds": retry_after
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

        dns_provider = getattr(settings, 'PORTFOLIO_DNS_PROVIDER', 'wildcard').strip().lower()
        if dns_provider == 'wildcard':
            now = timezone.now()
            with transaction.atomic():
                profile.subdomain_status = PortfolioConfig.SubdomainStatus.ACTIVE
                profile.subdomain_provisioned_at = profile.subdomain_provisioned_at or now
                profile.subdomain_dns_checked_at = now
                profile.subdomain_dns_record_type = 'A'
                profile.subdomain_dns_record_data = getattr(settings, 'PORTFOLIO_SERVER_IP', '31.97.232.245')
                profile.subdomain_dns_provider = 'wildcard'
                profile.subdomain_dns_managed = True
                profile.subdomain_error = ''
                profile.save(update_fields=[
                    'subdomain_status',
                    'subdomain_provisioned_at',
                    'subdomain_dns_checked_at',
                    'subdomain_dns_record_type',
                    'subdomain_dns_record_data',
                    'subdomain_dns_provider',
                    'subdomain_dns_managed',
                    'subdomain_error',
                    'updated_at'
                ])
            return Response(
                {
                    "status": "active",
                    "subdomain": profile.subdomain,
                    "message": "Subdomain is verified and active via Wildcard DNS."
                },
                status=status.HTTP_200_OK
            )

        # Trigger retry
        with transaction.atomic():
            profile.subdomain_status = PortfolioConfig.SubdomainStatus.PENDING
            profile.subdomain_error = ''
            profile.subdomain_last_retry_at = timezone.now()
            profile.subdomain_retry_count += 1
            profile.save(update_fields=[
                'subdomain_status',
                'subdomain_error',
                'subdomain_last_retry_at',
                'subdomain_retry_count',
                'updated_at'
            ])

            profile_id = profile.id
            sub = profile.subdomain
            transaction.on_commit(lambda: provision_subdomain_dns_task.delay(profile_id, sub))

        return Response(
            {
                "status": "pending",
                "subdomain": profile.subdomain,
                "message": "DNS provisioning retry scheduled."
            },
            status=status.HTTP_202_ACCEPTED
        )


# Backward-compatibility aliases
PortfolioSubdomainAvailabilityView = SubdomainAvailabilityView
PortfolioSubdomainClaimView = ClaimSubdomainView
PortfolioSubdomainStatusView = SubdomainStatusView
PortfolioSubdomainRetryView = SubdomainRetryProvisioningView

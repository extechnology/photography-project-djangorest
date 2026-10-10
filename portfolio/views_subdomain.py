from django.db import transaction, IntegrityError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.core.exceptions import ValidationError

from .models import (
    PortfolioConfig,
    ReservedSubdomain,
    RESERVED_SUBDOMAINS,
    validate_subdomain,
)
from .subdomain_service import (
    check_subdomain_availability,
    validate_subdomain_label,
    normalize_subdomain,
)


class SubdomainAvailabilityView(APIView):
    """
    GET /api/portfolio/subdomain/availability/?name={name}
    Public/Authenticated debounced endpoint to check if a subdomain name is available.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        name = request.query_params.get('name', '').strip().lower()
        if not name:
            return Response(
                {
                    "available": False,
                    "reason": "Name is required.",
                    "code": "MISSING_NAME_PARAMETER"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1. Format validation
        try:
            validate_subdomain(name)
        except ValidationError as e:
            return Response(
                {
                    "name": name,
                    "available": False,
                    "reason": str(e.messages[0]) if hasattr(e, 'messages') else str(e),
                    "is_current_owner": False,
                },
                status=status.HTTP_200_OK
            )

        # 2. Check ownership
        current_profile = getattr(request.user, 'portfolio_config', None)
        if not current_profile and hasattr(request.user, 'photographer_profile'):
            current_profile = getattr(request.user.photographer_profile, 'portfolio_config', None)

        if current_profile and current_profile.subdomain and current_profile.subdomain.lower() == name:
            return Response(
                {
                    "name": name,
                    "available": True,
                    "reason": None,
                    "is_current_owner": True,
                },
                status=status.HTTP_200_OK
            )

        # 3. Check if reserved in dynamic database table
        if ReservedSubdomain.objects.filter(name=name).exists():
            return Response(
                {
                    "name": name,
                    "available": False,
                    "reason": "reserved",
                    "is_current_owner": False,
                },
                status=status.HTTP_200_OK
            )

        # 4. Check if already claimed by another portfolio
        exists = PortfolioConfig.objects.filter(subdomain__iexact=name).exists()
        if exists:
            return Response(
                {
                    "name": name,
                    "available": False,
                    "reason": "already_taken",
                    "is_current_owner": False,
                },
                status=status.HTTP_200_OK
            )

        return Response(
            {
                "name": name,
                "available": True,
                "reason": None,
                "is_current_owner": False,
            },
            status=status.HTTP_200_OK
        )


class ClaimSubdomainView(APIView):
    """
    PUT /api/portfolio/subdomain/
    Atomically claim or assign a subdomain for the authenticated photographer.
    Uses select_for_update() and database transactions to prevent race-condition claims.
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

        if ReservedSubdomain.objects.filter(name=subdomain).exists():
            return Response(
                {
                    "error": f"The subdomain '{subdomain}' is reserved and unavailable.",
                    "code": "INVALID_SUBDOMAIN"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        current_profile, _ = PortfolioConfig.objects.get_or_create(
            user=request.user,
            defaults={'studio_name': request.user.username}
        )

        # Idempotent repeat: if already assigned to current user
        if current_profile.subdomain and current_profile.subdomain.lower() == subdomain:
            full_url = current_profile.public_url or f"https://{subdomain}.exshare.ai"
            return Response(
                {
                    "status": "success",
                    "subdomain": subdomain,
                    "domain": current_profile.full_domain or f"{subdomain}.exshare.ai",
                    "url": full_url,
                    "message": "Subdomain is already assigned to your portfolio."
                },
                status=status.HTTP_200_OK
            )

        # In version 1: prohibit self-service renames to prevent link hijacking/breakage if requested differently
        if current_profile.subdomain and current_profile.subdomain.lower() != subdomain:
            return Response(
                {
                    "error": f"Self-service subdomain renaming is not permitted in v1. Your portfolio is already bound to '{current_profile.subdomain}'. Please contact support to request a domain modification.",
                    "code": "RENAME_PROHIBITED",
                    "current_subdomain": current_profile.subdomain
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                # Check if someone else just claimed it right before this call (Race Condition Lock)
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

                # Assign and save atomically
                current_profile.subdomain = subdomain
                current_profile.save(update_fields=['subdomain', 'updated_at'])

        except IntegrityError:
            return Response(
                {
                    "error": "This subdomain was just claimed by another photographer.",
                    "code": "SUBDOMAIN_ALREADY_TAKEN"
                },
                status=status.HTTP_409_CONFLICT
            )

        full_url = current_profile.public_url or f"https://{subdomain}.exshare.ai"
        return Response(
            {
                "status": "success",
                "subdomain": subdomain,
                "domain": current_profile.full_domain or f"{subdomain}.exshare.ai",
                "url": full_url,
                "message": f"Subdomain '{subdomain}' successfully claimed."
            },
            status=status.HTTP_200_OK
        )


# Backward-compatibility aliases
PortfolioSubdomainAvailabilityView = SubdomainAvailabilityView
PortfolioSubdomainClaimView = ClaimSubdomainView

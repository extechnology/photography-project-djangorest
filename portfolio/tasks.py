"""
Celery background tasks for asynchronous BigRock DNS provisioning and reconciliation.
Ensures non-blocking network calls, controlled exponential backoff, state locking,
and self-healing recovery.
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from celery import shared_task
from django.conf import settings

from .models import PortfolioConfig
from .bigrock_service import (
    get_bigrock_client,
    BigRockDNSException,
    BigRockAuthError,
    BigRockValidationError,
    BigRockConflictError,
    BigRockRateLimitError,
    BigRockServerError,
    # Aliases
    get_godaddy_client,
    GoDaddyAuthError,
    GoDaddyValidationError,
    GoDaddyConflictError,
    GoDaddyRateLimitError,
    GoDaddyServerError,
)

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5, queue='exshare')
def provision_subdomain_dns_task(self, portfolio_config_id: int, subdomain: str, target_ip: str = None):
    """
    Asynchronously creates and verifies an A-record via BigRock HTTP API.
    - Prevents concurrent execution using state locking.
    - Does NOT hold a database transaction open during external HTTP calls.
    - Controlled retries with exponential backoff only for network / rate-limit failures.
    - Fails fast on authentication, conflict, or validation errors.
    """
    logger.info(f"[Task provision_subdomain_dns] Starting attempt #{self.request.retries + 1} for portfolio {portfolio_config_id} (subdomain: '{subdomain}')")

    try:
        portfolio = PortfolioConfig.objects.get(id=portfolio_config_id)
    except PortfolioConfig.DoesNotExist:
        logger.warning(f"[Task provision_subdomain_dns] PortfolioConfig {portfolio_config_id} not found. Aborting.")
        return {"status": "aborted", "reason": "portfolio_not_found"}

    # Guard 1: Subdomain mismatch or cleared
    if not portfolio.subdomain or portfolio.subdomain.lower() != subdomain.lower():
        logger.info(f"[Task provision_subdomain_dns] Subdomain on portfolio {portfolio_config_id} changed or removed. Aborting.")
        return {"status": "aborted", "reason": "subdomain_mismatch"}

    # Guard 2: Already active
    if portfolio.subdomain_status == PortfolioConfig.SubdomainStatus.ACTIVE:
        logger.info(f"[Task provision_subdomain_dns] Subdomain '{subdomain}' is already ACTIVE.")
        return {"status": "already_active", "subdomain": subdomain}

    # Step 1: Atomic state lock transition to PROVISIONING (committing immediately)
    with transaction.atomic():
        locked = PortfolioConfig.objects.select_for_update().get(id=portfolio_config_id)
        if locked.subdomain_status == PortfolioConfig.SubdomainStatus.ACTIVE:
            return {"status": "already_active", "subdomain": subdomain}

        # Check if already running by another worker recently
        if locked.subdomain_status == PortfolioConfig.SubdomainStatus.PROVISIONING:
            if locked.updated_at and (timezone.now() - locked.updated_at).total_seconds() < 45:
                if self.request.retries == 0:
                    logger.info(f"[Task provision_subdomain_dns] Another worker is currently provisioning portfolio {portfolio_config_id}.")
                    return {"status": "already_in_progress"}

        locked.subdomain_status = PortfolioConfig.SubdomainStatus.PROVISIONING
        locked.subdomain_dns_checked_at = timezone.now()
        locked.save(update_fields=['subdomain_status', 'subdomain_dns_checked_at', 'updated_at'])

    # Step 2: Provisioning strategy check
    dns_provider = getattr(settings, 'PORTFOLIO_DNS_PROVIDER', 'wildcard').strip().lower()
    if dns_provider == 'wildcard':
        now = timezone.now()
        effective_ip = (target_ip or getattr(settings, 'PORTFOLIO_SERVER_IP', '31.97.232.245')).strip()
        portfolio.subdomain_status = PortfolioConfig.SubdomainStatus.ACTIVE
        portfolio.subdomain_provisioned_at = now
        portfolio.subdomain_dns_checked_at = now
        portfolio.subdomain_dns_record_type = 'A'
        portfolio.subdomain_dns_record_data = effective_ip
        portfolio.subdomain_dns_provider = 'wildcard'
        portfolio.subdomain_dns_managed = True
        portfolio.subdomain_error = ''
        portfolio.save(update_fields=[
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
        logger.info(f"[Task provision_subdomain_dns] Subdomain '{subdomain}' successfully activated via Wildcard DNS.")
        return {
            "status": "active",
            "subdomain": subdomain,
            "ip": effective_ip,
            "provider": "wildcard"
        }

    # Step 2b: External BigRock API Calls (OUTSIDE of DB transaction)
    client = get_bigrock_client()
    effective_ip = (target_ip or client.server_ip).strip()

    try:
        # Pre-reconcile provider state to avoid duplicate requests
        is_conflict, conflict_reason = client.check_subdomain_conflict(subdomain)
        if is_conflict:
            raise BigRockConflictError(conflict_reason or "Conflicting DNS record exists on BigRock.")

        if conflict_reason == "already_configured":
            logger.info(f"[Task provision_subdomain_dns] Existing matching record found on BigRock for '{subdomain}'. Reconciled.")
            result_data = {
                "action": "reconciled_existing",
                "name": subdomain,
                "data": effective_ip,
                "type": "A"
            }
        else:
            # Provision record via BigRock add-ipv4-record.json
            result_data = client.provision_portfolio_a_record(
                subdomain=subdomain,
                ttl=14400
            )

        # Step 3: Mark ACTIVE in database
        now = timezone.now()
        portfolio.subdomain_status = PortfolioConfig.SubdomainStatus.ACTIVE
        portfolio.subdomain_provisioned_at = now
        portfolio.subdomain_dns_checked_at = now
        portfolio.subdomain_dns_record_type = 'A'
        portfolio.subdomain_dns_record_data = effective_ip
        portfolio.subdomain_dns_provider = 'bigrock'
        portfolio.subdomain_dns_managed = True
        portfolio.subdomain_error = ''
        portfolio.save(update_fields=[
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

        logger.info(f"[Task provision_subdomain_dns] Subdomain '{subdomain}' successfully provisioned on BigRock and marked ACTIVE.")
        return {
            "status": "active",
            "subdomain": subdomain,
            "ip": effective_ip,
            "details": result_data
        }

    except (BigRockAuthError, BigRockValidationError, BigRockConflictError) as non_retryable:
        # Permanent failure - Do NOT retry
        safe_msg = str(non_retryable)
        logger.error(f"[Task provision_subdomain_dns] Permanent failure for '{subdomain}': {safe_msg}")
        portfolio.subdomain_status = PortfolioConfig.SubdomainStatus.FAILED
        portfolio.subdomain_error = safe_msg
        portfolio.subdomain_dns_checked_at = timezone.now()
        portfolio.save(update_fields=['subdomain_status', 'subdomain_error', 'subdomain_dns_checked_at', 'updated_at'])
        return {"status": "failed", "reason": safe_msg, "retriable": False}

    except (BigRockRateLimitError, BigRockServerError) as retryable:
        # Temporary failure - Retry with exponential backoff
        safe_msg = str(retryable)
        logger.warning(f"[Task provision_subdomain_dns] Temporary failure on attempt {self.request.retries + 1} for '{subdomain}': {safe_msg}")

        if self.request.retries >= self.max_retries:
            portfolio.subdomain_status = PortfolioConfig.SubdomainStatus.FAILED
            portfolio.subdomain_error = f"Max retries exceeded: {safe_msg}"
            portfolio.subdomain_dns_checked_at = timezone.now()
            portfolio.save(update_fields=['subdomain_status', 'subdomain_error', 'subdomain_dns_checked_at', 'updated_at'])
            return {"status": "failed", "reason": safe_msg, "retriable": True}

        countdown = (2 ** self.request.retries) * 10
        raise self.retry(exc=retryable, countdown=countdown)

    except Exception as unexpected:
        safe_msg = f"Unexpected error during DNS provisioning: {str(unexpected)}"
        logger.exception(f"[Task provision_subdomain_dns] Unexpected exception for '{subdomain}': {str(unexpected)}")
        portfolio.subdomain_status = PortfolioConfig.SubdomainStatus.FAILED
        portfolio.subdomain_error = "An internal DNS error occurred while connecting to BigRock."
        portfolio.subdomain_dns_checked_at = timezone.now()
        portfolio.save(update_fields=['subdomain_status', 'subdomain_error', 'subdomain_dns_checked_at', 'updated_at'])
        return {"status": "failed", "reason": safe_msg, "retriable": False}


@shared_task(queue='exshare')
def reconcile_pending_subdomains_task():
    """
    Self-healing recovery task:
    Periodically checks for portfolios stuck in PENDING or PROVISIONING state
    for more than 5 minutes and enqueues re-provisioning.
    Runs every 10 minutes via Celery Beat.
    """
    stale_threshold = timezone.now() - timedelta(minutes=5)
    stale_pending = PortfolioConfig.objects.filter(
        subdomain_status__in=[PortfolioConfig.SubdomainStatus.PENDING, PortfolioConfig.SubdomainStatus.PROVISIONING],
        updated_at__lt=stale_threshold
    ).exclude(subdomain__isnull=True).exclude(subdomain__exact='')

    count = stale_pending.count()
    if count == 0:
        logger.debug("[Task reconcile_pending_subdomains] No stale subdomains found.")
        return {"reconciled": 0}

    logger.info(f"[Task reconcile_pending_subdomains] Found {count} stale subdomains to reconcile.")
    recovered = 0

    dns_provider = getattr(settings, 'PORTFOLIO_DNS_PROVIDER', 'wildcard').strip().lower()
    if dns_provider == 'wildcard':
        now = timezone.now()
        effective_ip = getattr(settings, 'PORTFOLIO_SERVER_IP', '31.97.232.245')
        for profile in stale_pending:
            profile.subdomain_status = PortfolioConfig.SubdomainStatus.ACTIVE
            profile.subdomain_provisioned_at = profile.subdomain_provisioned_at or now
            profile.subdomain_dns_checked_at = now
            profile.subdomain_dns_record_type = 'A'
            profile.subdomain_dns_record_data = effective_ip
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
            recovered += 1
            logger.info(f"[Task reconcile_pending_subdomains] Reconciled '{profile.subdomain}' to ACTIVE via Wildcard DNS.")
        return {"reconciled": recovered}

    for profile in stale_pending:
        # Check if already active on BigRock before dispatching
        try:
            client = get_bigrock_client()
            has_conflict, reason = client.check_subdomain_conflict(profile.subdomain)
            if reason == "already_configured":
                profile.subdomain_status = PortfolioConfig.SubdomainStatus.ACTIVE
                profile.subdomain_provisioned_at = timezone.now()
                profile.subdomain_error = ''
                profile.save(update_fields=['subdomain_status', 'subdomain_provisioned_at', 'subdomain_error', 'updated_at'])
                recovered += 1
                logger.info(f"[Task reconcile_pending_subdomains] Reconciled '{profile.subdomain}' directly to ACTIVE.")
                continue
        except Exception as e:
            logger.warning(f"[Task reconcile_pending_subdomains] Direct check failed for '{profile.subdomain}': {str(e)}")

        provision_subdomain_dns_task.delay(profile.id, profile.subdomain)
        recovered += 1

    return {"reconciled": recovered}

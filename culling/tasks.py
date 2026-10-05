from celery import shared_task
from django.utils import timezone
from .models import CullingSession

@shared_task
def cleanup_abandoned_culling_sessions():
    """
    Runs daily to purge staging files from sessions that have expired or been abandoned for > 7 days.
    """
    expired_sessions = CullingSession.objects.filter(
        status__in=[CullingSession.Status.ACTIVE, CullingSession.Status.PENDING_PAYMENT],
        expires_at__lt=timezone.now()
    )

    count = 0
    for session in expired_sessions:
        session.purge_staging_storage()
        session.status = CullingSession.Status.EXPIRED
        session.save(update_fields=['status'])
        count += 1

    return f"Purged staging storage for {count} expired culling session(s)."

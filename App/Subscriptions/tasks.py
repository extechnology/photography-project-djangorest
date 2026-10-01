"""
App/Subscriptions/tasks.py
==========================
Celery periodic tasks for subscription lifecycle management:
  - check_subscription_expiry_task: Runs once per day to:
      1. Warn subscriptions expiring in 7 days.
      2. Final-warn subscriptions expiring in 1 day.
      3. Mark subscriptions that have passed expiry as 'expired' and notify.
"""
import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='App.Subscriptions.tasks.check_subscription_expiry_task', max_retries=3)
def check_subscription_expiry_task(self):
    """
    Periodic Celery beat task — runs daily at midnight IST.
    Scans all active PhotographerSubscription records and:
      1. Sends a 7-day advance expiry warning notification (once).
      2. Sends a 1-day final expiry warning notification (once).
      3. Marks subscriptions as 'expired' and fires the expiry notification.

    De-duplication: checks StudioNotification.metadata for a 'warning_days_remaining'
    key so the same warning is not sent twice in the same cycle.
    """
    # Late imports to avoid circular dependencies at module load time
    from django.db import models
    from App.Subscriptions.sub_models import PhotographerSubscription

    try:
        from backend.atelier_notifications import (
            notify_plan_expiry_warning,
            notify_plan_expired,
            StudioNotification,
        )
        has_notifications = True
    except ImportError:
        try:
            from atelier_notifications import (
                notify_plan_expiry_warning,
                notify_plan_expired,
                StudioNotification,
            )
            has_notifications = True
        except ImportError:
            logger.error("check_subscription_expiry_task: Cannot import notification functions. Skipping.")
            has_notifications = False

    now = timezone.now()
    warned_count = 0
    expired_count = 0

    # -----------------------------------------------------------------------
    # 1. Warn subscriptions expiring in 7 days and 1 day
    # -----------------------------------------------------------------------
    for warn_days in [7, 1]:
        window_start = now + timedelta(days=warn_days - 1)
        window_end = now + timedelta(days=warn_days)

        expiring_subs = PhotographerSubscription.objects.filter(
            status='active',
            expires_at__gte=window_start,
            expires_at__lt=window_end,
        ).select_related('user', 'photographer', 'plan')

        for sub in expiring_subs:
            target_user = sub.user or (sub.photographer.user if sub.photographer else None)
            if not target_user:
                continue

            plan_name = sub.plan.name if sub.plan else 'Studio Plan'

            if not has_notifications:
                logger.info(
                    f"[EXPIRY WARNING] Would notify user {target_user.id} "
                    f"({warn_days}d warning) for plan '{plan_name}'."
                )
                warned_count += 1
                continue

            # De-duplicate: skip if a warning for this exact days_remaining was already sent today
            already_warned = StudioNotification.objects.filter(
                user=target_user,
                type='plan',
                created_at__date=now.date(),
                metadata__contains={'days_remaining': warn_days},
            ).exists()

            if already_warned:
                logger.debug(
                    f"Skipping duplicate {warn_days}d warning for user {target_user.id}."
                )
                continue

            try:
                notify_plan_expiry_warning(
                    user=target_user,
                    plan_name=plan_name,
                    expiry_date=sub.expires_at,
                    days_remaining=warn_days,
                )
                warned_count += 1
                logger.info(
                    f"Sent {warn_days}d expiry warning to user {target_user.id} "
                    f"for plan '{plan_name}'."
                )
            except Exception as e:
                logger.warning(
                    f"Failed to send {warn_days}d expiry warning to user {target_user.id}: {e}"
                )

    # -----------------------------------------------------------------------
    # 2. Mark expired subscriptions and send 'plan expired' notification
    # -----------------------------------------------------------------------
    newly_expired = PhotographerSubscription.objects.filter(
        status='active',
        expires_at__lte=now,
    ).select_related('user', 'photographer', 'plan')

    for sub in newly_expired:
        target_user = sub.user or (sub.photographer.user if sub.photographer else None)
        plan_name = sub.plan.name if sub.plan else 'Studio Plan'

        # Mark as expired in DB
        try:
            sub.status = 'expired'
            sub.auto_renew = False
            update_fields = ['status', 'auto_renew']
            if hasattr(sub, 'updated_at'):
                update_fields.append('updated_at')
            sub.save(update_fields=update_fields)
            expired_count += 1
            logger.info(
                f"Marked subscription {sub.id} (user {getattr(target_user, 'id', '?')}, "
                f"plan '{plan_name}') as expired."
            )
        except Exception as db_exc:
            logger.error(f"Failed to mark subscription {sub.id} as expired: {db_exc}")
            continue

        if not target_user or not has_notifications:
            continue

        # De-duplicate: skip if an 'expired' notification was already sent today
        already_notified = StudioNotification.objects.filter(
            user=target_user,
            type='plan',
            created_at__date=now.date(),
            title__icontains='expired',
        ).exists()

        if already_notified:
            logger.debug(f"Skipping duplicate expiry notification for user {target_user.id}.")
            continue

        try:
            notify_plan_expired(user=target_user, plan_name=plan_name)
            logger.info(
                f"Sent plan-expired notification to user {target_user.id} "
                f"for plan '{plan_name}'."
            )
        except Exception as e:
            logger.warning(
                f"Failed to send plan-expired notification to user {target_user.id}: {e}"
            )

    logger.info(
        f"check_subscription_expiry_task complete — "
        f"warned: {warned_count}, newly expired: {expired_count}."
    )
    return {
        'warned': warned_count,
        'expired': expired_count,
    }

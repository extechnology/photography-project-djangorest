"""
====================================================================================================
PHOTO-GARAPHY (EX SHARE) — BACKEND SUBSCRIPTION EXPIRATION & ENFORCEMENT SPECIFICATION
====================================================================================================
File: backend/atelier_plans/subscription_enforcement.py (or copy into your billing / plans app)
Framework: Django 4+ & Django REST Framework (DRF)

WHY THIS IS NEEDED:
1. When a subscription reaches its expiry_date (e.g. 2026-09-30) and status is "expired":
   - `auto_renew` should NOT return True (since recurring billing has lapsed or failed).
   - `days_remaining` should be 0.
   - The studio must be blocked from creating new galleries, live events, and uploading media.
2. In the plan upgrade endpoint (/api/plans/upgrade/):
   - When a plan is ACTIVE and UNEXPIRED: Only upward tier upgrades are permitted.
   - When a plan is EXPIRED: The studio is permitted to select ANY plan (same tier renewal, 
     lower tier, or higher tier) to reactivate their subscription.
====================================================================================================
"""

import os
import uuid
from datetime import timedelta
from django.db import models
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from rest_framework import serializers, status, views, permissions
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied

from App.Auth.auth_utils import CookieJWTAuthentication, get_user_from_request
from App.Subscriptions.sub_models import Plan as StudioPlan, PhotographerSubscription, SubscriptionPayment
from App.Photographers.photo_models import PhotographerProfile

User = get_user_model()


def resolve_user_from_request(request):
    """Resolves authenticated user from standard header or HTTP-only cookies."""
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        return user
    try:
        return get_user_from_request(request)
    except Exception:
        return None


# ==================================================================================================
# 1. DJANGO MODEL METHODS & PROPERTIES (Add to your StudioSubscription model)
# ==================================================================================================

def update_subscription_expiration_state(subscription):
    """
    Checks if a subscription has passed its expiry_date without renewal.
    Updates status to 'expired' and turns off auto_renew.
    """
    if not subscription:
        return None

    now = timezone.now()
    expiry = getattr(subscription, 'expiry_date', None) or getattr(subscription, 'expires_at', None)

    if expiry and now >= expiry:
        needs_save = False
        update_fields = []
        if subscription.status != 'expired':
            subscription.status = 'expired'
            needs_save = True
            update_fields.append('status')
        if subscription.auto_renew:
            subscription.auto_renew = False  # Auto-renew cannot remain true once lapsed
            needs_save = True
            update_fields.append('auto_renew')

        if needs_save:
            if hasattr(subscription, 'updated_at'):
                update_fields.append('updated_at')
            subscription.save(update_fields=update_fields)

    return subscription


def is_studio_active(user) -> bool:
    """
    Returns True ONLY if the photographer has an active subscription whose expiry date
    is strictly in the future.
    """
    if not user:
        return False

    # Handle case where a PhotographerProfile was passed instead of User
    if hasattr(user, 'user') and hasattr(user, 'studio_name'):
        photographer = user
        user = user.user
    else:
        photographer = getattr(user, 'photographer_profile', None)

    # Superuser or staff bypass
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return True

    now = timezone.now()
    q = models.Q(user=user)
    if photographer:
        q |= models.Q(photographer=photographer)
    else:
        q |= models.Q(photographer__user=user)

    # Prioritize any active subscription
    active_sub = PhotographerSubscription.objects.filter(q, status='active').order_by('-expires_at', '-created_at').first()
    if active_sub:
        update_subscription_expiration_state(active_sub)
        if active_sub.status == 'active':
            expiry = getattr(active_sub, 'expiry_date', None) or getattr(active_sub, 'expires_at', None)
            if not expiry or now < expiry:
                return True

    sub = PhotographerSubscription.objects.filter(q).order_by('-created_at').first()

    if not sub:
        # If photographer profile exists without any subscription row, auto-provision default active plan
        if photographer:
            default_plan = StudioPlan.objects.filter(is_active=True).exclude(id='plan-test-20gb').order_by('sort_order').first()
            if default_plan:
                sub = PhotographerSubscription.objects.create(
                    user=user,
                    photographer=photographer,
                    plan=default_plan,
                    status="active",
                    started_at=now,
                    expires_at=now + timedelta(days=365),
                    auto_renew=True,
                    storage_limit_bytes=getattr(default_plan, 'storage_limit_bytes', 16106127360),
                )
                photographer.studio_plan = default_plan
                photographer.save(update_fields=['studio_plan'])
                return True
        return False

    update_subscription_expiration_state(sub)

    # Check status and past date
    if sub.status != 'active':
        return False
    expiry = getattr(sub, 'expiry_date', None) or getattr(sub, 'expires_at', None)
    if expiry and now >= expiry:
        return False

    return True


class IsActiveStudioSubscriber(permissions.BasePermission):
    """
    DRF Permission class to block expired studios from performing management actions:
    - Creating galleries
    - Creating events
    - Uploading photos or media
    """
    message = "Your studio membership has expired. Please renew your plan to perform this action."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if getattr(request.user, 'is_staff', False) or getattr(request.user, 'is_superuser', False):
            return True

        if not is_studio_active(request.user):
            raise PermissionDenied({
                "code": "studio_plan_expired",
                "error_code": "PLAN_EXPIRED",
                "detail": self.message,
                "message": self.message,
                "is_expired": True,
                "upgrade_required": True,
            })

        return True


# ==================================================================================================
# 2. DRF SERIALIZER ENHANCEMENTS (Fixes auto_renew & days_remaining on expired plans)
# ==================================================================================================

class CurrentSubscriptionSerializer(serializers.ModelSerializer):
    """
    Serializer ensuring expired plans return consistent status flags to the frontend.
    """
    days_remaining = serializers.SerializerMethodField()
    auto_renew = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    plan = serializers.SerializerMethodField()
    storage = serializers.SerializerMethodField()
    usage = serializers.SerializerMethodField()
    start_date = serializers.DateTimeField(source='started_at', read_only=True)
    expiry_date = serializers.DateTimeField(source='expires_at', read_only=True)

    class Meta:
        model = PhotographerSubscription
        fields = [
            'id',
            'status',
            'plan',
            'start_date',
            'expiry_date',
            'days_remaining',
            'storage',
            'usage',
            'auto_renew',
            'cancel_at_period_end',
            'cancelled_at',
            'payment_gateway_ref',
            'razorpay_subscription_id',
        ]

    def get_status(self, obj):
        now = timezone.now()
        expiry = getattr(obj, 'expiry_date', None) or getattr(obj, 'expires_at', None)
        # If past expiry date, always report status as 'expired'
        if expiry and now >= expiry:
            return 'expired'
        if getattr(obj, 'is_expired', False):
            return 'expired'
        return getattr(obj, 'status', 'active')

    def get_days_remaining(self, obj):
        now = timezone.now()
        expiry = getattr(obj, 'expiry_date', None) or getattr(obj, 'expires_at', None)
        if not expiry or now >= expiry:
            return 0
        diff = expiry - now
        return max(0, diff.days)

    def get_auto_renew(self, obj):
        # CRITICAL FIX: If subscription is expired or cancelled, auto_renew CANNOT be True
        now = timezone.now()
        expiry = getattr(obj, 'expiry_date', None) or getattr(obj, 'expires_at', None)
        if expiry and now >= expiry:
            return False
        if getattr(obj, 'status', '') == 'expired':
            return False
        if getattr(obj, 'cancel_at_period_end', False):
            return False
        return bool(getattr(obj, 'auto_renew', False))

    def get_plan(self, obj):
        plan = getattr(obj, 'plan', None)
        if not plan:
            return None
        return {
            'id': str(plan.id),
            'name': plan.name,
            'tier': getattr(plan, 'tier', 'standard'),
            'billing_cycle': getattr(plan, 'billing_cycle', 'monthly'),
            'duration_months': getattr(plan, 'duration_months', 1),
            'total_price': str(getattr(plan, 'total_price', '0.00')),
            'currency': getattr(plan, 'currency', 'INR'),
            'max_galleries': getattr(plan, 'max_galleries', 0),
            'allowed_templates': getattr(plan, 'allowed_templates', ['editorial', 'masonry']),
            'face_search_enabled': getattr(plan, 'face_search_enabled', False),
            'gallery_expiry_days': getattr(plan, 'gallery_expiry_days', 0),
            'max_events': getattr(plan, 'max_events', 0),
            'max_portfolio_posts': getattr(plan, 'max_portfolio_posts', 0),
            'has_full_inquiry_access': getattr(plan, 'has_full_inquiry_access', True),
        }

    def get_storage(self, obj):
        user = obj.user
        photographer = getattr(user, 'photographer_profile', None) if user else obj.photographer
        storage_limit_bytes = obj.storage_limit_bytes or (obj.plan.storage_limit_bytes if obj.plan else 16106127360)
        used_bytes = 0
        if photographer:
            used_bytes = getattr(photographer, 'storage_used_bytes', 0) or 0
        elif hasattr(user, 'profile') and hasattr(user.profile, 'storage_used_bytes'):
            used_bytes = user.profile.storage_used_bytes or 0

        used_gb = round(used_bytes / (1024 ** 3), 2)
        limit_gb = round(storage_limit_bytes / (1024 ** 3), 2)
        used_percentage = min(100.0, round((used_bytes / storage_limit_bytes) * 100, 1)) if storage_limit_bytes > 0 else 0.0

        return {
            'used_bytes': used_bytes,
            'limit_bytes': storage_limit_bytes,
            'used_gb': used_gb,
            'limit_gb': limit_gb,
            'used_percentage': used_percentage,
        }

    def get_usage(self, obj):
        user = obj.user
        photographer = getattr(user, 'photographer_profile', None) if user else obj.photographer
        plan = obj.plan

        # Galleries count
        galleries_used = 0
        if photographer and hasattr(photographer, 'galleries'):
            try:
                galleries_used = photographer.galleries.exclude(status='archived').count()
            except Exception:
                galleries_used = photographer.galleries.count()
        elif hasattr(user, 'galleries'):
            galleries_used = user.galleries.count()

        # Events count
        events_used = 0
        if photographer and hasattr(photographer, 'shared_events'):
            events_used = photographer.shared_events.count()
        elif photographer and hasattr(photographer, 'events'):
            events_used = photographer.events.count()
        elif hasattr(user, 'events'):
            events_used = user.events.count()

        # Posts count
        posts_used = 0
        if photographer and hasattr(photographer, 'posts'):
            posts_used = photographer.posts.count()
        elif hasattr(user, 'portfolio_posts'):
            posts_used = user.portfolio_posts.count()

        max_gal = getattr(plan, 'max_galleries', 0) if plan else 0
        max_ev = getattr(plan, 'max_events', 0) if plan else 0
        max_post = getattr(plan, 'max_portfolio_posts', 0) if plan else 0

        return {
            'galleries': {
                'used': galleries_used,
                'limit': max_gal,
                'remaining': None if max_gal == 0 else max(0, max_gal - galleries_used),
                'is_unlimited': max_gal == 0,
            },
            'events': {
                'used': events_used,
                'limit': max_ev,
                'remaining': None if max_ev == 0 else max(0, max_ev - events_used),
                'is_unlimited': max_ev == 0,
            },
            'portfolio_posts': {
                'used': posts_used,
                'limit': max_post,
                'remaining': None if max_post == 0 else max(0, max_post - posts_used),
                'is_unlimited': max_post == 0,
            }
        }


# ==================================================================================================
# 3. BACKEND GATEKEEPER / ENFORCEMENT FUNCTION
# ==================================================================================================

def enforce_active_subscription(user, feature_name="studio features"):
    """
    Call this at the beginning of:
      1. Gallery creation view (POST /api/galleries/)
      2. Media upload view (POST /api/galleries/<id>/media/ or pre-signed URL)
      3. Live event creation view (POST /api/events/)
    
    Raises 403 Forbidden with upgrade_required payload if subscription is expired.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None

    # Handle case where a PhotographerProfile was passed instead of User
    if hasattr(user, 'user') and hasattr(user, 'studio_name'):
        photographer = user
        user = user.user
    else:
        photographer = getattr(user, 'photographer_profile', None)

    # Staff and Superusers can bypass
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return None

    # Look up subscription
    subscription = getattr(user, 'subscription', None)
    if not subscription and photographer:
        subscription = getattr(photographer, 'subscription', None)
    if not subscription:
        q = models.Q(user=user)
        if photographer:
            q |= models.Q(photographer=photographer)
        else:
            q |= models.Q(photographer__user=user)
        subscription = PhotographerSubscription.objects.filter(q).order_by('-created_at').first()

    now = timezone.now()

    if subscription:
        # Update expiration state if lapsed
        update_subscription_expiration_state(subscription)
        expiry = getattr(subscription, 'expiry_date', None) or getattr(subscription, 'expires_at', None)
        if subscription.status == 'expired' or (expiry and now >= expiry) or getattr(subscription, 'is_expired', False):
            raise PermissionDenied(detail={
                "code": "studio_plan_expired",
                "error_code": "PLAN_EXPIRED",
                "detail": f"Your studio membership has expired. Please renew your plan to perform this action.",
                "message": f"Your studio membership has expired. Please renew or upgrade your plan to use {feature_name}.",
                "is_expired": True,
                "upgrade_required": True,
            })
        return subscription

    # If photographer profile exists without any subscription row, auto-provision default active plan
    if photographer:
        default_plan = StudioPlan.objects.filter(is_active=True).exclude(id='plan-test-20gb').order_by('sort_order').first()
        if default_plan:
            subscription = PhotographerSubscription.objects.create(
                user=user,
                photographer=photographer,
                plan=default_plan,
                status="active",
                started_at=now,
                expires_at=now + timedelta(days=365),
                auto_renew=True,
                storage_limit_bytes=getattr(default_plan, 'storage_limit_bytes', 16106127360),
            )
            photographer.studio_plan = default_plan
            photographer.save(update_fields=['studio_plan'])
            return subscription

    raise PermissionDenied(detail={
        "error_code": "NO_SUBSCRIPTION",
        "upgrade_required": True,
        "message": f"You do not have an active subscription to access {feature_name}. Please choose a plan."
    })


# ==================================================================================================
# 4. PLAN UPGRADE & RENEWAL ENDPOINT LOGIC
# ==================================================================================================

def get_plan_rank(plan):
    """Computes numerical tier rank for a plan."""
    if not plan:
        return 0

    sort_order = getattr(plan, 'sort_order', 0) or 0
    if sort_order > 0:
        return sort_order * 1000

    tier = str(getattr(plan, 'tier', '')).lower()
    if any(k in tier for k in ['master', 'elite', 'premium']):
        tier_weight = 5000
    elif any(k in tier for k in ['standard', 'pro']):
        tier_weight = 2000
    else:
        tier_weight = 1000

    monthly_price = float(getattr(plan, 'monthly_price', 0) or 0)
    storage_limit_bytes = getattr(plan, 'storage_limit_bytes', 0) or 0
    storage_gb = storage_limit_bytes / (1024 ** 3)
    duration_months = getattr(plan, 'duration_months', 0) or (
        12 if getattr(plan, 'billing_cycle', '') == 'annual' else (
            3 if getattr(plan, 'billing_cycle', '') == 'quarterly' else 1
        )
    )

    return int(tier_weight + (monthly_price * 5) + (duration_months * 10) + storage_gb)


def can_user_select_plan(user, target_plan, PhotographerSubscriptionModel=PhotographerSubscription):
    """
    Returns (is_allowed: bool, reason: str).
    Rules:
      - If user has NO active subscription -> ALLOWED (any tier)
      - If user's subscription is EXPIRED or days_remaining <= 0 -> ALLOWED (any tier / renewal)
      - If user has an ACTIVE unexpired subscription -> ONLY allow upward tiers (reject downgrades)
    """
    current_sub = PhotographerSubscriptionModel.objects.filter(
        models.Q(user=user) | models.Q(photographer__user=user)
    ).order_by('-created_at').first()

    if not current_sub:
        return True, "Eligible for any plan."

    # Check if lapsed or expired
    now = timezone.now()
    expiry = getattr(current_sub, 'expiry_date', None) or getattr(current_sub, 'expires_at', None)
    is_expired = (
        current_sub.status in ['expired', 'cancelled']
        or (expiry and now >= expiry)
        or getattr(current_sub, 'is_expired', False)
        or getattr(current_sub, 'days_remaining', 0) <= 0
    )

    if is_expired:
        return True, "Subscription expired. Eligible to renew or pick any plan."

    # Active subscription: prevent downgrade or identical re-subscription
    if str(current_sub.plan_id) == str(target_plan.id):
        return False, "You already have an active subscription to this plan."

    current_sort = getattr(current_sub.plan, 'sort_order', 0) if current_sub.plan else 0
    target_sort = getattr(target_plan, 'sort_order', 0)

    current_rank = get_plan_rank(current_sub.plan)
    target_rank = get_plan_rank(target_plan)

    if target_rank <= current_rank or (target_sort > 0 and current_sort > 0 and target_sort <= current_sort):
        return False, "You can only upgrade to a higher-tier plan while your subscription is active."

    return True, "Upgrade eligible."


class PlanUpgradeView(views.APIView):
    """
    POST /api/plans/upgrade/
    Payload: { "plan_id": "plan-premium-elite", "gateway": "razorpay" (or "direct") }
    
    RULE ENFORCEMENT:
    - If user has an ACTIVE, UNEXPIRED plan: Downgrade is blocked (upgrades permitted upwards only).
    - If user's plan is EXPIRED: User can select ANY plan to reactivate (including same plan renewal).
    """
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = resolve_user_from_request(request)
        if not user or not user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        target_plan_id = request.data.get('plan_id')
        gateway = request.data.get('gateway', 'razorpay')
        if not target_plan_id:
            return Response({
                "error_code": "PLAN_ID_REQUIRED",
                "message": "plan_id is required"
            }, status=status.HTTP_400_BAD_REQUEST)

        target_plan = get_object_or_404(StudioPlan, id=target_plan_id, is_active=True)

        photographer = getattr(user, 'photographer_profile', None)
        if not photographer:
            from App.Subscriptions.views_razorpay import get_or_create_photographer_profile
            photographer = get_or_create_photographer_profile(user)

        subscription = PhotographerSubscription.objects.filter(
            models.Q(user=user) | models.Q(photographer=photographer)
        ).order_by('-created_at').first()

        now = timezone.now()
        is_expired = False
        if not subscription:
            is_expired = True
        else:
            expiry = getattr(subscription, 'expiry_date', None) or getattr(subscription, 'expires_at', None)
            if subscription.status in ['expired', 'cancelled'] or (expiry and now >= expiry) or getattr(subscription, 'is_expired', False) or getattr(subscription, 'days_remaining', 0) <= 0:
                is_expired = True

        # Tier Rank Verification: only enforce upward restriction if currently ACTIVE and NOT expired
        is_allowed, reason = can_user_select_plan(user, target_plan, PhotographerSubscription)
        if not is_allowed:
            code = "CURRENT_PLAN_ACTIVE" if "already have an active subscription" in reason else "DOWNGRADE_NOT_ALLOWED"
            return Response({
                "error_code": code,
                "message": reason,
                "detail": reason
            }, status=status.HTTP_400_BAD_REQUEST)

        # Handle direct activation for testing / internal workflows
        if gateway == 'direct':
            duration_months = getattr(target_plan, 'duration_months', 1)
            expiry_date = now + timedelta(days=duration_months * 30)

            if subscription:
                subscription.user = user
                subscription.photographer = photographer
                subscription.plan = target_plan
                subscription.status = 'active'
                subscription.started_at = now
                subscription.expires_at = expiry_date
                subscription.auto_renew = True
                subscription.cancel_at_period_end = False
                subscription.cancelled_at = None
                subscription.payment_gateway_ref = 'direct'
                subscription.storage_limit_bytes = target_plan.storage_limit_bytes
                subscription.save()
                sub = subscription
            else:
                sub = PhotographerSubscription.objects.create(
                    user=user,
                    photographer=photographer,
                    plan=target_plan,
                    status='active',
                    started_at=now,
                    expires_at=expiry_date,
                    auto_renew=True,
                    payment_gateway_ref='direct',
                    storage_limit_bytes=target_plan.storage_limit_bytes,
                )

            # Mark all prior subscriptions as superseded
            PhotographerSubscription.objects.filter(
                models.Q(user=user) | models.Q(photographer=photographer)
            ).exclude(id=sub.id).update(status='superseded', auto_renew=False)

            if photographer:
                photographer.studio_plan = target_plan
                photographer.save(update_fields=['studio_plan'])

            if hasattr(user, 'profile') and user.profile:
                profile_fields = {f.name for f in user.profile._meta.get_fields()} if hasattr(user.profile, '_meta') else set()
                update_fields = []
                if 'storage_limit_bytes' in profile_fields:
                    user.profile.storage_limit_bytes = target_plan.storage_limit_bytes
                    update_fields.append('storage_limit_bytes')
                elif hasattr(user.profile, 'storage_limit_bytes'):
                    user.profile.storage_limit_bytes = target_plan.storage_limit_bytes

                if 'current_plan' in profile_fields:
                    user.profile.current_plan = target_plan.name
                    update_fields.append('current_plan')
                elif hasattr(user.profile, 'current_plan'):
                    user.profile.current_plan = target_plan.name

                if update_fields:
                    try:
                        user.profile.save(update_fields=update_fields)
                    except Exception:
                        pass

            SubscriptionPayment.objects.create(
                subscription=sub,
                plan=target_plan,
                amount=target_plan.total_price,
                currency=target_plan.currency,
                gateway='direct',
                gateway_order_id=f"dir_{int(now.timestamp())}",
                gateway_payment_id='pay_direct_sandbox',
                status='success',
                paid_at=now
            )

            return Response({
                "status": "success",
                "message": f"Successfully activated {target_plan.name} directly.",
                "direct_activated": True,
                "is_renewal": is_expired,
                "subscription": CurrentSubscriptionSerializer(sub).data
            }, status=status.HTTP_200_OK)

        # Standard Razorpay order / subscription creation
        from backend.atelier_plans.views_razorpay import get_or_create_razorpay_plan, razorpay_client, RAZORPAY_KEY_ID

        rzp_plan_id, amount_paise, duration_months = get_or_create_razorpay_plan(target_plan)
        order_receipt = f"order_{user.id}_{int(timezone.now().timestamp())}"
        order_id = None
        subscription_id = None

        try:
            rzp_order = razorpay_client.order.create({
                "amount": amount_paise,
                "currency": "INR",
                "receipt": order_receipt,
                "notes": {
                    "user_id": str(user.id),
                    "plan_id": target_plan.id,
                    "is_renewal": str(is_expired),
                }
            })
            order_id = rzp_order.get('id')
        except Exception:
            order_id = f"order_mock_{user.id}_{int(timezone.now().timestamp())}"

        try:
            rzp_sub = razorpay_client.subscription.create({
                "plan_id": rzp_plan_id,
                "total_count": 60,
                "quantity": 1,
                "customer_notify": 1,
                "notes": {
                    "user_id": str(user.id),
                    "target_plan_id": target_plan.id,
                }
            })
            subscription_id = rzp_sub.get('id')
        except Exception:
            subscription_id = f"sub_mock_{user.id}_{int(timezone.now().timestamp())}"

        return Response({
            "status": "success",
            "message": "Upgrade order created.",
            "is_renewal": is_expired,
            "razorpay_key": RAZORPAY_KEY_ID,
            "order_id": order_id,
            "subscription_id": subscription_id,
            "amount": float(amount_paise) / 100.0,
            "amount_paise": amount_paise,
            "currency": "INR",
            "plan_id": target_plan.id,
        }, status=status.HTTP_200_OK)

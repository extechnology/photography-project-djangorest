from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied
from django.utils import timezone
from django.db import models


class HasAICullingAccess(BasePermission):
    """
    Allows access only to authenticated users whose active main studio subscription
    includes AI Smart Culling.
    """
    message = "AI Smart Culling is not included in your current studio plan. Please upgrade your plan to access this feature."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Staff and superusers have unrestricted access
        if user.is_staff or user.is_superuser:
            return True

        from App.Subscriptions.sub_models import PhotographerSubscription

        now = timezone.now()
        photographer = getattr(user, 'photographer_profile', None)

        q = models.Q(user=user)
        if photographer:
            q |= models.Q(photographer=photographer)
        else:
            q |= models.Q(photographer__user=user)

        sub = getattr(user, 'subscription', None)
        if not sub:
            sub = PhotographerSubscription.objects.filter(q, status__in=['active', 'trial']).order_by('-created_at').first()

        if not sub or not getattr(sub, 'is_active', False):
            raise PermissionDenied({
                "error": "Active studio subscription required to use smart culling.",
                "detail": "No active studio subscription found. Please subscribe to a plan with AI Smart Culling.",
                "code": "no_active_plan",
                "ai_culling_enabled": False
            })

        expiry = getattr(sub, 'expires_at', None) or getattr(sub, 'expiry_date', None)
        if expiry and now >= expiry:
            raise PermissionDenied({
                "error": "Your subscription has expired. Please renew to continue using AI Smart Culling.",
                "detail": "Your subscription has expired. Please renew to continue using AI Smart Culling.",
                "code": "subscription_expired",
                "ai_culling_enabled": False
            })

        plan = getattr(sub, 'plan', None)
        legacy_plan = getattr(sub, 'legacy_plan', None)

        is_culling_enabled = False
        plan_name = "current"
        if plan:
            plan_name = plan.name
            is_culling_enabled = getattr(plan, 'ai_culling_enabled', False)
        elif legacy_plan:
            plan_name = legacy_plan.name
            is_culling_enabled = getattr(legacy_plan, 'ai_culling_enabled', False)

        if not is_culling_enabled:
            raise PermissionDenied({
                "error": "Your current plan does not include AI Smart Culling. Please upgrade to Studio Premium Elite.",
                "detail": f"AI Smart Culling is not included in your current subscription plan ('{plan_name}'). Please upgrade to Studio Premium Elite to unlock.",
                "code": "plan_ai_culling_disabled",
                "current_plan": plan_name,
                "ai_culling_enabled": False
            })

        return True


# Backward-compatible alias
HasAICullingPlanPermission = HasAICullingAccess


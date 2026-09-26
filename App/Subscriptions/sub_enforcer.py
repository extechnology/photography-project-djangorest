from datetime import timedelta
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied


class PlanEnforcementError(PermissionDenied):
    def __init__(self, code, message, upgrade_required=True):
        super().__init__({
            "error_code": code,
            "message": message,
            "upgrade_required": upgrade_required
        })


class PlanFeatureEnforcer:
    @staticmethod
    def get_subscription(photographer):
        sub = getattr(photographer, 'subscription', None)
        if sub and getattr(sub, 'is_currently_active', False):
            return sub
        plan = getattr(photographer, 'studio_plan', None) or getattr(photographer, 'plan', None)
        if plan:
            class MockSub:
                def __init__(self, p, prof):
                    self.plan = p
                    self.is_currently_active = True
                    self.effective_storage_limit_bytes = getattr(p, 'storage_limit_bytes', 0)
            return MockSub(plan, photographer)
        raise PlanEnforcementError("NO_ACTIVE_SUBSCRIPTION", "Please activate a Studio Plan to continue.")

    @classmethod
    def check_gallery_creation(cls, photographer):
        sub = cls.get_subscription(photographer)
        plan = sub.plan
        if not plan:
            return
        if plan.max_galleries > 0:
            active_count = photographer.galleries.exclude(status='archived').count()
            if active_count >= plan.max_galleries:
                raise PlanEnforcementError(
                    "GALLERY_LIMIT_EXCEEDED",
                    f"Your {plan.name} allows up to {plan.max_galleries} active galleries. Please upgrade to unlock more."
                )

    @classmethod
    def compute_gallery_expiry(cls, photographer):
        try:
            sub = cls.get_subscription(photographer)
            if sub.plan and sub.plan.gallery_expiry_days > 0:
                return timezone.now() + timedelta(days=sub.plan.gallery_expiry_days)
        except Exception:
            pass
        return None  # Permanent on Premium Elite

    @classmethod
    def check_gallery_template(cls, photographer, template_id):
        sub = cls.get_subscription(photographer)
        if not sub.plan:
            return
        allowed = sub.plan.allowed_templates
        if allowed and template_id not in allowed:
            raise PlanEnforcementError(
                "TEMPLATE_TIER_LOCKED",
                f"The '{template_id}' layout requires Studio Premium Elite. Your current plan supports: {', '.join(allowed)}."
            )

    @classmethod
    def check_face_search_permission(cls, photographer):
        sub = cls.get_subscription(photographer)
        if not sub.plan:
            return
        if not sub.plan.face_search_enabled:
            raise PlanEnforcementError(
                "FACE_SEARCH_LOCKED",
                "AI Biometric Face Search is disabled on Standard Quarterly. Upgrade to Standard Annual or Studio Premium Elite."
            )

    @classmethod
    def check_event_creation(cls, photographer):
        sub = cls.get_subscription(photographer)
        plan = sub.plan
        if not plan:
            return
        if plan.max_events > 0:
            events_count = photographer.shared_events.count() if hasattr(photographer, 'shared_events') else 0
            if events_count >= plan.max_events:
                raise PlanEnforcementError(
                    "EVENT_LIMIT_EXCEEDED",
                    f"Your plan allows up to {plan.max_events} Live Event albums. Please upgrade to unlock unlimited events."
                )

    @classmethod
    def check_storage_quota(cls, photographer, incoming_bytes):
        sub = cls.get_subscription(photographer)
        limit_bytes = sub.effective_storage_limit_bytes
        used_bytes = getattr(photographer, 'storage_used_bytes', 0)

        if used_bytes + incoming_bytes > limit_bytes:
            used_gb = round(used_bytes / (1024**3), 2)
            limit_gb = round(limit_bytes / (1024**3), 2)
            raise PlanEnforcementError(
                "STORAGE_LIMIT_EXCEEDED",
                f"Storage limit reached ({used_gb} GB used of {limit_gb} GB limit). Upgrade storage to continue uploading."
            )

    @classmethod
    def filter_inquiries_for_photographer(cls, photographer, queryset):
        try:
            sub = cls.get_subscription(photographer)
            if sub.plan and sub.plan.has_full_inquiry_access:
                return queryset, False  # full access

            limit = (sub.plan.max_inquiries if sub.plan else 10) or 10
            total_count = queryset.count()
            is_gated = total_count > limit
            return queryset[:limit], is_gated
        except Exception:
            return queryset, False

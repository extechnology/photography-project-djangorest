from rest_framework import serializers
from .sub_models import Plan, SubscriptionPlans, PhotographerSubscription, SubscriptionPayment


class PlanSerializer(serializers.ModelSerializer):
    period_label = serializers.CharField(read_only=True)
    billing_text = serializers.CharField(read_only=True)
    image_storage = serializers.SerializerMethodField()
    video_storage = serializers.SerializerMethodField()
    inquiry_access = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = [
            'id',
            'name',
            'subtitle',
            'tier',
            'billing_cycle',
            'period_label',
            'duration_months',
            'monthly_price',
            'original_monthly_price',
            'total_price',
            'billing_text',
            'currency',
            'image_storage_gb',
            'video_storage_gb',
            'image_storage',
            'video_storage',
            'storage_limit_bytes',
            'tag',
            'tag_type',
            'cta_text',
            'features',
            'max_galleries',
            'gallery_expiry_days',
            'face_search_enabled',
            'allowed_templates',
            'allowed_portfolio_templates',
            'max_events',
            'max_portfolio_posts',
            'can_upgrade_storage',
            'max_upgrade_image_gb',
            'max_inquiries',
            'has_full_inquiry_access',
            'inquiry_access',
            'is_active',
            'sort_order',
        ]

    def get_inquiry_access(self, obj):
        max_inq = getattr(obj, 'max_inquiries', 0)
        has_full = getattr(obj, 'has_full_inquiry_access', False)
        if max_inq > 0 and not has_full:
            return f"Random {max_inq} Inquiries"
        return "All Inquiries"

    def get_image_storage(self, obj):
        return f"{obj.image_storage_gb} GB"

    def get_video_storage(self, obj):
        return f"{obj.video_storage_gb} GB"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        templates = data.get('allowed_templates')
        if not templates:
            data['allowed_templates'] = ["editorial", "masonry", "cinematic", "minimal"] if instance.tier == 'premium' else ["editorial", "masonry"]
        elif isinstance(templates, str):
            import json
            try:
                data['allowed_templates'] = json.loads(templates)
            except Exception:
                data['allowed_templates'] = [templates]
        return data


StudioPlanSerializer = PlanSerializer


class PlanSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            'id',
            'name',
            'tier',
            'billing_cycle',
            'max_galleries',
            'allowed_templates',
            'face_search_enabled',
            'gallery_expiry_days',
            'max_events',
            'max_portfolio_posts',
            'has_full_inquiry_access',
            'duration_months',
            'total_price',
            'currency',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        templates = data.get('allowed_templates')
        if not templates:
            data['allowed_templates'] = ["editorial", "masonry", "cinematic", "minimal"] if instance.tier == 'premium' else ["editorial", "masonry"]
        elif isinstance(templates, str):
            import json
            try:
                data['allowed_templates'] = json.loads(templates)
            except Exception:
                data['allowed_templates'] = [templates]
        return data


class CurrentSubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSummarySerializer(read_only=True)
    start_date = serializers.DateTimeField(source='started_at', read_only=True)
    expiry_date = serializers.DateTimeField(source='expires_at', read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    storage = serializers.SerializerMethodField()
    usage = serializers.SerializerMethodField()

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
            'payment_gateway_ref',
        ]

    def get_storage(self, obj):
        photographer = obj.photographer
        limit_bytes = obj.effective_storage_limit_bytes if hasattr(obj, 'effective_storage_limit_bytes') else (photographer.get_storage_limit() if photographer else 225485783040)
        used_bytes = (photographer.storage_used_bytes + photographer.storage_reserved_bytes) if photographer else 0
        used_gb = round(used_bytes / (1024 ** 3), 1)
        limit_gb = round(limit_bytes / (1024 ** 3), 1)
        used_pct = round((used_bytes / limit_bytes) * 100, 1) if limit_bytes > 0 else 0.0

        return {
            "used_bytes": used_bytes,
            "limit_bytes": limit_bytes,
            "used_gb": used_gb,
            "limit_gb": limit_gb,
            "used_percentage": min(100.0, used_pct),
        }

    def get_usage(self, obj):
        photographer = obj.photographer
        plan = obj.plan

        # Galleries usage
        galleries_used = 0
        if photographer and hasattr(photographer, 'galleries'):
            try:
                galleries_used = photographer.galleries.exclude(status='archived').count()
            except Exception:
                galleries_used = 0
        galleries_limit = getattr(plan, 'max_galleries', 0) if plan else 0
        galleries_unlimited = bool(galleries_limit == 0)
        galleries_remaining = None if galleries_unlimited else max(0, galleries_limit - galleries_used)

        # Events usage
        events_used = 0
        if photographer and hasattr(photographer, 'shared_events'):
            try:
                events_used = photographer.shared_events.count()
            except Exception:
                events_used = 0
        events_limit = getattr(plan, 'max_events', 0) if plan else 0
        events_unlimited = bool(events_limit == 0)
        events_remaining = None if events_unlimited else max(0, events_limit - events_used)

        # Portfolio Posts usage
        posts_used = 0
        if photographer and hasattr(photographer, 'posts'):
            try:
                posts_used = photographer.posts.count()
            except Exception:
                posts_used = 0
        posts_limit = getattr(plan, 'max_portfolio_posts', 0) if plan else 0
        posts_unlimited = bool(posts_limit == 0)
        posts_remaining = None if posts_unlimited else max(0, posts_limit - posts_used)

        return {
            "galleries": {
                "used": galleries_used,
                "limit": galleries_limit,
                "remaining": galleries_remaining,
                "is_unlimited": galleries_unlimited,
            },
            "events": {
                "used": events_used,
                "limit": events_limit,
                "remaining": events_remaining,
                "is_unlimited": events_unlimited,
            },
            "portfolio_posts": {
                "used": posts_used,
                "limit": posts_limit,
                "remaining": posts_remaining,
                "is_unlimited": posts_unlimited,
            },
        }


class CheckoutRequestSerializer(serializers.Serializer):
    plan_id = serializers.CharField(required=True)
    gateway = serializers.ChoiceField(choices=['razorpay', 'direct'], default='razorpay')


class VerifyPaymentRequestSerializer(serializers.Serializer):
    plan_id = serializers.CharField(required=True)
    gateway_order_id = serializers.CharField(required=False, allow_blank=True, default='')
    gateway_payment_id = serializers.CharField(required=False, allow_blank=True, default='')
    gateway_signature = serializers.CharField(required=False, allow_blank=True, default='')

    def to_internal_value(self, data):
        # Support both generic gateway_* and razorpay_* param names
        data = data.copy()
        if 'razorpay_order_id' in data and not data.get('gateway_order_id'):
            data['gateway_order_id'] = data['razorpay_order_id']
        if 'razorpay_payment_id' in data and not data.get('gateway_payment_id'):
            data['gateway_payment_id'] = data['razorpay_payment_id']
        if 'razorpay_signature' in data and not data.get('gateway_signature'):
            data['gateway_signature'] = data['razorpay_signature']
        return super().to_internal_value(data)


# =============================================================================
# Legacy Serializers (Preserved for Backward Compatibility)
# =============================================================================

class SubscriptionPlansSerializer(serializers.ModelSerializer):
    formatted_storage = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlans
        fields = [
            'id',
            'name',
            'tier',
            'billing_cycle',
            'price_monthly',
            'price',
            'storage_limit_bytes',
            'formatted_storage',
            'max_galleries',
            'allowed_templates',
            'video_delivery_enabled',
            'face_search_enabled',
            'watermark_customization',
            'features_list',
        ]

    def get_formatted_storage(self, obj):
        gb = round(obj.storage_limit_bytes / (1024 ** 3), 1)
        if gb >= 1000:
            return f"{round(gb / 1024, 1)} TB"
        return f"{int(gb) if gb.is_integer() else gb} GB"


class PhotographerSubscriptionSerializer(serializers.ModelSerializer):
    plan = serializers.SerializerMethodField()
    storage_used_bytes = serializers.IntegerField(source='photographer.storage_used_bytes', read_only=True)
    storage_reserved_bytes = serializers.IntegerField(source='photographer.storage_reserved_bytes', read_only=True)
    storage_limit_bytes = serializers.SerializerMethodField()
    storage_percentage = serializers.SerializerMethodField()

    class Meta:
        model = PhotographerSubscription
        fields = [
            'id',
            'status',
            'start_date',
            'expiry_date',
            'auto_renew',
            'plan',
            'storage_used_bytes',
            'storage_reserved_bytes',
            'storage_limit_bytes',
            'storage_percentage',
        ]

    def get_plan(self, obj):
        if obj.plan:
            return PlanSummarySerializer(obj.plan).data
        if obj.legacy_plan:
            return SubscriptionPlansSerializer(obj.legacy_plan).data
        return None

    def get_storage_limit_bytes(self, obj):
        if hasattr(obj, 'effective_storage_limit_bytes'):
            return obj.effective_storage_limit_bytes
        if obj.plan:
            return obj.plan.storage_limit_bytes
        if obj.legacy_plan:
            return obj.legacy_plan.storage_limit_bytes
        from django.conf import settings
        return getattr(settings, 'TEST_USER_STORAGE_LIMIT_BYTES', 21474836480)

    def get_storage_percentage(self, obj):
        limit = self.get_storage_limit_bytes(obj)
        if limit <= 0:
            return 0.0
        used = obj.photographer.storage_used_bytes + obj.photographer.storage_reserved_bytes
        return min(100.0, round((used / limit) * 100, 2))


class UpgradeSubscriptionSerializer(serializers.Serializer):
    plan_id = serializers.CharField(required=True)
    billing_cycle = serializers.ChoiceField(choices=['monthly', 'annual', 'quarterly'], default='annual')
    payment_method = serializers.CharField(required=False, default='card')

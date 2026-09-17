from rest_framework import serializers
from .sub_models import Plan, SubscriptionPlans, PhotographerSubscription, SubscriptionPayment


class PlanSerializer(serializers.ModelSerializer):
    period_label = serializers.CharField(read_only=True)
    billing_text = serializers.CharField(read_only=True)
    image_storage = serializers.SerializerMethodField()
    video_storage = serializers.SerializerMethodField()

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
            'tag',
            'tag_type',
            'image_storage',
            'video_storage',
            'storage_limit_bytes',
            'features',
            'cta_text',
            'is_active',
            'sort_order',
        ]

    def get_image_storage(self, obj):
        return f"{obj.image_storage_gb} GB"

    def get_video_storage(self, obj):
        return f"{obj.video_storage_gb} GB"


class PlanSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ['id', 'name', 'tier', 'billing_cycle', 'duration_months', 'total_price', 'currency']


class CurrentSubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSummarySerializer(read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    storage = serializers.SerializerMethodField()

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
            'auto_renew',
            'payment_gateway_ref',
        ]

    def get_storage(self, obj):
        photographer = obj.photographer
        limit_bytes = obj.plan.storage_limit_bytes if obj.plan else photographer.get_storage_limit()
        used_bytes = photographer.storage_used_bytes + photographer.storage_reserved_bytes
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
    plan = SubscriptionPlansSerializer(read_only=True)
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

    def get_storage_limit_bytes(self, obj):
        if obj.plan:
            return obj.plan.storage_limit_bytes
        if obj.legacy_plan:
            return obj.legacy_plan.storage_limit_bytes
        return 10737418240

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

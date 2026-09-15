from rest_framework import serializers
from .sub_models import SubscriptionPlans, PhotographerSubscription


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
            'started_at',
            'expires_at',
            'auto_renew',
            'plan',
            'storage_used_bytes',
            'storage_reserved_bytes',
            'storage_limit_bytes',
            'storage_percentage',
        ]

    def get_storage_limit_bytes(self, obj):
        return obj.plan.storage_limit_bytes if obj.plan else 10737418240

    def get_storage_percentage(self, obj):
        limit = self.get_storage_limit_bytes(obj)
        if limit <= 0:
            return 0.0
        used = obj.photographer.storage_used_bytes + obj.photographer.storage_reserved_bytes
        return min(100.0, round((used / limit) * 100, 2))


class UpgradeSubscriptionSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField(required=True)
    billing_cycle = serializers.ChoiceField(choices=['monthly', 'annual'], default='annual')
    payment_method = serializers.CharField(required=False, default='card')

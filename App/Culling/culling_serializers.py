from rest_framework import serializers
from .culling_models import (
    CullingSession,
    CullingClusterGroup,
    CullingItem,
    CullingPaymentOrder,
)


class CullingItemSerializer(serializers.ModelSerializer):
    cluster_id = serializers.UUIDField(source='cluster.id', read_only=True, allow_null=True)
    image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = CullingItem
        fields = [
            'id',
            'cluster_id',
            'original_filename',
            'size_bytes',
            'width',
            'height',
            'sharpness_score',
            'similarity_with_winner',
            'status',
            'is_best_pick',
            'assigned_category',
            'image_url',
            'thumbnail_url',
            'file_url',
            'created_at',
        ]

    def get_image_url(self, obj):
        request = self.context.get('request')
        target = obj.image or getattr(obj, 'file', None)
        if target:
            return request.build_absolute_uri(target.url) if request else target.url
        return None

    def get_thumbnail_url(self, obj):
        request = self.context.get('request')
        target = obj.thumbnail or obj.image or getattr(obj, 'file', None)
        if target:
            return request.build_absolute_uri(target.url) if request else target.url
        return None

    def get_file_url(self, obj):
        return self.get_image_url(obj)


class CullingClusterSerializer(serializers.ModelSerializer):
    photos = CullingItemSerializer(many=True, read_only=True)
    best_pick_id = serializers.UUIDField(source='best_pick_item.id', read_only=True, allow_null=True)

    class Meta:
        model = CullingClusterGroup
        fields = [
            'id',
            'cluster_number',
            'average_similarity',
            'total_photos',
            'duplicates_count',
            'wasted_bytes',
            'best_pick_id',
            'photos',
        ]


# Backward compatibility alias
CullingClusterGroupSerializer = CullingClusterSerializer


class CullingSessionSerializer(serializers.ModelSerializer):
    clusters = CullingClusterSerializer(many=True, read_only=True)
    items_count = serializers.IntegerField(source='items.count', read_only=True)
    items = CullingItemSerializer(many=True, read_only=True)

    class Meta:
        model = CullingSession
        fields = [
            'id',
            'session_key',
            'title',
            'status',
            'is_paid',
            'paid_tier',
            'max_photos_allowed',
            'paid_amount',
            'currency',
            'paid_at',
            'total_photos',
            'duplicate_count',
            'keeper_count',
            'total_saved_bytes',
            'progress_percentage',
            'progress_status_text',
            'items_count',
            'clusters',
            'items',
            'created_at',
            'updated_at',
        ]


class CullingPaymentOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = CullingPaymentOrder
        fields = [
            'id',
            'user',
            'session',
            'razorpay_order_id',
            'razorpay_payment_id',
            'tier_name',
            'amount_inr',
            'amount_paisa',
            'currency',
            'status',
            'created_at',
        ]
        read_only_fields = fields

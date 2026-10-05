from rest_framework import serializers
from .models import CullingPricingTier, CullingSession, CullingPhoto, CullingCluster


class CullingPricingTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = CullingPricingTier
        fields = [
            'id', 'name', 'price_inr', 'photos_limit', 
            'badge', 'description', 'features', 'is_popular'
        ]


class CullingPhotoSerializer(serializers.ModelSerializer):
    previewUrl = serializers.SerializerMethodField()
    sizeBytes = serializers.IntegerField(source='size_bytes')
    sizeMB = serializers.FloatField(source='size_mb')
    sharpnessScore = serializers.FloatField(source='sharpness_score')
    rawSharpnessVariance = serializers.FloatField(source='raw_sharpness_variance')
    clusterId = serializers.CharField(source='cluster_id', allow_blank=True)
    isBestPick = serializers.BooleanField(source='is_best_pick')
    similarityWithBest = serializers.FloatField(source='similarity_with_best')

    class Meta:
        model = CullingPhoto
        fields = [
            'id', 'name', 'previewUrl', 'sizeBytes', 'sizeMB',
            'sharpnessScore', 'rawSharpnessVariance', 'clusterId',
            'isBestPick', 'status', 'similarityWithBest', 'hash'
        ]

    def get_previewUrl(self, obj):
        if not obj.file:
            return ""
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url


class CullingClusterSerializer(serializers.ModelSerializer):
    bestPickId = serializers.CharField(source='best_pick_id')
    photoIds = serializers.ListField(source='photo_ids')
    averageSimilarity = serializers.FloatField(source='average_similarity')

    class Meta:
        model = CullingCluster
        fields = ['id', 'bestPickId', 'photoIds', 'averageSimilarity']


class ActiveCullingSessionResponseSerializer(serializers.ModelSerializer):
    tier = CullingPricingTierSerializer(read_only=True)
    photos = CullingPhotoSerializer(many=True, read_only=True)
    clusters = CullingClusterSerializer(many=True, read_only=True)

    class Meta:
        model = CullingSession
        fields = [
            'id', 'status', 'is_paid', 'tier',
            'total_photos', 'total_bytes', 'photos', 'clusters'
        ]


class CullingPhotoSyncItemSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=128)
    status = serializers.ChoiceField(choices=['keep', 'discard'])
    isBestPick = serializers.BooleanField(default=False)
    clusterId = serializers.CharField(max_length=128, required=False, allow_blank=True)
    similarityWithBest = serializers.FloatField(required=False, default=0.0)
    sharpnessScore = serializers.FloatField(required=False, default=0.0)
    rawSharpnessVariance = serializers.FloatField(required=False, default=0.0)
    hash = serializers.CharField(max_length=64, required=False, allow_blank=True)


class CullingClusterSyncItemSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=128)
    bestPickId = serializers.CharField(max_length=128, allow_blank=True)
    photoIds = serializers.ListField(child=serializers.CharField(max_length=128))
    averageSimilarity = serializers.FloatField(required=False, default=0.0)


class CullingSessionSyncSerializer(serializers.Serializer):
    session_id = serializers.CharField(max_length=64)
    tier_id = serializers.CharField(max_length=64, required=False, allow_null=True)
    is_paid = serializers.BooleanField(required=False, default=True)
    photos = CullingPhotoSyncItemSerializer(many=True)
    clusters = CullingClusterSyncItemSerializer(many=True)

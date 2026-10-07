from rest_framework import serializers
from django.db import models
from .models import CullingPricingTier, CullingSession, CullingPhoto, CullingCluster

 
class CullingPricingTierSerializer(serializers.ModelSerializer):
    photosLimit = serializers.IntegerField(source="photos_limit")
    isPopular = serializers.BooleanField(source="is_popular", required=False)
    price = serializers.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        model = CullingPricingTier
        fields = [
            "id",
            "name",
            "price",
            "photosLimit",
            "badge",
            "description",
            "features",
            "is_popular",
            "isPopular",
            "is_active",
            "display_order",
        ]


class CullingPhotoSerializer(serializers.ModelSerializer):
    previewUrl = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    sizeBytes = serializers.SerializerMethodField()
    sizeMB = serializers.SerializerMethodField()
    sharpnessScore = serializers.FloatField(source="sharpness_score")
    rawSharpnessVariance = serializers.FloatField(source="raw_sharpness_variance")
    clusterId = serializers.CharField(source="cluster_id", allow_null=True, required=False)
    isBestPick = serializers.BooleanField(source="is_best_pick")
    similarityWithBest = serializers.SerializerMethodField()
    hash = serializers.SerializerMethodField()
    faceAnalysis = serializers.JSONField(source="face_analysis", required=False, default=dict)

    class Meta:
        model = CullingPhoto
        fields = [
            "id",
            "name",
            "previewUrl",
            "sizeBytes",
            "sizeMB",
            "sharpnessScore",
            "rawSharpnessVariance",
            "clusterId",
            "isBestPick",
            "status",
            "similarityWithBest",
            "hash",
            "faceAnalysis",
        ]

    def get_name(self, obj):
        return obj.original_filename or obj.name or ""

    def get_sizeBytes(self, obj):
        return obj.file_size_bytes or obj.size_bytes or 0

    def get_similarityWithBest(self, obj):
        if obj.similarity_with_winner is not None:
            return obj.similarity_with_winner
        return obj.similarity_with_best

    def get_hash(self, obj):
        return obj.perceptual_hash or obj.hash or ""

    def get_previewUrl(self, obj):
        request = self.context.get("request")
        if obj.file:
            if request:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return ""

    def get_sizeMB(self, obj):
        sz = obj.file_size_bytes or obj.size_bytes or 0
        if sz > 0:
            return round(sz / (1024 * 1024), 1)
        return obj.size_mb or 1.5


class CullingClusterSerializer(serializers.ModelSerializer):
    bestPickId = serializers.SerializerMethodField()
    photoIds = serializers.SerializerMethodField()
    averageSimilarity = serializers.FloatField(source="average_similarity")
    totalPhotos = serializers.SerializerMethodField()
    duplicatesCount = serializers.SerializerMethodField()
    wastedBytes = serializers.SerializerMethodField()

    class Meta:
        model = CullingCluster
        fields = [
            "id",
            "title",
            "averageSimilarity",
            "bestPickId",
            "photoIds",
            "totalPhotos",
            "duplicatesCount",
            "wastedBytes",
        ]

    def get_bestPickId(self, obj):
        return obj.best_pick_item_id or obj.best_pick_id or ""

    def get_photoIds(self, obj):
        p_ids = list(
            CullingPhoto.objects.filter(session=obj.session, cluster_id=obj.id).values_list("id", flat=True)
        )
        if p_ids:
            return p_ids
        return obj.photo_ids or []

    def get_totalPhotos(self, obj):
        if obj.total_photos and obj.total_photos > 1:
            return obj.total_photos
        count = CullingPhoto.objects.filter(session=obj.session, cluster_id=obj.id).count()
        return count or len(obj.photo_ids or []) or 1

    def get_duplicatesCount(self, obj):
        tot = self.get_totalPhotos(obj)
        return max(0, tot - 1)

    def get_wastedBytes(self, obj):
        if obj.wasted_bytes:
            return obj.wasted_bytes
        wasted_qs = CullingPhoto.objects.filter(
            session=obj.session,
            cluster_id=obj.id,
            is_best_pick=False
        ).aggregate(total=models.Sum('file_size_bytes'))
        return wasted_qs['total'] or 0


class ActiveCullingSessionSerializer(serializers.ModelSerializer):
    photos = serializers.SerializerMethodField()
    clusters = CullingClusterSerializer(many=True, read_only=True)
    photo_count = serializers.SerializerMethodField()

    class Meta:
        model = CullingSession
        fields = [
            "id",
            "title",
            "status",
            "photo_count",
            "photos",
            "clusters",
            "keeper_count",
            "duplicate_count",
            "wasted_bytes",
            "created_at",
            "updated_at",
        ]

    def get_photos(self, obj):
        request = self.context.get("request")
        photos = obj.photos.all()
        return CullingPhotoSerializer(photos, many=True, context={"request": request}).data

    def get_photo_count(self, obj):
        return obj.total_photos or obj.photos.count()


# Aliases for backward compatibility
CullingSessionDetailSerializer = ActiveCullingSessionSerializer
ActiveCullingSessionResponseSerializer = ActiveCullingSessionSerializer

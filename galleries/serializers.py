"""
Compatibility module mapping galleries.serializers to App.Storage.storage_serializers
"""
from App.Storage.storage_serializers import (
    GallerySerializer,
    GalleryDetailResponseSerializer,
    GalleryDetailResponseSerializer as GalleryDetailSerializer,
    GallerySettingsUpdateSerializer,
    GallerySettingsUpdateSerializer as GalleryUpdateSerializer,
    PublicGallerySerializer,
    MediaSerializer,
    MediaSerializer as MediaItemSerializer,
)

from rest_framework import serializers
from .models import GalleryViewer, ViewerLikedMedia

__all__ = [
    'GallerySerializer',
    'GalleryDetailResponseSerializer',
    'GalleryDetailSerializer',
    'GallerySettingsUpdateSerializer',
    'GalleryUpdateSerializer',
    'PublicGallerySerializer',
    'MediaSerializer',
    'MediaItemSerializer',
    'ViewerSendOtpSerializer',
    'ViewerVerifyOtpSerializer',
    'ViewerProfileSerializer',
    'ViewerToggleFavoriteSerializer',
    'ViewerBulkToggleFavoriteSerializer',
]


class ViewerSendOtpSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class ViewerVerifyOtpSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp = serializers.CharField(max_length=6, min_length=4, required=True)


class ViewerProfileSerializer(serializers.ModelSerializer):
    liked_media_ids = serializers.SerializerMethodField()

    class Meta:
        model = GalleryViewer
        fields = ['email', 'name', 'session_token', 'liked_media_ids']

    def get_liked_media_ids(self, obj):
        return [
            str(mid)
            for mid in ViewerLikedMedia.objects.filter(viewer=obj).values_list('media_id', flat=True)
        ]


class ViewerToggleFavoriteSerializer(serializers.Serializer):
    media_id = serializers.CharField(required=True)
    is_favorite = serializers.BooleanField(required=True)
    email = serializers.EmailField(required=False)


class ViewerBulkToggleFavoriteSerializer(serializers.Serializer):
    media_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )
    is_favorite = serializers.BooleanField(required=True)
    select_all = serializers.BooleanField(required=False, default=False)
    email = serializers.EmailField(required=False)

from rest_framework import serializers
from App.Storage.storage_serializers import GalleryDetailResponseSerializer
from gallery.models import (
    Gallery,
    GalleryMedia,
)

class ReorderGalleryMediaSerializer(serializers.Serializer):
    media_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        help_text="Full ordered list of all media item UUIDs in the gallery section"
    )
    media_id = serializers.CharField(
        required=False,
        help_text="Single media ID to move"
    )
    action = serializers.ChoiceField(
        choices=['move_up', 'move_down', 'set_cover', 'move_to_position'],
        required=False,
        help_text="Quick directional sequence mutation"
    )
    target_position = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Target absolute index when moving a single item"
    )

    def validate(self, attrs):
        if not attrs.get('media_ids') and not (attrs.get('media_id') and attrs.get('action')):
            raise serializers.ValidationError("Either 'media_ids' or ('media_id' and 'action') must be provided.")
        return attrs


# Alias for compatibility
GalleryDetailSerializer = GalleryDetailResponseSerializer

from galleries.serializers import (
    ViewerSendOtpSerializer,
    ViewerVerifyOtpSerializer,
    ViewerProfileSerializer,
    ViewerToggleFavoriteSerializer,
    ViewerBulkToggleFavoriteSerializer,
)

__all__ = [
    'ReorderGalleryMediaSerializer',
    'GalleryDetailSerializer',
    'ViewerSendOtpSerializer',
    'ViewerVerifyOtpSerializer',
    'ViewerProfileSerializer',
    'ViewerToggleFavoriteSerializer',
    'ViewerBulkToggleFavoriteSerializer',
]

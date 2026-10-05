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

__all__ = [
    'GallerySerializer',
    'GalleryDetailResponseSerializer',
    'GalleryDetailSerializer',
    'GallerySettingsUpdateSerializer',
    'GalleryUpdateSerializer',
    'PublicGallerySerializer',
    'MediaSerializer',
    'MediaItemSerializer',
]

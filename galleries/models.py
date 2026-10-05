"""
Compatibility module mapping galleries.models to App.Storage.storage_models
"""
from App.Storage.storage_models import (
    Gallery,
    Media,
    Media as MediaItem,
    Media as GalleryMedia,
    GallerySection,
    GalleryClientSelection,
    BulkDownloadJob,
)

__all__ = [
    'Gallery',
    'Media',
    'MediaItem',
    'GalleryMedia',
    'GallerySection',
    'GalleryClientSelection',
    'BulkDownloadJob',
]


"""
gallery.models compatibility module mapping to App.Storage.storage_models
"""
from App.Storage.storage_models import (
    Gallery,
    GallerySection,
    Media as GalleryMedia,
    Media,
    GalleryClientSelection,
    BulkDownloadJob,
    GalleryGuestSession,
    GalleryStoryVideo,
    story_video_upload_path,
)

__all__ = [
    'Gallery',
    'GallerySection',
    'GalleryMedia',
    'Media',
    'GalleryClientSelection',
    'BulkDownloadJob',
    'GalleryGuestSession',
    'GalleryStoryVideo',
    'story_video_upload_path',
]

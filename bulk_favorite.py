"""
Compatibility module re-exporting from galleries.views.bulk_favorite
"""
from galleries.views.bulk_favorite import (
    BulkMediaFavoriteAPIView,
    BulkFavoriteService,
    BulkMediaFavoriteRequestSerializer,
    BulkMediaFavoriteResponseSerializer,
    get_gallery_model,
    get_media_model,
    urlpatterns,
)

__all__ = [
    'BulkMediaFavoriteAPIView',
    'BulkFavoriteService',
    'BulkMediaFavoriteRequestSerializer',
    'BulkMediaFavoriteResponseSerializer',
    'get_gallery_model',
    'get_media_model',
    'urlpatterns',
]

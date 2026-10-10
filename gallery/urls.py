from django.urls import path
from .views import (
    GalleryViewSet,
    GalleryGuestSessionView,
    GalleryStoryVideoListCreateView,
    TrackStoryVideoActionView,
)
from galleries.views.bulk_favorite import BulkMediaFavoriteAPIView
from gallery_favorites_api import (
    BulkToggleMediaFavoriteView,
    ToggleMediaFavoriteView,
)
from galleries.views_upload import (
    BulkUploadGalleryMediaView,
    GalleryUploadResumeStatusView,
)


urlpatterns = [
    # Reorder Sequence
    path('galleries/<uuid:pk>/media/reorder/', GalleryViewSet.as_view({'post': 'reorder_media'}), name='gallery-media-reorder-uuid'),
    path('galleries/<str:pk>/media/reorder/', GalleryViewSet.as_view({'post': 'reorder_media'}), name='gallery-media-reorder'),

    # Guest Profile & Session Management (Public)
    path('public/galleries/<str:id_or_slug>/guest-session/', GalleryGuestSessionView.as_view(), name='gallery-guest-session'),
    path('galleries/<str:id_or_slug>/guest-session/', GalleryGuestSessionView.as_view(), name='gallery-guest-session-direct'),

    # Story & Reel Videos CRUD
    path('public/galleries/<str:id_or_slug>/story-videos/', GalleryStoryVideoListCreateView.as_view(), name='gallery-story-videos'),
    path('galleries/<str:id_or_slug>/story-videos/', GalleryStoryVideoListCreateView.as_view(), name='gallery-story-videos-direct'),

    # Story Video Telemetry (download / share track)
    path('public/galleries/<str:id_or_slug>/story-videos/<uuid:video_id>/track/', TrackStoryVideoActionView.as_view(), name='gallery-story-video-track-uuid'),
    path('public/galleries/<str:id_or_slug>/story-videos/<str:video_id>/track/', TrackStoryVideoActionView.as_view(), name='gallery-story-video-track'),
    path('galleries/<str:id_or_slug>/story-videos/<uuid:video_id>/track/', TrackStoryVideoActionView.as_view(), name='gallery-story-video-track-direct-uuid'),
    path('galleries/<str:id_or_slug>/story-videos/<str:video_id>/track/', TrackStoryVideoActionView.as_view(), name='gallery-story-video-track-direct'),

    # Reusable Bulk Media Favorite & Unfavorite Module
    path('galleries/<uuid:gallery_id>/media/bulk-favorite/', BulkToggleMediaFavoriteView.as_view(), name='gallery-media-bulk-favorite'),
    path('galleries/<str:gallery_id>/media/bulk-favorite/', BulkToggleMediaFavoriteView.as_view(), name='gallery-media-bulk-favorite-str'),
    path('galleries/media/bulk-favorite/', BulkMediaFavoriteAPIView.as_view(), name='gallery-media-bulk-favorite-flat'),
    path('galleries/<uuid:gallery_id>/media/<uuid:media_id>/favorite/', ToggleMediaFavoriteView.as_view(), name='gallery-media-single-favorite'),
    path('galleries/<str:gallery_id>/media/<str:media_id>/favorite/', ToggleMediaFavoriteView.as_view(), name='gallery-media-single-favorite-str'),

    # High-Performance Batch Chunked Uploads & Resume Status
    path('galleries/<uuid:gallery_id>/media/bulk-upload/', BulkUploadGalleryMediaView.as_view(), name='gallery-media-bulk-upload-uuid'),
    path('galleries/<str:gallery_id>/media/bulk-upload/', BulkUploadGalleryMediaView.as_view(), name='gallery-media-bulk-upload'),
    path('galleries/<uuid:gallery_id>/upload-status/', GalleryUploadResumeStatusView.as_view(), name='gallery-upload-status-uuid'),
    path('galleries/<str:gallery_id>/upload-status/', GalleryUploadResumeStatusView.as_view(), name='gallery-upload-status'),
]


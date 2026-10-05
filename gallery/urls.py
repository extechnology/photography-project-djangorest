from django.urls import path
from .views import (
    GalleryViewSet,
    GalleryGuestSessionView,
    GalleryStoryVideoListCreateView,
    TrackStoryVideoActionView,
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
]

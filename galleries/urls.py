from django.urls import path
from .views.media_download import MediaDownloadView
from .views.gallery_zip_download import GalleryZipDownloadView
from .views.viewer_likes import (
    ViewerSendOtpView,
    ViewerVerifyOtpView,
    ViewerLikedMediaListView,
    ViewerToggleFavoriteView,
    ViewerBulkToggleFavoriteView,
    GalleryClientFavoritesReviewView,
)

urlpatterns = [
    # Single media item download with format selection
    path('api/galleries/media/<uuid:media_id>/download/', MediaDownloadView.as_view(), name='gallery-media-download'),
    path('galleries/media/<uuid:media_id>/download/', MediaDownloadView.as_view(), name='gallery-media-download-rel'),
    
    # Public gallery ZIP download with format selection
    path('api/public/galleries/<str:id_or_slug>/download-zip/', GalleryZipDownloadView.as_view(), name='public-gallery-download-zip'),
    path('public/galleries/<str:id_or_slug>/download-zip/', GalleryZipDownloadView.as_view(), name='public-gallery-download-zip-rel'),
    
    # Dashboard gallery ZIP download with format selection
    path('api/galleries/<uuid:gallery_id>/download-zip/', GalleryZipDownloadView.as_view(), name='gallery-download-zip'),
    path('galleries/<uuid:gallery_id>/download-zip/', GalleryZipDownloadView.as_view(), name='gallery-download-zip-rel'),

    # Viewing user public liking & OTP endpoints
    path('public/galleries/<str:slug_or_id>/auth/send-otp/', ViewerSendOtpView.as_view(), name='galleries-viewer-send-otp'),
    path('public/galleries/<str:slug_or_id>/auth/verify-otp/', ViewerVerifyOtpView.as_view(), name='galleries-viewer-verify-otp'),
    path('public/galleries/<str:slug_or_id>/likes/', ViewerLikedMediaListView.as_view(), name='galleries-viewer-likes-list'),
    path('public/galleries/<str:slug_or_id>/favorite/', ViewerToggleFavoriteView.as_view(), name='galleries-viewer-toggle-favorite'),
    path('public/galleries/<str:slug_or_id>/bulk-like/', ViewerBulkToggleFavoriteView.as_view(), name='galleries-viewer-bulk-like'),

    # Studio Photographer Client Favorites Review
    path('galleries/<uuid:gallery_id>/client-favorites/', GalleryClientFavoritesReviewView.as_view(), name='galleries-client-favorites-uuid'),
    path('galleries/<str:gallery_id>/client-favorites/', GalleryClientFavoritesReviewView.as_view(), name='galleries-client-favorites'),
]

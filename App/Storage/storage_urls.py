from django.urls import path
from App.Storage.storage_views import (
    # Gallery Management Views
    GalleryListCreateView,
    GalleryDetailView,
    GalleryRestoreView,
    GalleryTemplateUpdateView,
    GalleryBannerUpdateView,
    GalleryMasonrySlotBannerView,
    GalleryCoverUpdateView,
    GalleryMediaReorderView,
    GalleryMoveMediaSectionView,
    GallerySectionListCreateView,
    GallerySectionDetailDeleteView,
    GallerySectionRenameView,
    GallerySectionReorderView,
    GalleryMediaFavoriteToggleView,
    GalleryAnalyticsView,
    GalleryAnalyticsEventTrackView,
    GalleryAnalyticsExportCsvView,
    GalleryShareDetailsView,

    # Media Uploads & Management
    StandardMediaUploadView,
    MediaDetailDeleteView,
    MediaBulkDeleteView,

    # Public Client Access
    PublicGallerySlugOrIdView,
    PublicGalleryDownloadZipView,
    PublicGalleryVerifyPinView,
    PublicGalleryTrackView,

    # Face Discovery
    GalleryFaceSearchView,
)
from galleries.views.bulk_favorite import BulkMediaFavoriteAPIView
from galleries.views_upload import (
    BulkUploadGalleryMediaView,
    GalleryUploadResumeStatusView,
)

urlpatterns = [
    # -------------------------------------------------------------------------
    # Galleries Management (Frontend API Contract)
    # -------------------------------------------------------------------------
    path('galleries/', GalleryListCreateView.as_view(), name='gallery-list-create'),

    # Sections
    path('galleries/<str:gallery_id>/sections/', GallerySectionListCreateView.as_view(), name='gallery-sections-list-create'),
    path('galleries/<str:gallery_id>/sections/rename/', GallerySectionRenameView.as_view(), name='gallery-sections-rename'),
    path('galleries/<str:gallery_id>/sections/reorder/', GallerySectionReorderView.as_view(), name='gallery-sections-reorder'),
    path('galleries/<str:gallery_id>/sections/<str:section_title>/', GallerySectionDetailDeleteView.as_view(), name='gallery-section-delete'),

    # Move Media Section
    path('galleries/<str:gallery_id>/media/move-section/', GalleryMoveMediaSectionView.as_view(), name='gallery-media-move-section'),

    # Layout, Cover & Template
    path('galleries/<str:gallery_id>/template/', GalleryTemplateUpdateView.as_view(), name='gallery-template-update'),
    path('galleries/<str:gallery_id>/banners/', GalleryBannerUpdateView.as_view(), name='gallery-banners-update'),
    path('galleries/<str:gallery_id>/masonry-slots/', GalleryMasonrySlotBannerView.as_view(), name='gallery-masonry-slots'),
    path('galleries/<str:gallery_id>/cover/', GalleryCoverUpdateView.as_view(), name='gallery-cover-update'),

    # Media Reordering & Favorites
    path('galleries/<str:gallery_id>/media/reorder/', GalleryMediaReorderView.as_view(), name='gallery-media-reorder'),
    path('galleries/<str:gallery_id>/media/<uuid:media_id>/favorite/', GalleryMediaFavoriteToggleView.as_view(), name='gallery-media-toggle-favorite'),
    path('galleries/<uuid:gallery_id>/media/bulk-favorite/', BulkMediaFavoriteAPIView.as_view(), name='storage-gallery-media-bulk-favorite'),
    path('galleries/<str:gallery_id>/media/bulk-favorite/', BulkMediaFavoriteAPIView.as_view(), name='storage-gallery-media-bulk-favorite-str'),
    path('galleries/media/bulk-favorite/', BulkMediaFavoriteAPIView.as_view(), name='storage-gallery-media-bulk-favorite-flat'),

    # High-Performance Batch Chunked Uploads & Direct Media Ingestion
    path('galleries/<str:gallery_id>/upload/', StandardMediaUploadView.as_view(), name='standard-media-upload'),
    path('galleries/<uuid:gallery_id>/media/bulk-upload/', BulkUploadGalleryMediaView.as_view(), name='storage-gallery-media-bulk-upload-uuid'),
    path('galleries/<str:gallery_id>/media/bulk-upload/', BulkUploadGalleryMediaView.as_view(), name='storage-gallery-media-bulk-upload'),
    path('galleries/<uuid:gallery_id>/upload-status/', GalleryUploadResumeStatusView.as_view(), name='storage-gallery-upload-status-uuid'),
    path('galleries/<str:gallery_id>/upload-status/', GalleryUploadResumeStatusView.as_view(), name='storage-gallery-upload-status'),

    # Analytics & Visitor Intelligence
    path('galleries/<str:gallery_id>/analytics/', GalleryAnalyticsView.as_view(), name='gallery-analytics'),
    path('galleries/<str:gallery_id>/analytics/event/', GalleryAnalyticsEventTrackView.as_view(), name='gallery-analytics-event-track'),
    path('galleries/<str:gallery_id>/analytics/export-csv/', GalleryAnalyticsExportCsvView.as_view(), name='gallery-analytics-export-csv'),

    # Share Link & QR Metadata
    path('galleries/<str:gallery_id>/share-details/', GalleryShareDetailsView.as_view(), name='gallery-share-details'),

    # Bulk Delete Media
    path('galleries/media/bulk-delete/', MediaBulkDeleteView.as_view(), name='media-bulk-delete'),
    path('galleries/<str:gallery_id>/media/bulk-delete/', MediaBulkDeleteView.as_view(), name='gallery-media-bulk-delete'),

    # Restore Archived Gallery
    path('galleries/<str:gallery_id>/restore/', GalleryRestoreView.as_view(), name='gallery-restore'),
    path('galleries/<uuid:gallery_id>/restore/', GalleryRestoreView.as_view(), name='gallery-restore-uuid'),

    # Single Media Deletion
    path('galleries/<str:gallery_id>/media/<uuid:media_id>/', MediaDetailDeleteView.as_view(), name='gallery-media-delete'),

    # Gallery Detail (Retrieve, Update, Delete)
    path('galleries/<str:pk>/', GalleryDetailView.as_view(), name='gallery-detail'),

    # -------------------------------------------------------------------------
    # Public Client Proofing Gallery Endpoints
    # -------------------------------------------------------------------------
    path('public/galleries/<str:slug_or_id>/track-view/', PublicGalleryTrackView.as_view(), name='public-gallery-track-view'),
    path('public/galleries/<str:slug_or_id>/download-zip/', PublicGalleryDownloadZipView.as_view(), name='public-gallery-download-zip'),
    path('public/galleries/<str:slug_or_id>/verify-pin/', PublicGalleryVerifyPinView.as_view(), name='public-gallery-verify-pin'),
    path('public/galleries/<str:slug_or_id>/', PublicGallerySlugOrIdView.as_view(), name='public-gallery-detail'),

    # -------------------------------------------------------------------------
    # Face Search Biometric AI
    # -------------------------------------------------------------------------
    path('galleries/<str:gallery_id>/face-search/', GalleryFaceSearchView.as_view(), name='gallery-face-search'),
    path('public/galleries/<str:gallery_id>/face-search/', GalleryFaceSearchView.as_view(), name='public-gallery-face-search'),
]

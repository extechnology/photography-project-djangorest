from django.urls import path
from App.Storage.storage_views import (
    # Backward compatible event views
    SharedEventListCreateView,
    SharedEventDetailView,
    EventBulkPhotoUploadView,
    EventZipPhotoUploadView,
    EventPhotoDeleteView,
    EventPhotoBulkDeleteView,
    PublicEventGalleryView,
    PublicEventVerifyPinView,
    PublicPhotoDownloadView,
    PublicEventDownloadAllZipView,
    PublicEventQRView,

    # Enterprise Photographer Gallery Views
    GalleryListCreateView,
    GalleryDetailView,
    GalleryRestoreView,
    GallerySettingsDetailView,
    GalleryShareView,
    GalleryTemplateSwitchView,
    GalleryTemplateUpdateView,
    GalleryBannerUpdateView,
    GalleryMasonrySlotBannerView,
    GallerySetCoverView,
    GalleryCoverUpdateView,
    GalleryReorderMediaView,
    GalleryMediaReorderView,
    GalleryMoveMediaSectionView,
    MoveMediaSectionView,
    GallerySectionListCreateView,
    GallerySectionDetailDeleteView,
    GallerySectionRenameView,
    GallerySectionReorderView,
    GalleryMediaFavoriteToggleView,
    GalleryAnalyticsView,
    GalleryAnalyticsEventTrackView,
    GalleryAnalyticsExportCsvView,
    GalleryShareDetailsView,

    # Enterprise Media Uploads & Management
    DirectUploadInitView,
    DirectUploadConfirmView,
    StandardMediaUploadView,
    MediaDetailDeleteView,
    MediaBulkDeleteView,
    MediaToggleFavoriteView,

    # Enterprise Public & Client Access
    PublicGallerySlugOrIdView,
    PublicGalleryDetailView,
    PublicGalleryDownloadZipView,
    PublicGalleryVerifyPinView,
    VerifyGalleryPinView,
    PublicGalleryTrackView,
    TrackGalleryView,
    SharedGalleryView,
    VerifyGalleryPasswordView,

    # Client Proofing & Selections
    ClientSelectionListCreateView,
    ClientSelectionSubmitView,

    # Enterprise Secure Downloads
    MediaDownloadView,
    GalleryBulkDownloadView,
    BulkDownloadJobStatusView,

    # Enterprise Face Discovery
    GalleryFaceSearchView,

    # Enterprise Storage Usage
    PhotographerStorageUsageView,
)

urlpatterns = [
    # -------------------------------------------------------------------------
    # Backward Compatible Photo Sharing Routes
    # -------------------------------------------------------------------------
    path('events/', SharedEventListCreateView.as_view(), name='shared-event-list-create'),
    path('events/<int:pk>/', SharedEventDetailView.as_view(), name='shared-event-detail'),
    path('events/<int:event_id>/upload/', EventBulkPhotoUploadView.as_view(), name='event-bulk-photo-upload'),
    path('events/<int:event_id>/upload-zip/', EventZipPhotoUploadView.as_view(), name='event-zip-photo-upload'),
    path('events/<int:event_id>/photos/bulk-delete/', EventPhotoBulkDeleteView.as_view(), name='event-photo-bulk-delete'),
    path('photos/<int:pk>/delete/', EventPhotoDeleteView.as_view(), name='event-photo-delete'),
    path('share/<str:access_code>/', PublicEventGalleryView.as_view(), name='public-event-gallery'),
    path('share/<str:access_code>/verify-pin/', PublicEventVerifyPinView.as_view(), name='public-event-verify-pin'),
    path('share/<str:access_code>/download-all/', PublicEventDownloadAllZipView.as_view(), name='public-event-download-all'),
    path('share/<str:access_code>/qr/', PublicEventQRView.as_view(), name='public-event-qr'),
    path('photos/<int:photo_id>/download/', PublicPhotoDownloadView.as_view(), name='public-photo-download'),

    # -------------------------------------------------------------------------
    # Enterprise Gallery Management APIs (Photographer Dashboard & Atelier Suite)
    # -------------------------------------------------------------------------
    path('galleries/', GalleryListCreateView.as_view(), name='gallery-list-create'),

    # Custom Section Management
    path('galleries/<str:gallery_id>/sections/', GallerySectionListCreateView.as_view(), name='gallery-sections-list-create'),
    path('galleries/<str:gallery_id>/sections/rename/', GallerySectionRenameView.as_view(), name='gallery-sections-rename'),
    path('galleries/<str:gallery_id>/sections/reorder/', GallerySectionReorderView.as_view(), name='gallery-sections-reorder'),
    path('galleries/<str:gallery_id>/sections/<str:section_title>/', GallerySectionDetailDeleteView.as_view(), name='gallery-section-delete'),

    # Move Photos Between Sections
    path('galleries/<str:gallery_id>/media/move-section/', GalleryMoveMediaSectionView.as_view(), name='gallery-media-move-section'),

    # Design & Layout Customization
    path('galleries/<str:gallery_id>/template/', GalleryTemplateUpdateView.as_view(), name='gallery-template-update'),
    path('galleries/<str:gallery_id>/banners/', GalleryBannerUpdateView.as_view(), name='gallery-banners-update'),
    path('galleries/<str:gallery_id>/masonry-slots/', GalleryMasonrySlotBannerView.as_view(), name='gallery-masonry-slots'),
    path('galleries/<str:gallery_id>/cover/', GalleryCoverUpdateView.as_view(), name='gallery-cover-update'),
    path('galleries/<str:gallery_id>/set-cover/', GallerySetCoverView.as_view(), name='gallery-set-cover'),

    # Media Reordering & Favorites
    path('galleries/<str:gallery_id>/media/reorder/', GalleryMediaReorderView.as_view(), name='gallery-media-reorder'),
    path('galleries/<str:gallery_id>/reorder-media/', GalleryReorderMediaView.as_view(), name='gallery-reorder-media'),
    path('galleries/<str:gallery_id>/media/<uuid:media_id>/favorite/', GalleryMediaFavoriteToggleView.as_view(), name='gallery-media-toggle-favorite'),

    # Analytics & Visitor Intelligence
    path('galleries/<str:gallery_id>/analytics/', GalleryAnalyticsView.as_view(), name='gallery-analytics'),
    path('galleries/<str:gallery_id>/analytics/event/', GalleryAnalyticsEventTrackView.as_view(), name='gallery-analytics-event-track'),
    path('galleries/<str:gallery_id>/analytics/export-csv/', GalleryAnalyticsExportCsvView.as_view(), name='gallery-analytics-export-csv'),

    # Share & Client Access Controls
    path('galleries/<str:gallery_id>/share-details/', GalleryShareDetailsView.as_view(), name='gallery-share-details'),
    path('galleries/<str:gallery_id>/share/', GalleryShareView.as_view(), name='gallery-share'),

    # Enterprise Media Uploads & Direct-to-Storage
    path('galleries/<str:gallery_id>/upload-init/', DirectUploadInitView.as_view(), name='direct-upload-init'),
    path('galleries/<str:gallery_id>/upload-confirm/', DirectUploadConfirmView.as_view(), name='direct-upload-confirm'),
    path('galleries/<str:gallery_id>/upload/', StandardMediaUploadView.as_view(), name='standard-media-upload'),

    # Gallery Detail & Settings (placed after sub-routes so <str:pk> matches clean gallery IDs or slugs)
    path('galleries/<str:gallery_id>/restore/', GalleryRestoreView.as_view(), name='gallery-restore'),
    path('galleries/<uuid:gallery_id>/restore/', GalleryRestoreView.as_view(), name='gallery-restore-uuid'),
    path('galleries/<str:pk>/', GalleryDetailView.as_view(), name='gallery-detail'),

    # Individual Photo / Media Deletion in Gallery
    path('galleries/<str:gallery_id>/media/<uuid:media_id>/', MediaDetailDeleteView.as_view(), name='gallery-media-delete'),
    path('galleries/<str:gallery_id>/photos/<uuid:photo_id>/', MediaDetailDeleteView.as_view(), name='gallery-photo-delete'),
    path('galleries/<str:gallery_id>/media/<uuid:media_id>/delete/', MediaDetailDeleteView.as_view(), name='gallery-media-delete-action'),
    path('galleries/<str:gallery_id>/photos/<uuid:photo_id>/delete/', MediaDetailDeleteView.as_view(), name='gallery-photo-delete-action'),
    path('galleries/<str:gallery_id>/media/bulk-delete/', MediaBulkDeleteView.as_view(), name='gallery-media-bulk-delete'),

    # Direct Media & Photo Deletion Routes
    path('galleries/media/<uuid:media_id>/', MediaDetailDeleteView.as_view(), name='media-detail-delete'),
    path('galleries/media/<uuid:media_id>/delete/', MediaDetailDeleteView.as_view(), name='media-detail-delete-action'),
    path('galleries/photos/<uuid:photo_id>/', MediaDetailDeleteView.as_view(), name='gallery-photo-detail-delete'),
    path('galleries/photos/<uuid:photo_id>/delete/', MediaDetailDeleteView.as_view(), name='gallery-photo-detail-delete-action'),
    path('media/<uuid:media_id>/', MediaDetailDeleteView.as_view(), name='media-direct-delete'),
    path('media/<uuid:media_id>/delete/', MediaDetailDeleteView.as_view(), name='media-direct-delete-action'),
    path('photos/<uuid:photo_id>/', MediaDetailDeleteView.as_view(), name='photo-direct-delete'),
    path('photos/<uuid:photo_id>/delete/', MediaDetailDeleteView.as_view(), name='photo-direct-delete-action'),

    path('galleries/media/bulk-delete/', MediaBulkDeleteView.as_view(), name='media-bulk-delete'),
    path('galleries/media/<uuid:media_id>/favorite/', MediaToggleFavoriteView.as_view(), name='media-toggle-favorite'),

    # -------------------------------------------------------------------------
    # Enterprise Client / Public Gallery Access & Proofing
    # -------------------------------------------------------------------------
    path('public/galleries/<str:slug_or_id>/track-view/', PublicGalleryTrackView.as_view(), name='public-gallery-track-view'),
    path('public/galleries/<str:slug_or_id>/download-zip/', PublicGalleryDownloadZipView.as_view(), name='public-gallery-download-zip'),
    path('public/galleries/<str:slug_or_id>/verify-pin/', PublicGalleryVerifyPinView.as_view(), name='public-gallery-verify-pin'),
    path('public/galleries/<str:slug_or_id>/', PublicGallerySlugOrIdView.as_view(), name='public-gallery-detail'),
    path('public/galleries/<str:slug_or_id>/', PublicGallerySlugOrIdView.as_view(), name='public-gallery-slug-or-id'),
    path('shared-galleries/<str:share_token>/', SharedGalleryView.as_view(), name='shared-gallery-view'),
    path('shared-galleries/<str:share_token>/verify-password/', VerifyGalleryPasswordView.as_view(), name='verify-gallery-password'),
    path('galleries/<uuid:gallery_id>/client-selections/', ClientSelectionListCreateView.as_view(), name='client-selection-list-create'),
    path('galleries/<uuid:gallery_id>/client-selections/<uuid:selection_id>/submit/', ClientSelectionSubmitView.as_view(), name='client-selection-submit'),

    # -------------------------------------------------------------------------
    # Enterprise Secure Downloads (Single & Async Master / Selective Bulk)
    # -------------------------------------------------------------------------
    path('galleries/media/<uuid:media_id>/download/', MediaDownloadView.as_view(), name='media-download'),
    path('galleries/<uuid:gallery_id>/bulk-download/', GalleryBulkDownloadView.as_view(), name='gallery-bulk-download'),
    path('galleries/bulk-download-jobs/<uuid:job_id>/', BulkDownloadJobStatusView.as_view(), name='bulk-download-job-status'),

    # -------------------------------------------------------------------------
    # Enterprise Face-Based Discovery
    # -------------------------------------------------------------------------
    path('galleries/<uuid:gallery_id>/face-search/', GalleryFaceSearchView.as_view(), name='gallery-face-search'),

    # -------------------------------------------------------------------------
    # Enterprise Storage Usage & Quota API
    # -------------------------------------------------------------------------
    path('account/storage/', PhotographerStorageUsageView.as_view(), name='photographer-storage-usage'),
]

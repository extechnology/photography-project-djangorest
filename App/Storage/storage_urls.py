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
    GalleryShareView,
    GalleryTemplateSwitchView,
    GallerySetCoverView,
    GalleryReorderMediaView,

    # Enterprise Media Uploads & Management
    DirectUploadInitView,
    DirectUploadConfirmView,
    StandardMediaUploadView,
    MediaDetailDeleteView,
    MediaBulkDeleteView,
    MediaToggleFavoriteView,

    # Enterprise Public & Client Access
    PublicGallerySlugOrIdView,
    PublicGalleryVerifyPinView,
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
    # Enterprise Gallery Management APIs (Photographer Dashboard)
    # -------------------------------------------------------------------------
    path('galleries/', GalleryListCreateView.as_view(), name='gallery-list-create'),
    path('galleries/<uuid:pk>/', GalleryDetailView.as_view(), name='gallery-detail'),
    path('galleries/<uuid:gallery_id>/template/', GalleryTemplateSwitchView.as_view(), name='gallery-template-switch'),
    path('galleries/<uuid:gallery_id>/set-cover/', GallerySetCoverView.as_view(), name='gallery-set-cover'),
    path('galleries/<uuid:gallery_id>/reorder-media/', GalleryReorderMediaView.as_view(), name='gallery-reorder-media'),
    path('galleries/<uuid:gallery_id>/share/', GalleryShareView.as_view(), name='gallery-share'),

    # -------------------------------------------------------------------------
    # Enterprise Media Uploads & Direct-to-Storage
    # -------------------------------------------------------------------------
    path('galleries/<uuid:gallery_id>/upload-init/', DirectUploadInitView.as_view(), name='direct-upload-init'),
    path('galleries/<uuid:gallery_id>/upload-confirm/', DirectUploadConfirmView.as_view(), name='direct-upload-confirm'),
    path('galleries/<uuid:gallery_id>/upload/', StandardMediaUploadView.as_view(), name='standard-media-upload'),
    path('galleries/<uuid:gallery_id>/media/upload/', StandardMediaUploadView.as_view(), name='gallery-media-upload-alias'),
    path('galleries/media/<uuid:media_id>/', MediaDetailDeleteView.as_view(), name='media-detail-delete'),
    path('galleries/media/bulk-delete/', MediaBulkDeleteView.as_view(), name='media-bulk-delete'),
    path('galleries/media/<uuid:media_id>/favorite/', MediaToggleFavoriteView.as_view(), name='media-toggle-favorite'),

    # -------------------------------------------------------------------------
    # Enterprise Client / Public Gallery Access & Proofing
    # -------------------------------------------------------------------------
    path('public/galleries/<str:slug_or_id>/', PublicGallerySlugOrIdView.as_view(), name='public-gallery-slug-or-id'),
    path('public/galleries/<str:slug_or_id>/verify-pin/', PublicGalleryVerifyPinView.as_view(), name='public-gallery-verify-pin'),
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

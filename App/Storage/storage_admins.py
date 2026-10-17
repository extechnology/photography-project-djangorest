from django.contrib import admin
from unfold.admin import ModelAdmin
from App.Storage.storage_models import (
    SharedEvent,
    EventPhoto,
    Gallery,
    Media,
    FaceEmbedding,
    UploadReservation,
    BulkDownloadJob,
    StorageAuditLog,
    GalleryClientSelection,
)


@admin.register(SharedEvent)
class SharedEventAdmin(ModelAdmin):
    list_display = (
        'title',
        'photographer',
        'event_type',
        'access_code',
        'is_pin_protected',
        'is_public',
        'allow_downloads',
        'views_count',
        'downloads_count',
        'created_at',
    )
    list_filter = ('event_type', 'is_public', 'allow_downloads', 'created_at')
    search_fields = ('title', 'access_code', 'venue', 'photographer__name')
    readonly_fields = ('access_code', 'views_count', 'downloads_count', 'created_at', 'updated_at')
    list_filter_submit = True
    compressed_fields = True
    warn_unsaved_form = True


@admin.register(EventPhoto)
class EventPhotoAdmin(ModelAdmin):
    list_display = (
        'id',
        'event',
        'original_filename',
        'category_tag',
        'file_size',
        'downloads_count',
        'uploaded_at',
    )
    list_filter = ('category_tag', 'uploaded_at')
    search_fields = ('original_filename', 'caption', 'category_tag', 'event__title')
    readonly_fields = ('file_size', 'downloads_count', 'uploaded_at')
    list_filter_submit = True
    compressed_fields = True


@admin.register(Gallery)
class GalleryAdmin(ModelAdmin):
    list_display = (
        'id',
        'title',
        'photographer',
        'status',
        'visibility',
        'downloads_enabled',
        'face_search_enabled',
        'views_count',
        'downloads_count',
        'created_at',
    )
    list_filter = ('status', 'visibility', 'downloads_enabled', 'face_search_enabled', 'created_at')
    search_fields = ('title', 'share_token', 'photographer__name')
    readonly_fields = ('id', 'share_token', 'views_count', 'downloads_count', 'created_at', 'updated_at')
    list_filter_submit = True
    compressed_fields = True
    warn_unsaved_form = True


@admin.register(Media)
class MediaAdmin(ModelAdmin):
    list_display = (
        'id',
        'original_filename',
        'gallery',
        'photographer',
        'file_size',
        'processing_status',
        'upload_status',
        'downloads_count',
        'created_at',
    )
    list_filter = ('processing_status', 'upload_status', 'created_at')
    search_fields = ('original_filename', 'storage_key', 'gallery__title', 'photographer__name')
    readonly_fields = ('id', 'file_size', 'downloads_count', 'created_at', 'updated_at')
    list_filter_submit = True
    compressed_fields = True


@admin.register(FaceEmbedding)
class FaceEmbeddingAdmin(ModelAdmin):
    list_display = ('id', 'gallery', 'media', 'confidence', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('gallery__title', 'media__original_filename')
    readonly_fields = ('id', 'gallery', 'media', 'confidence', 'bounding_box', 'created_at')
    exclude = ('embedding',)  # Never display raw high-dimensional biometric vectors in admin
    list_filter_submit = True
    compressed_fields = True


@admin.register(UploadReservation)
class UploadReservationAdmin(ModelAdmin):
    list_display = ('id', 'photographer', 'gallery', 'reserved_bytes', 'status', 'expires_at', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('photographer__name', 'gallery__title')
    readonly_fields = ('id', 'photographer', 'gallery', 'reserved_bytes', 'expires_at', 'created_at')
    list_filter_submit = True
    compressed_fields = True


@admin.register(BulkDownloadJob)
class BulkDownloadJobAdmin(ModelAdmin):
    list_display = ('id', 'gallery', 'download_type', 'status', 'selected_count', 'progress_percent', 'file_size', 'created_at')
    list_filter = ('download_type', 'status', 'created_at')
    search_fields = ('gallery__title',)
    readonly_fields = ('id', 'gallery', 'file_size', 'selected_count', 'created_at')
    list_filter_submit = True
    compressed_fields = True


@admin.register(StorageAuditLog)
class StorageAuditLogAdmin(ModelAdmin):
    list_display = ('id', 'photographer', 'action', 'gallery', 'user', 'ip_address', 'timestamp')
    list_filter = ('action', 'timestamp')
    search_fields = ('photographer__name', 'action')
    readonly_fields = ('id', 'photographer', 'gallery', 'user', 'action', 'details', 'ip_address', 'timestamp')
    list_filter_submit = True
    compressed_fields = True


@admin.register(GalleryClientSelection)
class GalleryClientSelectionAdmin(ModelAdmin):
    list_display = ('id', 'gallery', 'client_email', 'client_name', 'status', 'selected_count', 'submitted_at', 'updated_at')
    list_filter = ('status', 'submitted_at', 'updated_at')
    search_fields = ('client_email', 'client_name', 'gallery__title')
    readonly_fields = ('id', 'selected_count', 'submitted_at', 'created_at', 'updated_at')
    list_filter_submit = True
    compressed_fields = True
    warn_unsaved_form = True

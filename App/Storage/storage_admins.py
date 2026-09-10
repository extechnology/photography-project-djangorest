from django.contrib import admin
from App.Storage.storage_models import (
    SharedEvent,
    EventPhoto,
    Gallery,
    Media,
    FaceEmbedding,
    UploadReservation,
    BulkDownloadJob,
    StorageAuditLog,
)


@admin.register(SharedEvent)
class SharedEventAdmin(admin.ModelAdmin):
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


@admin.register(EventPhoto)
class EventPhotoAdmin(admin.ModelAdmin):
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


@admin.register(Gallery)
class GalleryAdmin(admin.ModelAdmin):
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


@admin.register(Media)
class MediaAdmin(admin.ModelAdmin):
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


@admin.register(FaceEmbedding)
class FaceEmbeddingAdmin(admin.ModelAdmin):
    list_display = ('id', 'gallery', 'media', 'confidence', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('gallery__title', 'media__original_filename')
    readonly_fields = ('id', 'gallery', 'media', 'confidence', 'bounding_box', 'created_at')
    exclude = ('embedding',)  # Never display raw high-dimensional biometric vectors in admin


@admin.register(UploadReservation)
class UploadReservationAdmin(admin.ModelAdmin):
    list_display = ('id', 'photographer', 'gallery', 'reserved_bytes', 'status', 'expires_at', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('photographer__name', 'gallery__title')
    readonly_fields = ('id', 'photographer', 'gallery', 'reserved_bytes', 'expires_at', 'created_at')


@admin.register(BulkDownloadJob)
class BulkDownloadJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'gallery', 'status', 'selected_count', 'file_size', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('gallery__title',)
    readonly_fields = ('id', 'gallery', 'file_size', 'selected_count', 'created_at')


@admin.register(StorageAuditLog)
class StorageAuditLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'photographer', 'action', 'gallery', 'user', 'ip_address', 'timestamp')
    list_filter = ('action', 'timestamp')
    search_fields = ('photographer__name', 'action')
    readonly_fields = ('id', 'photographer', 'gallery', 'user', 'action', 'details', 'ip_address', 'timestamp')

from rest_framework import serializers
from App.Storage.storage_models import (
    SharedEvent,
    EventPhoto,
    Gallery,
    Media,
    GalleryClientAccess,
    UploadReservation,
    BulkDownloadJob,
)
from App.Storage.services.storage_service import get_storage_provider


# =============================================================================
# 1. Existing Serializers (Maintained for Backward Compatibility)
# =============================================================================

class EventPhotoSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = EventPhoto
        fields = [
            'id',
            'event',
            'image',
            'original_filename',
            'file_size',
            'category_tag',
            'caption',
            'downloads_count',
            'uploaded_at',
            'download_url',
        ]
        read_only_fields = ['id', 'file_size', 'downloads_count', 'uploaded_at', 'download_url']

    def get_download_url(self, obj):
        request = self.context.get('request')
        relative_url = f"/api/storage/photos/{obj.id}/download/"
        if request:
            return request.build_absolute_uri(relative_url)
        return relative_url


class SharedEventListSerializer(serializers.ModelSerializer):
    photos_count = serializers.IntegerField(source='photos.count', read_only=True)
    photographer_name = serializers.ReadOnlyField(source='photographer.name')
    is_pin_protected = serializers.BooleanField(read_only=True)
    share_url = serializers.SerializerMethodField()

    class Meta:
        model = SharedEvent
        fields = [
            'id',
            'title',
            'event_type',
            'event_date',
            'venue',
            'description',
            'cover_image',
            'access_code',
            'is_pin_protected',
            'is_public',
            'allow_downloads',
            'views_count',
            'downloads_count',
            'photos_count',
            'photographer_name',
            'share_url',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'access_code',
            'is_pin_protected',
            'views_count',
            'downloads_count',
            'photos_count',
            'photographer_name',
            'share_url',
            'created_at',
            'updated_at',
        ]

    def get_share_url(self, obj):
        request = self.context.get('request')
        relative_url = f"/api/storage/share/{obj.access_code}/"
        if request:
            return request.build_absolute_uri(relative_url)
        return relative_url


class SharedEventDetailSerializer(serializers.ModelSerializer):
    photos_count = serializers.IntegerField(source='photos.count', read_only=True)
    photographer_name = serializers.ReadOnlyField(source='photographer.name')
    is_pin_protected = serializers.BooleanField(read_only=True)
    share_url = serializers.SerializerMethodField()
    photos = EventPhotoSerializer(many=True, read_only=True)

    class Meta:
        model = SharedEvent
        fields = [
            'id',
            'photographer',
            'photographer_name',
            'title',
            'event_type',
            'event_date',
            'venue',
            'description',
            'cover_image',
            'access_code',
            'pin_code',
            'is_pin_protected',
            'is_public',
            'allow_downloads',
            'views_count',
            'downloads_count',
            'photos_count',
            'share_url',
            'expiry_date',
            'photos',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'photographer',
            'photographer_name',
            'access_code',
            'is_pin_protected',
            'views_count',
            'downloads_count',
            'photos_count',
            'share_url',
            'photos',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {
            'pin_code': {'write_only': True, 'required': False},
        }

    def get_share_url(self, obj):
        request = self.context.get('request')
        relative_url = f"/api/storage/share/{obj.access_code}/"
        if request:
            return request.build_absolute_uri(relative_url)
        return relative_url


class PublicSharedEventSerializer(serializers.ModelSerializer):
    photos_count = serializers.IntegerField(source='photos.count', read_only=True)
    photographer_name = serializers.ReadOnlyField(source='photographer.name')
    is_pin_protected = serializers.BooleanField(read_only=True)
    download_all_url = serializers.SerializerMethodField()
    available_tags = serializers.SerializerMethodField()

    class Meta:
        model = SharedEvent
        fields = [
            'id',
            'title',
            'event_type',
            'event_date',
            'venue',
            'description',
            'cover_image',
            'access_code',
            'is_pin_protected',
            'allow_downloads',
            'photos_count',
            'photographer_name',
            'download_all_url',
            'available_tags',
            'created_at',
        ]

    def get_download_all_url(self, obj):
        if not obj.allow_downloads:
            return None
        request = self.context.get('request')
        relative_url = f"/api/storage/share/{obj.access_code}/download-all/"
        if request:
            return request.build_absolute_uri(relative_url)
        return relative_url

    def get_available_tags(self, obj):
        return list(
            obj.photos.exclude(category_tag='').values_list('category_tag', flat=True).distinct()
        )


# =============================================================================
# 2. Enterprise Media, Gallery, and Quota Serializers
# =============================================================================

class MediaSerializer(serializers.ModelSerializer):
    thumbnail_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Media
        fields = [
            'id',
            'gallery',
            'original_filename',
            'file_size',
            'width',
            'height',
            'mime_type',
            'file_extension',
            'processing_status',
            'upload_status',
            'downloads_count',
            'thumbnail_url',
            'preview_url',
            'download_url',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'file_size',
            'width',
            'height',
            'mime_type',
            'file_extension',
            'processing_status',
            'upload_status',
            'downloads_count',
            'thumbnail_url',
            'preview_url',
            'download_url',
            'created_at',
        ]

    def get_thumbnail_url(self, obj):
        storage = get_storage_provider()
        key = obj.thumbnail_storage_key or obj.storage_key
        return storage.generate_cdn_url(key)

    def get_preview_url(self, obj):
        storage = get_storage_provider()
        key = obj.preview_storage_key or obj.storage_key
        return storage.generate_cdn_url(key)

    def get_download_url(self, obj):
        request = self.context.get('request')
        relative = f"/api/galleries/media/{obj.id}/download/"
        if request:
            return request.build_absolute_uri(relative)
        return relative


class GallerySerializer(serializers.ModelSerializer):
    photos_count = serializers.SerializerMethodField()
    photographer_name = serializers.ReadOnlyField(source='photographer.name')
    share_url = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Gallery
        fields = [
            'id',
            'photographer',
            'photographer_name',
            'title',
            'description',
            'status',
            'visibility',
            'share_token',
            'password',
            'expires_at',
            'downloads_enabled',
            'face_search_enabled',
            'views_count',
            'downloads_count',
            'photos_count',
            'share_url',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'photographer',
            'photographer_name',
            'share_token',
            'views_count',
            'downloads_count',
            'photos_count',
            'share_url',
            'created_at',
            'updated_at',
        ]

    def get_photos_count(self, obj):
        return obj.media_items.filter(deleted_at__isnull=True).count()

    def get_share_url(self, obj):
        request = self.context.get('request')
        relative = f"/api/shared-galleries/{obj.share_token}/"
        if request:
            return request.build_absolute_uri(relative)
        return relative

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        gallery = Gallery(**validated_data)
        if password:
            gallery.set_access_password(password)
        gallery.save()
        return gallery

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        if password is not None:
            instance.set_access_password(password)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        return instance


class PublicGallerySerializer(serializers.ModelSerializer):
    """Client/guest gallery serializer; excludes internal keys and sensitive tokens."""
    photos_count = serializers.SerializerMethodField()
    photographer_name = serializers.ReadOnlyField(source='photographer.name')
    requires_password = serializers.SerializerMethodField()
    media = serializers.SerializerMethodField()

    class Meta:
        model = Gallery
        fields = [
            'id',
            'title',
            'description',
            'visibility',
            'downloads_enabled',
            'face_search_enabled',
            'photos_count',
            'photographer_name',
            'requires_password',
            'media',
            'created_at',
        ]

    def get_photos_count(self, obj):
        return obj.media_items.filter(deleted_at__isnull=True).count()

    def get_requires_password(self, obj):
        return obj.visibility == 'password_protected'

    def get_media(self, obj):
        # Only return media if access is granted (handled in view)
        request = self.context.get('request')
        if self.context.get('access_granted', True):
            qs = obj.media_items.filter(deleted_at__isnull=True)[:100]
            return MediaSerializer(qs, many=True, context={'request': request}).data
        return []


class DirectUploadInitSerializer(serializers.Serializer):
    original_filename = serializers.CharField(max_length=255)
    file_size = serializers.IntegerField(min_value=1, max_value=200 * 1024 * 1024)  # Max 200MB per file
    mime_type = serializers.CharField(max_length=100, default='image/jpeg')


class DirectUploadConfirmSerializer(serializers.Serializer):
    reservation_id = serializers.UUIDField()
    storage_key = serializers.CharField(max_length=512)
    original_filename = serializers.CharField(max_length=255)
    file_size = serializers.IntegerField(min_value=1)
    mime_type = serializers.CharField(max_length=100, default='image/jpeg')


class GalleryClientAccessSerializer(serializers.ModelSerializer):
    class Meta:
        model = GalleryClientAccess
        fields = [
            'id',
            'gallery',
            'user',
            'email',
            'can_download',
            'can_face_search',
            'expires_at',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class StorageUsageSerializer(serializers.Serializer):
    plan = serializers.CharField()
    storage_used_bytes = serializers.IntegerField()
    storage_reserved_bytes = serializers.IntegerField()
    storage_limit_bytes = serializers.IntegerField()
    storage_remaining_bytes = serializers.IntegerField()
    usage_percentage = serializers.FloatField()


class BulkDownloadJobSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = BulkDownloadJob
        fields = [
            'id',
            'gallery',
            'status',
            'selected_count',
            'file_size',
            'error_message',
            'download_url',
            'expires_at',
            'created_at',
        ]
        read_only_fields = ['id', 'status', 'selected_count', 'file_size', 'error_message', 'download_url', 'expires_at', 'created_at']

    def get_download_url(self, obj):
        if obj.status == 'ready' and obj.archive_storage_key:
            storage = get_storage_provider()
            return storage.generate_signed_download_url(
                obj.archive_storage_key,
                expires_in=86400,
                filename=f"gallery_{obj.gallery_id}_photos.zip"
            )
        return None

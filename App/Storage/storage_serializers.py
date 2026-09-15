from rest_framework import serializers
from App.Storage.storage_models import (
    SharedEvent,
    EventPhoto,
    Gallery,
    Media,
    GalleryClientAccess,
    GalleryClientSelection,
    UploadReservation,
    BulkDownloadJob,
)
from App.Storage.services.storage_service import get_storage_provider


# =============================================================================
# 1. Event Photo Sharing Serializers (Backward Compatibility)
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
# 2. Enterprise Media, Gallery, and Quota Serializers (Version 2.0)
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
            'media_type',
            'title',
            'caption',
            'original_filename',
            'file_size',
            'width',
            'height',
            'aspect_ratio',
            'duration',
            'video_embed_url',
            'video_stream_key',
            'display_order',
            'is_cover',
            'is_favorite',
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
            'aspect_ratio',
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
        relative = f"/api/storage/galleries/media/{obj.id}/download/"
        if request:
            return request.build_absolute_uri(relative)
        return relative


class GallerySerializer(serializers.ModelSerializer):
    photos_count = serializers.SerializerMethodField()
    photographer_name = serializers.ReadOnlyField(source='photographer.name')
    studio_name = serializers.ReadOnlyField(source='photographer.studio_name')
    share_url = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    cover_image = serializers.SerializerMethodField()
    media_items = serializers.SerializerMethodField()

    class Meta:
        model = Gallery
        fields = [
            'id',
            'photographer',
            'photographer_name',
            'studio_name',
            'title',
            'slug',
            'client_name',
            'client_email',
            'event_date',
            'description',
            'template_id',
            'status',
            'visibility',
            'share_token',
            'is_password_protected',
            'password',
            'expires_at',
            'cover_media',
            'cover_image_url',
            'cover_image',
            'downloads_enabled',
            'allow_downloads',
            'allow_favorites',
            'face_search_enabled',
            'views_count',
            'downloads_count',
            'favorites_count',
            'photos_count',
            'share_url',
            'media_items',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'photographer',
            'photographer_name',
            'studio_name',
            'slug',
            'share_token',
            'is_password_protected',
            'views_count',
            'downloads_count',
            'favorites_count',
            'photos_count',
            'share_url',
            'cover_image',
            'media_items',
            'created_at',
            'updated_at',
        ]

    def get_photos_count(self, obj):
        return obj.media_items.filter(deleted_at__isnull=True).count()

    def get_share_url(self, obj):
        request = self.context.get('request')
        relative = f"/api/storage/shared-galleries/{obj.share_token}/"
        if request:
            return request.build_absolute_uri(relative)
        return relative

    def get_cover_image(self, obj):
        if obj.cover_image_url:
            return obj.cover_image_url
        if obj.cover_media:
            storage = get_storage_provider()
            key = obj.cover_media.preview_storage_key or obj.cover_media.storage_key
            return storage.generate_cdn_url(key)
        first_media = obj.media_items.filter(deleted_at__isnull=True).first()
        if first_media:
            storage = get_storage_provider()
            key = first_media.preview_storage_key or first_media.storage_key
            return storage.generate_cdn_url(key)
        return ""

    def get_media_items(self, obj):
        # Only populate when serializer is requested in detail mode
        if self.context.get('include_media', False):
            qs = obj.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at')
            return MediaSerializer(qs, many=True, context=self.context).data
        return []

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
    studio_name = serializers.ReadOnlyField(source='photographer.studio_name')
    requires_password = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()
    media = serializers.SerializerMethodField()

    class Meta:
        model = Gallery
        fields = [
            'id',
            'title',
            'slug',
            'client_name',
            'event_date',
            'description',
            'template_id',
            'visibility',
            'is_password_protected',
            'requires_password',
            'allow_downloads',
            'allow_favorites',
            'face_search_enabled',
            'photos_count',
            'favorites_count',
            'photographer_name',
            'studio_name',
            'cover_image',
            'media',
            'created_at',
        ]

    def get_photos_count(self, obj):
        return obj.media_items.filter(deleted_at__isnull=True).count()

    def get_requires_password(self, obj):
        return obj.is_password_protected or obj.visibility == 'password_protected'

    def get_cover_image(self, obj):
        if obj.cover_image_url:
            return obj.cover_image_url
        if obj.cover_media:
            storage = get_storage_provider()
            key = obj.cover_media.preview_storage_key or obj.cover_media.storage_key
            return storage.generate_cdn_url(key)
        first_media = obj.media_items.filter(deleted_at__isnull=True).first()
        if first_media:
            storage = get_storage_provider()
            key = first_media.preview_storage_key or first_media.storage_key
            return storage.generate_cdn_url(key)
        return ""

    def get_media(self, obj):
        request = self.context.get('request')
        if self.context.get('access_granted', True):
            qs = obj.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at')
            return MediaSerializer(qs, many=True, context={'request': request}).data
        return []


class GalleryClientSelectionSerializer(serializers.ModelSerializer):
    selected_media_items = MediaSerializer(source='selected_media', many=True, read_only=True)

    class Meta:
        model = GalleryClientSelection
        fields = [
            'id',
            'gallery',
            'client_email',
            'client_name',
            'status',
            'selected_count',
            'client_notes',
            'selected_media',
            'selected_media_items',
            'submitted_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'selected_count', 'selected_media_items', 'submitted_at', 'created_at', 'updated_at']


class DirectUploadInitItemSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255, required=False)
    original_filename = serializers.CharField(max_length=255, required=False)
    file_size = serializers.IntegerField(min_value=1)
    mime_type = serializers.CharField(max_length=100, default='image/jpeg')
    media_type = serializers.ChoiceField(choices=['photo', 'video'], default='photo')


class DirectUploadConfirmSerializer(serializers.Serializer):
    media_id = serializers.UUIDField(required=False)
    reservation_id = serializers.UUIDField()
    storage_key = serializers.CharField(max_length=512, required=False)
    original_filename = serializers.CharField(max_length=255, required=False)
    file_size = serializers.IntegerField(min_value=1, required=False)
    mime_type = serializers.CharField(max_length=100, default='image/jpeg', required=False)
    media_type = serializers.ChoiceField(choices=['photo', 'video'], default='photo', required=False)
    aspect_ratio = serializers.FloatField(required=False)
    width = serializers.IntegerField(required=False)
    height = serializers.IntegerField(required=False)
    duration = serializers.CharField(max_length=50, required=False)


class GalleryTemplateUpdateSerializer(serializers.Serializer):
    template_id = serializers.ChoiceField(choices=['editorial', 'masonry', 'cinematic', 'minimal'])


class GallerySetCoverSerializer(serializers.Serializer):
    media_id = serializers.UUIDField(required=False)
    cover_image_url = serializers.CharField(max_length=512, required=False)


class GalleryReorderMediaSerializer(serializers.Serializer):
    order = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of items e.g. [{'media_id': 'uuid', 'display_order': 0}, ...]"
    )


class BulkDownloadJobSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = BulkDownloadJob
        fields = [
            'id',
            'gallery',
            'download_type',
            'status',
            'selected_count',
            'file_size',
            'progress_percent',
            'error_message',
            'download_url',
            'expires_at',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'status',
            'selected_count',
            'file_size',
            'progress_percent',
            'error_message',
            'download_url',
            'expires_at',
            'created_at'
        ]

    def get_download_url(self, obj):
        if obj.status == 'ready' and obj.archive_storage_key:
            storage = get_storage_provider()
            return storage.generate_signed_download_url(
                obj.archive_storage_key,
                expires_in=86400,
                filename=f"gallery_{obj.gallery_id}_photos.zip"
            )
        return None


class StorageUsageSerializer(serializers.Serializer):
    plan = serializers.CharField()
    storage_used_bytes = serializers.IntegerField()
    storage_reserved_bytes = serializers.IntegerField()
    storage_limit_bytes = serializers.IntegerField()
    storage_remaining_bytes = serializers.IntegerField()
    usage_percentage = serializers.FloatField()

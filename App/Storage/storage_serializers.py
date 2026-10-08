from django.db import models
from rest_framework import serializers
from App.Storage.storage_models import (
    SharedEvent,
    EventPhoto,
    Gallery,
    GallerySection,
    GalleryAnalyticsEvent,
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
    url = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    gallery_id = serializers.UUIDField(source='gallery.id', read_only=True)
    type = serializers.CharField(source='media_type', read_only=True)
    size_bytes = serializers.IntegerField(source='file_size', read_only=True)
    sort_order = serializers.IntegerField(source='display_order', read_only=True)
    size_mb = serializers.SerializerMethodField()

    class Meta:
        model = Media
        fields = [
            'id',
            'gallery_id',
            'gallery',
            'media_type',
            'type',
            'title',
            'section_title',
            'caption',
            'original_filename',
            'file_size',
            'size_bytes',
            'size_mb',
            'width',
            'height',
            'aspect_ratio',
            'duration',
            'video_embed_url',
            'video_stream_key',
            'display_order',
            'sort_order',
            'is_cover',
            'is_favorite',
            'mime_type',
            'file_extension',
            'processing_status',
            'upload_status',
            'downloads_count',
            'views_count',
            'favorites_count',
            'thumbnail_url',
            'preview_url',
            'file_url',
            'url',
            'thumbnail',
            'download_url',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'gallery_id',
            'file_size',
            'size_bytes',
            'size_mb',
            'width',
            'height',
            'aspect_ratio',
            'mime_type',
            'file_extension',
            'processing_status',
            'upload_status',
            'downloads_count',
            'views_count',
            'favorites_count',
            'thumbnail_url',
            'preview_url',
            'file_url',
            'url',
            'thumbnail',
            'download_url',
            'created_at',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['file_size'] = instance.file_size or 0
        data['size_bytes'] = instance.file_size or 0
        data['size_mb'] = self.get_size_mb(instance)
        return data

    def get_size_mb(self, obj):
        size = getattr(obj, 'file_size', 0) or (obj.file.size if getattr(obj, 'file', None) else 0)
        return round((size or 0) / (1024 * 1024), 2)

    def get_url(self, obj):
        return self.get_file_url(obj)

    def get_thumbnail(self, obj):
        return self.get_thumbnail_url(obj)

    def get_thumbnail_url(self, obj):
        storage = get_storage_provider()
        key = obj.thumbnail_storage_key or obj.preview_storage_key or obj.storage_key
        url = storage.generate_cdn_url(key) if key else ""
        request = self.context.get('request')
        if request and url and url.startswith('/'):
            return request.build_absolute_uri(url)
        return url

    def get_preview_url(self, obj):
        storage = get_storage_provider()
        key = obj.preview_storage_key or obj.storage_key
        url = storage.generate_cdn_url(key) if key else ""
        request = self.context.get('request')
        if request and url and url.startswith('/'):
            return request.build_absolute_uri(url)
        return url

    def get_file_url(self, obj):
        url = ""
        if obj.storage_key or obj.preview_storage_key:
            storage = get_storage_provider()
            key = obj.preview_storage_key or obj.storage_key
            url = storage.generate_cdn_url(key) if key else ""
        elif obj.file:
            try:
                url = obj.file.url
            except Exception:
                url = ""

        request = self.context.get('request')
        if request and url and url.startswith('/'):
            return request.build_absolute_uri(url)
        return url

    def get_download_url(self, obj):
        relative = f"/api/galleries/media/{obj.id}/download/"
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(relative)
        return relative


GalleryMediaItemSerializer = MediaSerializer


def _sanitize_banner_dict(banners_dict, gallery, request=None):
    if not banners_dict or not isinstance(banners_dict, dict):
        return {}
    deleted_ids = set(gallery.media_items.filter(deleted_at__isnull=False).values_list('id', flat=True))
    if not deleted_ids:
        return banners_dict

    deleted_str_ids = {str(d) for d in deleted_ids}
    first_active = gallery.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at', 'id').first()
    fallback_url = ""
    if first_active:
        storage = get_storage_provider()
        key = first_active.preview_storage_key or first_active.storage_key
        fallback_url = storage.generate_cdn_url(key) if key else ""
        if request and fallback_url.startswith('/'):
            fallback_url = request.build_absolute_uri(fallback_url)

    cleaned = {}
    for k, v in banners_dict.items():
        if v and any(did in str(v) for did in deleted_str_ids):
            if fallback_url:
                cleaned[k] = fallback_url
        else:
            cleaned[k] = v
    return cleaned


def _sanitize_banner_list(banners_list, gallery, request=None):
    if not banners_list or not isinstance(banners_list, list):
        return []
    deleted_ids = set(gallery.media_items.filter(deleted_at__isnull=False).values_list('id', flat=True))
    if not deleted_ids:
        return banners_list

    deleted_str_ids = {str(d) for d in deleted_ids}
    first_active = gallery.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at', 'id').first()
    fallback_url = ""
    if first_active:
        storage = get_storage_provider()
        key = first_active.preview_storage_key or first_active.storage_key
        fallback_url = storage.generate_cdn_url(key) if key else ""
        if request and fallback_url.startswith('/'):
            fallback_url = request.build_absolute_uri(fallback_url)

    cleaned = []
    for v in banners_list:
        if v and any(did in str(v) for did in deleted_str_ids):
            if fallback_url:
                cleaned.append(fallback_url)
        else:
            cleaned.append(v)
    return cleaned


class GallerySerializer(serializers.ModelSerializer):
    status = serializers.ChoiceField(choices=Gallery.STATUS_CHOICES, default='active', required=False)
    client_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='Valued Client')
    client_phone = serializers.CharField(max_length=40, required=False, allow_blank=True, default='')
    download_pin = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    cover_image = serializers.CharField(required=False, allow_blank=True)
    sections = serializers.JSONField(required=False, default=list)
    template_banners = serializers.SerializerMethodField()
    masonry_banner_images = serializers.SerializerMethodField()
    photos_count = serializers.IntegerField(read_only=True)
    videos_count = serializers.IntegerField(read_only=True)
    total_media_count = serializers.SerializerMethodField()
    total_size_bytes = serializers.IntegerField(read_only=True)
    total_size_mb = serializers.FloatField(read_only=True)
    total_size_formatted = serializers.CharField(read_only=True)
    photographer_name = serializers.ReadOnlyField(source='photographer.name')
    studio_name = serializers.ReadOnlyField(source='photographer.studio_name')
    share_url = serializers.SerializerMethodField()
    is_password_protected = serializers.BooleanField(required=False)
    face_search_enabled = serializers.BooleanField(required=False)
    watermark_enabled = serializers.BooleanField(required=False)
    watermark_type = serializers.CharField(max_length=10, required=False, allow_null=True, allow_blank=True)
    watermark_text = serializers.CharField(max_length=120, required=False, allow_null=True, allow_blank=True)
    watermark_opacity = serializers.FloatField(required=False, allow_null=True)
    watermark_position = serializers.CharField(max_length=20, required=False, allow_null=True, allow_blank=True)
    watermark_font_size = serializers.CharField(max_length=10, required=False, allow_null=True, allow_blank=True)
    watermark_font_color = serializers.CharField(max_length=20, required=False, allow_null=True, allow_blank=True)
    watermark_font_style = serializers.CharField(max_length=20, required=False, allow_null=True, allow_blank=True)
    watermark_image = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    expires_at = serializers.DateTimeField(allow_null=True, required=False)
    is_expired = serializers.SerializerMethodField()
    section_counts = serializers.SerializerMethodField()
    media = serializers.SerializerMethodField()
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
            'client_phone',
            'event_date',
            'description',
            'template_id',
            'template_banners',
            'masonry_banner_images',
            'sections',
            'section_counts',
            'status',
            'visibility',
            'share_token',
            'is_password_protected',
            'password',
            'download_pin',
            'expires_at',
            'is_expired',
            'cover_media',
            'cover_image_url',
            'cover_image',
            'downloads_enabled',
            'allow_downloads',
            'allow_favorites',
            'face_search_enabled',
            'watermark_enabled',
            'watermark_type',
            'watermark_text',
            'watermark_opacity',
            'watermark_position',
            'watermark_font_size',
            'watermark_font_color',
            'watermark_font_style',
            'watermark_image',
            'views_count',
            'downloads_count',
            'favorites_count',
            'photos_count',
            'videos_count',
            'total_media_count',
            'total_size_bytes',
            'total_size_mb',
            'total_size_formatted',
            'share_url',
            'media',
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
            'is_expired',
            'views_count',
            'downloads_count',
            'favorites_count',
            'photos_count',
            'videos_count',
            'total_media_count',
            'total_size_bytes',
            'total_size_mb',
            'total_size_formatted',
            'share_url',
            'media',
            'media_items',
            'created_at',
            'updated_at',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not data.get('cover_image'):
            data['cover_image'] = self.get_cover_image(instance)
        data['photos_count'] = instance.photos_count
        data['videos_count'] = instance.videos_count
        data['total_media_count'] = (
            self.context.get('total_media_count')
            if 'total_media_count' in self.context
            else instance.total_media_count
        )
        data['total_size_bytes'] = instance.total_size_bytes
        data['total_size_mb'] = instance.total_size_mb
        data['total_size_formatted'] = instance.total_size_formatted
        data['sections'] = instance.sections_list
        data['is_expired'] = bool(instance.is_expired)
        data['favorites_count'] = self.get_favorites_count(instance)
        data['section_counts'] = self.get_section_counts(instance)
        data['watermark_enabled'] = self.get_watermark_enabled(instance)
        data['watermark_type'] = self.get_watermark_type(instance)
        data['watermark_text'] = self.get_watermark_text(instance)
        data['watermark_opacity'] = self.get_watermark_opacity(instance)
        data['watermark_position'] = self.get_watermark_position(instance)
        data['watermark_font_size'] = self.get_watermark_font_size(instance)
        data['watermark_font_color'] = self.get_watermark_font_color(instance)
        data['watermark_font_style'] = self.get_watermark_font_style(instance)
        data['watermark_image'] = self.get_watermark_image(instance)
        if 'next_cursor' in self.context:
            data['next_cursor'] = self.context.get('next_cursor')
        if 'has_more' in self.context:
            data['has_more'] = self.context.get('has_more')
        if 'filtered_media_count' in self.context:
            data['filtered_media_count'] = self.context.get('filtered_media_count')
        return data

    def get_section_counts(self, obj):
        counts = (
            obj.media_items.filter(deleted_at__isnull=True)
            .values('section_title')
            .annotate(count=models.Count('id'))
        )
        return {
            (item['section_title'] or 'UNASSIGNED').upper(): item['count']
            for item in counts
        }

    def get_favorites_count(self, obj):
        count = obj.media_items.filter(deleted_at__isnull=True, is_favorite=True).count()
        return count if count > 0 else getattr(obj, 'favorites_count', 0)

    def get_total_media_count(self, obj):
        return (getattr(obj, 'photos_count', 0) or 0) + (getattr(obj, 'videos_count', 0) or 0)

    def create(self, validated_data):
        cover_image = validated_data.pop('cover_image', None)
        if cover_image:
            validated_data['cover_image_url'] = cover_image
        return super().create(validated_data)

    def validate_face_search_enabled(self, value):
        if value:
            request = self.context.get('request')
            if request and getattr(request, 'user', None):
                user = request.user
                if not (user.is_staff or user.is_superuser):
                    from App.Photographers.photo_models import PhotographerProfile
                    profile = PhotographerProfile.objects.filter(user=user).first()
                    if profile:
                        sub = getattr(profile, 'subscription', None)
                        plan = getattr(sub, 'plan', None) if sub else None
                        if not plan:
                            plan = getattr(profile, 'studio_plan', None) or getattr(profile, 'plan', None)
                        plan_allowed = getattr(plan, 'face_search_enabled', False)
                        if not plan_allowed:
                            raise serializers.ValidationError(
                                "AI Biometric Face Search is locked on your current subscription plan. Upgrade to enable."
                            )
        return value

    def validate_watermark_enabled(self, value):
        if value:
            request = self.context.get('request')
            if request and getattr(request, 'user', None):
                user = request.user
                if not (user.is_staff or user.is_superuser):
                    from App.Photographers.photo_models import PhotographerProfile
                    from rest_framework.exceptions import PermissionDenied
                    profile = getattr(user, 'photographer_profile', None) or PhotographerProfile.objects.filter(user=user).first()
                    sub = getattr(profile, 'subscription', None) if profile else None
                    if not sub and hasattr(user, 'subscription'):
                        sub = user.subscription
                    plan = getattr(sub, 'plan', None) if sub and getattr(sub, 'is_active', True) else None
                    if not plan and profile:
                        plan = getattr(profile, 'studio_plan', None) or getattr(profile, 'plan', None)

                    if not plan or not getattr(plan, 'watermark_enabled', False):
                        raise PermissionDenied({
                            "error_code": "WATERMARK_LOCKED",
                            "upgrade_required": True,
                            "detail": "Custom studio watermarking is not included in your current subscription plan. Please upgrade your plan to watermark proofing galleries.",
                            "message": "Custom studio watermarking is not included in your current subscription plan. Please upgrade your plan to watermark proofing galleries."
                        })
        return value

    def _get_profile(self, obj):
        p = getattr(obj, 'photographer', None)
        if p and hasattr(p, 'enable_watermark'):
            return p
        if p and hasattr(p, 'profile'):
            return getattr(p, 'profile', None)
        if p and hasattr(p, 'photographer_profile'):
            return getattr(p, 'photographer_profile', None)
        user = getattr(obj, 'user', None)
        if user and hasattr(user, 'photographer_profile'):
            return user.photographer_profile
        return None

    def get_watermark_enabled(self, obj):
        if hasattr(obj, 'watermark_enabled') and obj.watermark_enabled is not None:
            return bool(obj.watermark_enabled)
        if hasattr(obj, 'enable_watermark') and obj.enable_watermark is not None:
            return bool(obj.enable_watermark)
        profile = self._get_profile(obj)
        return getattr(profile, 'enable_watermark', True) if profile else True

    def get_watermark_type(self, obj):
        if hasattr(obj, 'watermark_type') and obj.watermark_type:
            return obj.watermark_type
        profile = self._get_profile(obj)
        # Defaults strictly to 'text'
        return getattr(profile, 'watermark_type', 'text') or 'text'

    def get_watermark_text(self, obj):
        legacy_placeholders = {'ex studio', '© ex studio', 'atelier studio', '© atelier studio', 'studio', '© studio'}
        if obj.watermark_text and str(obj.watermark_text).strip():
            txt = str(obj.watermark_text).strip()
            if txt.lower() not in legacy_placeholders:
                return txt if txt.startswith('©') else f"© {txt}"
        profile = self._get_profile(obj)
        if profile and hasattr(profile, 'get_watermark_text'):
            return profile.get_watermark_text()
        if profile and hasattr(profile, 'get_effective_watermark_text'):
            return profile.get_effective_watermark_text()
        user = getattr(profile, 'user', None) or getattr(obj, 'user', None)
        full_name = user.get_full_name().strip() if (user and hasattr(user, 'get_full_name')) else ''
        name = full_name or (getattr(profile, 'name', '') if profile else '') or (getattr(user, 'username', '') if user else '') or 'Photographer'
        return f"© {name}"

    def get_watermark_opacity(self, obj):
        if hasattr(obj, 'watermark_opacity') and obj.watermark_opacity is not None:
            return float(obj.watermark_opacity)
        profile = self._get_profile(obj)
        return float(getattr(profile, 'watermark_opacity', 0.45) if profile else 0.45)

    def get_watermark_position(self, obj):
        if hasattr(obj, 'watermark_position') and obj.watermark_position:
            return str(obj.watermark_position).replace('_', '-')
        profile = self._get_profile(obj)
        pos = getattr(profile, 'watermark_position', 'bottom-right') if profile else 'bottom-right'
        return str(pos).replace('_', '-') if pos else 'bottom-right'

    def get_watermark_image(self, obj):
        # STRICT ONE-AT-A-TIME:
        # If watermark_type is 'text', image MUST be null!
        active_type = self.get_watermark_type(obj)
        if active_type != 'image':
            return None

        # If active_type == 'image', return the logo URL
        img = None
        if hasattr(obj, 'watermark_image') and obj.watermark_image:
            img = obj.watermark_image
        else:
            profile = self._get_profile(obj)
            img = getattr(profile, 'watermark_image', None)

        if img:
            request = self.context.get('request')
            try:
                url = img.url
                return request.build_absolute_uri(url) if request else url
            except Exception:
                return None
        return None

    def get_watermark_font_size(self, obj):
        if hasattr(obj, 'watermark_font_size') and obj.watermark_font_size:
            return obj.watermark_font_size
        profile = self._get_profile(obj)
        return getattr(profile, 'watermark_font_size', 'md') if profile else 'md'

    def get_watermark_font_color(self, obj):
        if hasattr(obj, 'watermark_font_color') and obj.watermark_font_color:
            return obj.watermark_font_color
        profile = self._get_profile(obj)
        return getattr(profile, 'watermark_font_color', '#FFFFFF') if profile else '#FFFFFF'

    def get_watermark_font_style(self, obj):
        if hasattr(obj, 'watermark_font_style') and obj.watermark_font_style:
            return obj.watermark_font_style
        profile = self._get_profile(obj)
        return getattr(profile, 'watermark_font_style', 'serif') if profile else 'serif'

    def update(self, instance, validated_data):
        cover_image = validated_data.pop('cover_image', None)
        if cover_image is not None:
            instance.cover_image_url = cover_image

        # Explicit password wipe handling when is_password_protected is False
        if 'is_password_protected' in validated_data:
            is_prot = validated_data['is_password_protected']
            instance.is_password_protected = is_prot
            if not is_prot:
                instance.password = ''
                if instance.visibility == 'password_protected':
                    instance.visibility = 'public'
            elif 'password' in validated_data and validated_data['password']:
                instance.set_access_password(validated_data['password'].strip())
        elif 'password' in validated_data:
            pwd = validated_data['password']
            if pwd and instance.is_password_protected:
                instance.set_access_password(pwd.strip())
            elif not instance.is_password_protected:
                instance.password = ''

        return super().update(instance, validated_data)

    def get_is_expired(self, obj):
        return bool(obj.is_expired)

    def get_photos_count(self, obj):
        if hasattr(obj, 'photos_count') and obj.photos_count is not None:
            return obj.photos_count
        return obj.media_items.filter(media_type='photo', deleted_at__isnull=True).count()

    def get_videos_count(self, obj):
        if hasattr(obj, 'videos_count') and obj.videos_count is not None:
            return obj.videos_count
        return obj.media_items.filter(media_type='video', deleted_at__isnull=True).count()

    def get_media(self, obj):
        # 1. Injected paginated slice from view
        if 'paginated_media' in self.context:
            media_items = self.context['paginated_media']
            return MediaSerializer(media_items, many=True, context=self.context).data

        # 2. Injected filtered queryset from view
        if 'media_qs' in self.context:
            return MediaSerializer(self.context['media_qs'], many=True, context=self.context).data

        if self.context.get('include_media', True):
            items = obj.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at', 'id')
            return MediaSerializer(items, many=True, context=self.context).data
        return []

    def get_media_items(self, obj):
        return self.get_media(obj)

    def get_share_url(self, obj):
        request = self.context.get('request')
        relative = f"/api/storage/shared-galleries/{obj.share_token}/"
        if request:
            return request.build_absolute_uri(relative)
        return relative

    def get_template_banners(self, obj):
        return _sanitize_banner_dict(obj.template_banners, obj, self.context.get('request'))

    def get_masonry_banner_images(self, obj):
        return _sanitize_banner_list(obj.masonry_banner_images, obj, self.context.get('request'))

    def get_cover_image(self, obj):
        url = ""
        # 1. Prefer active non-deleted cover_media
        if obj.cover_media and not getattr(obj.cover_media, 'deleted_at', None):
            storage = get_storage_provider()
            key = obj.cover_media.preview_storage_key or obj.cover_media.storage_key
            url = storage.generate_cdn_url(key) if key else ""
        elif obj.cover_image_url:
            deleted_ids = {str(d) for d in obj.media_items.filter(deleted_at__isnull=False).values_list('id', flat=True)}
            if not any(did in str(obj.cover_image_url) for did in deleted_ids):
                url = obj.cover_image_url
            else:
                first_media = obj.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at', 'id').first()
                if first_media:
                    storage = get_storage_provider()
                    key = first_media.preview_storage_key or first_media.storage_key
                    url = storage.generate_cdn_url(key) if key else ""
        else:
            first_media = obj.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at', 'id').first()
            if first_media:
                storage = get_storage_provider()
                key = first_media.preview_storage_key or first_media.storage_key
                url = storage.generate_cdn_url(key) if key else ""

        request = self.context.get('request')
        if request and url and url.startswith('/'):
            return request.build_absolute_uri(url)
        return url


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
    photos_count = serializers.IntegerField(read_only=True)
    videos_count = serializers.IntegerField(read_only=True)
    total_media_count = serializers.SerializerMethodField()
    total_size_bytes = serializers.IntegerField(read_only=True)
    total_size_mb = serializers.FloatField(read_only=True)
    total_size_formatted = serializers.CharField(read_only=True)
    photographer_name = serializers.SerializerMethodField()
    studio_name = serializers.SerializerMethodField()
    requires_password = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()
    media = serializers.SerializerMethodField()
    sections = serializers.ReadOnlyField(source='sections_list')
    template_banners = serializers.SerializerMethodField()
    expires_at = serializers.DateTimeField(read_only=True)
    is_expired = serializers.SerializerMethodField()
    section_counts = serializers.SerializerMethodField()
    watermark_enabled = serializers.SerializerMethodField()
    watermark_type = serializers.SerializerMethodField()
    watermark_text = serializers.SerializerMethodField()
    watermark_opacity = serializers.SerializerMethodField()
    watermark_position = serializers.SerializerMethodField()
    watermark_font_size = serializers.SerializerMethodField()
    watermark_font_color = serializers.SerializerMethodField()
    watermark_font_style = serializers.SerializerMethodField()
    watermark_image = serializers.SerializerMethodField()

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
            'template_banners',
            'visibility',
            'is_password_protected',
            'requires_password',
            'allow_downloads',
            'allow_favorites',
            'expires_at',
            'is_expired',
            'face_search_enabled',
            'watermark_enabled',
            'watermark_type',
            'watermark_text',
            'watermark_opacity',
            'watermark_position',
            'watermark_font_size',
            'watermark_font_color',
            'watermark_font_style',
            'watermark_image',
            'photos_count',
            'videos_count',
            'total_media_count',
            'total_size_bytes',
            'total_size_mb',
            'total_size_formatted',
            'favorites_count',
            'photographer_name',
            'studio_name',
            'cover_image',
            'sections',
            'section_counts',
            'media',
            'created_at',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['photos_count'] = instance.photos_count
        data['videos_count'] = instance.videos_count
        data['total_media_count'] = instance.total_media_count
        data['total_size_bytes'] = instance.total_size_bytes
        data['total_size_mb'] = instance.total_size_mb
        data['total_size_formatted'] = instance.total_size_formatted
        data['favorites_count'] = self.get_favorites_count(instance)
        data['section_counts'] = self.get_section_counts(instance)
        data['watermark_enabled'] = self.get_watermark_enabled(instance)
        data['watermark_type'] = self.get_watermark_type(instance)
        data['watermark_text'] = self.get_watermark_text(instance)
        data['watermark_opacity'] = self.get_watermark_opacity(instance)
        data['watermark_position'] = self.get_watermark_position(instance)
        data['watermark_font_size'] = self.get_watermark_font_size(instance)
        data['watermark_font_color'] = self.get_watermark_font_color(instance)
        data['watermark_font_style'] = self.get_watermark_font_style(instance)
        data['watermark_image'] = self.get_watermark_image(instance)
        data['photographer_name'] = self.get_photographer_name(instance)
        data['studio_name'] = self.get_studio_name(instance)
        return data

    def get_watermark_enabled(self, obj) -> bool:
        """
        Returns True if the gallery has watermarking enabled AND
        the photographer's current subscription plan allows watermarking.
        """
        if not getattr(obj, 'watermark_enabled', False):
            return False

        profile = getattr(obj.photographer, 'photographer_profile', None) or getattr(obj, 'photographer', None)
        user = getattr(profile, 'user', None) or getattr(obj, 'user', None) or getattr(obj.photographer, 'user', None)

        from App.Subscriptions.sub_models import PhotographerSubscription
        if user:
            curr_sub = PhotographerSubscription.objects.filter(photographer__user=user, status='active').first()
            if curr_sub and curr_sub.plan and hasattr(curr_sub.plan, 'watermark_enabled'):
                return bool(curr_sub.plan.watermark_enabled)
        return True

    def get_section_counts(self, obj):
        counts = (
            obj.media_items.filter(deleted_at__isnull=True)
            .values('section_title')
            .annotate(count=models.Count('id'))
        )
        return {
            (item['section_title'] or 'UNASSIGNED').upper(): item['count']
            for item in counts
        }

    def get_photographer_name(self, obj) -> str:
        if not obj.photographer:
            return 'Photographer'
        profile = getattr(obj.photographer, 'photographer_profile', None) or getattr(obj, 'photographer', None)
        if profile and getattr(profile, 'name', None) and str(profile.name).strip():
            return str(profile.name).strip()
        user = getattr(profile, 'user', None) or getattr(obj, 'user', None) or getattr(obj.photographer, 'user', None)
        if user and hasattr(user, 'get_full_name') and user.get_full_name().strip():
            return user.get_full_name().strip()
        return getattr(user, 'username', 'Photographer') if user else 'Photographer'

    def get_studio_name(self, obj) -> str:
        profile = getattr(obj.photographer, 'photographer_profile', None) or getattr(obj, 'photographer', None)
        if profile and getattr(profile, 'studio_name', None) and str(profile.studio_name).strip():
            return str(profile.studio_name).strip()
        return f"{self.get_photographer_name(obj)} Studio"

    def get_watermark_text(self, obj) -> str:
        """Returns the custom gallery watermark or defaults to photographer's name."""
        legacy_placeholders = {'ex studio', '© ex studio', 'atelier studio', '© atelier studio', 'studio', '© studio'}
        if obj.watermark_text and str(obj.watermark_text).strip():
            txt = str(obj.watermark_text).strip()
            if txt.lower() not in legacy_placeholders:
                return txt if txt.startswith('©') else f"© {txt}"

        profile = getattr(obj.photographer, 'photographer_profile', None) or getattr(obj, 'photographer', None)
        if profile and hasattr(profile, 'get_effective_watermark_text'):
            return profile.get_effective_watermark_text()

        return f"© {self.get_photographer_name(obj)}"

    def get_watermark_opacity(self, obj) -> float:
        if obj.watermark_opacity is not None:
            return float(obj.watermark_opacity)
        profile = getattr(obj.photographer, 'photographer_profile', None) or getattr(obj, 'photographer', None)
        if profile and getattr(profile, 'watermark_opacity', None) is not None:
            return float(profile.watermark_opacity)
        return 0.45

    def get_watermark_position(self, obj) -> str:
        if obj.watermark_position and str(obj.watermark_position).strip():
            return str(obj.watermark_position).strip().replace('_', '-')
        profile = getattr(obj.photographer, 'photographer_profile', None) or getattr(obj, 'photographer', None)
        if profile and getattr(profile, 'watermark_position', None):
            return str(profile.watermark_position).replace('_', '-')
        return 'bottom-right'

    def get_watermark_type(self, obj) -> str:
        if hasattr(obj, 'watermark_type') and obj.watermark_type:
            return obj.watermark_type
        profile = getattr(obj.photographer, 'photographer_profile', None) or getattr(obj, 'photographer', None)
        return getattr(profile, 'watermark_type', 'text') or 'text'

    def get_watermark_image(self, obj):
        # STRICT ONE-AT-A-TIME:
        # If watermark_type is 'text', image MUST be null!
        active_type = self.get_watermark_type(obj)
        if active_type != 'image':
            return None

        profile = getattr(obj.photographer, 'photographer_profile', None) or getattr(obj, 'photographer', None)
        img = getattr(profile, 'watermark_image', None) if profile else None
        if img:
            request = self.context.get('request')
            try:
                url = img.url
                return request.build_absolute_uri(url) if request else url
            except Exception:
                return None
        return None

    def get_watermark_font_size(self, obj) -> str:
        if hasattr(obj, 'watermark_font_size') and obj.watermark_font_size:
            return obj.watermark_font_size
        profile = getattr(obj.photographer, 'photographer_profile', None) or getattr(obj, 'photographer', None)
        return getattr(profile, 'watermark_font_size', 'md') if profile else 'md'

    def get_watermark_font_color(self, obj) -> str:
        if hasattr(obj, 'watermark_font_color') and obj.watermark_font_color:
            return obj.watermark_font_color
        profile = getattr(obj.photographer, 'photographer_profile', None) or getattr(obj, 'photographer', None)
        return getattr(profile, 'watermark_font_color', '#FFFFFF') if profile else '#FFFFFF'

    def get_watermark_font_style(self, obj) -> str:
        if hasattr(obj, 'watermark_font_style') and obj.watermark_font_style:
            return obj.watermark_font_style
        profile = getattr(obj.photographer, 'photographer_profile', None) or getattr(obj, 'photographer', None)
        return getattr(profile, 'watermark_font_style', 'serif') if profile else 'serif'

    def get_favorites_count(self, obj):
        count = obj.media_items.filter(deleted_at__isnull=True, is_favorite=True).count()
        return count if count > 0 else getattr(obj, 'favorites_count', 0)

    def get_template_banners(self, obj):
        return _sanitize_banner_dict(obj.template_banners, obj, self.context.get('request'))

    def get_is_expired(self, obj):
        return bool(obj.is_expired)

    def get_photos_count(self, obj):
        return obj.photos_count

    def get_videos_count(self, obj):
        return obj.videos_count

    def get_total_media_count(self, obj):
        return obj.total_media_count

    def get_requires_password(self, obj):
        return obj.is_password_protected or obj.visibility == 'password_protected'

    def get_cover_image(self, obj):
        url = ""
        if obj.cover_media and not getattr(obj.cover_media, 'deleted_at', None):
            storage = get_storage_provider()
            key = obj.cover_media.preview_storage_key or obj.cover_media.storage_key
            url = storage.generate_cdn_url(key) if key else ""
        elif obj.cover_image_url:
            deleted_ids = {str(d) for d in obj.media_items.filter(deleted_at__isnull=False).values_list('id', flat=True)}
            if not any(did in str(obj.cover_image_url) for did in deleted_ids):
                url = obj.cover_image_url
            else:
                first_media = obj.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at', 'id').first()
                if first_media:
                    storage = get_storage_provider()
                    key = first_media.preview_storage_key or first_media.storage_key
                    url = storage.generate_cdn_url(key) if key else ""
        else:
            first_media = obj.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at', 'id').first()
            if first_media:
                storage = get_storage_provider()
                key = first_media.preview_storage_key or first_media.storage_key
                url = storage.generate_cdn_url(key) if key else ""

        request = self.context.get('request')
        if request and url and url.startswith('/'):
            return request.build_absolute_uri(url)
        return url

    def get_media(self, obj):
        if self.context.get('access_granted', True):
            qs = obj.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at')
            return MediaSerializer(qs, many=True, context=self.context).data
        return []


class GalleryClientSelectionSerializer(serializers.ModelSerializer):
    selected_media_items = serializers.SerializerMethodField()

    class Meta:
        model = GalleryClientSelection
        fields = [
            'id',
            'gallery',
            'client_name',
            'client_email',
            'selection_notes',
            'status',
            'selected_media',
            'selected_media_items',
            'submitted_at',
            'reviewed_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'status', 'submitted_at', 'reviewed_at', 'created_at', 'updated_at']

    def get_selected_media_items(self, obj):
        return MediaSerializer(obj.selected_media.all(), many=True, context=self.context).data


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


class GalleryDetailResponseSerializer(GallerySerializer):
    """
    Upgraded Gallery Serializer for Ex Share Atelier frontend.
    Returns gallery metadata along with the dynamically paginated media slice.
    """
    sections = serializers.ReadOnlyField(source='sections_list')
    media = serializers.SerializerMethodField()
    photos_count = serializers.SerializerMethodField()
    videos_count = serializers.SerializerMethodField()
    total_media_count = serializers.SerializerMethodField()
    section_counts = serializers.SerializerMethodField()
    favorites_count = serializers.SerializerMethodField()

    def get_media(self, obj):
        """
        Dynamically returns the paginated media slice supplied by the view context.
        If no paginated slice was injected, falls back to the gallery's full media queryset.
        """
        if 'paginated_media' in self.context:
            media_items = self.context['paginated_media']
            return MediaSerializer(media_items, many=True, context=self.context).data

        if 'media_qs' in self.context:
            return MediaSerializer(self.context['media_qs'], many=True, context=self.context).data

        return MediaSerializer(
            obj.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at', 'id'),
            many=True,
            context=self.context
        ).data

    def get_photos_count(self, obj):
        if hasattr(obj, 'photos_count') and obj.photos_count is not None:
            return obj.photos_count
        return obj.media_items.filter(media_type='photo', deleted_at__isnull=True).count()

    def get_videos_count(self, obj):
        if hasattr(obj, 'videos_count') and obj.videos_count is not None:
            return obj.videos_count
        return obj.media_items.filter(media_type='video', deleted_at__isnull=True).count()

    def get_total_media_count(self, obj):
        if 'total_media_count' in self.context:
            return self.context['total_media_count']
        return getattr(obj, '_total_media_count', None) or obj.total_media_count

    def get_section_counts(self, obj):
        return super().get_section_counts(obj)

    def get_favorites_count(self, obj):
        return super().get_favorites_count(obj)


class GallerySettingsUpdateSerializer(serializers.ModelSerializer):
    expires_at = serializers.DateTimeField(allow_null=True, required=False)
    is_expired = serializers.SerializerMethodField()

    def get_is_expired(self, obj):
        return bool(obj.is_expired)

    class Meta:
        model = Gallery
        fields = [
            'title',
            'client_name',
            'client_email',
            'client_phone',
            'event_date',
            'is_password_protected',
            'password',
            'allow_downloads',
            'download_pin',
            'allow_favorites',
            'face_search_enabled',
            'watermark_enabled',
            'watermark_type',
            'watermark_text',
            'watermark_opacity',
            'watermark_position',
            'watermark_font_size',
            'watermark_font_color',
            'watermark_font_style',
            'expires_at',
            'is_expired',
            'status',
            'template_id',
        ]
        read_only_fields = ['is_expired']
        extra_kwargs = {
            'title': {'required': False},
            'client_name': {'required': False},
            'password': {'required': False, 'allow_blank': True},
            'download_pin': {'required': False, 'allow_blank': True},
            'face_search_enabled': {'required': False},
            'watermark_enabled': {'required': False},
        }

    def validate_face_search_enabled(self, value):
        if value:
            request = self.context.get('request')
            if request and getattr(request, 'user', None):
                user = request.user
                if not (user.is_staff or user.is_superuser):
                    from App.Photographers.photo_models import PhotographerProfile
                    profile = PhotographerProfile.objects.filter(user=user).first()
                    if profile:
                        sub = getattr(profile, 'subscription', None)
                        plan = getattr(sub, 'plan', None) if sub else None
                        if not plan:
                            plan = getattr(profile, 'studio_plan', None) or getattr(profile, 'plan', None)
                        plan_allowed = getattr(plan, 'face_search_enabled', False)
                        if not plan_allowed:
                            raise serializers.ValidationError(
                                "AI Biometric Face Search is locked on your current subscription plan. Upgrade to enable."
                            )
        return value

    def validate_watermark_enabled(self, value):
        if value:
            request = self.context.get('request')
            if request and getattr(request, 'user', None):
                user = request.user
                if not (user.is_staff or user.is_superuser):
                    from App.Photographers.photo_models import PhotographerProfile
                    from rest_framework.exceptions import PermissionDenied
                    profile = getattr(user, 'photographer_profile', None) or PhotographerProfile.objects.filter(user=user).first()
                    sub = getattr(profile, 'subscription', None) if profile else None
                    if not sub and hasattr(user, 'subscription'):
                        sub = user.subscription
                    plan = getattr(sub, 'plan', None) if sub and getattr(sub, 'is_active', True) else None
                    if not plan and profile:
                        plan = getattr(profile, 'studio_plan', None) or getattr(profile, 'plan', None)

                    if not plan or not getattr(plan, 'watermark_enabled', False):
                        raise PermissionDenied({
                            "error_code": "WATERMARK_LOCKED",
                            "upgrade_required": True,
                            "detail": "Custom studio watermarking is not included in your current subscription plan. Please upgrade your plan to watermark proofing galleries.",
                            "message": "Custom studio watermarking is not included in your current subscription plan. Please upgrade your plan to watermark proofing galleries."
                        })
        return value

    def update(self, instance, validated_data):
        if 'is_password_protected' in validated_data:
            is_prot = validated_data['is_password_protected']
            instance.is_password_protected = is_prot
            if not is_prot:
                instance.password = ''
                if instance.visibility == 'password_protected':
                    instance.visibility = 'public'
            elif 'password' in validated_data and validated_data['password']:
                instance.set_access_password(validated_data['password'].strip())
        elif 'password' in validated_data:
            pwd = validated_data['password']
            if pwd and instance.is_password_protected:
                instance.set_access_password(pwd.strip())
            elif not instance.is_password_protected:
                instance.password = ''

        for attr, val in validated_data.items():
            if attr not in ['is_password_protected', 'password']:
                setattr(instance, attr, val)
        instance.save()
        return instance


# Aliases for specification consistency
GalleryUpdateSerializer = GallerySettingsUpdateSerializer
GalleryDetailSerializer = GalleryDetailResponseSerializer
MediaItemSerializer = MediaSerializer



class GallerySectionSerializer(serializers.ModelSerializer):
    media_count = serializers.SerializerMethodField()

    class Meta:
        model = GallerySection
        fields = ['id', 'title', 'order', 'media_count']

    def get_media_count(self, obj: GallerySection) -> int:
        return obj.gallery.media_items.filter(section_title__iexact=obj.title, deleted_at__isnull=True).count()


class MoveMediaSectionSerializer(serializers.Serializer):
    media_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False,
        help_text="List of media UUIDs to move"
    )
    target_section = serializers.CharField(
        max_length=120, allow_blank=False,
        help_text="Target section name (e.g. CEREMONY or UNASSIGNED)"
    )


class SectionCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120, min_length=1)


class SectionRenameSerializer(serializers.Serializer):
    old_title = serializers.CharField(max_length=120)
    new_title = serializers.CharField(max_length=120)


class SectionReorderSerializer(serializers.Serializer):
    sections = serializers.ListField(child=serializers.CharField(max_length=120))


class MediaReorderSerializer(serializers.Serializer):
    media_ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_empty=True)
    order = serializers.ListField(child=serializers.DictField(), required=False, allow_empty=True)

    def validate(self, data):
        if not data.get('media_ids') and not data.get('order'):
            raise serializers.ValidationError("Either 'media_ids' or 'order' must be provided.")
        return data


class GalleryReorderMediaSerializer(MediaReorderSerializer):
    pass


class TemplateUpdateSerializer(serializers.Serializer):
    template_id = serializers.CharField(max_length=50)


class GalleryTemplateUpdateSerializer(TemplateUpdateSerializer):
    pass


class TemplateBannerUpdateSerializer(serializers.Serializer):
    template_id = serializers.CharField(max_length=40)
    media_url = serializers.URLField(max_length=800)
    media_id = serializers.UUIDField(required=False, allow_null=True)


class MasonrySlotSerializer(serializers.Serializer):
    slot_index = serializers.IntegerField(min_value=0, max_value=3)
    media_url = serializers.URLField(max_length=800)


class GalleryCoverSerializer(serializers.Serializer):
    media_url = serializers.URLField(max_length=800, required=False, allow_blank=True)
    cover_image_url = serializers.CharField(max_length=800, required=False, allow_blank=True)
    media_id = serializers.UUIDField(required=False, allow_null=True)


class GallerySetCoverSerializer(GalleryCoverSerializer):
    pass


class AnalyticsEventTrackSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=GalleryAnalyticsEvent.EVENT_TYPES)
    media_id = serializers.UUIDField(required=False, allow_null=True)
    device = serializers.CharField(max_length=30, required=False, default='desktop')
    traffic_source = serializers.CharField(max_length=30, required=False, default='direct_link')
    details = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


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
            url = storage.generate_signed_download_url(
                obj.archive_storage_key,
                expires_in=86400,
                filename=f"gallery_{obj.gallery_id}_photos.zip"
            )
            request = self.context.get('request')
            if request and url and url.startswith('/'):
                return request.build_absolute_uri(url)
            return url
        return None


class StorageUsageSerializer(serializers.Serializer):
    plan = serializers.CharField()
    storage_used_bytes = serializers.IntegerField()
    storage_reserved_bytes = serializers.IntegerField()
    storage_limit_bytes = serializers.IntegerField()
    storage_remaining_bytes = serializers.IntegerField()
    usage_percentage = serializers.FloatField()


# Explicit Aliases matching Frontend / Specification Naming
GalleryListSerializer = GallerySerializer
GalleryDetailSerializer = GalleryDetailResponseSerializer
MediaItemSerializer = MediaSerializer

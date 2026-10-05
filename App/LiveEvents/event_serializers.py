from datetime import timedelta, datetime, time
from django.utils import timezone
from rest_framework import serializers
from .event_models import LiveEvent, EventMedia, EventFaceEmbedding
from App.utils import format_bytes_human


from django.db import models


class EventMediaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    thumbnailUrl = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    title = serializers.CharField(source='original_filename', read_only=True)
    type = serializers.CharField(source='media_type', read_only=True)
    size_bytes = serializers.IntegerField(source='file_size', read_only=True)
    sectionTitle = serializers.CharField(source='section_title', required=False)
    section_title = serializers.CharField(required=False)
    sizeMB = serializers.FloatField(source='size_mb', read_only=True)
    size_mb = serializers.SerializerMethodField()
    file_size = serializers.IntegerField(read_only=True)
    dateAdded = serializers.DateTimeField(source='created_at', read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    media_type = serializers.CharField(read_only=True)

    class Meta:
        model = EventMedia
        fields = [
            'id', 'title', 'original_filename', 'url', 'file_url', 'thumbnailUrl', 'thumbnail_url',
            'type', 'media_type', 'sectionTitle', 'section_title', 'width', 'height', 'aspect_ratio',
            'file_size', 'size_bytes', 'size_mb', 'sizeMB', 'is_favorite', 'is_cover', 'dateAdded', 'created_at'
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['file_size'] = instance.file_size or 0
        data['size_bytes'] = instance.file_size or 0
        data['size_mb'] = self.get_size_mb(instance)
        data['type'] = instance.media_type or 'photo'
        data['title'] = instance.original_filename or ''
        return data

    def get_url(self, obj):
        url = obj.file_url or (obj.file.url if obj.file else '')
        request = self.context.get('request')
        if request and url and url.startswith('/'):
            return request.build_absolute_uri(url)
        return url

    def get_file_url(self, obj):
        return self.get_url(obj)

    def get_thumbnailUrl(self, obj):
        url = obj.thumbnail_url or (obj.thumbnail.url if obj.thumbnail else (obj.file.url if obj.file else ''))
        request = self.context.get('request')
        if request and url and url.startswith('/'):
            return request.build_absolute_uri(url)
        return url

    def get_thumbnail_url(self, obj):
        return self.get_thumbnailUrl(obj)

    def get_size_mb(self, obj):
        size = getattr(obj, 'file_size', None) or (obj.file.size if getattr(obj, 'file', None) else 0)
        if size:
            return round(size / (1024 * 1024), 2)
        return getattr(obj, 'size_mb', 0.0) or 0.0


class LiveEventListSerializer(serializers.ModelSerializer):
    total_size_bytes = serializers.IntegerField(read_only=True)
    total_size_mb = serializers.FloatField(read_only=True)
    total_size_formatted = serializers.CharField(read_only=True)
    photos_count = serializers.IntegerField(read_only=True)
    videos_count = serializers.IntegerField(read_only=True)
    total_media_count = serializers.IntegerField(read_only=True)
    media_count = serializers.IntegerField(source='media.count', read_only=True)
    section_counts = serializers.SerializerMethodField()
    qrSettings = serializers.SerializerMethodField()
    qr_settings = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()

    class Meta:
        model = LiveEvent
        fields = [
            'id', 'slug', 'title', 'client_name', 'client_contact',
            'event_type', 'status', 'banner_url', 'event_date',
            'event_time', 'venue', 'city', 'description',
            'qrSettings', 'qr_settings', 'stats', 'photos_count', 'videos_count',
            'total_media_count', 'media_count', 'section_counts', 'total_size_bytes', 'total_size_mb',
            'total_size_formatted', 'created_at', 'updated_at'
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['photos_count'] = instance.photos_count
        data['videos_count'] = instance.videos_count
        data['total_media_count'] = instance.total_media_count
        data['total_size_bytes'] = instance.total_size_bytes
        data['total_size_mb'] = instance.total_size_mb
        data['total_size_formatted'] = instance.total_size_formatted
        data['section_counts'] = self.get_section_counts(instance)
        return data

    def get_section_counts(self, obj):
        counts = (
            obj.media
            .values('section_title')
            .annotate(count=models.Count('id'))
        )
        return {
            (item['section_title'] or 'UNASSIGNED').upper(): item['count']
            for item in counts
        }

    def get_qrSettings(self, obj):
        return {
            'valid_from': obj.qr_valid_from.isoformat() if obj.qr_valid_from else None,
            'expires_at': obj.qr_expires_at.isoformat() if obj.qr_expires_at else None,
            'duration_hours': obj.qr_duration_hours,
            'is_active': not obj.is_qr_expired,
            'pin_code': obj.qr_pin_code,
            'allow_guest_uploads': obj.allow_guest_uploads,
        }

    def get_qr_settings(self, obj):
        return self.get_qrSettings(obj)

    def get_stats(self, obj):
        return {
            'views': obj.guest_views,
            'qr_scans': obj.qr_scans,
            'qrScans': obj.qr_scans,
            'ai_searches': obj.ai_searches,
            'aiSearches': obj.ai_searches,
            'matches_found': obj.matches_found,
            'matchesFound': obj.matches_found,
            'downloads_count': obj.downloads_count,
            'downloadsCount': obj.downloads_count,
        }


class LiveEventDetailSerializer(LiveEventListSerializer):
    media = serializers.SerializerMethodField()
    section_counts = serializers.SerializerMethodField()

    class Meta(LiveEventListSerializer.Meta):
        fields = LiveEventListSerializer.Meta.fields + ['media']

    def get_media(self, obj):
        if 'filtered_media' in self.context:
            return EventMediaSerializer(self.context['filtered_media'], many=True, context=self.context).data

        request = self.context.get('request')
        qs = obj.media.all().order_by('-created_at')
        if request:
            section = request.query_params.get('section', '').strip()
            if section and section.lower() != 'all':
                qs = qs.filter(section_title__iexact=section)
        return EventMediaSerializer(qs, many=True, context=self.context).data

    def get_section_counts(self, obj):
        return super().get_section_counts(obj)


class PublicEventPortalSerializer(serializers.ModelSerializer):
    """
    Public guest endpoint: STRICT PRIVACY.
    Intentionally omits full media stream to protect guest privacy.
    """
    total_size_bytes = serializers.IntegerField(read_only=True)
    total_size_mb = serializers.FloatField(read_only=True)
    total_size_formatted = serializers.CharField(read_only=True)
    photos_count = serializers.IntegerField(read_only=True)
    videos_count = serializers.IntegerField(read_only=True)
    total_media_count = serializers.IntegerField(read_only=True)
    qrSettings = serializers.SerializerMethodField()
    qr_settings = serializers.SerializerMethodField()
    isExpired = serializers.BooleanField(source='is_qr_expired', read_only=True)

    class Meta:
        model = LiveEvent
        fields = [
            'id', 'slug', 'title', 'event_type', 'banner_url',
            'event_date', 'venue', 'city', 'qrSettings', 'qr_settings', 'isExpired',
            'photos_count', 'videos_count', 'total_media_count',
            'total_size_bytes', 'total_size_mb', 'total_size_formatted'
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['photos_count'] = instance.photos_count
        data['videos_count'] = instance.videos_count
        data['total_media_count'] = instance.total_media_count
        data['total_size_bytes'] = instance.total_size_bytes
        data['total_size_mb'] = instance.total_size_mb
        data['total_size_formatted'] = instance.total_size_formatted
        return data

    def get_qrSettings(self, obj):
        return {
            'valid_from': obj.qr_valid_from.isoformat() if obj.qr_valid_from else None,
            'expires_at': obj.qr_expires_at.isoformat() if obj.qr_expires_at else None,
            'is_active': not obj.is_qr_expired,
            'allow_guest_uploads': obj.allow_guest_uploads,
        }

    def get_qr_settings(self, obj):
        return self.get_qrSettings(obj)


class MoveEventToGallerySerializer(serializers.Serializer):
    target_mode = serializers.ChoiceField(choices=['new', 'existing'])
    target_gallery_id = serializers.UUIDField(required=False, allow_null=True)
    new_gallery_title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    category_assignments = serializers.DictField(child=serializers.CharField(), required=False)


class LiveEventUpdateSerializer(serializers.ModelSerializer):
    pin_code = serializers.CharField(required=False, allow_blank=True, allow_null=True, write_only=True)
    qr_pin_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    qr_duration_hours = serializers.IntegerField(required=False)
    allow_guest_uploads = serializers.BooleanField(required=False)
    event_date = serializers.DateField(required=False, allow_null=True)
    event_time = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = LiveEvent
        fields = [
            'title',
            'client_name',
            'client_contact',
            'event_type',
            'status',
            'event_date',
            'event_time',
            'venue',
            'city',
            'description',
            'banner_url',
            'qr_duration_hours',
            'pin_code',
            'qr_pin_code',
            'allow_guest_uploads',
        ]

    def update(self, instance, validated_data):
        pin = validated_data.pop('pin_code', None)
        if pin is not None:
            instance.qr_pin_code = str(pin).strip() or None
        elif 'qr_pin_code' in validated_data:
            raw_pin = validated_data.pop('qr_pin_code')
            instance.qr_pin_code = str(raw_pin).strip() if raw_pin else None

        qr_duration = validated_data.get('qr_duration_hours')
        date_updated = 'event_date' in validated_data and validated_data['event_date'] != instance.event_date
        time_updated = 'event_time' in validated_data and validated_data['event_time'] != instance.event_time
        duration_updated = qr_duration is not None and qr_duration != instance.qr_duration_hours

        if duration_updated:
            instance.qr_duration_hours = qr_duration

        if duration_updated or date_updated or time_updated:
            duration = instance.qr_duration_hours or 24
            target_date = validated_data.get('event_date') or instance.event_date
            target_time = validated_data.get('event_time') or instance.event_time

            base_time = None
            if target_date:
                t_val = time(18, 0)
                if target_time and isinstance(target_time, str):
                    try:
                        parts = target_time.split(':')
                        t_val = time(int(parts[0]), int(parts[1]))
                    except Exception:
                        t_val = time(18, 0)
                elif hasattr(target_time, 'hour'):
                    t_val = target_time

                event_dt = datetime.combine(target_date, t_val)
                if timezone.is_naive(event_dt):
                    event_dt = timezone.make_aware(event_dt, timezone.get_current_timezone())

                # If event date is future, base expiration on scheduled event start
                if event_dt > timezone.now():
                    base_time = event_dt

            if not base_time:
                base_time = instance.qr_valid_from or timezone.now()
                if timezone.is_naive(base_time):
                    base_time = timezone.make_aware(base_time, timezone.get_current_timezone())
                if instance.is_qr_expired:
                    base_time = timezone.now()

            instance.qr_expires_at = base_time + timedelta(hours=duration)

        return super().update(instance, validated_data)


# Explicit Aliases matching Frontend / Specification Naming
EventListSerializer = LiveEventListSerializer
EventDetailSerializer = LiveEventDetailSerializer
EventUpdateSerializer = LiveEventUpdateSerializer
PublicEventSerializer = PublicEventPortalSerializer
EventMediaItemSerializer = EventMediaSerializer

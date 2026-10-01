import uuid
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from App.utils import format_bytes_human


class LiveEvent(models.Model):
    EVENT_TYPES = [
        ('wedding', 'Wedding Celebration'),
        ('reception', 'Reception / Sangeet'),
        ('sangeet', 'Sangeet / Mehendi'),
        ('gala', 'VIP Gala / Soirée'),
        ('fashion', 'Fashion Show'),
        ('birthday', 'Birthday / Anniversary'),
        ('anniversary', 'Anniversary Celebration'),
        ('corporate', 'Corporate Summit'),
        ('concert', 'Concert / Performance'),
        ('other', 'Special Event'),
    ]

    STATUS_CHOICES = [
        ('live', 'Live Streaming'),
        ('upcoming', 'Upcoming Scheduled'),
        ('completed', 'Completed'),
        ('moved_to_gallery', 'Moved to Gallery'),
        ('trash', 'In Trash'),
        ('archived', 'Archived'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    photographer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='events'
    )
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    client_name = models.CharField(max_length=255, blank=True, default='Private Client')
    client_contact = models.CharField(max_length=255, blank=True, default='')
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, default='wedding')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='live', db_index=True)
    banner_url = models.URLField(max_length=1000, blank=True, default='')
    event_date = models.DateField(default=timezone.localdate)
    event_time = models.CharField(max_length=20, blank=True, default='18:00')
    venue = models.CharField(max_length=255, blank=True, default='Private Venue')
    city = models.CharField(max_length=150, blank=True, default='')
    description = models.TextField(blank=True, default='')

    # QR Security & Expiry Controls
    qr_valid_from = models.DateTimeField(default=timezone.now)
    qr_expires_at = models.DateTimeField(null=True, blank=True)
    qr_duration_hours = models.IntegerField(default=24)  # Preset or custom
    qr_pin_code = models.CharField(max_length=20, blank=True, null=True)
    allow_guest_uploads = models.BooleanField(default=False)
    auto_sync_enabled = models.BooleanField(default=False)

    # Engagement & Analytics
    guest_views = models.PositiveIntegerField(default=0)
    qr_scans = models.PositiveIntegerField(default=0)
    ai_searches = models.PositiveIntegerField(default=0)
    matches_found = models.PositiveIntegerField(default=0)
    downloads_count = models.PositiveIntegerField(default=0)

    # Trash / Soft Delete
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    @property
    def user(self):
        return self.photographer

    def save(self, *args, **kwargs):
        if self.event_date and hasattr(self.event_date, 'date'):
            self.event_date = self.event_date.date()
        if not self.slug:
            base_slug = slugify(self.title)[:40] or "event"
            candidate_slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
            while LiveEvent.objects.filter(slug=candidate_slug).exists():
                candidate_slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
            self.slug = candidate_slug

        from django.utils.dateparse import parse_datetime, parse_date
        if self.qr_valid_from and isinstance(self.qr_valid_from, str):
            parsed = parse_datetime(self.qr_valid_from)
            if not parsed:
                d = parse_date(self.qr_valid_from)
                if d:
                    from datetime import datetime, time
                    parsed = datetime.combine(d, time.min)
            if parsed and timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            if parsed:
                self.qr_valid_from = parsed

        if self.qr_expires_at and isinstance(self.qr_expires_at, str):
            parsed = parse_datetime(self.qr_expires_at)
            if not parsed:
                d = parse_date(self.qr_expires_at)
                if d:
                    from datetime import datetime, time
                    parsed = datetime.combine(d, time.max)
            if parsed and timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            if parsed:
                self.qr_expires_at = parsed

        if not self.qr_expires_at:
            duration = self.qr_duration_hours if self.qr_duration_hours and self.qr_duration_hours > 0 else 24
            base_time = self.qr_valid_from or timezone.now()
            if isinstance(base_time, str):
                parsed_base = parse_datetime(base_time)
                base_time = parsed_base if parsed_base else timezone.now()
            if timezone.is_naive(base_time):
                base_time = timezone.make_aware(base_time, timezone.get_current_timezone())
            self.qr_expires_at = base_time + timedelta(hours=duration)
        super().save(*args, **kwargs)

    @property
    def is_qr_expired(self):
        if not self.qr_expires_at:
            return False
        exp = self.qr_expires_at
        if isinstance(exp, str):
            from django.utils.dateparse import parse_datetime, parse_date
            parsed = parse_datetime(exp)
            if not parsed:
                d = parse_date(exp)
                if d:
                    from datetime import datetime, time
                    parsed = datetime.combine(d, time.max)
            exp = parsed
            if not exp:
                return False
        if timezone.is_naive(exp):
            exp = timezone.make_aware(exp, timezone.get_current_timezone())
        return timezone.now() > exp

    @property
    def total_size_bytes(self) -> int:
        """Sum of file_size across all event media items."""
        if hasattr(self, '_total_size_bytes') and self._total_size_bytes is not None:
            return self._total_size_bytes
        aggregate_res = self.media.aggregate(total=models.Sum('file_size'))
        total = aggregate_res['total']
        if not total:
            # Fallback if size_mb exists
            sum_mb = self.media.aggregate(total_mb=models.Sum('size_mb'))['total_mb']
            if sum_mb:
                total = int(sum_mb * 1024 * 1024)
        return total or 0

    @total_size_bytes.setter
    def total_size_bytes(self, value):
        self._total_size_bytes = value

    @property
    def total_size_mb(self) -> float:
        """Total size in megabytes rounded to 2 decimals."""
        return round(self.total_size_bytes / (1024 * 1024), 2)

    @property
    def total_size_formatted(self) -> str:
        """Formatted display string e.g. '124.5 MB' or '1.45 GB'."""
        return format_bytes_human(self.total_size_bytes)

    @property
    def photos_count(self) -> int:
        if hasattr(self, '_photos_count') and self._photos_count is not None:
            return self._photos_count
        return self.media.filter(models.Q(media_type='photo') | models.Q(media_type='image') | models.Q(media_type='')).exclude(
            models.Q(original_filename__iendswith='.mp4') |
            models.Q(original_filename__iendswith='.mov') |
            models.Q(original_filename__iendswith='.webm') |
            models.Q(original_filename__iendswith='.mkv') |
            models.Q(original_filename__iendswith='.avi') |
            models.Q(media_type='video')
        ).count()

    @photos_count.setter
    def photos_count(self, value):
        self._photos_count = value

    @property
    def videos_count(self) -> int:
        if hasattr(self, '_videos_count') and self._videos_count is not None:
            return self._videos_count
        return self.media.filter(
            models.Q(media_type='video') |
            models.Q(original_filename__iendswith='.mp4') |
            models.Q(original_filename__iendswith='.mov') |
            models.Q(original_filename__iendswith='.webm') |
            models.Q(original_filename__iendswith='.mkv') |
            models.Q(original_filename__iendswith='.avi')
        ).count()

    @videos_count.setter
    def videos_count(self, value):
        self._videos_count = value

    @property
    def total_media_count(self) -> int:
        if hasattr(self, '_total_media_count') and self._total_media_count is not None:
            return self._total_media_count
        return (self.photos_count or 0) + (self.videos_count or 0)

    @total_media_count.setter
    def total_media_count(self, value):
        self._total_media_count = value


class EventMedia(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(LiveEvent, on_delete=models.CASCADE, related_name='media')
    original_filename = models.CharField(max_length=255)
    file = models.FileField(upload_to='events/media/%Y/%m/%d/')
    thumbnail = models.FileField(upload_to='events/thumbs/%Y/%m/%d/', blank=True, null=True)
    file_url = models.URLField(max_length=1000, blank=True)
    thumbnail_url = models.URLField(max_length=1000, blank=True)
    section_title = models.CharField(max_length=100, default='HIGHLIGHTS')
    width = models.PositiveIntegerField(default=1920)
    height = models.PositiveIntegerField(default=1080)
    aspect_ratio = models.FloatField(default=1.77)
    media_type = models.CharField(max_length=20, default='photo', choices=[('photo', 'Photo'), ('video', 'Video')])
    file_size = models.BigIntegerField(default=0, help_text="File size in bytes")
    size_mb = models.FloatField(default=3.5)
    is_favorite = models.BooleanField(default=False)
    is_cover = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.original_filename} ({self.event.title})"

    def save(self, *args, **kwargs):
        if not self.file_size and self.file:
            try:
                self.file_size = self.file.size
            except Exception:
                pass
        if not self.file_size and self.size_mb:
            self.file_size = int(self.size_mb * 1024 * 1024)
        if (not self.size_mb or self.size_mb == 3.5) and self.file_size:
            self.size_mb = round(self.file_size / (1024 * 1024), 2)

        fn = (self.original_filename or '').lower()
        if any(fn.endswith(ext) for ext in ['.mp4', '.mov', '.webm', '.mkv', '.avi', '.m4v']):
            self.media_type = 'video'
        elif not self.media_type:
            self.media_type = 'photo'

        super().save(*args, **kwargs)


class EventFaceEmbedding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_media = models.ForeignKey(
        EventMedia,
        on_delete=models.CASCADE,
        related_name='face_embeddings'
    )
    face_id = models.CharField(max_length=100, blank=True)
    # Store 512-dim embedding as JSON vector
    embedding = models.JSONField(help_text="512-dim face recognition vector")
    bounding_box = models.JSONField(blank=True, null=True)  # {"x": .., "y": .., "w": .., "h": ..}
    confidence = models.FloatField(default=0.95)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Embedding for {self.event_media.original_filename} (conf: {self.confidence})"

import uuid
import secrets
from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from django.utils.text import slugify
from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile


def generate_event_access_code():
    """Generates a clean, unique random access code for event sharing (e.g. EVT-A8B9C2)."""
    random_part = secrets.token_hex(4).upper()
    return f"EVT-{random_part}"


def generate_secure_share_token():
    """Generates a cryptographically secure 32-byte hex token for gallery sharing."""
    return secrets.token_urlsafe(32)


# =============================================================================
# 1. Event Photo Sharing Models (Maintained for Backward Compatibility)
# =============================================================================

class SharedEvent(models.Model):
    EVENT_TYPES = [
        ('wedding', 'Wedding'),
        ('reception', 'Reception'),
        ('engagement', 'Engagement'),
        ('birthday', 'Birthday'),
        ('anniversary', 'Anniversary'),
        ('corporate', 'Corporate Event'),
        ('family', 'Family Function'),
        ('other', 'Other'),
    ]

    photographer = models.ForeignKey(
        PhotographerProfile,
        on_delete=models.CASCADE,
        related_name='shared_events'
    )
    title = models.CharField(max_length=255)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, default='wedding')
    event_date = models.DateField(null=True, blank=True)
    venue = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to='event_covers/', null=True, blank=True)
    
    access_code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        default=generate_event_access_code
    )
    pin_code = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Optional PIN code required for guests to view/download photos"
    )
    is_public = models.BooleanField(
        default=True,
        help_text="When True, accessible via access code. When False, gallery is hidden"
    )
    allow_downloads = models.BooleanField(
        default=True,
        help_text="Allow guests to download individual photos or the bulk ZIP"
    )
    
    views_count = models.PositiveIntegerField(default=0)
    downloads_count = models.PositiveIntegerField(default=0)
    expiry_date = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.access_code})"

    def save(self, *args, **kwargs):
        if not self.access_code:
            self.access_code = generate_event_access_code()
            while SharedEvent.objects.filter(access_code=self.access_code).exists():
                self.access_code = generate_event_access_code()
        super().save(*args, **kwargs)

    @property
    def is_pin_protected(self):
        return bool(self.pin_code and self.pin_code.strip())

    def verify_pin(self, pin):
        if not self.is_pin_protected:
            return True
        return str(self.pin_code).strip() == str(pin).strip()


class EventPhoto(models.Model):
    event = models.ForeignKey(
        SharedEvent,
        on_delete=models.CASCADE,
        related_name='photos'
    )
    image = models.ImageField(upload_to='event_photos/%Y/%m/%d/')
    original_filename = models.CharField(max_length=255, blank=True)
    file_size = models.BigIntegerField(default=0, help_text="File size in bytes")
    category_tag = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Tag like Ceremony, Reception, Stage, Candid, Dinner"
    )
    caption = models.CharField(max_length=255, blank=True)
    downloads_count = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f"Photo {self.id} - {self.original_filename or self.event.title}"


# =============================================================================
# 2. Enterprise Client Gallery & Media Delivery System
# =============================================================================

class ExpiredStatus:
    def __init__(self, val: bool):
        self._val = bool(val)
    def __bool__(self):
        return self._val
    def __call__(self):
        return self._val
    def __repr__(self):
        return repr(self._val)
    def __eq__(self, other):
        return self._val == bool(other)
    def __hash__(self):
        return hash(self._val)


class GalleryQuerySet(models.QuerySet):
    def active(self):
        """Galleries that have either no expiration date or whose expiration is in the future."""
        now = timezone.now()
        return self.filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))

    def expired(self):
        """Galleries whose expiration date has passed."""
        now = timezone.now()
        return self.filter(expires_at__isnull=False, expires_at__lte=now)


class GalleryManager(models.Manager):
    def get_queryset(self):
        return GalleryQuerySet(self.model, using=self._db)

    def active(self):
        return self.get_queryset().active()

    def expired(self):
        return self.get_queryset().expired()


class Gallery(models.Model):
    objects = GalleryManager()
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('delivered', 'Delivered'),
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]

    VISIBILITY_CHOICES = [
        ('public', 'Public'),
        ('private', 'Private (Invite Only)'),
        ('password_protected', 'Password Protected'),
    ]

    TEMPLATE_CHOICES = [
        ('editorial', 'Editorial High-Fashion'),
        ('masonry', 'Dynamic Masonry Mosaic'),
        ('slideshow', 'Full-bleed Cinematic Slideshow'),
        ('filmstrip', 'Horizontal Filmstrip Flow'),
        ('minimal', 'Fine Art Minimal White'),
        ('columns', 'Multi-Column Grid'),
        ('grid', 'Classic Balanced Grid'),
        ('cinematic', 'Widescreen Cinematic'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    photographer = models.ForeignKey(
        PhotographerProfile,
        on_delete=models.CASCADE,
        related_name='galleries'
    )
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    client_name = models.CharField(max_length=255, blank=True, default='')
    client_email = models.EmailField(blank=True, null=True)
    client_phone = models.CharField(max_length=40, blank=True, default='')
    event_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    template_id = models.CharField(max_length=50, choices=TEMPLATE_CHOICES, default='editorial')
    template_banners = models.JSONField(
        default=dict, blank=True,
        help_text="Dictionary mapping templateId to hero banner URL, e.g. {'editorial': 'https://...', 'cinematic': 'https://...'}"
    )
    masonry_banner_images = models.JSONField(
        default=list, blank=True,
        help_text="Array of up to 4 image URLs for the Masonry mosaic header"
    )
    
    cover_media = models.ForeignKey(
        'Media',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    cover_image_url = models.CharField(max_length=512, blank=True, default='')
    cover_image = models.URLField(max_length=750, blank=True, default='')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    visibility = models.CharField(max_length=30, choices=VISIBILITY_CHOICES, default='public')
    sections = models.JSONField(default=list, blank=True)

    # Cryptographically secure sharing
    share_token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_secure_share_token
    )
    is_password_protected = models.BooleanField(default=False)
    password = models.CharField(max_length=128, blank=True, null=True)
    download_pin = models.CharField(max_length=20, blank=True, default='')
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="UTC timestamp when client viewing access expires. NULL means permanent access (never expires)."
    )

    # Feature Toggles
    downloads_enabled = models.BooleanField(default=True)
    allow_downloads = models.BooleanField(default=True)
    allow_favorites = models.BooleanField(default=True)
    face_search_enabled = models.BooleanField(default=True)

    # Analytics & Engagements
    views_count = models.PositiveIntegerField(default=0)
    downloads_count = models.PositiveIntegerField(default=0)
    favorites_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['photographer', 'created_at']),
            models.Index(fields=['share_token']),
            models.Index(fields=['slug']),
            models.Index(fields=['status', 'visibility']),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.share_token:
            self.share_token = generate_secure_share_token()
            while Gallery.objects.filter(share_token=self.share_token).exists():
                self.share_token = generate_secure_share_token()

        if not self.slug:
            base_slug = slugify(self.title) or "gallery"
            unique_slug = f"{base_slug}-{secrets.token_hex(3)}"
            while Gallery.objects.filter(slug=unique_slug).exists():
                unique_slug = f"{base_slug}-{secrets.token_hex(3)}"
            self.slug = unique_slug

        if self.password:
            self.is_password_protected = True

        super().save(*args, **kwargs)

    def set_access_password(self, raw_password):
        if raw_password:
            self.password = make_password(raw_password)
            self.visibility = 'password_protected'
            self.is_password_protected = True
        else:
            self.password = None
            self.is_password_protected = False
            if self.visibility == 'password_protected':
                self.visibility = 'public'

    def check_access_password(self, raw_password):
        if not self.password:
            return True
        if not raw_password:
            return False
        return check_password(raw_password, self.password)

    @property
    def is_expired(self):
        val = False
        if self.expires_at:
            val = timezone.now() > self.expires_at
        return ExpiredStatus(val)

    @property
    def sections_list(self):
        """Returns ordered list of custom section names."""
        secs = list(self.section_items.values_list('title', flat=True).order_by('order', 'id'))
        if secs:
            return secs
        if self.sections and isinstance(self.sections, list) and len(self.sections) > 0:
            return self.sections
        distinct_secs = list(
            self.media_items.filter(deleted_at__isnull=True)
            .exclude(section_title='')
            .values_list('section_title', flat=True)
            .distinct()
        )
        return distinct_secs or ['HIGHLIGHTS']

    def revoke_share_token(self):
        """Generates a new share token, invalidating any previously distributed links."""
        self.share_token = generate_secure_share_token()
        while Gallery.objects.filter(share_token=self.share_token).exists():
            self.share_token = generate_secure_share_token()
        self.save(update_fields=['share_token'])
        return self.share_token

    @property
    def media(self):
        return self.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at')


class GallerySection(models.Model):
    """
    Custom Sections / Event Parts inside a Gallery (e.g. CEREMONY, RECEPTION, PORTRAITS).
    """
    id = models.BigAutoField(primary_key=True)
    gallery = models.ForeignKey(
        Gallery, on_delete=models.CASCADE, related_name='section_items', db_index=True
    )
    title = models.CharField(max_length=120)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']
        unique_together = ('gallery', 'title')

    def __str__(self):
        return f"{self.gallery.title} — {self.title}"


class Media(models.Model):
    MEDIA_TYPE_CHOICES = [
        ('photo', 'Photo'),
        ('video', 'Video'),
    ]

    PROCESSING_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('ready', 'Ready'),
        ('failed', 'Failed'),
    ]

    UPLOAD_STATUS_CHOICES = [
        ('reserved', 'Reserved'),
        ('uploading', 'Uploading'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    photographer = models.ForeignKey(
        PhotographerProfile,
        on_delete=models.CASCADE,
        related_name='media_items'
    )
    gallery = models.ForeignKey(
        Gallery,
        on_delete=models.CASCADE,
        related_name='media_items'
    )
    section = models.ForeignKey(
        GallerySection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='media_items'
    )
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPE_CHOICES, default='photo')
    title = models.CharField(max_length=255, blank=True, default='')
    caption = models.TextField(blank=True, default='')
    section_title = models.CharField(max_length=100, default='Highlights', db_index=True)
    file = models.FileField(upload_to='galleries/%Y/%m/', null=True, blank=True)
    original_filename = models.CharField(max_length=255)

    # Object storage keys (decoupled from storage provider/CDN URLs)
    storage_key = models.CharField(max_length=512, db_index=True)
    original_storage_key = models.CharField(max_length=512, blank=True, null=True)
    preview_storage_key = models.CharField(max_length=512, blank=True, null=True)
    thumbnail_storage_key = models.CharField(max_length=512, blank=True, null=True)

    # Video attributes
    duration = models.CharField(max_length=50, blank=True, null=True, help_text="e.g. '02:45'")
    video_embed_url = models.URLField(blank=True, null=True)
    video_stream_key = models.CharField(max_length=512, blank=True, null=True)

    mime_type = models.CharField(max_length=100, default='image/jpeg')
    file_extension = models.CharField(max_length=20, default='.jpg')
    file_size = models.BigIntegerField(default=0, help_text="Exact file size in bytes")
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    aspect_ratio = models.FloatField(null=True, blank=True)

    # Layout sequencing & flags
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    is_cover = models.BooleanField(default=False)
    is_favorite = models.BooleanField(default=False, db_index=True)

    processing_status = models.CharField(max_length=20, choices=PROCESSING_STATUS_CHOICES, default='ready')
    upload_status = models.CharField(max_length=20, choices=UPLOAD_STATUS_CHOICES, default='completed')
    downloads_count = models.PositiveIntegerField(default=0)
    views_count = models.PositiveIntegerField(default=0)
    favorites_count = models.PositiveIntegerField(default=0)

    # Soft deletion
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', '-created_at', 'id']
        indexes = [
            # Composite cursor pagination indexes for O(1) keyset seeking
            models.Index(fields=['gallery', 'display_order', '-created_at', 'id']),
            models.Index(fields=['gallery', 'section_title', 'display_order', '-created_at', 'id']),
            models.Index(fields=['gallery', 'is_favorite', 'display_order', '-created_at', 'id']),

            models.Index(fields=['gallery', 'display_order']),
            models.Index(fields=['gallery', 'section_title']),
            models.Index(fields=['gallery', 'created_at']),
            models.Index(fields=['photographer', 'file_size']),
            models.Index(fields=['processing_status']),
            models.Index(fields=['deleted_at']),
        ]

    def __str__(self):
        return f"{self.original_filename} ({self.id})"

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def sort_order(self):
        return self.display_order

    @sort_order.setter
    def sort_order(self, val):
        self.display_order = val


class GalleryAnalyticsEvent(models.Model):
    """
    Real-time telemetry event stream (views, downloads, favorites, shares).
    """
    EVENT_TYPES = (
        ('view', 'Gallery View'),
        ('download', 'Photo or Zip Download'),
        ('favorite', 'Photo Favorited'),
        ('share', 'Gallery Shared'),
    )

    id = models.BigAutoField(primary_key=True)
    gallery = models.ForeignKey(
        Gallery, on_delete=models.CASCADE, related_name='analytics_events', db_index=True
    )
    media = models.ForeignKey(
        Media, on_delete=models.SET_NULL, null=True, blank=True, related_name='analytics_events'
    )
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, db_index=True)
    device = models.CharField(max_length=20, default='desktop')  # desktop, mobile, tablet
    traffic_source = models.CharField(max_length=30, default='direct_link')  # direct_link, social, email, qr_code
    ip_hash = models.CharField(max_length=64, blank=True, db_index=True)
    user_agent = models.TextField(blank=True)
    details = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['gallery', 'event_type', 'created_at']),
        ]

    def __str__(self):
        return f"{self.gallery.title} - {self.event_type} ({self.created_at})"


class GalleryClientAccess(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gallery = models.ForeignKey(
        Gallery,
        on_delete=models.CASCADE,
        related_name='client_accesses'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='gallery_accesses'
    )
    email = models.EmailField(blank=True)
    can_download = models.BooleanField(default=True)
    can_face_search = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('gallery', 'user', 'email')

    def is_valid(self):
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True


class GalleryClientSelection(models.Model):
    """
    Client proofing, favorites, and album selection submissions.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('reviewed', 'Reviewed'),
        ('approved', 'Approved'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gallery = models.ForeignKey(
        Gallery,
        on_delete=models.CASCADE,
        related_name='client_selections'
    )
    client_email = models.EmailField()
    client_name = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    selected_media = models.ManyToManyField(
        Media,
        related_name='client_selections',
        blank=True
    )
    selected_count = models.PositiveIntegerField(default=0)
    client_notes = models.TextField(blank=True, default='')
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Selection by {self.client_email} for {self.gallery.title} ({self.selected_count} items)"


class FaceEmbedding(models.Model):
    """
    Stores face embedding vectors and bounding boxes strictly associated with a gallery.
    Internal backend data structure - never exposed directly in REST responses.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    media = models.ForeignKey(
        Media,
        on_delete=models.CASCADE,
        related_name='face_embeddings'
    )
    gallery = models.ForeignKey(
        Gallery,
        on_delete=models.CASCADE,
        related_name='face_embeddings'
    )
    embedding = models.JSONField(help_text="Internal 128-dimensional normalized vector array")
    bounding_box = models.JSONField(null=True, blank=True, help_text="{'x': int, 'y': int, 'w': int, 'h': int}")
    confidence = models.FloatField(default=1.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['gallery']),
            models.Index(fields=['media']),
        ]

    def __str__(self):
        return f"Face in {self.media_id}"


class UploadReservation(models.Model):
    """
    Guarantees atomic storage quota allocation across concurrent in-flight uploads.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('committed', 'Committed'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    photographer = models.ForeignKey(
        PhotographerProfile,
        on_delete=models.CASCADE,
        related_name='upload_reservations'
    )
    gallery = models.ForeignKey(
        Gallery,
        on_delete=models.CASCADE,
        related_name='upload_reservations'
    )
    reserved_bytes = models.BigIntegerField(help_text="Estimated upload size")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    expires_at = models.DateTimeField(help_text="Auto-expires if upload not finalized")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['photographer', 'status']),
            models.Index(fields=['expires_at']),
        ]

    def is_expired(self):
        return timezone.now() > self.expires_at


class BulkDownloadJob(models.Model):
    """
    Tracks asynchronous bulk ZIP generation for master or selective downloads.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('ready', 'Ready'),
        ('failed', 'Failed'),
        ('expired', 'Expired'),
    ]

    DOWNLOAD_TYPE_CHOICES = [
        ('master_all', 'Master All'),
        ('selected_subset', 'Selected Subset'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gallery = models.ForeignKey(
        Gallery,
        on_delete=models.CASCADE,
        related_name='bulk_download_jobs'
    )
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    download_type = models.CharField(max_length=30, choices=DOWNLOAD_TYPE_CHOICES, default='master_all')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    archive_storage_key = models.CharField(max_length=512, blank=True, null=True)
    selected_count = models.PositiveIntegerField(default=0)
    file_size = models.BigIntegerField(default=0)
    progress_percent = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class StorageAuditLog(models.Model):
    photographer = models.ForeignKey(
        PhotographerProfile,
        on_delete=models.CASCADE,
        related_name='storage_audit_logs'
    )
    gallery = models.ForeignKey(
        Gallery,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    action = models.CharField(max_length=50)  # e.g. UPLOAD, DELETE, SHARE_GENERATE, DOWNLOAD, PROOF_SUBMIT
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['photographer', 'action']),
            models.Index(fields=['timestamp']),
        ]


# Backward & REST compatibility alias
MediaItem = Media


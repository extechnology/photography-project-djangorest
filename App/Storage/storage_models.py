import uuid
import secrets
from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
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

class Gallery(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]

    VISIBILITY_CHOICES = [
        ('public', 'Public'),
        ('private', 'Private (Invite Only)'),
        ('password_protected', 'Password Protected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    photographer = models.ForeignKey(
        PhotographerProfile,
        on_delete=models.CASCADE,
        related_name='galleries'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    cover_media = models.ForeignKey(
        'Media',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='published')
    visibility = models.CharField(max_length=30, choices=VISIBILITY_CHOICES, default='public')

    # Cryptographically secure sharing
    share_token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generate_secure_share_token
    )
    password = models.CharField(max_length=128, blank=True, null=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    # Feature Toggles
    downloads_enabled = models.BooleanField(default=True)
    face_search_enabled = models.BooleanField(default=True)

    # Analytics
    views_count = models.PositiveIntegerField(default=0)
    downloads_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['photographer', 'created_at']),
            models.Index(fields=['share_token']),
            models.Index(fields=['status', 'visibility']),
        ]

    def __str__(self):
        return f"{self.title} ({self.id})"

    def save(self, *args, **kwargs):
        if not self.share_token:
            self.share_token = generate_secure_share_token()
            while Gallery.objects.filter(share_token=self.share_token).exists():
                self.share_token = generate_secure_share_token()
        super().save(*args, **kwargs)

    def set_access_password(self, raw_password):
        if raw_password:
            self.password = make_password(raw_password)
            self.visibility = 'password_protected'
        else:
            self.password = None
            if self.visibility == 'password_protected':
                self.visibility = 'public'

    def check_access_password(self, raw_password):
        if not self.password:
            return True
        if not raw_password:
            return False
        return check_password(raw_password, self.password)

    def is_expired(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    def revoke_share_token(self):
        """Generates a new share token, invalidating any previously distributed links."""
        self.share_token = generate_secure_share_token()
        while Gallery.objects.filter(share_token=self.share_token).exists():
            self.share_token = generate_secure_share_token()
        self.save(update_fields=['share_token'])
        return self.share_token


class Media(models.Model):
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
    original_filename = models.CharField(max_length=255)

    # Object storage keys (decoupled from storage provider/CDN URLs)
    storage_key = models.CharField(max_length=512, db_index=True)
    original_storage_key = models.CharField(max_length=512, blank=True, null=True)
    preview_storage_key = models.CharField(max_length=512, blank=True, null=True)
    thumbnail_storage_key = models.CharField(max_length=512, blank=True, null=True)

    mime_type = models.CharField(max_length=100, default='image/jpeg')
    file_extension = models.CharField(max_length=20, default='.jpg')
    file_size = models.BigIntegerField(default=0, help_text="Exact file size in bytes")
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration = models.FloatField(null=True, blank=True, help_text="Duration in seconds if video")

    processing_status = models.CharField(max_length=20, choices=PROCESSING_STATUS_CHOICES, default='ready')
    upload_status = models.CharField(max_length=20, choices=UPLOAD_STATUS_CHOICES, default='completed')
    downloads_count = models.PositiveIntegerField(default=0)

    # Soft deletion
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
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
    # 128 or 512 dimensional normalized float array
    embedding = models.JSONField(help_text="Internal vector array representation")
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
    Tracks asynchronous bulk ZIP generation.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('ready', 'Ready'),
        ('failed', 'Failed'),
        ('expired', 'Expired'),
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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    archive_storage_key = models.CharField(max_length=512, blank=True, null=True)
    selected_count = models.PositiveIntegerField(default=0)
    file_size = models.BigIntegerField(default=0)
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
    action = models.CharField(max_length=50)  # e.g. UPLOAD, DELETE, SHARE_GENERATE, DOWNLOAD
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['photographer', 'action']),
            models.Index(fields=['timestamp']),
        ]

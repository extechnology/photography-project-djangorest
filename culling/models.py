import os
import shutil
import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def culling_staging_upload_path(instance, filename):
    clean_name = os.path.basename(filename)
    return f"culling_staging/{instance.session.id}/{uuid.uuid4().hex}_{clean_name}"


culling_upload_path = culling_staging_upload_path


class CullingPricingTier(models.Model):
    """
    Dynamic pricing plans for AI Culling shoots.
    Admin-manageable with custom photo limits and pricing.
    """
    id = models.CharField(
        max_length=64, 
        primary_key=True,
        help_text="Unique tier slug/id, e.g. tier_starter, tier_pro, tier_wedding"
    )
    name = models.CharField(max_length=120, help_text="e.g. Starter Shoot, Studio Event")
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("149.00"), help_text="Price in INR")
    price_inr = models.PositiveIntegerField(default=149, help_text="Price in INR integer fallback")
    photos_limit = models.PositiveIntegerField(
        default=300,
        help_text="Maximum photos permitted in one batch. Use 999999 for unlimited."
    )
    badge = models.CharField(max_length=100, blank=True, default="", help_text="e.g. Up to 300 Photos")
    description = models.TextField(blank=True, default="")
    features = models.JSONField(
        default=list, 
        blank=True,
        help_text="List of feature bullet strings displayed in UI"
    )
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = "culling_pricing_tier"
        ordering = ['display_order', 'price']

    def save(self, *args, **kwargs):
        if self.price is not None and not self.price_inr:
            self.price_inr = int(self.price)
        elif self.price_inr is not None and (self.price is None or self.price == Decimal("149.00")):
            self.price = Decimal(str(self.price_inr))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} (Max {self.photos_limit} photos - ₹{self.price})"


class CullingSession(models.Model):
    """
    A single culling batch session tied to an upfront paid plan and photographer storage.
    """
    STATUS_CHOICES = (
        ("staging", "Staging / Uploading"),
        ("draft", "Draft / Staging"),
        ("analyzed", "Analyzed & Curated"),
        ("moved_to_gallery", "Moved to Gallery"),
        ("discarded", "Discarded / Purged"),
        ("paid", "Paid & Unlocked"),
        ("active", "Active Batch In Progress"),
        ("completed", "Completed (Moved to Gallery)"),
    )

    class Status(models.TextChoices):
        STAGING = 'staging', _('Staging / Uploading')
        DRAFT = 'draft', _('Draft / Staging')
        ANALYZED = 'analyzed', _('Analyzed & Curated')
        MOVED_TO_GALLERY = 'moved_to_gallery', _('Moved to Gallery')
        DISCARDED = 'discarded', _('Discarded & Storage Cleared')
        PAID = 'paid', _('Paid & Unlocked')
        ACTIVE = 'active', _('Active Batch In Progress')
        COMPLETED = 'completed', _('Completed (Moved to Gallery)')

    id = models.CharField(max_length=100, primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='culling_sessions'
    )
    tier = models.ForeignKey(
        CullingPricingTier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sessions'
    )
    title = models.CharField(max_length=255, default="AI Smart Cull Session")
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="staging",
        db_index=True
    )
    is_paid = models.BooleanField(default=True)
    paid_amount_inr = models.PositiveIntegerField(default=0)
    razorpay_order_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    razorpay_payment_id = models.CharField(max_length=128, blank=True, default="")
    razorpay_signature = models.CharField(max_length=255, blank=True, default="")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    photo_count = models.PositiveIntegerField(default=0)
    total_photos = models.PositiveIntegerField(default=0)
    keeper_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    total_duplicates = models.PositiveIntegerField(default=0)
    wasted_bytes = models.BigIntegerField(default=0)
    total_bytes = models.BigIntegerField(default=0)
    total_clusters = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "culling_session"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        user_id = getattr(self.user, 'email', None) or getattr(self.user, 'username', str(self.user_id))
        return f"Cull Session {self.id} - {user_id} ({self.status})"

    def purge_staging_storage(self):
        """
        Recursively deletes all physical files staged in media/culling_staging/<session_id>/
        """
        paths = [
            os.path.join(settings.MEDIA_ROOT, 'culling_staging', str(self.id)),
            os.path.join(settings.MEDIA_ROOT, 'culling_staging', str(self.user_id), str(self.id)),
        ]
        for staging_dir in paths:
            if os.path.exists(staging_dir):
                try:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"Failed to remove staging directory {staging_dir}: {e}")

        # Bulk delete photo records
        self.photos.all().delete()
        self.clusters.all().delete()


class CullingStagingPhoto(models.Model):
    """
    Individual photo stored temporarily in staging disk for analysis.
    """
    STATUS_CHOICES = (
        ("keep", "Keep"),
        ("discard", "Discard"),
    )

    class PhotoStatus(models.TextChoices):
        KEEP = 'keep', _('Keep')
        DISCARD = 'discard', _('Discard')

    id = models.CharField(max_length=128, primary_key=True, default=uuid.uuid4)
    session = models.ForeignKey(
        CullingSession,
        on_delete=models.CASCADE,
        related_name='photos'
    )
    file = models.FileField(upload_to=culling_upload_path, max_length=512)
    name = models.CharField(max_length=255, blank=True, default="")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)
    file_size_bytes = models.BigIntegerField(default=0)
    size_mb = models.FloatField(default=0.0)

    sharpness_score = models.FloatField(default=80.0)
    raw_sharpness_variance = models.FloatField(default=100.0)
    perceptual_hash = models.CharField(max_length=64, blank=True, default="")
    hash = models.CharField(max_length=64, blank=True, default="")

    cluster_id = models.CharField(max_length=128, blank=True, null=True, default="", db_index=True)
    is_best_pick = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="keep",
        db_index=True
    )
    similarity_with_winner = models.FloatField(null=True, blank=True)
    similarity_with_best = models.FloatField(default=0.0, null=True, blank=True)

    face_analysis = models.JSONField(
        default=dict,
        blank=True,
        help_text="AI-detected facial analysis: landmarks, eyes, lips, expression data"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "culling_photo"
        ordering = ['id']

    def save(self, *args, **kwargs):
        if not self.original_filename and self.name:
            self.original_filename = self.name
        elif not self.name and self.original_filename:
            self.name = self.original_filename
        if not self.file_size_bytes and self.size_bytes:
            self.file_size_bytes = self.size_bytes
        elif not self.size_bytes and self.file_size_bytes:
            self.size_bytes = self.file_size_bytes
        if not self.perceptual_hash and self.hash:
            self.perceptual_hash = self.hash
        elif not self.hash and self.perceptual_hash:
            self.hash = self.perceptual_hash
        if self.similarity_with_winner is not None and not self.similarity_with_best:
            self.similarity_with_best = self.similarity_with_winner
        elif self.similarity_with_best is not None and self.similarity_with_winner is None:
            self.similarity_with_winner = self.similarity_with_best
        if self.file_size_bytes > 0 and not self.size_mb:
            self.size_mb = round(self.file_size_bytes / (1024 * 1024), 2)
        super().save(*args, **kwargs)

    @property
    def uploaded_at(self):
        return self.created_at

    def __str__(self):
        return f"{self.original_filename or self.name} [{self.status}]"


# Alias for backward compatibility
CullingPhoto = CullingStagingPhoto


class CullingCluster(models.Model):
    """
    Burst group of duplicate photos identified by AI.
    """
    id = models.CharField(max_length=128, primary_key=True, default=uuid.uuid4)
    session = models.ForeignKey(
        CullingSession,
        on_delete=models.CASCADE,
        related_name='clusters'
    )
    title = models.CharField(max_length=100, default="Burst Set")
    average_similarity = models.FloatField(default=90.0)
    best_pick_item_id = models.CharField(max_length=128, blank=True, default="")
    best_pick_id = models.CharField(max_length=128, blank=True, default="")
    photo_ids = models.JSONField(default=list)
    total_photos = models.PositiveIntegerField(default=1)
    duplicates_count = models.PositiveIntegerField(default=0)
    wasted_bytes = models.BigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "culling_cluster"
        ordering = ['id']

    def save(self, *args, **kwargs):
        if not self.best_pick_item_id and self.best_pick_id:
            self.best_pick_item_id = self.best_pick_id
        elif not self.best_pick_id and self.best_pick_item_id:
            self.best_pick_id = self.best_pick_item_id
        super().save(*args, **kwargs)

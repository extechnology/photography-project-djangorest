import os
import shutil
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def culling_upload_path(instance, filename):
    """
    Staging storage path: media/culling_staging/<user_id>/<session_id>/<filename>
    """
    clean_name = os.path.basename(filename)
    return f"culling_staging/{instance.session.user_id}/{instance.session.id}/{clean_name}"


class CullingPricingTier(models.Model):
    """
    Dynamic pricing plans managed in Django Admin.
    """
    id = models.CharField(
        max_length=64, 
        primary_key=True,
        help_text="Unique tier slug/id, e.g. cull_single_300, cull_wedding_1200, cull_pro_unlimited"
    )
    name = models.CharField(max_length=120)
    price_inr = models.PositiveIntegerField(help_text="Price in INR, e.g. 149")
    photos_limit = models.PositiveIntegerField(
        help_text="Maximum photos permitted in one session. Use 999999 for unlimited."
    )
    badge = models.CharField(max_length=60, blank=True, default="")
    description = models.TextField(blank=True, default="")
    features = models.JSONField(
        default=list, 
        blank=True,
        help_text="List of feature bullet strings displayed in UI"
    )
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'photos_limit']

    def __str__(self):
        return f"{self.name} (Max {self.photos_limit} photos - ₹{self.price_inr})"


class CullingSession(models.Model):
    """
    A single culling batch session tied to an upfront paid plan and photographer storage.
    """
    class Status(models.TextChoices):
        PENDING_PAYMENT = 'pending_payment', _('Pending Payment')
        ACTIVE = 'active', _('Active Batch In Progress')
        COMPLETED = 'completed', _('Completed (Moved to Gallery)')
        EXPORTED = 'exported', _('Exported via ZIP')
        DISCARDED = 'discarded', _('Discarded & Storage Cleared')
        EXPIRED = 'expired', _('Expired / Auto-Purged')

    id = models.CharField(max_length=64, primary_key=True, default=uuid.uuid4)
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
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
        db_index=True
    )
    is_paid = models.BooleanField(default=False)
    paid_amount_inr = models.PositiveIntegerField(default=0)
    razorpay_order_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    razorpay_payment_id = models.CharField(max_length=128, blank=True, default="")

    total_photos = models.PositiveIntegerField(default=0)
    total_bytes = models.BigIntegerField(default=0)
    total_clusters = models.PositiveIntegerField(default=0)
    total_duplicates = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"Cull Session {self.id} - User {self.user_id} [{self.status}]"

    def purge_staging_storage(self):
        """
        Recursively deletes all physical files staged in media/culling_staging/<user_id>/<session_id>/
        """
        staging_dir = os.path.join(
            settings.MEDIA_ROOT, 
            'culling_staging', 
            str(self.user_id), 
            str(self.id)
        )
        if os.path.exists(staging_dir):
            try:
                shutil.rmtree(staging_dir)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to remove staging directory {staging_dir}: {e}")

        # Bulk delete photo records
        self.photos.all().delete()
        self.clusters.all().delete()


class CullingPhoto(models.Model):
    """
    Individual image analyzed inside a culling session.
    """
    class PhotoStatus(models.TextChoices):
        KEEP = 'keep', _('Keep')
        DISCARD = 'discard', _('Discard')

    id = models.CharField(max_length=128, primary_key=True)
    session = models.ForeignKey(
        CullingSession,
        on_delete=models.CASCADE,
        related_name='photos'
    )
    file = models.FileField(upload_to=culling_upload_path, max_length=512)
    name = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField(default=0)
    size_mb = models.FloatField(default=0.0)

    sharpness_score = models.FloatField(default=0.0)
    raw_sharpness_variance = models.FloatField(default=0.0)
    cluster_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    is_best_pick = models.BooleanField(default=False)
    status = models.CharField(
        max_length=12,
        choices=PhotoStatus.choices,
        default=PhotoStatus.KEEP,
        db_index=True
    )
    similarity_with_best = models.FloatField(default=0.0)
    hash = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['cluster_id', '-sharpness_score']

    def __str__(self):
        return f"{self.name} [{self.status}] (Score: {self.sharpness_score})"


class CullingCluster(models.Model):
    """
    Duplicate group / burst cluster information.
    """
    id = models.CharField(max_length=128, primary_key=True)
    session = models.ForeignKey(
        CullingSession,
        on_delete=models.CASCADE,
        related_name='clusters'
    )
    best_pick_id = models.CharField(max_length=128, blank=True, default="")
    photo_ids = models.JSONField(default=list)
    average_similarity = models.FloatField(default=0.0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

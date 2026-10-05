import uuid
from django.db import models
from django.conf import settings


class CullingPricingTier(models.TextChoices):
    SINGLE_SHOOT = 'cull_single_300', 'Single Shoot Batch (Up to 300) - ₹149'
    WEDDING_EVENT = 'cull_wedding_1200', 'Full Event / Wedding (Up to 1,200) - ₹249'
    STUDIO_PRO = 'cull_pro_unlimited', 'Studio Pro Unlimited - ₹499'


TIER_LIMITS = {
    'cull_single_300': {'price': 149, 'max_photos': 300},
    'cull_wedding_1200': {'price': 249, 'max_photos': 1200},
    'cull_pro_unlimited': {'price': 499, 'max_photos': 999999},
}


class CullingSession(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft (Awaiting Payment)'),
        ('paid', 'Paid & Processing'),
        ('analyzing', 'AI Analyzing'),
        ('ready', 'Cull Ready For Review'),
        ('completed', 'Completed & Moved to Gallery'),
        ('archived', 'Archived'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.CharField(max_length=120, unique=True, db_index=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='legacy_culling_sessions'
    )
    title = models.CharField(max_length=255, default='AI Shoot Culling')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    # UPFRONT PAYMENT FIELDS (Enforced before upload/cull)
    is_paid = models.BooleanField(default=False, db_index=True)
    paid_tier = models.CharField(
        max_length=50,
        choices=CullingPricingTier.choices,
        default=CullingPricingTier.SINGLE_SHOOT
    )
    max_photos_allowed = models.PositiveIntegerField(default=300)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=10, default='INR')
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # Metrics
    total_photos = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    keeper_count = models.PositiveIntegerField(default=0)
    total_saved_bytes = models.BigIntegerField(default=0)
    progress_percentage = models.PositiveIntegerField(default=0)
    progress_status_text = models.CharField(max_length=255, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'App'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.session_key:
            self.session_key = str(self.id)
        super().save(*args, **kwargs)

    def __str__(self):
        paid_label = "PAID" if self.is_paid else "UNPAID"
        return f"[{paid_label}] {self.title} ({self.total_photos} photos) - {self.user}"


class CullingClusterGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        CullingSession,
        on_delete=models.CASCADE,
        related_name='clusters'
    )
    cluster_number = models.PositiveIntegerField(default=1)
    average_similarity = models.FloatField(default=0.0)
    best_pick_item = models.ForeignKey(
        'CullingItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='won_clusters'
    )
    total_photos = models.PositiveIntegerField(default=0)
    duplicates_count = models.PositiveIntegerField(default=0)
    wasted_bytes = models.BigIntegerField(default=0)

    class Meta:
        app_label = 'App'
        ordering = ['cluster_number']

    @property
    def items(self):
        return self.photos

    def __str__(self):
        return f"Cluster #{self.cluster_number} (Session {self.session_id}) - {self.total_photos} photos"


def culling_upload_path(instance, filename):
    return f"culling_staging/{instance.session.user.id}/{instance.session.id}/{filename}"


def culling_thumb_path(instance, filename):
    return f"culling_staging/{instance.session.user.id}/{instance.session.id}/thumbs/{filename}"


class CullingItem(models.Model):
    STATUS_CHOICES = [
        ('keep', 'Keep (Approved Winner)'),
        ('discard', 'Discard (Inferior Duplicate)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        CullingSession,
        on_delete=models.CASCADE,
        related_name='items'
    )
    cluster = models.ForeignKey(
        CullingClusterGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='photos'
    )

    image = models.ImageField(upload_to=culling_upload_path, blank=True, null=True)
    thumbnail = models.ImageField(upload_to=culling_thumb_path, blank=True, null=True)
    original_filename = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField(default=0)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)

    # AI Visual Metrics
    dhash_hex = models.CharField(max_length=64, blank=True, db_index=True)
    sharpness_score = models.FloatField(default=0.0)  # Laplacian edge variance
    similarity_with_winner = models.FloatField(default=0.0)

    # Status
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='keep')
    is_best_pick = models.BooleanField(default=False)
    assigned_category = models.CharField(max_length=100, default='HIGHLIGHTS')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'App'
        ordering = ['-sharpness_score', 'created_at']

    def __init__(self, *args, **kwargs):
        # Backward-compatible parameter mappings
        if 'file' in kwargs and 'image' not in kwargs:
            kwargs['image'] = kwargs.pop('file')
        if 'file_size_bytes' in kwargs and 'size_bytes' not in kwargs:
            kwargs['size_bytes'] = kwargs.pop('file_size_bytes')
        if 'dhash_string' in kwargs and 'dhash_hex' not in kwargs:
            kwargs['dhash_hex'] = kwargs.pop('dhash_string')
        super().__init__(*args, **kwargs)

    @property
    def file(self):
        return self.image

    @file.setter
    def file(self, val):
        self.image = val

    @property
    def file_size_bytes(self):
        return self.size_bytes

    @file_size_bytes.setter
    def file_size_bytes(self, val):
        self.size_bytes = val

    @property
    def dhash_string(self):
        if not self.dhash_hex:
            return ''
        if len(self.dhash_hex) == 16:
            try:
                return ''.join(f"{int(c, 16):04b}" for c in self.dhash_hex)
            except ValueError:
                return self.dhash_hex
        return self.dhash_hex

    @dhash_string.setter
    def dhash_string(self, val):
        if val and len(val) == 64 and all(c in '01' for c in val):
            try:
                self.dhash_hex = f"{int(val, 2):016x}"
                return
            except ValueError:
                pass
        self.dhash_hex = val or ''

    def __str__(self):
        return f"{self.original_filename} ({self.status}) - Score: {self.sharpness_score:.1f}"


class CullingPaymentOrder(models.Model):
    STATUS_CHOICES = [
        ('created', 'Created'),
        ('verified', 'Verified'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    session = models.ForeignKey(CullingSession, on_delete=models.CASCADE, related_name='payments')
    razorpay_order_id = models.CharField(max_length=100, unique=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)
    tier_name = models.CharField(max_length=100, default='Single Shoot Batch')
    amount_inr = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paisa = models.PositiveIntegerField()
    currency = models.CharField(max_length=10, default='INR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'App'

    def __str__(self):
        return f"Order {self.razorpay_order_id} - ₹{self.amount_inr} ({self.status})"

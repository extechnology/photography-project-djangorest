import uuid
from django.db import models
from django.utils import timezone


def default_allowed_templates():
    return ["editorial", "masonry", "cinematic", "minimal"]


def default_features():
    return [
        "Editorial, Masonry & Minimal layouts",
        "4K Video Embedding & Direct Streaming",
        "AI-Powered Face Discovery",
        "Custom Studio Typography & Watermarking",
        "Selective Client Proofing & Downloads"
    ]


# =============================================================================
# 1. Studio Plan Model (Configurable Tiers)
# =============================================================================

class Plan(models.Model):
    TIER_CHOICES = [
        ('standard', 'Standard'),
        ('premium', 'Premium Elite'),
        ('custom', 'Custom'),
    ]

    CYCLE_CHOICES = [
        ('quarterly', 'Quarterly (3 Months)'),
        ('annual', 'Annual (1 Year)'),
        ('monthly', 'Monthly'),
    ]

    TAG_TYPE_CHOICES = [
        ('default', 'Default'),
        ('popular', 'Popular'),
        ('current', 'Current'),
    ]

    id = models.CharField(max_length=50, primary_key=True, help_text="e.g. 'plan-standard-3m', 'plan-standard-1y'")
    name = models.CharField(max_length=100)
    subtitle = models.CharField(max_length=255, blank=True, default='')
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, default='standard')
    billing_cycle = models.CharField(max_length=20, choices=CYCLE_CHOICES, default='quarterly')
    duration_months = models.PositiveIntegerField(default=3)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    original_monthly_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=10, default='INR')
    image_storage_gb = models.PositiveIntegerField(default=200)
    video_storage_gb = models.PositiveIntegerField(default=10)
    storage_limit_bytes = models.BigIntegerField(default=225485783040)
    tag = models.CharField(max_length=50, blank=True, default='')
    tag_type = models.CharField(max_length=20, choices=TAG_TYPE_CHOICES, default='default')
    cta_text = models.CharField(max_length=100, default='Choose Plan')
    features = models.JSONField(default=list)
    allowed_templates = models.JSONField(default=default_allowed_templates, help_text="List of allowed gallery layouts for this tier")
    allowed_portfolio_templates = models.JSONField(default=default_allowed_templates, help_text="List of allowed portfolio showcase layouts")
    max_galleries = models.PositiveIntegerField(default=0, help_text="Max active client galleries (0 for unlimited)")
    gallery_expiry_days = models.PositiveIntegerField(default=0, help_text="Gallery link/access validity in days (0 for unlimited)")
    face_search_enabled = models.BooleanField(default=True, help_text="Whether AI face search/discovery is enabled")
    max_events = models.PositiveIntegerField(default=0, help_text="Max shared events allowed in event section (0 for unlimited)")
    max_portfolio_posts = models.PositiveIntegerField(default=0, help_text="Max showcase portfolio posts (0 for unlimited)")
    can_upgrade_storage = models.BooleanField(default=False, help_text="Whether this tier can purchase additional storage upgrades")
    max_upgrade_image_gb = models.PositiveIntegerField(default=0, help_text="Maximum expandable image storage in GB (e.g. 1000 GB)")
    has_full_inquiry_access = models.BooleanField(default=True, help_text="Whether photographer can access all inquiries or only a sampled limit")
    max_inquiries = models.PositiveIntegerField(default=0, help_text="Max client inquiries accessible (0 for all/unlimited)")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'total_price']

    def __str__(self):
        return f"{self.name} ({self.id})"

    def save(self, *args, **kwargs):
        if not self.storage_limit_bytes:
            self.storage_limit_bytes = (self.image_storage_gb + self.video_storage_gb) * 1024 * 1024 * 1024
        super().save(*args, **kwargs)

    @property
    def period_label(self):
        if self.duration_months == 12:
            return "For 01 Year"
        elif self.duration_months == 3:
            return "For 03 Months"
        elif self.duration_months == 1:
            return "For 01 Month"
        return f"For {self.duration_months} Months"

    @property
    def billing_text(self):
        curr_symbol = "₹" if self.currency == 'INR' else "$"
        monthly = int(self.monthly_price) if self.monthly_price == int(self.monthly_price) else self.monthly_price
        total = int(self.total_price) if self.total_price == int(self.total_price) else self.total_price
        cycle_name = "Annually" if self.billing_cycle == 'annual' else ("Quarterly" if self.billing_cycle == 'quarterly' else "Monthly")
        return f"{curr_symbol}{monthly:,} / Month • Billed {cycle_name} ({curr_symbol}{total:,})"


# =============================================================================
# 2. Legacy SubscriptionPlans (Kept for Backward Compatibility)
# =============================================================================

class SubscriptionPlans(models.Model):
    TIER_CHOICES = [
        ('starter', 'Starter'),
        ('pro', 'Pro'),
        ('studio', 'Studio'),
        ('master', 'Master'),
    ]

    CYCLE_CHOICES = [
        ('monthly', 'Monthly'),
        ('annual', 'Annual'),
    ]

    name = models.CharField(max_length=255)
    tier = models.CharField(max_length=50, choices=TIER_CHOICES, default='pro')
    billing_cycle = models.CharField(max_length=20, choices=CYCLE_CHOICES, default='annual')
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=39.00)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=39.00)
    
    storage_limit_bytes = models.BigIntegerField(
        default=128849018880,  # 120 GB
        help_text="Storage limit in bytes"
    )
    max_galleries = models.PositiveIntegerField(
        default=0,
        help_text="Maximum active galleries allowed (0 for unlimited)"
    )
    allowed_templates = models.JSONField(
        default=default_allowed_templates,
        help_text="List of gallery layouts enabled for this tier"
    )
    video_delivery_enabled = models.BooleanField(
        default=True,
        help_text="Whether 4K video asset streaming is enabled"
    )
    face_search_enabled = models.BooleanField(
        default=True,
        help_text="Whether AI face search feature is enabled"
    )
    watermark_customization = models.BooleanField(
        default=True,
        help_text="Whether studio watermarking suite is enabled"
    )
    features_list = models.JSONField(
        default=default_features,
        help_text="Display bullet points for pricing UI"
    )

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.tier.upper()} - ${self.price_monthly}/mo)"


# =============================================================================
# 3. Photographer Subscription & Payment Audit Trails
# =============================================================================

class PhotographerSubscription(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('pending', 'Pending Payment'),
        ('cancelled', 'Cancelled'),
        ('trial', 'Trial'),
        ('past_due', 'Past Due'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    photographer = models.OneToOneField(
        'App.PhotographerProfile',
        on_delete=models.CASCADE,
        related_name='subscription'
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='subscriptions'
    )
    legacy_plan = models.ForeignKey(
        SubscriptionPlans,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='legacy_subscriptions'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    started_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    payment_gateway_ref = models.CharField(max_length=255, blank=True, default='')
    extra_storage_gb = models.PositiveIntegerField(default=0, help_text="For Elite Plan storage add-on")
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        plan_name = self.plan.name if self.plan else (self.legacy_plan.name if self.legacy_plan else "No Plan")
        return f"{self.photographer} - {plan_name} ({self.status})"

    @property
    def start_date(self):
        return self.started_at

    @start_date.setter
    def start_date(self, val):
        self.started_at = val

    @property
    def expiry_date(self):
        return self.expires_at

    @expiry_date.setter
    def expiry_date(self, val):
        self.expires_at = val

    @property
    def days_remaining(self):
        if not self.expires_at:
            return 0
        now = timezone.now()
        if self.expires_at <= now:
            return 0
        return (self.expires_at - now).days

    @property
    def is_active(self):
        if self.status != 'active':
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True

    @property
    def is_currently_active(self):
        return self.is_active

    @property
    def effective_storage_limit_bytes(self):
        from django.conf import settings
        test_storage_limit = getattr(settings, 'TEST_USER_STORAGE_LIMIT_BYTES', None)

        if self.plan and self.plan.storage_limit_bytes:
            base_bytes = self.plan.storage_limit_bytes
            if getattr(self.plan, 'can_upgrade_storage', False) and self.extra_storage_gb > 0:
                base_bytes += (self.extra_storage_gb * 1024 * 1024 * 1024)
            return base_bytes

        if self.legacy_plan and self.legacy_plan.storage_limit_bytes:
            return self.legacy_plan.storage_limit_bytes

        if test_storage_limit:
            return test_storage_limit

        return 21474836480  # Default 20 GB (20 * 1024^3)



class SubscriptionPayment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(
        PhotographerSubscription,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')
    gateway = models.CharField(max_length=50, default='razorpay')
    gateway_order_id = models.CharField(max_length=100, blank=True, db_index=True)
    gateway_payment_id = models.CharField(max_length=100, blank=True)
    gateway_signature = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    invoice_url = models.URLField(blank=True, null=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment {self.id} - {self.amount} {self.currency} ({self.status})"
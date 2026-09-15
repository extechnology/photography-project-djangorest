import uuid
from django.db import models


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


class PhotographerSubscription(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('trial', 'Trial'),
        ('past_due', 'Past Due'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    photographer = models.OneToOneField(
        'App.PhotographerProfile',
        on_delete=models.CASCADE,
        related_name='subscription'
    )
    plan = models.ForeignKey(
        SubscriptionPlans,
        on_delete=models.PROTECT,
        related_name='active_subscriptions'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    payment_gateway_ref = models.CharField(max_length=255, blank=True, default='')

    def __str__(self):
        return f"{self.photographer} - {self.plan.name} ({self.status})"
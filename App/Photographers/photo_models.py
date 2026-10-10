import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from App.Auth.auth_models import User
from App.Subscriptions.sub_models import SubscriptionPlans, Plan


class PhotoCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class PhotographerProfile(models.Model):
    TEMPLATE_CHOICES = [
        ('editorial', 'Editorial'),
        ('masonry', 'Masonry'),
        ('cinematic', 'Cinematic'),
        ('minimal', 'Minimal'),
    ]

    WATERMARK_TYPE_CHOICES = [
        ('text', 'Text Signature'),
        ('image', 'Image Logo'),
    ]

    WATERMARK_POSITION_CHOICES = [
        ('bottom-right', 'Bottom Right'),
        ('bottom_right', 'Bottom Right'),
        ('bottom-left', 'Bottom Left'),
        ('bottom_left', 'Bottom Left'),
        ('top-right', 'Top Right'),
        ('top_right', 'Top Right'),
        ('top-left', 'Top Left'),
        ('top_left', 'Top Left'),
        ('center', 'Center'),
        ('tiled', 'Tiled Pattern'),
        ('repeated', 'Repeated Pattern'),
    ]

    FONT_SIZE_CHOICES = [
        ('sm', 'Small'),
        ('md', 'Medium'),
        ('lg', 'Large'),
        ('xl', 'Extra Large'),
    ]

    FONT_STYLE_CHOICES = [
        ('serif', 'Editorial Serif'),
        ('sans', 'Modern Sans'),
        ('script', 'Signature Script'),
        ('mono', 'Minimal Mono'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='photographer_profile'
    )
    plan = models.ForeignKey(
        SubscriptionPlans,
        on_delete=models.SET_NULL,
        related_name='photographer_profiles',
        null=True,
        blank=True
    )
    studio_plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        related_name='photographer_profiles',
        null=True,
        blank=True
    )

    studio_name = models.CharField(max_length=255, blank=True, default='')
    name = models.CharField(max_length=255)
    avatar = models.ImageField(
        upload_to='photographer_profiles/',
        blank=True,
        null=True
    )
    avatar_url = models.CharField(max_length=512, blank=True, default='')
    profile_image = models.ImageField(
        upload_to='photographer_profiles/',
        blank=True,
        null=True
    )
    bio = models.TextField(blank=True, default='')
    occupation = models.CharField(max_length=255, blank=True, default='')
    phone = models.CharField(max_length=20, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    address = models.CharField(max_length=255, blank=True, default='')
    location = models.CharField(max_length=255, blank=True, default='')
    website_url = models.URLField(blank=True, default='')
    instagram_handle = models.CharField(max_length=100, blank=True, default='')
    default_template = models.CharField(
        max_length=50,
        choices=TEMPLATE_CHOICES,
        default='editorial'
    )

    # Watermark Suite
    enable_watermark = models.BooleanField(
        default=True,
        help_text="Enable or disable watermark branding on client galleries"
    )
    watermark_type = models.CharField(
        max_length=10,
        choices=WATERMARK_TYPE_CHOICES,
        default='text',
        help_text="Active branding format: 'text' or 'image'"
    )
    watermark_text = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="Custom watermark signature. If blank, defaults to photographer's name."
    )
    watermark_image = models.ImageField(
        upload_to='watermarks/%Y/%m/',
        null=True,
        blank=True,
        help_text="Studio watermark logo (transparent PNG/SVG recommended)"
    )
    watermark_opacity = models.FloatField(
        default=0.45,
        validators=[MinValueValidator(0.05), MaxValueValidator(1.0)],
        help_text="Opacity between 0.05 and 1.0 (default 0.45)"
    )
    watermark_position = models.CharField(
        max_length=50,
        choices=WATERMARK_POSITION_CHOICES,
        default='bottom-right',
        help_text="Watermark screen placement"
    )
    watermark_font_size = models.CharField(
        max_length=10,
        choices=FONT_SIZE_CHOICES,
        default='md',
        help_text="Typography size preset: sm, md, lg, xl"
    )
    watermark_font_color = models.CharField(
        max_length=20,
        default='#FFFFFF',
        help_text="Hex color code for watermark typography"
    )
    watermark_font_style = models.CharField(
        max_length=20,
        choices=FONT_STYLE_CHOICES,
        default='serif',
        help_text="Typography family: serif, sans, script, mono"
    )

    def get_watermark_text(self) -> str:
        """Fallback to photographer name if watermark_text is blank."""
        if self.watermark_text and self.watermark_text.strip():
            return self.watermark_text.strip()
        photographer_name = self.name or (self.user.get_full_name() if self.user else 'Photographer')
        return f"© {photographer_name}"

    def get_photographer_display_name(self) -> str:
        """Returns the photographer's real name or username."""
        full_name = self.user.get_full_name().strip() if self.user else ''
        if full_name:
            return full_name
        if hasattr(self, 'name') and (self.name or '').strip():
            return self.name.strip()
        return self.user.username if self.user else 'Photographer'

    def get_effective_watermark_text(self) -> str:
        """
        STRICT REQUIREMENT: The default watermark text must be the photographer's name.
        Cleans legacy placeholders ('Ex Studio', '© Ex Studio', etc.) and returns '© <Photographer Name>'.
        """
        raw = (self.watermark_text or '').strip()
        legacy_placeholders = {
            'ex studio', '© ex studio', 'atelier studio',
            '© atelier studio', 'studio', '© studio'
        }
        if raw and raw.lower() not in legacy_placeholders:
            return raw if raw.startswith('©') else f"© {raw}"

        name = self.get_photographer_display_name()
        return f"© {name}"

    def save(self, *args, **kwargs):
        # Automatically populate watermark_text with photographer name on first creation or legacy placeholder
        legacy_placeholders = {'ex studio', '© ex studio', 'atelier studio', '© atelier studio', 'studio', '© studio'}
        if not self.watermark_text or self.watermark_text.strip().lower() in legacy_placeholders:
            self.watermark_text = f"© {self.get_photographer_display_name()}"
            if 'update_fields' in kwargs and kwargs['update_fields'] is not None:
                fields_set = set(kwargs['update_fields'])
                fields_set.add('watermark_text')
                kwargs['update_fields'] = list(fields_set)
        super().save(*args, **kwargs)

    # Onboarding & Quota Tracking
    is_onboarded = models.BooleanField(default=False)
    onboarding_step = models.PositiveIntegerField(default=1)
    storage_used_bytes = models.BigIntegerField(
        default=0,
        help_text="Current total storage used across all galleries in bytes"
    )
    storage_reserved_bytes = models.BigIntegerField(
        default=0,
        help_text="Storage temporarily reserved during in-flight uploads in bytes"
    )

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    @property
    def subdomain(self):
        config = getattr(self.user, 'portfolio_config', None)
        return config.subdomain if config else None

    @subdomain.setter
    def subdomain(self, value):
        config = getattr(self.user, 'portfolio_config', None)
        if config:
            config.subdomain = value
            config.save(update_fields=['subdomain', 'updated_at'])

    def check_onboarded(self):
        return bool((self.name or '').strip() and ((self.phone or '').strip() or (self.occupation or '').strip()))

    def get_avatar_url(self):
        if self.avatar:
            try:
                return self.avatar.url
            except Exception:
                pass
        if self.profile_image:
            try:
                return self.profile_image.url
            except Exception:
                pass
        if self.avatar_url:
            return self.avatar_url
        return ""

    def get_storage_limit(self):
        """Returns effective storage limit in bytes based on plan or default."""
        from django.conf import settings
        test_storage_limit = getattr(settings, 'TEST_USER_STORAGE_LIMIT_BYTES', None)

        if hasattr(self, 'subscription') and self.subscription:
            sub = self.subscription
            if sub.plan and sub.plan.storage_limit_bytes:
                base_bytes = sub.plan.storage_limit_bytes
                if getattr(sub.plan, 'can_upgrade_storage', False) and getattr(sub, 'extra_storage_gb', 0) > 0:
                    base_bytes += (sub.extra_storage_gb * 1024 * 1024 * 1024)
                return base_bytes
        if hasattr(self, 'studio_plan') and self.studio_plan and self.studio_plan.storage_limit_bytes:
            return self.studio_plan.storage_limit_bytes
        if self.plan and self.plan.storage_limit_bytes:
            return self.plan.storage_limit_bytes

        if test_storage_limit:
            return test_storage_limit

        return 21474836480  # Default 20 GB (20 * 1024^3)


    def get_storage_remaining(self):
        """Returns remaining available storage in bytes."""
        limit = self.get_storage_limit()
        used_total = self.storage_used_bytes + self.storage_reserved_bytes
        return max(0, limit - used_total)

    def can_allocate_storage(self, bytes_needed):
        """Checks if the required bytes can be accommodated within the quota."""
        limit = self.get_storage_limit()
        return (self.storage_used_bytes + self.storage_reserved_bytes + bytes_needed) <= limit

    def get_total_storage_used_bytes(self):
        """Returns total storage used across galleries and staging in bytes."""
        if self.user and hasattr(self.user, 'get_total_storage_used_bytes'):
            return self.user.get_total_storage_used_bytes()
        return int((self.storage_used_bytes or 0) + (self.storage_reserved_bytes or 0))

    def get_active_subscription(self):
        """Returns the active subscription for this studio."""
        if hasattr(self, 'subscription') and self.subscription:
            if getattr(self.subscription, 'status', None) == 'active':
                return self.subscription
        if self.user and hasattr(self.user, 'subscription'):
            sub = self.user.subscription
            if sub and getattr(sub, 'status', None) == 'active':
                return sub
        return None

    @property
    def events(self):
        if self.user and hasattr(self.user, 'events'):
            return self.user.events
        if hasattr(self, 'shared_events'):
            return self.shared_events
        from App.LiveEvents.event_models import LiveEvent
        return LiveEvent.objects.filter(photographer=self.user)

    @property
    def portfolio_projects(self):
        if self.user and hasattr(self.user, 'portfolio_projects'):
            return self.user.portfolio_projects
        from portfolio.models import PortfolioWork
        return PortfolioWork.objects.none()

    @property
    def inquiries(self):
        if self.user:
            from portfolio.models import PortfolioInquiry
            return PortfolioInquiry.objects.filter(photographer=self.user)
        return getattr(self, 'inquiry_set', None)

    def __str__(self):
        return f"{self.studio_name} ({self.name})"


class NotificationPreference(models.Model):
    photographer = models.OneToOneField(
        PhotographerProfile,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    notify_client_visited = models.BooleanField(default=True)
    notify_photos_downloaded = models.BooleanField(default=True)
    notify_favorites_selected = models.BooleanField(default=True)
    notify_storage_alerts = models.BooleanField(default=True)
    notify_marketing_updates = models.BooleanField(default=False)

    def __str__(self):
        return f"Preferences for {self.photographer}"


class Notification(models.Model):
    EVENT_TYPES = [
        ('client_visit', 'Client Visit'),
        ('download', 'Download'),
        ('proofing_submitted', 'Proofing Submitted'),
        ('storage_warning', 'Storage Warning'),
        ('system', 'System'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
        null=True,
        blank=True
    )
    photographer = models.ForeignKey(
        PhotographerProfile,
        on_delete=models.CASCADE,
        related_name='notifications',
        null=True,
        blank=True
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, default='system')
    related_gallery_id = models.UUIDField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.event_type.upper()}] {self.title}"


class PhotographerPost(models.Model):
    photographer = models.ForeignKey(
        PhotographerProfile,
        on_delete=models.CASCADE,
        related_name='posts'
    )
    photo_category = models.ForeignKey(
        PhotoCategory,
        on_delete=models.CASCADE,
        related_name='posts'
    )
    caption = models.TextField(blank=True)
    tech_details = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.photographer.name} - {self.id}"


class PostImage(models.Model):
    post = models.ForeignKey(
        PhotographerPost,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = models.ImageField(upload_to='post_images/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image - Post {self.post.id}"


class PostFeedback(models.Model):
    post = models.ForeignKey(
        PhotographerPost,
        on_delete=models.CASCADE,
        related_name='feedbacks'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='feedbacks'
    )
    feedback = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - Post {self.post.id}"


class Inquiry(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('booked', 'Booked'),
        ('archived', 'Archived'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    photographer = models.ForeignKey(
        PhotographerProfile,
        on_delete=models.CASCADE,
        related_name='inquiries',
        null=True,
        blank=True,
        help_text="Direct inquiry to specific photographer, or null for general lead pool"
    )
    client_name = models.CharField(max_length=255)
    client_email = models.EmailField()
    client_phone = models.CharField(max_length=20, blank=True, default='')
    event_type = models.CharField(max_length=100, blank=True, default='Wedding')
    event_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True, default='')
    budget = models.CharField(max_length=100, blank=True, default='')
    message = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Inquiry: {self.client_name} - {self.event_type}"
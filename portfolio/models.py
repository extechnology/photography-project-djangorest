import uuid
from django.db import models
from django.conf import settings


class PortfolioConfig(models.Model):
    TEMPLATE_CHOICES = (
        ('editorial', 'Editorial'),
        ('masonry', 'Masonry'),
        ('cinematic', 'Cinematic'),
        ('minimal', 'Minimal'),
        ('darkroom-atelier', 'Darkroom Atelier (Masonry)'),
        ('editorial-vogue', 'Editorial Vogue'),
        ('cinematic-luxury', 'Cinematic Luxury'),
        ('minimal-zen', 'Minimal Zen'),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='portfolio_config'
    )
    template_id = models.CharField(
        max_length=64,
        choices=TEMPLATE_CHOICES,
        default='darkroom-atelier'
    )
    studio_name = models.CharField(max_length=255, default='My Photography Studio')
    artist_name = models.CharField(max_length=255, default='Lead Artist')
    tagline = models.TextField(
        default='Visual Storytelling • Luxury Documentaries & Fine Art'
    )
    bio = models.TextField(
        blank=True,
        default='Documenting raw emotion, modern romanticism, and timeless moments.'
    )
    about_story = models.TextField(
        blank=True,
        default='Our studio blends documentary photojournalism with refined fine-art aesthetics.'
    )
    location = models.CharField(max_length=255, default='Mumbai & Worldwide')
    avatar_url = models.URLField(
        max_length=1024,
        default='https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=600&auto=format&fit=crop&q=80'
    )
    banner_url = models.URLField(
        max_length=1024,
        default='https://images.unsplash.com/photo-1492691527719-9d1e07e534b4?w=1920&auto=format&fit=crop&q=85'
    )
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=64, blank=True)
    instagram_handle = models.CharField(max_length=128, blank=True, default='')
    youtube_handle = models.CharField(max_length=128, blank=True, default='')
    website_url = models.URLField(max_length=512, blank=True, default='')
    is_booking_open = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'portfolio_config'
        verbose_name = 'Portfolio Configuration'
        verbose_name_plural = 'Portfolio Configurations'

    def __str__(self):
        return f"{self.studio_name} ({getattr(self.user, 'username', self.user_id)})"


class PortfolioWork(models.Model):
    CATEGORY_CHOICES = (
        ('weddings', 'Weddings'),
        ('editorial', 'Editorial'),
        ('commercial', 'Commercial'),
        ('pre-wedding', 'Pre-Wedding'),
        ('cinematic', 'Cinematic'),
        ('portrait', 'Portrait'),
    )

    portfolio = models.ForeignKey(
        PortfolioConfig,
        on_delete=models.CASCADE,
        related_name='works'
    )
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=64, choices=CATEGORY_CHOICES, default='weddings')
    cover_url = models.URLField(max_length=1024)
    year = models.CharField(max_length=16, default='2026')
    location = models.CharField(max_length=255, default='Location')
    description = models.TextField(blank=True, default='')
    client_name = models.CharField(max_length=255, blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'portfolio_work'
        ordering = ['order', '-created_at']
        verbose_name = 'Portfolio Work'
        verbose_name_plural = 'Portfolio Works'

    def __str__(self):
        return f"{self.title} - {self.portfolio.studio_name}"


class PortfolioWorkPhoto(models.Model):
    work = models.ForeignKey(
        PortfolioWork,
        on_delete=models.CASCADE,
        related_name='photos'
    )
    photo_url = models.URLField(max_length=1024)
    caption = models.CharField(max_length=255, blank=True, default='')
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'portfolio_work_photo'
        ordering = ['order', 'id']
        verbose_name = 'Portfolio Work Photo'
        verbose_name_plural = 'Portfolio Work Photos'

    def __str__(self):
        return f"Photo {self.id} for {self.work.title}"


class PortfolioInquiry(models.Model):
    EVENT_TYPE_CHOICES = (
        ('wedding', 'Wedding'),
        ('pre-wedding', 'Pre-Wedding'),
        ('editorial', 'Editorial / Fashion'),
        ('commercial', 'Commercial'),
        ('portrait', 'Portrait Session'),
        ('workshop', 'Workshop / Mentorship'),
        ('maternity', 'Maternity'),
        ('other', 'Other'),
    )

    STATUS_CHOICES = (
        ('new', 'New Lead'),
        ('contacted', 'In Discussion'),
        ('booked', 'Confirmed Booked'),
        ('archived', 'Archived'),
    )

    photographer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='inquiries'
    )
    client_name = models.CharField(max_length=255)
    client_email = models.EmailField()
    client_phone = models.CharField(max_length=64, blank=True, default='')
    event_type = models.CharField(max_length=64, choices=EVENT_TYPE_CHOICES, default='wedding')
    event_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True, default='')
    budget = models.CharField(max_length=128, blank=True, default='')
    message = models.TextField()
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='new')
    notes = models.TextField(blank=True, default='')
    project_id = models.CharField(max_length=128, blank=True, null=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'portfolio_inquiry'
        ordering = ['-created_at']
        verbose_name = 'Portfolio Inquiry'
        verbose_name_plural = 'Portfolio Inquiries'

    def __str__(self):
        return f"{self.client_name} ({self.event_type}) -> {self.photographer.username or self.photographer_id}"


class PortfolioView(models.Model):
    DEVICE_CHOICES = (
        ('mobile', 'Mobile'),
        ('desktop', 'Desktop'),
        ('tablet', 'Tablet'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    photographer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='portfolio_views'
    )
    visitor_ip_hash = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    session_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    city = models.CharField(max_length=100, default='Unknown')
    country = models.CharField(max_length=100, default='Unknown')
    device = models.CharField(max_length=16, choices=DEVICE_CHOICES, default='mobile')
    referrer = models.CharField(max_length=512, blank=True, null=True, default='direct')
    page_section = models.CharField(max_length=64, default='hero')
    project_id = models.CharField(max_length=128, blank=True, null=True, db_index=True)
    project_title = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __init__(self, *args, **kwargs):
        if 'timestamp' in kwargs:
            kwargs['created_at'] = kwargs.pop('timestamp')
        if 'photographer' in kwargs:
            p = kwargs['photographer']
            if hasattr(p, 'user') and getattr(p, 'user', None):
                kwargs['photographer'] = p.user
        super().__init__(*args, **kwargs)

    @property
    def timestamp(self):
        return self.created_at

    @timestamp.setter
    def timestamp(self, val):
        self.created_at = val

    class Meta:
        db_table = 'portfolio_view'
        indexes = [
            models.Index(fields=['photographer', 'created_at']),
            models.Index(fields=['photographer', 'project_id']),
        ]
        ordering = ['-created_at']
        verbose_name = 'Portfolio View Event'
        verbose_name_plural = 'Portfolio View Events'

    def __str__(self):
        return f"View {self.session_id or self.visitor_ip_hash} on {self.photographer.username} ({self.device})"


# Model Aliases for compatibility with Telemetry & Analytics Specifications
PortfolioVisit = PortfolioView
PortfolioViewEvent = PortfolioView

from App.Photographers.photo_models import PhotographerProfile as Photographer


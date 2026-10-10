import uuid
import re
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

# E.164 phone number validator allowing optional leading +, followed by 7-15 digits
phone_validator = RegexValidator(
    regex=r'^\+?[1-9]\d{6,14}$',
    message="Phone number must be entered in international format: e.g. '+919876543210' or '+15551234567'."
)

RESERVED_SUBDOMAINS = {
    'app', 'api', 'admin', 'auth', 'www', 'cdn', 'static',
    'mail', 'support', 'staging', 'billing', 'dashboard', 'dev', 'test',
    'status', 'assets', 'culling', 'gallery', 'galleries', 'events', 'storage'
}

SUBDOMAIN_REGEX = re.compile(r'^[a-z0-9]([a-z0-9-]{1,61}[a-z0-9])?$')


def validate_subdomain(value):
    if not value:
        return
    clean = str(value).strip().lower()
    if len(clean) < 3 or len(clean) > 63:
        raise ValidationError("Subdomain must be between 3 and 63 characters long.")
    if clean.startswith('-') or clean.endswith('-'):
        raise ValidationError("Subdomain cannot begin or end with a hyphen.")
    if not SUBDOMAIN_REGEX.match(clean):
        raise ValidationError("Only lowercase alphanumeric characters and hyphens are allowed.")
    if clean in RESERVED_SUBDOMAINS:
        raise ValidationError(f"'{clean}' is a reserved platform name and cannot be claimed.")


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
    subdomain = models.CharField(
        max_length=63,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        validators=[validate_subdomain],
        help_text="Custom unique subdomain label under base domain, e.g. 'mridhul' for mridhul.exshare.ai"
    )
    custom_domain = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Independent custom domain, e.g. 'elena-photography.com'"
    )
    is_published = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this showcase portfolio is published and accessible to public visitors"
    )
    is_booking_open = models.BooleanField(default=True)
    pricing_starting_at = models.CharField(max_length=64, blank=True, default='')
    philosophy_quote = models.TextField(blank=True, default='')
    philosophy_author = models.CharField(max_length=128, blank=True, default='')
    accent_color = models.CharField(max_length=32, default='#d4af37')

    # ─── WHATSAPP DIRECT CONNECT FIELDS ───
    whatsapp_enabled = models.BooleanField(
        default=True,
        help_text="Controls whether the floating WhatsApp button is rendered on the public portfolio."
    )
    whatsapp_number = models.CharField(
        max_length=32,
        blank=True,
        default='',
        validators=[phone_validator],
        help_text="International phone number for WhatsApp direct contact (e.g. +919876543210)."
    )
    whatsapp_prefill_message = models.TextField(
        blank=True,
        default="Hi, I'm interested in booking a photography session with your studio!",
        help_text="Default message pre-filled in the WhatsApp chat when clients click the button."
    )
    whatsapp_button_label = models.CharField(
        max_length=64,
        blank=True,
        default="Chat on WhatsApp",
        help_text="Text shown on the floating pill or hover tooltip."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'portfolio_config'
        verbose_name = 'Portfolio Configuration'
        verbose_name_plural = 'Portfolio Configurations'

    def __str__(self):
        return f"{self.studio_name} ({getattr(self.user, 'username', self.user_id)})"

    def get_clean_whatsapp_number(self):
        """Returns clean digits-only phone number for wa.me URL generation."""
        if not self.whatsapp_number:
            return ""
        return "".join(c for c in self.whatsapp_number if c.isdigit())

    @property
    def clean_whatsapp_number(self):
        return self.get_clean_whatsapp_number()

    @property
    def cleanWhatsappNumber(self):
        return self.get_clean_whatsapp_number()

    def clean(self):
        super().clean()
        if self.subdomain:
            self.subdomain = self.subdomain.strip().lower()
            validate_subdomain(self.subdomain)

    def save(self, *args, **kwargs):
        if self.subdomain:
            self.subdomain = self.subdomain.strip().lower()
        if self.custom_domain:
            self.custom_domain = self.custom_domain.strip().lower()
        if self.whatsapp_number:
            self.whatsapp_number = "".join(c for c in self.whatsapp_number if c.isdigit() or c == '+')
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return self.artist_name or (self.user.get_full_name() if self.user else '')

    @property
    def projects(self):
        return self.works

    @property
    def full_domain(self):
        base_domain = getattr(settings, 'PORTFOLIO_BASE_DOMAIN', 'exshare.ai')
        if self.custom_domain:
            return self.custom_domain
        if self.subdomain:
            return f"{self.subdomain}.{base_domain}"
        return None

    @property
    def public_url(self):
        domain = self.full_domain
        return f"https://{domain}" if domain else None


class ReservedSubdomain(models.Model):
    name = models.CharField(max_length=63, unique=True, db_index=True)
    reason = models.CharField(max_length=255, default='system_reserved')
    reserved_for_user_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'portfolio_reserved_subdomain'
        verbose_name = 'Reserved Subdomain'
        verbose_name_plural = 'Reserved Subdomains'

    def __str__(self):
        return f"{self.name} ({self.reason})"

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.strip().lower()
        super().save(*args, **kwargs)



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
    is_published = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this project work is published in the portfolio showcase"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'portfolio_work'
        ordering = ['order', '-created_at']
        verbose_name = 'Portfolio Work'
        verbose_name_plural = 'Portfolio Works'

    def __str__(self):
        return f"{self.title} - {self.portfolio.studio_name}"

    @property
    def highlight_media(self):
        return self.photos


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

    @property
    def url(self):
        return self.photo_url


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
from django.db.models.signals import post_delete
from django.dispatch import receiver


@receiver(post_delete, sender=PortfolioConfig)
def retain_subdomain_reservation_on_delete(sender, instance, **kwargs):
    """
    Preserve claims on deletion using a retained reservation to prevent
    old links from changing owners or being claimed by third parties.
    """
    if instance.subdomain:
        ReservedSubdomain.objects.get_or_create(
            name=instance.subdomain.strip().lower(),
            defaults={
                'reason': 'retained_after_deletion',
                'reserved_for_user_id': instance.user_id
            }
        )



from rest_framework import serializers
from .models import PortfolioConfig, PortfolioWork, PortfolioWorkPhoto, PortfolioInquiry


class PortfolioWorkPhotoSerializer(serializers.ModelSerializer):
    photoUrl = serializers.CharField(source='photo_url', read_only=True)

    class Meta:
        model = PortfolioWorkPhoto
        fields = ['id', 'photo_url', 'photoUrl', 'caption', 'order']


class PortfolioWorkSerializer(serializers.ModelSerializer):
    highlightMedia = serializers.SerializerMethodField()
    mediaCount = serializers.SerializerMethodField()
    coverUrl = serializers.CharField(source='cover_url', required=False)
    clientName = serializers.CharField(source='client_name', required=False, allow_null=True)
    photos = PortfolioWorkPhotoSerializer(many=True, read_only=True)

    class Meta:
        model = PortfolioWork
        fields = [
            'id', 'title', 'category', 'coverUrl', 'cover_url',
            'year', 'location', 'description', 'clientName',
            'client_name', 'order', 'highlightMedia', 'mediaCount',
            'photos', 'created_at', 'updated_at'
        ]

    def get_highlightMedia(self, obj):
        if hasattr(obj, '_prefetched_objects_cache') and 'photos' in obj._prefetched_objects_cache:
            photos = [p.photo_url for p in obj._prefetched_objects_cache['photos']]
        else:
            photos = [p.photo_url for p in obj.photos.all()]
        return photos if photos else ([obj.cover_url] if obj.cover_url else [])

    def get_mediaCount(self, obj):
        if hasattr(obj, '_prefetched_objects_cache') and 'photos' in obj._prefetched_objects_cache:
            count = len(obj._prefetched_objects_cache['photos'])
        else:
            photos = list(obj.photos.all())
            count = len(photos)
        return count if count > 0 else (1 if obj.cover_url else 0)


class PortfolioConfigSerializer(serializers.ModelSerializer):
    templateId = serializers.CharField(source='template_id', required=False)
    template_id = serializers.CharField(required=False)
    studioName = serializers.CharField(source='studio_name', required=False)
    artistName = serializers.CharField(source='artist_name', required=False)
    aboutStory = serializers.CharField(source='about_story', required=False)
    avatarUrl = serializers.CharField(source='avatar_url', required=False)
    bannerUrl = serializers.CharField(source='banner_url', required=False)
    contactEmail = serializers.EmailField(source='contact_email', required=False, allow_blank=True)
    contactPhone = serializers.CharField(source='contact_phone', required=False, allow_blank=True)
    instagramHandle = serializers.CharField(source='instagram_handle', required=False, allow_blank=True)
    youtubeHandle = serializers.CharField(source='youtube_handle', required=False, allow_blank=True)
    websiteUrl = serializers.CharField(source='website_url', required=False, allow_blank=True)
    isBookingOpen = serializers.BooleanField(source='is_booking_open', required=False)
    is_booking_open = serializers.BooleanField(required=False)
    subdomain = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    customDomain = serializers.CharField(source='custom_domain', required=False, allow_null=True, allow_blank=True)
    custom_domain = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    isPublished = serializers.BooleanField(source='is_published', required=False)
    is_published = serializers.BooleanField(required=False)
    portfolioUrl = serializers.SerializerMethodField()
    portfolio_url = serializers.SerializerMethodField()
    fullDomain = serializers.SerializerMethodField()
    full_domain = serializers.SerializerMethodField()
    featuredWorks = PortfolioWorkSerializer(source='works', many=True, read_only=True)
    photographerSlug = serializers.SerializerMethodField()
    photographer_slug = serializers.SerializerMethodField()
    photographer_id = serializers.ReadOnlyField(source='user_id')
    photographerId = serializers.ReadOnlyField(source='user_id')

    # WhatsApp Direct Connect Fields
    whatsapp_enabled = serializers.BooleanField(required=False)
    whatsappEnabled = serializers.BooleanField(source='whatsapp_enabled', required=False)
    whatsapp_number = serializers.CharField(required=False, allow_blank=True)
    whatsappNumber = serializers.CharField(source='whatsapp_number', required=False, allow_blank=True)
    whatsapp_prefill_message = serializers.CharField(required=False, allow_blank=True)
    whatsappPrefillMessage = serializers.CharField(source='whatsapp_prefill_message', required=False, allow_blank=True)
    whatsapp_button_label = serializers.CharField(required=False, allow_blank=True)
    whatsappButtonLabel = serializers.CharField(source='whatsapp_button_label', required=False, allow_blank=True)
    clean_whatsapp_number = serializers.CharField(source='get_clean_whatsapp_number', read_only=True)
    cleanWhatsappNumber = serializers.CharField(source='get_clean_whatsapp_number', read_only=True)

    # Branding & Custom Styling Fields
    pricingStartingAt = serializers.CharField(source='pricing_starting_at', required=False, allow_blank=True)
    pricing_starting_at = serializers.CharField(required=False, allow_blank=True)
    philosophyQuote = serializers.CharField(source='philosophy_quote', required=False, allow_blank=True)
    philosophy_quote = serializers.CharField(required=False, allow_blank=True)
    philosophyAuthor = serializers.CharField(source='philosophy_author', required=False, allow_blank=True)
    philosophy_author = serializers.CharField(required=False, allow_blank=True)
    accentColor = serializers.CharField(source='accent_color', required=False, allow_blank=True)
    accent_color = serializers.CharField(required=False, allow_blank=True)

    subdomainStatus = serializers.CharField(source='subdomain_status', read_only=True)
    subdomainError = serializers.CharField(source='subdomain_error', read_only=True)
    subdomainProvisionedAt = serializers.DateTimeField(source='subdomain_provisioned_at', read_only=True)

    class Meta:
        model = PortfolioConfig
        fields = [
            'id', 'photographer_id', 'photographerId',
            'templateId', 'template_id', 'studioName', 'studio_name',
            'artistName', 'artist_name', 'tagline', 'bio', 'aboutStory',
            'about_story', 'location', 'avatarUrl', 'avatar_url',
            'bannerUrl', 'banner_url', 'contactEmail', 'contact_email',
            'contactPhone', 'contact_phone', 'instagramHandle', 'instagram_handle',
            'youtubeHandle', 'youtube_handle', 'websiteUrl', 'website_url',
            'subdomain', 'customDomain', 'custom_domain',
            'subdomain_status', 'subdomainStatus',
            'subdomain_error', 'subdomainError',
            'subdomain_provisioned_at', 'subdomainProvisionedAt',
            'isPublished', 'is_published', 'portfolioUrl', 'portfolio_url',
            'fullDomain', 'full_domain',
            'isBookingOpen', 'is_booking_open', 'featuredWorks',
            'photographerSlug', 'photographer_slug',
            'pricingStartingAt', 'pricing_starting_at',
            'philosophyQuote', 'philosophy_quote',
            'philosophyAuthor', 'philosophy_author',
            'accentColor', 'accent_color',
            # WhatsApp fields (snake_case)
            'whatsapp_enabled', 'whatsapp_number',
            'whatsapp_prefill_message', 'whatsapp_button_label',
            'clean_whatsapp_number',
            # WhatsApp fields (camelCase)
            'whatsappEnabled', 'whatsappNumber',
            'whatsappPrefillMessage', 'whatsappButtonLabel',
            'cleanWhatsappNumber',
        ]

    def validate_whatsapp_number(self, value):
        if not value:
            return ""
        # Strip extraneous spaces or hyphens before validating
        clean_val = "".join(c for c in value if c.isdigit() or c == '+')
        digits_only = "".join(c for c in clean_val if c.isdigit())
        if clean_val and not (7 <= len(digits_only) <= 15):
            raise serializers.ValidationError("Phone number must have between 7 and 15 digits.")
        return clean_val

    def validate_whatsappNumber(self, value):
        return self.validate_whatsapp_number(value)

    def validate_subdomain(self, value):
        if not value:
            return None
        norm = str(value).strip().lower()
        if not norm:
            return None

        from .models import validate_subdomain as model_validate_subdomain, ReservedSubdomain
        from .subdomain_service import get_reserved_subdomains
        from django.core.exceptions import ValidationError as DjangoValidationError

        # 1. Format validation
        try:
            model_validate_subdomain(norm)
        except (DjangoValidationError, serializers.ValidationError) as e:
            err_msg = str(e.messages[0]) if hasattr(e, 'messages') else str(e)
            raise serializers.ValidationError(err_msg)

        # 2. Check reserved infrastructure names
        if norm in get_reserved_subdomains() or ReservedSubdomain.objects.filter(name=norm).exists():
            raise serializers.ValidationError(f"The subdomain '{norm}' is reserved for platform infrastructure.")

        # 3. Check uniqueness across existing portfolios
        qs = PortfolioConfig.objects.filter(subdomain__iexact=norm)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f"The subdomain '{norm}' is already claimed by another portfolio.")

        return norm

    def update(self, instance, validated_data):
        new_subdomain = validated_data.get('subdomain')
        if new_subdomain is not None and new_subdomain != instance.subdomain:
            from django.conf import settings
            from django.utils import timezone
            dns_provider = getattr(settings, 'PORTFOLIO_DNS_PROVIDER', 'wildcard').strip().lower()
            if dns_provider == 'wildcard':
                now = timezone.now()
                instance.subdomain_status = PortfolioConfig.SubdomainStatus.ACTIVE
                instance.subdomain_provisioned_at = now
                instance.subdomain_dns_checked_at = now
                instance.subdomain_dns_record_type = 'A'
                instance.subdomain_dns_record_data = getattr(settings, 'PORTFOLIO_SERVER_IP', '31.97.232.245')
                instance.subdomain_dns_provider = 'wildcard'
                instance.subdomain_dns_managed = True
                instance.subdomain_error = ''
                instance.subdomain_retry_count = 0
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Ensure default phone number fallback if whatsapp_number is not set
        if not ret.get('whatsapp_number') and hasattr(instance, 'contact_phone') and instance.contact_phone:
            ret['whatsapp_number'] = instance.contact_phone
            ret['whatsappNumber'] = instance.contact_phone
        return ret

    def get_portfolioUrl(self, obj):
        request = self.context.get('request')
        return obj.get_public_url(request=request) if hasattr(obj, 'get_public_url') else obj.public_url

    def get_portfolio_url(self, obj):
        return self.get_portfolioUrl(obj)

    def get_fullDomain(self, obj):
        request = self.context.get('request')
        return obj.get_full_domain(request=request) if hasattr(obj, 'get_full_domain') else obj.full_domain

    def get_full_domain(self, obj):
        return self.get_fullDomain(obj)

    def get_photographerSlug(self, obj):
        return obj.user.username or str(obj.user.id)

    def get_photographer_slug(self, obj):
        return obj.user.username or str(obj.user.id)


class SubdomainAvailabilityQuerySerializer(serializers.Serializer):
    subdomain = serializers.CharField(
        required=False,
        max_length=63,
        help_text="Subdomain label to check for availability."
    )
    name = serializers.CharField(
        required=False,
        max_length=63,
        help_text="Subdomain label to check for availability (alias for subdomain)."
    )

    def validate(self, attrs):
        if not attrs.get('subdomain') and not attrs.get('name'):
            raise serializers.ValidationError("Either 'subdomain' or 'name' parameter is required.")
        return attrs


class SubdomainClaimSerializer(serializers.Serializer):
    subdomain = serializers.CharField(
        required=True,
        max_length=63,
        help_text="Subdomain label to claim, e.g. 'mridhul'."
    )



class PortfolioInquirySerializer(serializers.ModelSerializer):
    clientName = serializers.CharField(source='client_name', required=False)
    clientEmail = serializers.EmailField(source='client_email', required=False)
    clientPhone = serializers.CharField(source='client_phone', required=False, allow_blank=True)
    eventType = serializers.CharField(source='event_type', required=False)
    eventDate = serializers.DateField(source='event_date', required=False, allow_null=True)
    photographerId = serializers.SerializerMethodField()
    projectId = serializers.CharField(source='project_id', required=False, allow_null=True)
    galleryTitle = serializers.CharField(source='gallery_title', required=False, allow_null=True)
    galleryId = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    isLocked = serializers.SerializerMethodField()

    class Meta:
        model = PortfolioInquiry
        fields = [
            'id', 'photographer', 'photographerId', 'client_name', 'clientName',
            'client_email', 'clientEmail', 'client_phone', 'clientPhone',
            'event_type', 'eventType', 'event_date', 'eventDate',
            'location', 'budget', 'message', 'status', 'notes',
            'gallery', 'gallery_title', 'galleryTitle', 'galleryId', 'source',
            'project_id', 'projectId',
            'is_locked', 'isLocked',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'photographer']

    def get_galleryId(self, obj):
        return str(obj.gallery_id) if getattr(obj, 'gallery_id', None) else None

    def get_photographerId(self, obj):
        if obj.photographer:
            return obj.photographer.username or str(obj.photographer.id)
        return None

    def _check_is_locked(self, obj):
        if hasattr(obj, '_is_locked_cached'):
            return obj._is_locked_cached
        if hasattr(obj, '_is_locked'):
            val = bool(obj._is_locked)
            obj._is_locked_cached = val
            return val
        request = self.context.get('request')
        if not request or not getattr(request, 'user', None) or not request.user.is_authenticated:
            obj._is_locked_cached = False
            return False
        if request.user.is_staff or request.user.is_superuser:
            obj._is_locked_cached = False
            return False
        sub = getattr(request.user, 'subscription', None)
        plan = getattr(sub, 'plan', None) if sub else None
        if not plan:
            obj._is_locked_cached = False
            return False
        if getattr(plan, 'has_full_inquiry_access', True):
            obj._is_locked_cached = False
            return False
        index = getattr(obj, '_inquiry_index', None)
        max_inquiries = getattr(plan, 'max_inquiries', 10) or 10
        val = (index >= max_inquiries) if index is not None else False
        obj._is_locked_cached = val
        return val

    def get_is_locked(self, obj):
        return self._check_is_locked(obj)

    def get_isLocked(self, obj):
        return self._check_is_locked(obj)

    def to_representation(self, obj):
        data = super().to_representation(obj)
        if self._check_is_locked(obj):
            data['is_locked'] = True
            data['isLocked'] = True
            data['client_phone'] = "+91 **********"
            data['clientPhone'] = "+91 **********"
            data['client_email'] = "********@*****.com"
            data['clientEmail'] = "********@*****.com"
        else:
            data['is_locked'] = False
            data['isLocked'] = False
        return data

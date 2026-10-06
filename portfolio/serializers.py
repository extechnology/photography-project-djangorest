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
        photos = [p.photo_url for p in obj.photos.all()]
        return photos if photos else ([obj.cover_url] if obj.cover_url else [])

    def get_mediaCount(self, obj):
        count = obj.photos.count()
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
    featuredWorks = PortfolioWorkSerializer(source='works', many=True, read_only=True)
    photographerSlug = serializers.SerializerMethodField()
    photographer_slug = serializers.SerializerMethodField()

    class Meta:
        model = PortfolioConfig
        fields = [
            'id', 'templateId', 'template_id', 'studioName', 'studio_name',
            'artistName', 'artist_name', 'tagline', 'bio', 'aboutStory',
            'about_story', 'location', 'avatarUrl', 'avatar_url',
            'bannerUrl', 'banner_url', 'contactEmail', 'contact_email',
            'contactPhone', 'contact_phone', 'instagramHandle', 'instagram_handle',
            'youtubeHandle', 'youtube_handle', 'websiteUrl', 'website_url',
            'isBookingOpen', 'is_booking_open', 'featuredWorks',
            'photographerSlug', 'photographer_slug'
        ]

    def get_photographerSlug(self, obj):
        return obj.user.username or str(obj.user.id)

    def get_photographer_slug(self, obj):
        return obj.user.username or str(obj.user.id)


class PortfolioInquirySerializer(serializers.ModelSerializer):
    clientName = serializers.CharField(source='client_name', required=False)
    clientEmail = serializers.EmailField(source='client_email', required=False)
    clientPhone = serializers.CharField(source='client_phone', required=False, allow_blank=True)
    eventType = serializers.CharField(source='event_type', required=False)
    eventDate = serializers.DateField(source='event_date', required=False, allow_null=True)
    photographerId = serializers.SerializerMethodField()
    projectId = serializers.CharField(source='project_id', required=False, allow_null=True)
    is_locked = serializers.SerializerMethodField()
    isLocked = serializers.SerializerMethodField()

    class Meta:
        model = PortfolioInquiry
        fields = [
            'id', 'photographer', 'photographerId', 'client_name', 'clientName',
            'client_email', 'clientEmail', 'client_phone', 'clientPhone',
            'event_type', 'eventType', 'event_date', 'eventDate',
            'location', 'budget', 'message', 'status', 'notes',
            'project_id', 'projectId',
            'is_locked', 'isLocked',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'photographer']

    def get_photographerId(self, obj):
        if obj.photographer:
            return obj.photographer.username or str(obj.photographer.id)
        return None

    def _check_is_locked(self, obj):
        if hasattr(obj, '_is_locked'):
            return bool(obj._is_locked)
        request = self.context.get('request')
        if not request or not getattr(request, 'user', None) or not request.user.is_authenticated:
            return False
        if request.user.is_staff or request.user.is_superuser:
            return False
        sub = getattr(request.user, 'subscription', None)
        plan = getattr(sub, 'plan', None) if sub else None
        if not plan:
            return False
        if getattr(plan, 'has_full_inquiry_access', True):
            return False
        index = getattr(obj, '_inquiry_index', None)
        max_inquiries = getattr(plan, 'max_inquiries', 10) or 10
        if index is not None:
            return index >= max_inquiries
        return False

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

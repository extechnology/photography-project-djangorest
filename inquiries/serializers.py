from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db.models import Q
from .models import Inquiry

User = get_user_model()


class PublicInquirySubmissionSerializer(serializers.ModelSerializer):
    photographer_id = serializers.IntegerField(required=False, write_only=True)
    gallery_id = serializers.CharField(required=False, allow_blank=True, write_only=True)
    gallery_slug = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Inquiry
        fields = [
            'id',
            'photographer_id',
            'gallery_id',
            'gallery_slug',
            'gallery_title',
            'source',
            'client_name',
            'client_email',
            'client_phone',
            'event_type',
            'event_date',
            'location',
            'budget',
            'message',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def to_internal_value(self, data):
        # Support camelCase payloads sent from frontend gallery modals
        mutable = data.copy() if hasattr(data, 'copy') else dict(data)
        mapping = {
            'photographerId': 'photographer_id',
            'galleryId': 'gallery_id',
            'gallerySlug': 'gallery_slug',
            'galleryTitle': 'gallery_title',
            'clientName': 'client_name',
            'clientEmail': 'client_email',
            'clientPhone': 'client_phone',
            'eventType': 'event_type',
            'eventDate': 'event_date',
        }
        for camel, snake in mapping.items():
            if camel in mutable and snake not in mutable:
                mutable[snake] = mutable[camel]

        # Convert string username to integer user ID if non-digit photographer_id provided
        p_id = mutable.get('photographer_id')
        if p_id is not None and isinstance(p_id, str) and not p_id.isdigit():
            user = User.objects.filter(Q(username__iexact=p_id)).first()
            if user:
                mutable['photographer_id'] = user.id

        return super().to_internal_value(mutable)

    def validate(self, attrs):
        # Ensure either photographer_id or gallery_id or gallery_slug is present to identify owner
        if not attrs.get('photographer_id') and not attrs.get('gallery_id') and not attrs.get('gallery_slug'):
            raise serializers.ValidationError(
                "Either photographer_id or gallery_id must be provided to attribute inquiry."
            )
        return attrs


class InquiryDetailSerializer(serializers.ModelSerializer):
    """Used for authenticated photographer dashboard (`GET /api/inquiries/`)."""
    clientName = serializers.CharField(source='client_name', read_only=True)
    clientEmail = serializers.EmailField(source='client_email', read_only=True)
    clientPhone = serializers.CharField(source='client_phone', read_only=True)
    eventType = serializers.CharField(source='event_type', read_only=True)
    eventDate = serializers.DateField(source='event_date', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    galleryTitle = serializers.CharField(source='gallery_title', read_only=True)
    galleryId = serializers.SerializerMethodField()
    photographerId = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    isLocked = serializers.SerializerMethodField()

    class Meta:
        model = Inquiry
        fields = '__all__'

    def get_galleryId(self, obj):
        return str(obj.gallery_id) if obj.gallery_id else None

    def get_photographerId(self, obj):
        if obj.photographer:
            return getattr(obj.photographer, 'username', str(obj.photographer_id))
        return None

    def get_is_locked(self, obj):
        return False

    def get_isLocked(self, obj):
        return False

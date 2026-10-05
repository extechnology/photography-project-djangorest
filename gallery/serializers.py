from rest_framework import serializers
from App.Storage.storage_serializers import GalleryDetailResponseSerializer
from .models import GalleryGuestSession, GalleryStoryVideo


class ReorderGalleryMediaSerializer(serializers.Serializer):
    media_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Ordered array of media UUIDs, or subset for batch actions."
    )
    media_id = serializers.UUIDField(
        required=False,
        help_text="Single media UUID when performing a targeted jump."
    )
    action = serializers.ChoiceField(
        choices=['top', 'bottom', 'position'],
        required=False,
        help_text="Movement action: 'top', 'bottom', or 'position'."
    )
    target_position = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="1-based index when action is 'position'."
    )

    def validate(self, attrs):
        if not attrs.get('media_ids') and not (attrs.get('media_id') and attrs.get('action')):
            raise serializers.ValidationError("Either 'media_ids' or ('media_id' and 'action') must be provided.")
        return attrs


class GalleryGuestSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GalleryGuestSession
        fields = ['id', 'guest_token', 'name', 'email', 'phone', 'created_at']
        read_only_fields = ['id', 'created_at']


class GalleryStoryVideoSerializer(serializers.ModelSerializer):
    videoUrl = serializers.SerializerMethodField()
    photoCount = serializers.SerializerMethodField()

    class Meta:
        model = GalleryStoryVideo
        fields = [
            'id', 'creator_name', 'title', 'subtitle',
            'aspect_ratio', 'transition_style', 'duration_seconds',
            'music_title', 'music_artist', 'photo_ids',
            'videoUrl', 'photoCount', 'file_size_bytes',
            'download_count', 'share_count', 'created_at'
        ]
        read_only_fields = ['id', 'videoUrl', 'photoCount', 'download_count', 'share_count', 'created_at']

    def get_videoUrl(self, obj):
        if not obj.video_file:
            return ""
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.video_file.url)
        return obj.video_file.url

    def get_photoCount(self, obj):
        return len(obj.photo_ids) if obj.photo_ids else 0


class CreateStoryVideoPayloadSerializer(serializers.Serializer):
    guest_token = serializers.CharField(max_length=128, required=False, allow_blank=True)
    creator_name = serializers.CharField(max_length=120, required=False, default="Guest Creator")
    title = serializers.CharField(max_length=255, required=False, default="Our Story")
    subtitle = serializers.CharField(max_length=255, required=False, allow_blank=True)
    aspect_ratio = serializers.ChoiceField(choices=['9:16', '1:1', '16:9'], default='9:16')
    transition_style = serializers.CharField(max_length=32, default='ken-burns')
    duration_seconds = serializers.FloatField(default=15.0)
    music_title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    music_artist = serializers.CharField(max_length=255, required=False, allow_blank=True)
    music_url = serializers.CharField(max_length=1024, required=False, allow_blank=True)
    photo_ids = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    video = serializers.FileField(required=True)


# Alias for compatibility
GalleryDetailSerializer = GalleryDetailResponseSerializer

__all__ = [
    'ReorderGalleryMediaSerializer',
    'GalleryDetailSerializer',
    'GalleryGuestSessionSerializer',
    'GalleryStoryVideoSerializer',
    'CreateStoryVideoPayloadSerializer',
]

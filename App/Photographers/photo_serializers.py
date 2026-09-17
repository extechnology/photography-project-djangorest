from rest_framework import serializers

from .photo_models import (
    PhotoCategory,
    PhotographerProfile,
    PhotographerPost,
    PostImage,
    PostFeedback,
    Notification,
    NotificationPreference,
)
from .photo_utils import validate_non_nude_image



class PhotoCategorySerializer(serializers.ModelSerializer):
    posts_count = serializers.IntegerField(source='posts.count', read_only=True)

    class Meta:
        model = PhotoCategory
        fields = ['id', 'name', 'posts_count']


from App.Auth.auth_models import User


class PhotographerProfileSerializer(serializers.ModelSerializer):
    user_username = serializers.ReadOnlyField(source='user.username')
    user_email = serializers.ReadOnlyField(source='user.email')
    plan_name = serializers.ReadOnlyField(source='plan.name')
    storage_limit_bytes = serializers.SerializerMethodField()
    storage_remaining_bytes = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    quick_info = serializers.SerializerMethodField()
    plan_details = serializers.SerializerMethodField()
    avatar = serializers.ImageField(required=False, allow_null=True, validators=[validate_non_nude_image])
    profile_image = serializers.ImageField(required=False, allow_null=True, validators=[validate_non_nude_image])


    class Meta:
        model = PhotographerProfile
        fields = [
            'id',
            'user',
            'user_username',
            'user_email',
            'plan',
            'plan_name',
            'plan_details',
            'studio_name',
            'name',
            'occupation',
            'avatar',
            'avatar_url',
            'profile_image',
            'bio',
            'phone',
            'email',
            'address',
            'location',
            'website_url',
            'instagram_handle',
            'default_template',
            'enable_watermark',
            'watermark_text',
            'watermark_image',
            'watermark_opacity',
            'watermark_position',
            'is_onboarded',
            'onboarding_step',
            'storage_used_bytes',
            'storage_reserved_bytes',
            'storage_limit_bytes',
            'storage_remaining_bytes',
            'quick_info',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'user',
            'user_username',
            'user_email',
            'plan',
            'plan_name',
            'plan_details',
            'storage_used_bytes',
            'storage_reserved_bytes',
            'storage_limit_bytes',
            'storage_remaining_bytes',
            'quick_info',
            'created_at',
            'updated_at',
        ]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        user = getattr(instance, 'user', None)
        if user:
            if not ret.get('name'):
                ret['name'] = user.fullname or user.username or ''
            if not ret.get('email'):
                ret['email'] = user.email or ''
            if not ret.get('phone'):
                ret['phone'] = user.phone or ''
        return ret

    def update(self, instance, validated_data):
        user = getattr(instance, 'user', None)
        name = validated_data.get('name')
        phone = validated_data.get('phone')
        email = validated_data.get('email')

        if user:
            user_updated_fields = []
            if name is not None and user.fullname != name:
                user.fullname = name
                user_updated_fields.append('fullname')
            if phone is not None:
                cleaned_phone = phone.strip() or None
                if cleaned_phone != user.phone:
                    if not cleaned_phone or not User.objects.filter(phone=cleaned_phone).exclude(pk=user.pk).exists():
                        user.phone = cleaned_phone
                        user_updated_fields.append('phone')
            if email is not None:
                cleaned_email = email.strip() or None
                if cleaned_email != user.email:
                    if not cleaned_email or not User.objects.filter(email__iexact=cleaned_email).exclude(pk=user.pk).exists():
                        user.email = cleaned_email
                        user_updated_fields.append('email')
            if user_updated_fields:
                user.save(update_fields=user_updated_fields)

        return super().update(instance, validated_data)

    def get_avatar_url(self, obj):
        return obj.get_avatar_url()

    def get_storage_limit_bytes(self, obj):
        return obj.get_storage_limit()

    def get_storage_remaining_bytes(self, obj):
        return obj.get_storage_remaining()

    @staticmethod
    def _format_bytes(num_bytes):
        if not num_bytes:
            return "0 GB"
        gb = num_bytes / (1024 ** 3)
        if gb >= 1:
            return f"{gb:.1f} GB" if (gb % 1 != 0) else f"{int(gb)} GB"
        mb = num_bytes / (1024 ** 2)
        return f"{mb:.1f} MB" if (mb % 1 != 0) else f"{int(mb)} MB"

    def get_quick_info(self, obj):
        from App.Storage.storage_models import Gallery, Media

        # Member Since
        user = getattr(obj, 'user', None)
        date_joined = getattr(user, 'date_joined', None) or getattr(obj, 'created_at', None)
        member_since = date_joined.strftime("%b %d, %Y") if date_joined else "N/A"
        member_since_iso = date_joined.isoformat() if date_joined else None

        # Galleries count
        try:
            galleries_count = Gallery.objects.filter(photographer=obj).count()
        except Exception:
            galleries_count = 0

        # Total Photos & Videos
        try:
            media_photos = Media.objects.filter(photographer=obj, media_type='photo').count()
            post_photos = PostImage.objects.filter(post__photographer=obj).count()
            total_photos = media_photos + post_photos
            total_videos = Media.objects.filter(photographer=obj, media_type='video').count()
        except Exception:
            total_photos = 0
            total_videos = 0

        # Storage
        used_bytes = obj.storage_used_bytes or 0
        limit_bytes = obj.get_storage_limit()
        used_formatted = self._format_bytes(used_bytes)
        limit_formatted = self._format_bytes(limit_bytes)

        return {
            "member_since": member_since,
            "member_since_iso": member_since_iso,
            "galleries_created": galleries_count,
            "total_photos": total_photos,
            "total_videos": total_videos,
            "storage_used_bytes": used_bytes,
            "storage_limit_bytes": limit_bytes,
            "storage_used_formatted": used_formatted,
            "storage_limit_formatted": limit_formatted,
            "storage_display": f"{used_formatted} / {limit_formatted}"
        }

    def get_plan_details(self, obj):
        plan = getattr(obj, 'studio_plan', None)
        if not plan and hasattr(obj, 'subscription') and obj.subscription and obj.subscription.plan:
            plan = obj.subscription.plan
        if not plan:
            plan = obj.plan

        if plan:
            plan_name = plan.name
            tier = plan.tier
            billing_cycle = plan.billing_cycle
        else:
            plan_name = "Standard Annual"
            tier = "standard"
            billing_cycle = "annual"


        return {
            "name": plan_name,
            "tier": tier,
            "billing_cycle": billing_cycle,
            "headline": f"You're on {plan_name}",
            "description": "Unlock more storage and premium features."
        }


class WatermarkConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhotographerProfile
        fields = [
            'enable_watermark',
            'watermark_text',
            'watermark_image',
            'watermark_opacity',
            'watermark_position',
        ]


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            'notify_client_visited',
            'notify_photos_downloaded',
            'notify_favorites_selected',
            'notify_storage_alerts',
            'notify_marketing_updates',
        ]


class NotificationSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source='user.username')

    class Meta:
        model = Notification
        fields = [
            'id',
            'user',
            'username',
            'photographer',
            'title',
            'message',
            'event_type',
            'related_gallery_id',
            'is_read',
            'created_at',
        ]
        read_only_fields = ['id', 'username', 'created_at']


class PostImageSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(validators=[validate_non_nude_image])

    class Meta:
        model = PostImage
        fields = ['id', 'post', 'image', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_image(self, value):
        return validate_non_nude_image(value)



class PostFeedbackSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source='user.username')

    class Meta:
        model = PostFeedback
        fields = ['id', 'post', 'user', 'username', 'feedback', 'created_at']
        read_only_fields = ['id', 'username', 'created_at']


class PhotographerPostSerializer(serializers.ModelSerializer):
    images = PostImageSerializer(many=True, read_only=True)
    feedbacks = PostFeedbackSerializer(many=True, read_only=True)
    feedback_count = serializers.IntegerField(source='feedbacks.count', read_only=True)
    photographer_name = serializers.ReadOnlyField(source='photographer.name')
    photo_category_name = serializers.ReadOnlyField(source='photo_category.name')
    uploaded_images = serializers.ListField(
        child=serializers.ImageField(allow_empty_file=False, use_url=False, validators=[validate_non_nude_image]),
        write_only=True,
        required=False
    )

    def validate_uploaded_images(self, value):
        if value:
            for img in value:
                validate_non_nude_image(img)
        return value


    class Meta:
        model = PhotographerPost
        fields = [
            'id',
            'photographer',
            'photographer_name',
            'photo_category',
            'photo_category_name',
            'caption',
            'tech_details',
            'images',
            'uploaded_images',
            'feedbacks',
            'feedback_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'photographer_name',
            'photo_category_name',
            'images',
            'feedbacks',
            'feedback_count',
            'created_at',
            'updated_at',
        ]

    def create(self, validated_data):
        uploaded_images = validated_data.pop('uploaded_images', [])
        post = PhotographerPost.objects.create(**validated_data)
        for image in uploaded_images:
            PostImage.objects.create(post=post, image=image)
        return post

    def update(self, instance, validated_data):
        uploaded_images = validated_data.pop('uploaded_images', [])
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        for image in uploaded_images:
            PostImage.objects.create(post=instance, image=image)
        return instance


class OnboardingSetupSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    occupation = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    studio_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    location = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    avatar = serializers.ImageField(required=False, allow_null=True, validators=[validate_non_nude_image])
    avatar_url = serializers.CharField(max_length=512, required=False, allow_blank=True, default='')

    onboarding_step = serializers.IntegerField(required=False, default=3)


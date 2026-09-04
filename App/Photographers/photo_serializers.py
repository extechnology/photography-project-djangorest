from rest_framework import serializers

from .photo_models import (
    PhotoCategory,
    PhotographerProfile,
    PhotographerPost,
    PostImage,
    PostFeedback,
    Notification,
)


class PhotoCategorySerializer(serializers.ModelSerializer):
    posts_count = serializers.IntegerField(source='posts.count', read_only=True)

    class Meta:
        model = PhotoCategory
        fields = ['id', 'name', 'posts_count']


class PhotographerProfileSerializer(serializers.ModelSerializer):
    user_username = serializers.ReadOnlyField(source='user.username')
    user_email = serializers.ReadOnlyField(source='user.email')
    plan_name = serializers.ReadOnlyField(source='plan.name')

    class Meta:
        model = PhotographerProfile
        fields = [
            'id',
            'user',
            'user_username',
            'user_email',
            'plan',
            'plan_name',
            'name',
            'profile_image',
            'bio',
            'phone',
            'email',
            'address',
        ]
        read_only_fields = ['id', 'user_username', 'user_email', 'plan_name']



class PostImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostImage
        fields = ['id', 'post', 'image', 'created_at']
        read_only_fields = ['id', 'created_at']


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
        child=serializers.ImageField(allow_empty_file=False, use_url=False),
        write_only=True,
        required=False
    )

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


class NotificationSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source='user.username')

    class Meta:
        model = Notification
        fields = ['id', 'user', 'username', 'title', 'message', 'is_read', 'created_at']
        read_only_fields = ['id', 'username', 'created_at']


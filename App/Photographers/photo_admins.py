from django.contrib import admin
from .photo_models import (
    PhotographerProfile,
    NotificationPreference,
    PhotoCategory,
    PhotographerPost,
    PostImage,
    PostFeedback,
    Notification,
)


@admin.register(PhotographerProfile)
class PhotographerProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'studio_name', 'user', 'plan', 'default_template', 'enable_watermark', 'is_onboarded', 'storage_used_bytes')
    search_fields = ('name', 'studio_name', 'email', 'phone')
    list_filter = ('default_template', 'enable_watermark', 'is_onboarded', 'plan')


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('photographer', 'notify_client_visited', 'notify_photos_downloaded', 'notify_favorites_selected', 'notify_storage_alerts')


@admin.register(PhotoCategory)
class PhotoCategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(PhotographerPost)
class PhotographerPostAdmin(admin.ModelAdmin):
    list_display = ('id', 'photographer', 'photo_category', 'created_at')
    list_filter = ('photo_category', 'created_at')
    search_fields = ('photographer__name', 'caption')


@admin.register(PostImage)
class PostImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'post', 'created_at')


@admin.register(PostFeedback)
class PostFeedbackAdmin(admin.ModelAdmin):
    list_display = ('id', 'post', 'user', 'created_at')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'photographer', 'event_type', 'title', 'is_read', 'created_at')
    list_filter = ('event_type', 'is_read', 'created_at')
    search_fields = ('title', 'message')

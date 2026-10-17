from django.contrib import admin
from unfold.admin import ModelAdmin
from .photo_models import (
    PhotographerProfile,
    NotificationPreference,
    PhotoCategory,
    PhotographerPost,
    PostImage,
    PostFeedback,
    Notification,
    Inquiry,
)


@admin.register(PhotographerProfile)
class PhotographerProfileAdmin(ModelAdmin):
    list_display = ('name', 'studio_name', 'user', 'plan', 'default_template', 'enable_watermark', 'is_onboarded', 'storage_used_bytes')
    search_fields = ('name', 'studio_name', 'email', 'phone')
    list_filter = ('default_template', 'enable_watermark', 'is_onboarded', 'plan')
    list_filter_submit = True
    compressed_fields = True
    warn_unsaved_form = True


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(ModelAdmin):
    list_display = ('photographer', 'notify_client_visited', 'notify_photos_downloaded', 'notify_favorites_selected', 'notify_storage_alerts')
    list_filter_submit = True
    compressed_fields = True


@admin.register(PhotoCategory)
class PhotoCategoryAdmin(ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
    list_filter_submit = True
    compressed_fields = True


@admin.register(PhotographerPost)
class PhotographerPostAdmin(ModelAdmin):
    list_display = ('id', 'photographer', 'photo_category', 'created_at')
    list_filter = ('photo_category', 'created_at')
    search_fields = ('photographer__name', 'caption')
    list_filter_submit = True
    compressed_fields = True


@admin.register(PostImage)
class PostImageAdmin(ModelAdmin):
    list_display = ('id', 'post', 'created_at')
    list_filter_submit = True
    compressed_fields = True


@admin.register(PostFeedback)
class PostFeedbackAdmin(ModelAdmin):
    list_display = ('id', 'post', 'user', 'created_at')
    list_filter_submit = True
    compressed_fields = True


@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    list_display = ('id', 'photographer', 'event_type', 'title', 'is_read', 'created_at')
    list_filter = ('event_type', 'is_read', 'created_at')
    search_fields = ('title', 'message')
    list_filter_submit = True
    compressed_fields = True


@admin.register(Inquiry)
class InquiryAdmin(ModelAdmin):
    list_display = ('id', 'client_name', 'client_email', 'client_phone', 'event_type', 'event_date', 'status', 'photographer', 'created_at')
    list_filter = ('status', 'event_type', 'created_at')
    search_fields = ('client_name', 'client_email', 'client_phone', 'location')
    list_filter_submit = True
    compressed_fields = True
    warn_unsaved_form = True

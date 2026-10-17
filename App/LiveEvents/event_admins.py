from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from .event_models import LiveEvent, EventMedia, EventFaceEmbedding


class EventMediaInline(TabularInline):
    model = EventMedia
    extra = 0
    fields = ('original_filename', 'section_title', 'size_mb', 'is_favorite', 'is_cover', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(LiveEvent)
class LiveEventAdmin(ModelAdmin):
    list_display = ('title', 'photographer', 'event_type', 'status', 'event_date', 'guest_views', 'qr_scans', 'is_archived', 'created_at')
    list_filter = ('status', 'event_type', 'is_archived', 'auto_sync_enabled')
    search_fields = ('title', 'client_name', 'slug', 'venue', 'city', 'photographer__email', 'photographer__username')
    readonly_fields = ('id', 'slug', 'guest_views', 'qr_scans', 'ai_searches', 'matches_found', 'downloads_count', 'created_at', 'updated_at')
    inlines = [EventMediaInline]
    list_filter_submit = True
    compressed_fields = True
    warn_unsaved_form = True


@admin.register(EventMedia)
class EventMediaAdmin(ModelAdmin):
    list_display = ('id', 'event', 'original_filename', 'section_title', 'size_mb', 'is_favorite', 'is_cover', 'created_at')
    list_filter = ('section_title', 'is_favorite', 'is_cover')
    search_fields = ('original_filename', 'event__title')
    list_filter_submit = True
    compressed_fields = True


@admin.register(EventFaceEmbedding)
class EventFaceEmbeddingAdmin(ModelAdmin):
    list_display = ('id', 'event_media', 'confidence', 'created_at')
    search_fields = ('event_media__original_filename', 'face_id')
    list_filter_submit = True
    compressed_fields = True

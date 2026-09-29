from django.contrib import admin
from .event_models import LiveEvent, EventMedia, EventFaceEmbedding


class EventMediaInline(admin.TabularInline):
    model = EventMedia
    extra = 0
    fields = ('original_filename', 'section_title', 'size_mb', 'is_favorite', 'is_cover', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(LiveEvent)
class LiveEventAdmin(admin.ModelAdmin):
    list_display = ('title', 'photographer', 'event_type', 'status', 'event_date', 'guest_views', 'qr_scans', 'is_archived', 'created_at')
    list_filter = ('status', 'event_type', 'is_archived', 'auto_sync_enabled')
    search_fields = ('title', 'client_name', 'slug', 'venue', 'city', 'photographer__email', 'photographer__username')
    readonly_fields = ('id', 'slug', 'guest_views', 'qr_scans', 'ai_searches', 'matches_found', 'downloads_count', 'created_at', 'updated_at')
    inlines = [EventMediaInline]


@admin.register(EventMedia)
class EventMediaAdmin(admin.ModelAdmin):
    list_display = ('id', 'event', 'original_filename', 'section_title', 'size_mb', 'is_favorite', 'is_cover', 'created_at')
    list_filter = ('section_title', 'is_favorite', 'is_cover')
    search_fields = ('original_filename', 'event__title')


@admin.register(EventFaceEmbedding)
class EventFaceEmbeddingAdmin(admin.ModelAdmin):
    list_display = ('id', 'event_media', 'confidence', 'created_at')
    search_fields = ('event_media__original_filename', 'face_id')

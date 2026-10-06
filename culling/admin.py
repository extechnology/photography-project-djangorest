# culling/admin.py
from django.contrib import admin
from .models import CullingSession, CullingStagingPhoto, CullingCluster, CullingPricingTier


class CullingStagingPhotoInline(admin.TabularInline):
    model = CullingStagingPhoto
    extra = 0
    readonly_fields = ["original_filename", "size_bytes", "sharpness_score", "status", "is_best_pick", "created_at"]


@admin.register(CullingSession)
class CullingSessionAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "status", "total_photos", "keeper_count", "duplicate_count", "updated_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["title", "user__email", "id"]
    inlines = [CullingStagingPhotoInline]


@admin.register(CullingCluster)
class CullingClusterAdmin(admin.ModelAdmin):
    list_display = ["title", "session", "average_similarity", "total_photos", "duplicates_count"]
    search_fields = ["title", "session__id"]


@admin.register(CullingPricingTier)
class CullingPricingTierAdmin(admin.ModelAdmin):
    list_display = ["name", "price", "photos_limit", "is_active", "display_order"]
    list_filter = ["is_active"]

"""
Gallery Favorites & Bulk Like System
Single-file drop-in implementation for Django REST Framework.
Compatible with Django 4.x / 5.x and DRF 3.14+.
"""

import uuid
from typing import Optional
from django.db import models, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import serializers, status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

# Dynamic / standard imports for models
try:
    from App.Storage.storage_models import Gallery, Media
except ImportError:
    try:
        from galleries.models import Gallery, Media
    except ImportError:
        from .models import Gallery, Media


# ==============================================================================
# 1. SERIALIZERS
# ==============================================================================

class BulkToggleMediaFavoriteSerializer(serializers.Serializer):
    """
    Validates input payload for bulk liking / unliking gallery media.
    """
    media_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="List of media IDs to update. Optional if select_all is True."
    )
    is_favorite = serializers.BooleanField(
        default=True,
        help_text="True to mark as liked, False to remove like."
    )
    select_all = serializers.BooleanField(
        default=False,
        help_text="If True, updates all media across the entire gallery."
    )

    def validate_media_ids(self, value):
        seen = set()
        deduped = []
        for item in value:
            item_str = str(item)
            if item_str not in seen:
                seen.add(item_str)
                deduped.append(item_str)
        return deduped


class SingleToggleMediaFavoriteSerializer(serializers.Serializer):
    """
    Validates input for single photo favorite toggling.
    """
    is_favorite = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Optional explicit target state. If omitted, toggles current state."
    )


class GalleryDetailFavoritesMixin(serializers.Serializer):
    """
    Reusable serializer mixin to provide bulletproof, unpaginated counts.
    """
    favorites_count = serializers.SerializerMethodField()
    total_media_count = serializers.SerializerMethodField()
    photos_count = serializers.SerializerMethodField()
    videos_count = serializers.SerializerMethodField()

    def get_favorites_count(self, obj) -> int:
        # Priority 1: Use O(1) queryset annotation if present
        if hasattr(obj, 'annotated_favorites_count') and obj.annotated_favorites_count is not None:
            return obj.annotated_favorites_count
        # Priority 2: Fallback query directly against the Media table (NEVER sliced)
        media_attr = getattr(obj, 'media', None)
        if media_attr is not None and hasattr(media_attr, 'filter'):
            return media_attr.filter(is_favorite=True).count()
        if hasattr(obj, 'media_items'):
            return obj.media_items.filter(deleted_at__isnull=True, is_favorite=True).count()
        return getattr(obj, 'favorites_count', 0)

    def get_total_media_count(self, obj) -> int:
        if hasattr(obj, 'annotated_total_media_count') and obj.annotated_total_media_count is not None:
            return obj.annotated_total_media_count
        media_attr = getattr(obj, 'media', None)
        if media_attr is not None and hasattr(media_attr, 'count'):
            return media_attr.count()
        if hasattr(obj, 'media_items'):
            return obj.media_items.filter(deleted_at__isnull=True).count()
        return getattr(obj, 'total_media_count', 0)

    def get_photos_count(self, obj) -> int:
        if hasattr(obj, 'annotated_photos_count') and obj.annotated_photos_count is not None:
            return obj.annotated_photos_count
        media_attr = getattr(obj, 'media', None)
        if media_attr is not None and hasattr(media_attr, 'filter'):
            try:
                return media_attr.filter(media_type='photo').count()
            except Exception:
                return media_attr.filter(type='photo').count()
        if hasattr(obj, 'media_items'):
            return obj.media_items.filter(deleted_at__isnull=True, media_type='photo').count()
        return getattr(obj, 'photos_count', 0)

    def get_videos_count(self, obj) -> int:
        if hasattr(obj, 'annotated_videos_count') and obj.annotated_videos_count is not None:
            return obj.annotated_videos_count
        media_attr = getattr(obj, 'media', None)
        if media_attr is not None and hasattr(media_attr, 'filter'):
            try:
                return media_attr.filter(media_type='video').count()
            except Exception:
                return media_attr.filter(type='video').count()
        if hasattr(obj, 'media_items'):
            return obj.media_items.filter(deleted_at__isnull=True, media_type='video').count()
        return getattr(obj, 'videos_count', 0)


# ==============================================================================
# 2. QUERYSET OPTIMIZATION HELPER
# ==============================================================================

def get_annotated_gallery_queryset(photographer_user=None):
    """
    Returns Gallery queryset with database-level aggregate counts annotated in SQL.
    Ensures 0 extra queries and zero pagination-coupling.
    """
    qs = Gallery.objects.all()

    # Apply photographer ownership filtering if a user is supplied
    if photographer_user is not None and hasattr(photographer_user, 'is_authenticated') and photographer_user.is_authenticated:
        if not (getattr(photographer_user, 'is_staff', False) or getattr(photographer_user, 'is_superuser', False)):
            profile = getattr(photographer_user, 'photographer_profile', None) or getattr(photographer_user, 'photographer', None)
            if profile:
                qs = qs.filter(photographer=profile)
            else:
                qs = qs.filter(Q(photographer__user=photographer_user) | Q(photographer__user_id=photographer_user.id))
    elif photographer_user is not None and hasattr(photographer_user, 'galleries'):
        qs = qs.filter(photographer=photographer_user)

    # Determine reverse relationship name and field names on Media
    media_rel = 'media_items' if any(
        f.name == 'media_items' or getattr(f, 'related_name', None) == 'media_items'
        for f in Gallery._meta.get_fields() if f.is_relation
    ) else 'media'

    media_model = Media
    has_deleted_at = hasattr(media_model, 'deleted_at')
    type_field = 'media_type' if hasattr(media_model, 'media_type') else 'type'

    base_filter = {f"{media_rel}__deleted_at__isnull": True} if has_deleted_at else {}
    fav_filter = {f"{media_rel}__is_favorite": True, **base_filter}
    photo_filter = {f"{media_rel}__{type_field}": 'photo', **base_filter}
    video_filter = {f"{media_rel}__{type_field}": 'video', **base_filter}

    return qs.annotate(
        annotated_total_media_count=Count(media_rel, filter=Q(**base_filter) if base_filter else None, distinct=True),
        annotated_favorites_count=Count(media_rel, filter=Q(**fav_filter), distinct=True),
        annotated_photos_count=Count(media_rel, filter=Q(**photo_filter), distinct=True),
        annotated_videos_count=Count(media_rel, filter=Q(**video_filter), distinct=True),
    )


# ==============================================================================
# 3. VIEWS
# ==============================================================================

class BulkToggleMediaFavoriteView(APIView):
    """
    POST /api/galleries/<gallery_id>/media/bulk-favorite/
    
    Accepts:
    {
        "media_ids": ["uuid-1", "uuid-2"],
        "is_favorite": true,
        "select_all": false
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, gallery_id):
        # 1. Resolve gallery owned by authenticated photographer
        gallery_qs = get_annotated_gallery_queryset(request.user)
        try:
            gallery_uuid = uuid.UUID(str(gallery_id))
            gallery = get_object_or_404(gallery_qs, id=gallery_uuid)
        except (ValueError, TypeError):
            gallery = get_object_or_404(gallery_qs, id=gallery_id)

        # 2. Validate payload
        serializer = BulkToggleMediaFavoriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        is_favorite = serializer.validated_data['is_favorite']
        select_all = serializer.validated_data['select_all']
        media_ids = serializer.validated_data['media_ids']

        if not select_all and not media_ids:
            return Response(
                {"error": "media_ids must be provided unless select_all is true."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3. Atomic bulk update directly in SQL
        with transaction.atomic():
            target_media = gallery.media.all() if hasattr(gallery.media, 'all') else gallery.media
            if not select_all:
                target_media = target_media.filter(id__in=media_ids)
            if hasattr(Media, 'deleted_at'):
                target_media = target_media.filter(deleted_at__isnull=True)

            updated_count = target_media.update(is_favorite=is_favorite)

            # 4. Compute fresh total counts across the full gallery
            fresh_media = gallery.media.all() if hasattr(gallery.media, 'all') else gallery.media
            fresh_favorites_count = fresh_media.filter(is_favorite=True).count()
            total_media_count = fresh_media.count()

            # Synchronize cached favorites_count field on gallery model
            if hasattr(gallery, 'favorites_count'):
                gallery.favorites_count = fresh_favorites_count
                gallery.save(update_fields=['favorites_count'])

        return Response({
            "status": "success",
            "is_favorite": is_favorite,
            "updated_count": updated_count,
            "favorites_count": fresh_favorites_count,
            "total_media_count": total_media_count,
            "media_ids": [str(m) for m in media_ids],
            "select_all": select_all,
        }, status=status.HTTP_200_OK)


class ToggleMediaFavoriteView(APIView):
    """
    POST /api/galleries/<gallery_id>/media/<media_id>/favorite/
    
    Accepts:
    {
        "is_favorite": true
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, gallery_id, media_id):
        gallery_qs = get_annotated_gallery_queryset(request.user)
        try:
            gallery_uuid = uuid.UUID(str(gallery_id))
            gallery = get_object_or_404(gallery_qs, id=gallery_uuid)
        except (ValueError, TypeError):
            gallery = get_object_or_404(gallery_qs, id=gallery_id)

        media_qs = gallery.media.all() if hasattr(gallery.media, 'all') else gallery.media
        try:
            media_uuid = uuid.UUID(str(media_id))
            media_item = get_object_or_404(media_qs, id=media_uuid)
        except (ValueError, TypeError):
            media_item = get_object_or_404(media_qs, id=media_id)

        serializer = SingleToggleMediaFavoriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        explicit_state = serializer.validated_data.get('is_favorite')
        if explicit_state is not None:
            media_item.is_favorite = explicit_state
        else:
            media_item.is_favorite = not media_item.is_favorite

        media_item.save(update_fields=['is_favorite'])

        fresh_media = gallery.media.all() if hasattr(gallery.media, 'all') else gallery.media
        fresh_favorites_count = fresh_media.filter(is_favorite=True).count()

        if hasattr(gallery, 'favorites_count'):
            gallery.favorites_count = fresh_favorites_count
            gallery.save(update_fields=['favorites_count'])

        return Response({
            "status": "success",
            "id": str(media_item.id),
            "is_favorite": media_item.is_favorite,
            "favorites_count": fresh_favorites_count,
        }, status=status.HTTP_200_OK)


# ==============================================================================
# 4. URL ROUTING
# ==============================================================================

urlpatterns = [
    path(
        'galleries/<uuid:gallery_id>/media/bulk-favorite/',
        BulkToggleMediaFavoriteView.as_view(),
        name='gallery-media-bulk-favorite'
    ),
    path(
        'galleries/<str:gallery_id>/media/bulk-favorite/',
        BulkToggleMediaFavoriteView.as_view(),
        name='gallery-media-bulk-favorite-str'
    ),
    path(
        'galleries/<uuid:gallery_id>/media/<uuid:media_id>/favorite/',
        ToggleMediaFavoriteView.as_view(),
        name='gallery-media-single-favorite'
    ),
    path(
        'galleries/<str:gallery_id>/media/<str:media_id>/favorite/',
        ToggleMediaFavoriteView.as_view(),
        name='gallery-media-single-favorite-str'
    ),
]

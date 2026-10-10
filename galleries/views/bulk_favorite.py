"""
EX SHARE Atelier — Reusable Bulk Media Favorite & Unfavorite Module
=====================================================================
File: bulk_favorite.py (or copy into galleries/views/bulk_favorite.py)
Framework: Django 4+ / Django 5+ & Django REST Framework (DRF)

FEATURES:
- Atomic batch update (executes a single SQL UPDATE query, 0 N+1 overhead).
- Supports both Bulk Liking (is_favorite=True) and Bulk Unliking (is_favorite=False).
- Dynamic model resolution (works with MediaItem, GalleryMedia, Media, or Photo).
- Re-calculates and caches `gallery.favorites_count` automatically.
- Dual endpoint support:
    * Nested:   POST /api/galleries/<gallery_id>/media/bulk-favorite/
    * Flat:     POST /api/galleries/media/bulk-favorite/
- Built-in Swagger/OpenAPI documentation schema & granular error handling.
"""

from typing import List, Optional, Tuple, Any
import logging
import uuid
from django.db import transaction, models
from django.apps import apps
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, serializers

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Optional OpenAPI / Swagger Decorators
# -----------------------------------------------------------------------------
try:
    from drf_spectacular.utils import extend_schema, OpenApiResponse
    spectacular_decorator = extend_schema(
        summary="Bulk Favorite / Unfavorite Media Items",
        description="Atomic batch update to mark media items as favorites or unfavorites in a gallery.",
        responses={
            200: OpenApiResponse(description="Successfully updated media favorites"),
            400: OpenApiResponse(description="Invalid payload or parameters"),
            404: OpenApiResponse(description="Gallery not found or access denied"),
        }
    )
except ImportError:
    spectacular_decorator = lambda f: f


# -----------------------------------------------------------------------------
# 1. Dynamic Model Resolvers (Zero-configuration compatibility)
# -----------------------------------------------------------------------------
def get_gallery_model() -> type[models.Model]:
    """Dynamically resolves the Gallery model across installed apps."""
    for model_name in ['Gallery', 'PhotoGallery', 'Album']:
        for app_label in ['galleries', 'gallery', 'App', 'Storage', 'core', 'studio']:
            try:
                return apps.get_model(app_label, model_name)
            except (LookupError, ValueError):
                continue
    # Fallback to direct import if standard path exists
    try:
        from galleries.models import Gallery
        return Gallery
    except ImportError:
        pass
    try:
        from App.Storage.storage_models import Gallery
        return Gallery
    except ImportError:
        raise RuntimeError("Could not find Gallery model. Please adjust the app label.")


def get_media_model() -> type[models.Model]:
    """Dynamically resolves the MediaItem / Photo model across installed apps."""
    for model_name in ['MediaItem', 'GalleryMedia', 'Media', 'Photo', 'Photograph']:
        for app_label in ['galleries', 'gallery', 'App', 'Storage', 'core', 'media']:
            try:
                return apps.get_model(app_label, model_name)
            except (LookupError, ValueError):
                continue
    try:
        from galleries.models import MediaItem
        return MediaItem
    except ImportError:
        pass
    try:
        from App.Storage.storage_models import Media
        return Media
    except ImportError:
        raise RuntimeError("Could not find MediaItem model. Please adjust the app label.")


# -----------------------------------------------------------------------------
# 2. Serializers
# -----------------------------------------------------------------------------
class BulkMediaFavoriteRequestSerializer(serializers.Serializer):
    """
    Validates request payload for bulk liking / unliking media items.
    """
    media_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="List of media IDs to update. Optional if select_all is True."
    )
    is_favorite = serializers.BooleanField(
        default=True,
        help_text="Set True to mark as liked/favorite, False to remove like."
    )
    select_all = serializers.BooleanField(
        default=False,
        help_text="If True, updates all media across the entire gallery."
    )
    gallery_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Gallery UUID (optional if provided in route URL parameter)."
    )

    def validate(self, attrs):
        select_all = attrs.get('select_all', False)
        media_ids = attrs.get('media_ids', [])
        if not select_all and not media_ids:
            raise serializers.ValidationError("media_ids must be provided unless select_all is true.")
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for item in media_ids:
            item_str = str(item)
            if item_str not in seen:
                seen.add(item_str)
                deduped.append(item)
        attrs['media_ids'] = deduped
        return attrs


class BulkMediaFavoriteResponseSerializer(serializers.Serializer):
    """
    Standard schema for the bulk favorite response.
    """
    status = serializers.CharField(default="success")
    message = serializers.CharField()
    updated_count = serializers.IntegerField()
    is_favorite = serializers.BooleanField()
    select_all = serializers.BooleanField(default=False)
    media_ids = serializers.ListField(child=serializers.CharField())
    favorites_count = serializers.IntegerField()
    total_media_count = serializers.IntegerField(required=False)


# -----------------------------------------------------------------------------
# 3. Service Layer (Reusable Core Business Logic)
# -----------------------------------------------------------------------------
class BulkFavoriteService:
    """
    Encapsulates database operations for liking and unliking gallery media in bulk.
    Can be used by API views, Celery background tasks, or management commands.
    """

    @classmethod
    def execute(
        cls,
        gallery: Any,
        media_ids: List[Any],
        is_favorite: bool,
        select_all: bool = False
    ) -> Tuple[int, int]:
        """
        Executes atomic bulk update and recalculates total favorites.

        Returns:
            Tuple[updated_count, total_favorites_count]
        """
        MediaModel = get_media_model()

        with transaction.atomic():
            # 1. Single efficient SQL UPDATE query (Zero N+1 query overhead)
            media_qs = MediaModel.objects.filter(gallery=gallery)
            if not select_all:
                media_qs = media_qs.filter(id__in=media_ids)
            if hasattr(MediaModel, 'deleted_at'):
                media_qs = media_qs.filter(deleted_at__isnull=True)

            updated_count = media_qs.update(is_favorite=is_favorite)

            # 2. Calculate new total favorites count for the gallery (unpaginated)
            count_qs = MediaModel.objects.filter(
                gallery=gallery,
                is_favorite=True
            )
            if hasattr(MediaModel, 'deleted_at'):
                count_qs = count_qs.filter(deleted_at__isnull=True)
            total_favorites = count_qs.count()

            # 3. Synchronize cached favorites_count field on gallery model if it exists
            update_fields = []
            if hasattr(gallery, 'favorites_count'):
                gallery.favorites_count = total_favorites
                update_fields.append('favorites_count')

            if update_fields:
                gallery.save(update_fields=update_fields)

            logger.info(
                f"[BulkFavoriteService] Gallery {gallery.id}: "
                f"{'liked' if is_favorite else 'unliked'} {updated_count} items. "
                f"Total favorites now: {total_favorites}."
            )

            return updated_count, total_favorites


# -----------------------------------------------------------------------------
# 4. API View
# -----------------------------------------------------------------------------
class BulkMediaFavoriteAPIView(APIView):
    """
    API Endpoint for bulk liking or unliking media items in a gallery.

    URL Patterns:
      - POST /api/galleries/<uuid:gallery_id>/media/bulk-favorite/
      - POST /api/galleries/media/bulk-favorite/ (with gallery_id in body)

    Headers:
      - Authorization: Bearer <jwt_token>

    Request Body:
      {
        "media_ids": ["8f731110-0ec6-4f40-8f96-3c588e401d4a", "..."],
        "is_favorite": true
      }

    Response (200 OK):
      {
        "status": "success",
        "message": "Successfully liked 5 photos.",
        "updated_count": 5,
        "is_favorite": true,
        "media_ids": ["8f731110-0ec6-4f40-8f96-3c588e401d4a", "..."],
        "favorites_count": 42
      }
    """
    permission_classes = [permissions.IsAuthenticated]

    @spectacular_decorator
    def post(self, request, gallery_id=None, *args, **kwargs) -> Response:
        serializer = BulkMediaFavoriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 1. Determine target gallery ID (from URL parameter or request payload)
        target_gallery_id = gallery_id or serializer.validated_data.get('gallery_id')
        if not target_gallery_id:
            return Response(
                {
                    "status": "error",
                    "detail": "Gallery ID must be specified in the URL or the request body as 'gallery_id'."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Fetch gallery and verify ownership
        GalleryModel = get_gallery_model()
        try:
            gallery_query = GalleryModel.objects.filter(id=target_gallery_id)

            # Enforce user tenancy/ownership if gallery has a 'user' or 'photographer' foreign key
            is_admin = getattr(request.user, 'is_staff', False) or getattr(request.user, 'is_superuser', False)
            if not is_admin:
                if hasattr(GalleryModel, 'user'):
                    gallery_query = gallery_query.filter(user=request.user)
                elif hasattr(GalleryModel, 'photographer') and hasattr(request.user, 'photographer_profile'):
                    gallery_query = gallery_query.filter(photographer=request.user.photographer_profile)
                elif hasattr(GalleryModel, 'photographer'):
                    gallery_query = gallery_query.filter(photographer__user=request.user)

            gallery = gallery_query.first()
        except (ValidationError, ValueError):
            gallery = None

        if not gallery:
            return Response(
                {
                    "status": "error",
                    "detail": f"Gallery '{target_gallery_id}' not found or access denied."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        media_ids = serializer.validated_data.get('media_ids', [])
        is_favorite = serializer.validated_data['is_favorite']
        select_all = serializer.validated_data.get('select_all', False)

        try:
            # 3. Execute bulk update via service layer
            updated_count, total_favorites = BulkFavoriteService.execute(
                gallery=gallery,
                media_ids=media_ids,
                is_favorite=is_favorite,
                select_all=select_all
            )

            fresh_media = gallery.media.all() if hasattr(gallery.media, 'all') else gallery.media
            total_media_count = fresh_media.count()

            action_verb = "liked" if is_favorite else "unliked"
            response_data = {
                "status": "success",
                "message": f"Successfully {action_verb} {updated_count} media items.",
                "updated_count": updated_count,
                "is_favorite": is_favorite,
                "select_all": select_all,
                "media_ids": [str(m_id) for m_id in media_ids],
                "favorites_count": total_favorites,
                "total_media_count": total_media_count,
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except ValidationError as e:
            return Response({"status": "error", "detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception(f"[BulkMediaFavoriteAPIView] Unexpected error: {e}")
            return Response(
                {"status": "error", "detail": "An internal server error occurred while processing bulk favorites."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# -----------------------------------------------------------------------------
# 5. URL Patterns (Include directly into your urls.py)
# -----------------------------------------------------------------------------
from django.urls import path

urlpatterns = [
    # Primary nested endpoint (matches frontend GalleryApi.ts)
    path(
        'api/galleries/<uuid:gallery_id>/media/bulk-favorite/',
        BulkMediaFavoriteAPIView.as_view(),
        name='gallery-media-bulk-favorite'
    ),
    # Secondary un-nested fallback endpoint
    path(
        'api/galleries/media/bulk-favorite/',
        BulkMediaFavoriteAPIView.as_view(),
        name='gallery-media-bulk-favorite-flat'
    ),
]

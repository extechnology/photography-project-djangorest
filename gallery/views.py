import uuid
from django.db import models
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from gallery.models import (
    Gallery,
    GalleryMedia,
    GalleryGuestSession,
    GalleryStoryVideo,
)
from gallery.serializers import (
    GalleryDetailSerializer,
    ReorderGalleryMediaSerializer,
)
from gallery.services.reorder import reorder_gallery_media


def get_gallery_by_id_or_slug(id_or_slug):
    """
    Robust lookup supporting both UUID string and slug.
    """
    try:
        val = uuid.UUID(str(id_or_slug))
        return get_object_or_404(Gallery, models.Q(id=val) | models.Q(slug=str(id_or_slug)))
    except (ValueError, AttributeError):
        return get_object_or_404(Gallery, slug=str(id_or_slug))


class GalleryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = GalleryDetailSerializer

    def get_queryset(self):
        user = self.request.user
        profile = getattr(user, 'photographer_profile', None)
        qs = Gallery.objects.all()
        if profile:
            qs = qs.filter(photographer=profile)
        else:
            qs = qs.filter(photographer__user=user)
        return qs.prefetch_related(
            Prefetch('media_items', queryset=GalleryMedia.objects.order_by('order', 'created_at'))
        )

    def get_object(self):
        lookup = self.kwargs.get('pk') or self.kwargs.get('gallery_id')
        if lookup:
            queryset = self.filter_queryset(self.get_queryset())
            try:
                return queryset.get(id=lookup)
            except Exception:
                try:
                    return queryset.get(slug=lookup)
                except Exception:
                    pass
        return super().get_object()

    # -------------------------------------------------------------
    # POST /api/galleries/{id}/media/reorder/
    # -------------------------------------------------------------
    @action(detail=True, methods=['post'], url_path='media/reorder')
    def reorder_media(self, request, pk=None):
        gallery = self.get_object()

        serializer = ReorderGalleryMediaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        updated_count = reorder_gallery_media(
            gallery=gallery,
            media_ids=data.get('media_ids'),
            media_id=data.get('media_id'),
            action=data.get('action'),
            target_position=data.get('target_position')
        )

        return Response(
            {
                "status": "success",
                "gallery_id": str(gallery.id),
                "updated_count": updated_count,
                "message": "Gallery media sequence reordered successfully."
            },
            status=status.HTTP_200_OK
        )



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
    GalleryGuestSessionSerializer,
    GalleryStoryVideoSerializer,
    CreateStoryVideoPayloadSerializer,
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


class GalleryGuestSessionView(APIView):
    """
    POST /api/public/galleries/{id_or_slug}/guest-session/
    Registers or updates an anonymous guest identity for the gallery.
    Stores guest token and creator name so their videos are kept separately.
    """
    permission_classes = [AllowAny]

    def post(self, request, id_or_slug):
        gallery = get_gallery_by_id_or_slug(id_or_slug)
        guest_token = request.data.get('guest_token')
        name = request.data.get('name', 'Guest Creator')
        email = request.data.get('email', '')
        phone = request.data.get('phone', '')

        if not guest_token:
            return Response({"error": "guest_token is required."}, status=status.HTTP_400_BAD_REQUEST)

        guest_session, created = GalleryGuestSession.objects.get_or_create(
            gallery=gallery,
            guest_token=guest_token,
            defaults={
                'name': name,
                'email': email,
                'phone': phone,
                'ip_address': request.META.get('REMOTE_ADDR')
            }
        )

        if not created:
            if name and name != 'Guest Creator':
                guest_session.name = name
            if email:
                guest_session.email = email
            if phone:
                guest_session.phone = phone
            guest_session.save(update_fields=['name', 'email', 'phone', 'last_active_at'])

        serializer = GalleryGuestSessionSerializer(guest_session)
        return Response(serializer.data, status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED)


class GalleryStoryVideoListCreateView(APIView):
    """
    GET  /api/public/galleries/{id_or_slug}/story-videos/
    POST /api/public/galleries/{id_or_slug}/story-videos/
    Lists or saves story reel videos created by gallery guests.
    """
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, id_or_slug):
        gallery = get_gallery_by_id_or_slug(id_or_slug)
        guest_token = request.query_params.get('guest_token')
        only_mine = request.query_params.get('mine') == 'true'

        qs = GalleryStoryVideo.objects.filter(gallery=gallery)

        # Filter to only the current guest/user creations if requested
        if only_mine and guest_token:
            qs = qs.filter(guest_session__guest_token=guest_token)
        elif only_mine and request.user.is_authenticated:
            qs = qs.filter(user=request.user)

        serializer = GalleryStoryVideoSerializer(qs, many=True, context={'request': request})
        return Response({
            "count": qs.count(),
            "results": serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request, id_or_slug):
        gallery = get_gallery_by_id_or_slug(id_or_slug)
        serializer = CreateStoryVideoPayloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        video_file = data['video']
        guest_token = data.get('guest_token')
        guest_session = None

        if guest_token:
            guest_session = GalleryGuestSession.objects.filter(gallery=gallery, guest_token=guest_token).first()
            if not guest_session:
                guest_session = GalleryGuestSession.objects.create(
                    gallery=gallery,
                    guest_token=guest_token,
                    name=data.get('creator_name', 'Guest Creator')
                )

        story_video = GalleryStoryVideo.objects.create(
            gallery=gallery,
            guest_session=guest_session,
            user=request.user if request.user.is_authenticated else None,
            creator_name=data.get('creator_name', 'Guest Creator'),
            title=data.get('title', 'Our Story'),
            subtitle=data.get('subtitle', ''),
            aspect_ratio=data.get('aspect_ratio', '9:16'),
            transition_style=data.get('transition_style', 'ken-burns'),
            duration_seconds=data.get('duration_seconds', 15.0),
            music_title=data.get('music_title', ''),
            music_artist=data.get('music_artist', ''),
            music_url=data.get('music_url', ''),
            photo_ids=data.get('photo_ids', []),
            video_file=video_file,
            file_size_bytes=video_file.size
        )

        response_serializer = GalleryStoryVideoSerializer(story_video, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class TrackStoryVideoActionView(APIView):
    """
    POST /api/public/galleries/{id_or_slug}/story-videos/{video_id}/track/
    Increments download or share count for telemetry.
    """
    permission_classes = [AllowAny]

    def post(self, request, id_or_slug, video_id):
        gallery = get_gallery_by_id_or_slug(id_or_slug)
        story_video = get_object_or_404(GalleryStoryVideo, id=video_id, gallery=gallery)
        action = request.data.get('action', 'download')

        if action == 'download':
            story_video.download_count += 1
            story_video.save(update_fields=['download_count'])
        elif action == 'share':
            story_video.share_count += 1
            story_video.save(update_fields=['share_count'])

        return Response({"status": "success", "action": action}, status=status.HTTP_200_OK)

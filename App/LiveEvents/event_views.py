import io
import os
from datetime import datetime, timedelta
import uuid
from PIL import Image
from django.db import models, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import NotFound

from .event_models import LiveEvent, EventMedia
from .event_serializers import (
    LiveEventListSerializer,
    LiveEventDetailSerializer,
    LiveEventUpdateSerializer,
    EventMediaSerializer,
    PublicEventPortalSerializer,
    MoveEventToGallerySerializer,
)
import base64
import threading
from .event_tasks import process_face_embeddings_task, compare_selfie_faces_task, run_indexing_safely
from App.Storage.storage_models import Gallery, Media as GalleryMedia, GallerySection
from App.Photographers.photo_models import PhotographerProfile


def _trigger_face_indexing(media_id_str: str):
    """Triggers face indexing via Celery and background thread fallback"""
    try:
        process_face_embeddings_task.delay(media_id_str)
    except Exception:
        pass
    threading.Thread(target=run_indexing_safely, args=(media_id_str,), daemon=True).start()


class LiveEventViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'pk'
    lookup_value_regex = '[^/]+'  # Allows slugs containing hyphens, underscores, and alphanumeric chars

    def get_queryset(self):
        """
        Return all events owned by the authenticated photographer.
        CRITICAL: Do NOT exclude status='trash' by default!
        The frontend dashboard fetches all events once and filters in-memory
        to compute live counters for Live, Upcoming, Past, and Trash tabs.
        """
        user = self.request.user
        if user.is_staff or user.is_superuser:
            qs = LiveEvent.objects.all()
        else:
            qs = LiveEvent.objects.filter(photographer=user)

        status_param = self.request.query_params.get('status')
        search_param = self.request.query_params.get('search')

        if status_param == 'trash':
            qs = qs.filter(models.Q(status='trash') | models.Q(is_archived=True))
        elif status_param == 'past':
            qs = qs.filter(status='completed', is_archived=False)
        elif status_param and status_param != 'all':
            qs = qs.filter(status=status_param, is_archived=False)

        if search_param:
            qs = qs.filter(
                models.Q(title__icontains=search_param)
                | models.Q(client_name__icontains=search_param)
                | models.Q(venue__icontains=search_param)
                | models.Q(city__icontains=search_param)
            )

        from django.db.models.functions import Coalesce
        qs = qs.annotate(
            total_size_bytes=Coalesce(models.Sum('media__file_size'), 0),
            photos_count=models.Count('media', filter=models.Q(media__media_type='photo'), distinct=True),
            videos_count=models.Count('media', filter=models.Q(media__media_type='video'), distinct=True),
        )

        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return LiveEventUpdateSerializer
        if self.action == 'retrieve':
            return LiveEventDetailSerializer
        return LiveEventListSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_object(self):
        """
        Resilient Resolver: Supports retrieving events by either UUID primary key OR string slug.
        Prevents UUID ValidationError on slugs like 'sample-e133fb'.
        """
        lookup_val = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field)

        # For restore or destroy actions, include archived events
        if self.action in ['restore', 'restore_event', 'destroy', 'retrieve']:
            queryset = LiveEvent.objects.filter(photographer=self.request.user)
        else:
            queryset = self.filter_queryset(self.get_queryset())

        is_uuid = False
        try:
            uuid.UUID(str(lookup_val))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid:
            obj = queryset.filter(id=lookup_val).first()
        else:
            obj = queryset.filter(slug=lookup_val).first()

        if not obj:
            unfiltered_exists = (
                LiveEvent.objects.filter(id=lookup_val).exists()
                if is_uuid
                else LiveEvent.objects.filter(slug=lookup_val).exists()
            )
            if unfiltered_exists:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("You do not have permission to access or edit this event.")
            raise NotFound(detail=f"Event '{lookup_val}' not found.")

        self.check_object_permissions(self.request, obj)
        return obj

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated_event = serializer.save()

        detail_serializer = LiveEventDetailSerializer(updated_event, context={'request': request})
        return Response(detail_serializer.data, status=status.HTTP_200_OK)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        # 1. Enforce Plan Limits
        subscription = getattr(request.user, 'subscription', None)
        if not subscription and hasattr(request.user, 'photographer_profile'):
            subscription = getattr(request.user.photographer_profile, 'subscription', None)

        active_count = LiveEvent.objects.filter(
            photographer=request.user, is_archived=False
        ).exclude(status='completed').count()

        if subscription and getattr(subscription, 'plan', None):
            plan = subscription.plan
            is_unlimited = getattr(plan, 'is_unlimited_events', False) or (getattr(plan, 'max_events', 0) == 0)
            if not is_unlimited:
                if active_count >= plan.max_events:
                    return Response(
                        {
                            "error_code": "EVENT_LIMIT_EXCEEDED",
                            "message": f"You have reached your limit of {plan.max_events} active events."
                        },
                        status=status.HTTP_403_FORBIDDEN
                    )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = serializer.save(photographer=request.user)
        return Response(
            LiveEventDetailSerializer(event, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )

    def destroy(self, request, *args, **kwargs):
        """
        Two-stage deletion:
        - DELETE /api/events/{id}/ -> Soft delete: marks status='trash'.
        - DELETE /api/events/{id}/?permanent=true -> Permanent purge: removes from database.
        """
        instance = self.get_object()
        is_permanent = request.query_params.get('permanent', '').lower() in ['true', '1', 'yes']

        if is_permanent:
            for media in instance.media.all():
                try:
                    media.file.delete(save=False)
                    if media.thumbnail:
                        media.thumbnail.delete(save=False)
                except Exception:
                    pass
            instance.delete()
            return Response(
                {
                    "success": True,
                    "permanent": True,
                    "message": f'Event "{instance.title}" and its media have been permanently deleted.'
                },
                status=status.HTTP_200_OK
            )
        else:
            instance.status = 'trash'
            instance.is_archived = True
            now = timezone.now()
            instance.deleted_at = now
            instance.archived_at = now
            instance.save(update_fields=['status', 'is_archived', 'deleted_at', 'archived_at', 'updated_at'])
            return Response(
                {
                    "success": True,
                    "permanent": False,
                    "status": "trash",
                    "message": f'Event "{instance.title}" has been moved to Trash (auto-purged after 15 days).'
                },
                status=status.HTTP_200_OK
            )

    @action(detail=False, methods=['get'], url_path='counts')
    def get_status_counts(self, request):
        """Returns tab counts for live, upcoming, past/completed, trash, and total."""
        base_qs = LiveEvent.objects.filter(photographer=request.user)
        live_count = base_qs.filter(status='live', is_archived=False).count()
        upcoming_count = base_qs.filter(status='upcoming', is_archived=False).count()
        past_count = base_qs.filter(status='completed', is_archived=False).count()
        trash_count = base_qs.filter(models.Q(status='trash') | models.Q(is_archived=True)).count()
        all_count = base_qs.filter(is_archived=False).count()

        return Response({
            "live": live_count,
            "upcoming": upcoming_count,
            "past": past_count,
            "trash": trash_count,
            "all": all_count,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='restore')
    def restore(self, request, pk=None):
        """
        Restore an event from Trash back to active/upcoming.
        Endpoint: POST /api/events/{id}/restore/
        Payload: {"target_status": "upcoming"} (or "live")
        """
        instance = self.get_object()
        target_status = request.data.get('target_status', 'upcoming')
        if target_status not in ['upcoming', 'live', 'completed']:
            target_status = 'upcoming'

        instance.status = target_status
        instance.is_archived = False
        instance.deleted_at = None
        instance.archived_at = None
        instance.save(update_fields=['status', 'is_archived', 'deleted_at', 'archived_at', 'updated_at'])
        return Response(
            LiveEventDetailSerializer(instance, context={'request': request}).data,
            status=status.HTTP_200_OK
        )

    def restore_event(self, request, pk=None):
        return self.restore(request, pk=pk)

    @action(detail=True, methods=['post'], url_path='tether')
    def upload_tether_photo(self, request, pk=None):
        """
        Ingest endpoint for camera shots, folder watcher, and single manual uploads.
        Accepts BOTH photos and video files (mp4, mov, webm, etc.).
        """
        event = self.get_object()
        file_obj = request.FILES.get('photo') or request.FILES.get('video') or request.FILES.get('file')

        if not file_obj:
            return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        # Detect video by mime type, file extension, or explicit type payload
        content_type = getattr(file_obj, 'content_type', '') or ''
        filename = (file_obj.name or '').lower()
        is_video = (
            content_type.startswith('video/')
            or any(filename.endswith(ext) for ext in ['.mp4', '.mov', '.webm', '.mkv', '.avi', '.m4v'])
            or request.data.get('type') == 'video'
        )

        # CLEAN DEFAULT: HIGHLIGHTS instead of CEREMONY
        raw_section = request.data.get('section_title')
        section_title = raw_section.strip().upper() if raw_section and raw_section.strip() else 'HIGHLIGHTS'

        # Pre-calculate dimensions and aspect ratio if photo
        width, height, aspect_ratio = 1920, 1080, 1.77
        if not is_video:
            try:
                content = file_obj.read()
                file_obj.seek(0)
                with Image.open(io.BytesIO(content)) as img:
                    width, height = img.size
                    if height > 0:
                        aspect_ratio = round(width / height, 2)
            except Exception:
                pass

        media = EventMedia.objects.create(
            event=event,
            original_filename=file_obj.name,
            file=file_obj,
            media_type='video' if is_video else 'photo',
            section_title=section_title,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            file_size=file_obj.size,
            size_mb=round(file_obj.size / (1024 * 1024), 2)
        )
        media.file_url = media.file.url
        media.thumbnail_url = media.file.url
        media.save(update_fields=['file_url', 'thumbnail_url'])

        # Only photos trigger biometric face embedding extraction
        if not is_video:
            _trigger_face_indexing(str(media.id))

        return Response(
            EventMediaSerializer(media, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'], url_path='upload')
    def bulk_upload_media(self, request, pk=None):
        """
        Batch upload endpoint matching the Studio Gallery upload experience.
        Ingests lists of photos and videos with section categorization in a single request.
        """
        event = self.get_object()
        photos = request.FILES.getlist('photos')
        videos = request.FILES.getlist('videos')
        # Also support single 'files' or 'photo'/'video' list fallbacks
        if not photos and not videos:
            all_files = request.FILES.getlist('files')
            for f in all_files:
                fn = (f.name or '').lower()
                ct = getattr(f, 'content_type', '') or ''
                if ct.startswith('video/') or any(fn.endswith(ext) for ext in ['.mp4', '.mov', '.webm', '.mkv', '.avi']):
                    videos.append(f)
                else:
                    photos.append(f)

        # CLEAN DEFAULT: HIGHLIGHTS instead of CEREMONY
        raw_section = request.data.get('section_title')
        section_title = raw_section.strip().upper() if raw_section and raw_section.strip() else 'HIGHLIGHTS'

        created_items = []

        for p in photos:
            width, height, aspect_ratio = 1920, 1080, 1.77
            try:
                content = p.read()
                p.seek(0)
                with Image.open(io.BytesIO(content)) as img:
                    width, height = img.size
                    if height > 0:
                        aspect_ratio = round(width / height, 2)
            except Exception:
                pass

            media = EventMedia.objects.create(
                event=event,
                original_filename=p.name,
                file=p,
                media_type='photo',
                section_title=section_title,
                width=width,
                height=height,
                aspect_ratio=aspect_ratio,
                file_size=p.size,
                size_mb=round(p.size / (1024 * 1024), 2)
            )
            media.file_url = media.file.url
            media.thumbnail_url = media.file.url
            media.save(update_fields=['file_url', 'thumbnail_url'])
            _trigger_face_indexing(str(media.id))
            created_items.append(media)

        for v in videos:
            media = EventMedia.objects.create(
                event=event,
                original_filename=v.name,
                file=v,
                media_type='video',
                section_title=section_title,
                file_size=v.size,
                size_mb=round(v.size / (1024 * 1024), 2)
            )
            media.file_url = media.file.url
            media.thumbnail_url = media.file.url
            media.save(update_fields=['file_url', 'thumbnail_url'])
            created_items.append(media)

        return Response({
            "message": f"Successfully ingested {len(created_items)} file(s).",
            "total_uploaded": len(created_items),
            "media": EventMediaSerializer(created_items, many=True, context={'request': request}).data
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='media')
    def get_media_items(self, request, pk=None):
        """Returns all media items belonging to this live event."""
        event = self.get_object()
        media_qs = event.media.all().order_by('-created_at')
        serializer = EventMediaSerializer(media_qs, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['delete'], url_path=r'media/(?P<media_id>[^/.]+)')
    def delete_event_media(self, request, pk=None, media_id=None):
        """Removes a single photo or video from the event stream."""
        event = self.get_object()
        media = get_object_or_404(EventMedia, id=media_id, event=event)
        try:
            media.file.delete(save=False)
            if media.thumbnail:
                media.thumbnail.delete(save=False)
        except Exception:
            pass
        media.delete()
        return Response({"success": True}, status=status.HTTP_200_OK)

    # =========================================================================
    # BULK DELETE EVENT MEDIA ENDPOINTS
    # =========================================================================
    @action(detail=True, methods=['post'], url_path='media/bulk-delete')
    def bulk_delete_media(self, request, pk=None):
        """
        Bulk delete multiple photos / videos belonging to an event.
        Payload: { "media_ids": ["uuid-1", "uuid-2", ...] }
        """
        event = self.get_object()
        media_ids = request.data.get('media_ids', [])

        if not isinstance(media_ids, list) or len(media_ids) == 0:
            return Response(
                {"error": "media_ids must be a non-empty list of UUID strings."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Filter only media items belonging strictly to this event
        media_qs = EventMedia.objects.filter(event=event, id__in=media_ids)
        found_count = media_qs.count()

        if found_count == 0:
            return Response(
                {
                    "status": "success",
                    "message": "No matching media items found to delete.",
                    "deleted_count": 0,
                    "deleted_media_ids": [],
                    "freed_bytes": 0,
                },
                status=status.HTTP_200_OK,
            )

        deleted_ids = []
        freed_bytes = 0

        with transaction.atomic():
            for item in media_qs:
                deleted_ids.append(str(item.id))
                # Calculate size in bytes if file_size, size_mb or file.size is present
                if item.file_size:
                    freed_bytes += item.file_size
                elif hasattr(item, 'file') and item.file:
                    try:
                        freed_bytes += item.file.size
                    except Exception:
                        pass
                elif getattr(item, 'size_mb', None):
                    freed_bytes += int(item.size_mb * 1024 * 1024)

                # Clean up physical storage files
                try:
                    if hasattr(item, 'file') and item.file:
                        item.file.delete(save=False)
                    if hasattr(item, 'thumbnail') and item.thumbnail:
                        item.thumbnail.delete(save=False)
                except Exception:
                    pass

                item.delete()

            # Decrement user's storage quota if tracked on profile/subscription
            user = request.user
            profile = getattr(user, 'photographer_profile', None) or getattr(user, 'profile', None)
            if profile and hasattr(profile, 'used_storage_bytes'):
                profile.used_storage_bytes = max(0, profile.used_storage_bytes - freed_bytes)
                profile.save(update_fields=['used_storage_bytes'])

        return Response(
            {
                "status": "success",
                "message": f"Successfully deleted {len(deleted_ids)} media item(s).",
                "deleted_count": len(deleted_ids),
                "deleted_media_ids": deleted_ids,
                "freed_bytes": freed_bytes,
            },
            status=status.HTTP_200_OK,
        )

    # Convenience alias for POST /api/events/{id}/bulk-delete/
    @action(detail=True, methods=['post'], url_path='bulk-delete')
    def bulk_delete_media_alias(self, request, pk=None):
        return self.bulk_delete_media(request, pk=pk)

    @action(detail=True, methods=['post'], url_path='qr-settings')
    def update_qr_settings(self, request, pk=None):
        event = self.get_object()
        duration = request.data.get('duration_hours')
        expires_at = request.data.get('expires_at')
        valid_from = request.data.get('valid_from')
        pin_code = request.data.get('pin_code')
        allow_guest_uploads = request.data.get('allow_guest_uploads')

        from django.utils.dateparse import parse_datetime, parse_date

        if expires_at:
            if isinstance(expires_at, str):
                parsed = parse_datetime(expires_at)
                if not parsed:
                    d = parse_date(expires_at)
                    if d:
                        from datetime import datetime, time
                        parsed = datetime.combine(d, time.max)
                if parsed and timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
                if parsed:
                    event.qr_expires_at = parsed
            elif hasattr(expires_at, 'year'):
                event.qr_expires_at = expires_at

        if valid_from:
            if isinstance(valid_from, str):
                parsed = parse_datetime(valid_from)
                if not parsed:
                    d = parse_date(valid_from)
                    if d:
                        from datetime import datetime, time
                        parsed = datetime.combine(d, time.min)
                if parsed and timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
                if parsed:
                    event.qr_valid_from = parsed
            elif hasattr(valid_from, 'year'):
                event.qr_valid_from = valid_from

        if duration:
            event.qr_duration_hours = int(duration) if str(duration).isdigit() else 24
            if not expires_at:
                base = event.qr_valid_from or timezone.now()
                if isinstance(base, str):
                    parsed_base = parse_datetime(base)
                    base = parsed_base if parsed_base else timezone.now()
                if timezone.is_naive(base):
                    base = timezone.make_aware(base, timezone.get_current_timezone())
                event.qr_expires_at = base + timedelta(hours=event.qr_duration_hours)

        if pin_code is not None:
            event.qr_pin_code = str(pin_code).strip() or None
        if allow_guest_uploads is not None:
            event.allow_guest_uploads = bool(allow_guest_uploads)

        event.save()
        return Response({
            "status": "success",
            "expires_at": event.qr_expires_at.isoformat() if event.qr_expires_at and hasattr(event.qr_expires_at, 'isoformat') else event.qr_expires_at,
            "valid_from": event.qr_valid_from.isoformat() if event.qr_valid_from and hasattr(event.qr_valid_from, 'isoformat') else event.qr_valid_from,
            "duration_hours": event.qr_duration_hours,
            "is_active": not event.is_qr_expired,
            "pin_code": event.qr_pin_code,
            "allow_guest_uploads": event.allow_guest_uploads,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='move-to-gallery')
    def move_to_gallery(self, request, pk=None):
        """
        Moves all event media to a Studio Gallery with categorized sections,
        and PERMANENTLY deletes the event from the events table.
        """
        event = self.get_object()
        serializer = MoveEventToGallerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        target_mode = data.get('target_mode', 'new')
        target_gallery_id = data.get('target_gallery_id')
        new_title = data.get('new_gallery_title') or event.title
        assignments = data.get('category_assignments', {})

        # Resolve photographer profile for Gallery model
        profile, _ = PhotographerProfile.objects.get_or_create(
            user=request.user,
            defaults={
                'name': getattr(request.user, 'fullname', '') or request.user.username,
                'email': request.user.email or '',
                'studio_name': f"{request.user.username}'s Studio",
            }
        )

        with transaction.atomic():
            if target_mode == 'existing' and target_gallery_id:
                gallery = get_object_or_404(Gallery, id=target_gallery_id, photographer=profile)
            else:
                gallery = Gallery.objects.create(
                    photographer=profile,
                    title=new_title,
                    status='active',
                    cover_image_url=event.banner_url
                )

            # Migrate media items into gallery
            for media in event.media.all():
                sec_title = assignments.get(str(media.id), media.section_title).strip().upper()
                section, _ = GallerySection.objects.get_or_create(gallery=gallery, title=sec_title)

                GalleryMedia.objects.create(
                    photographer=profile,
                    gallery=gallery,
                    section=section,
                    section_title=sec_title,
                    original_filename=media.original_filename,
                    file=media.file,
                    storage_key=f"galleries/{gallery.id}/originals/{media.id}_{media.original_filename}",
                    aspect_ratio=media.aspect_ratio,
                    file_size=int(media.size_mb * 1024 * 1024),
                    width=media.width,
                    height=media.height,
                    is_favorite=media.is_favorite,
                    is_cover=media.is_cover,
                )

            # Permanent cleanup of event as requested
            event.delete()

        return Response({
            "id": str(gallery.id),
            "title": gallery.title,
            "status": "success",
            "message": "Event migrated to Gallery and permanently deleted from Events."
        }, status=status.HTTP_200_OK)


# -----------------------------------------------------------------------------
# Public Guest Portal & AI Biometric Face Match API
# -----------------------------------------------------------------------------

class PublicEventDetailView(APIView):
    """
    Public Guest Mobile Portal:
    - AllowAny permissions: unauthenticated attendees scanning QR code can view event metadata.
    - Resolves both UUID pk and slug.
    - Zero event photos leaked (only exposes metadata & QR settings for biometric face search).
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, id_or_slug):
        is_uuid = False
        try:
            uuid.UUID(str(id_or_slug))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid:
            event = LiveEvent.objects.filter(id=id_or_slug, is_archived=False).first()
        else:
            event = LiveEvent.objects.filter(slug=id_or_slug, is_archived=False).first()

        if not event:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        event.guest_views += 1
        event.save(update_fields=['guest_views'])
        return Response(PublicEventPortalSerializer(event, context={'request': request}).data)


class EventFaceSearchView(APIView):
    """
    Processes guest selfie, matches against event face embeddings,
    and returns ONLY photographs where that guest appears.
    Supports multipart file upload or base64 JSON payload.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, event_id):
        is_uuid = False
        try:
            uuid.UUID(str(event_id))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid:
            event = LiveEvent.objects.filter(id=event_id, is_archived=False).first()
        else:
            event = LiveEvent.objects.filter(slug=event_id, is_archived=False).first()

        if not event:
            return Response({"detail": "Event not found."}, status=status.HTTP_404_NOT_FOUND)

        # 1. Resolve selfie image bytes from multipart upload or base64 string
        selfie_bytes = None
        selfie_file = (
            request.FILES.get('selfie')
            or request.FILES.get('photo')
            or request.FILES.get('image')
            or request.FILES.get('file')
        )
        if selfie_file:
            selfie_bytes = selfie_file.read()
        else:
            raw_val = (
                request.data.get('selfie')
                or request.data.get('photo')
                or request.data.get('image')
                or request.data.get('file')
            )
            if isinstance(raw_val, str) and len(raw_val) > 20:
                try:
                    if ';base64,' in raw_val:
                        b64_str = raw_val.split(';base64,', 1)[1]
                    else:
                        b64_str = raw_val
                    selfie_bytes = base64.b64decode(b64_str)
                except Exception:
                    selfie_bytes = None

        if not selfie_bytes:
            return Response(
                {"error": "Selfie image required under 'selfie' or 'photo'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Configurable similarity threshold (default 0.42 for SFace cosine matching)
        try:
            threshold = float(request.query_params.get('threshold') or request.data.get('threshold') or 0.42)
        except (ValueError, TypeError):
            threshold = 0.42

        # 3. Call biometric facial matcher with self-healing indexing
        match_res = compare_selfie_faces_task(str(event.id), selfie_bytes, threshold=threshold, return_dict=True)
        if isinstance(match_res, dict):
            matched_media_ids = match_res.get("matched_media_ids", [])
            confidence = match_res.get("confidence", 0.0)
        else:
            matched_media_ids = list(match_res)
            confidence = 0.92 if matched_media_ids else 0.0

        event.ai_searches += 1
        if matched_media_ids:
            event.matches_found += len(matched_media_ids)
        event.save(update_fields=['ai_searches', 'matches_found'])

        # 4. Fetch matched EventMedia objects in exact score order
        matched_qs = EventMedia.objects.filter(id__in=matched_media_ids)
        matched_dict = {str(m.id): m for m in matched_qs}
        ordered_media = [matched_dict[mid] for mid in matched_media_ids if mid in matched_dict]
        media_data = EventMediaSerializer(ordered_media, many=True, context={'request': request}).data

        return Response({
            "matched_media_ids": matched_media_ids,
            "matched_media": media_data,
            "total_matches": len(matched_media_ids),
            "confidence": round(float(confidence), 2),
        }, status=status.HTTP_200_OK)

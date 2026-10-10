import hashlib
import os
import uuid
import logging
from typing import List, Tuple
from django.db import transaction
from django.utils.text import slugify
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.parsers import MultiPartParser, FormParser
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from PIL import Image, ImageOps
import io

# Model resolution (compatible across apps)
try:
    from App.Storage.storage_models import Gallery, Media as GalleryMedia, GallerySection
except ImportError:
    from .models import Gallery, GalleryMedia, GallerySection

try:
    from App.LiveEvents.event_models import LiveEvent, EventMedia
except ImportError:
    LiveEvent, EventMedia = None, None

try:
    from App.Photographers.photo_models import PhotographerProfile
except ImportError:
    PhotographerProfile = None

try:
    from App.Storage.tasks import process_media_derivatives_and_faces_task, run_or_queue_task
except ImportError:
    process_media_derivatives_and_faces_task, run_or_queue_task = None, None

logger = logging.getLogger(__name__)


class BulkMediaUploadService:
    """
    Reusable, high-speed media processing service with storage quota enforcement,
    idempotent file ingestion, and thumbnail generation.
    """

    THUMBNAIL_SIZE = (400, 400)
    PREVIEW_SIZE = (1600, 1600)

    @classmethod
    def calculate_file_hash(cls, uploaded_file) -> str:
        """Compute SHA-256 hash for deduplication."""
        hasher = hashlib.sha256()
        for chunk in uploaded_file.chunks(chunk_size=65536):
            hasher.update(chunk)
        uploaded_file.seek(0)  # Reset pointer for subsequent reads/saves
        return hasher.hexdigest()

    @classmethod
    def validate_storage_quota(cls, user, additional_bytes: int) -> Tuple[bool, str]:
        """
        Validates if user's studio subscription allows the additional incoming bytes.
        Returns (is_valid, error_message).
        """
        # 1. Check photographer profile if available
        profile = getattr(user, 'photographer_profile', None) or getattr(user, 'photographer', None)
        if not profile and PhotographerProfile and hasattr(user, 'id'):
            profile = PhotographerProfile.objects.filter(user=user).first()

        if profile and hasattr(profile, 'can_allocate_storage'):
            if not profile.can_allocate_storage(additional_bytes):
                available_mb = max(0, profile.get_remaining_storage_bytes() / (1024 * 1024))
                return False, f"Studio cloud storage limit exceeded. Upgrade your plan to continue ({available_mb:.1f} MB remaining)."

        # 2. Check user subscription model if present
        subscription = getattr(user, 'subscription', None)
        if subscription:
            limit_bytes = getattr(subscription, 'storage_limit_bytes', 0)
            used_bytes = getattr(subscription, 'storage_used_bytes', 0)
            if limit_bytes > 0 and (used_bytes + additional_bytes) > limit_bytes:
                available_mb = max(0, (limit_bytes - used_bytes) / (1024 * 1024))
                return False, f"Studio cloud storage limit exceeded. Upgrade your plan to continue ({available_mb:.1f} MB remaining)."

        return True, ""

    @classmethod
    def generate_thumbnails(cls, original_file) -> Tuple[str, str, int, int]:
        """
        Extracts width/height and generates thumbnail & web preview images.
        Returns: (thumbnail_url, preview_url, width, height)
        """
        try:
            with Image.open(original_file) as img:
                img = ImageOps.exif_transpose(img)
                width, height = img.size

                # 1. Generate Web Preview (Max 1600px width/height)
                preview_io = io.BytesIO()
                preview_img = img.copy()
                preview_img.thumbnail(cls.PREVIEW_SIZE, Image.Resampling.LANCZOS)
                preview_img.convert('RGB').save(preview_io, format='WEBP', quality=85, optimize=True)
                preview_path = f"previews/{uuid.uuid4().hex}.webp"
                default_storage.save(preview_path, ContentFile(preview_io.getvalue()))
                preview_url = default_storage.url(preview_path)

                # 2. Generate Grid Thumbnail (Max 400px width/height)
                thumb_io = io.BytesIO()
                thumb_img = img.copy()
                thumb_img.thumbnail(cls.THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                thumb_img.convert('RGB').save(thumb_io, format='WEBP', quality=80, optimize=True)
                thumb_path = f"thumbnails/{uuid.uuid4().hex}.webp"
                default_storage.save(thumb_path, ContentFile(thumb_io.getvalue()))
                thumb_url = default_storage.url(thumb_path)

                original_file.seek(0)
                return thumb_url, preview_url, width, height
        except Exception as e:
            logger.warning(f"[BulkMediaUploadService] Thumbnail generation skipped or failed: {e}")
            try:
                original_file.seek(0)
            except Exception:
                pass
            return "", "", 0, 0


class BulkUploadGalleryMediaView(APIView):
    """
    POST /api/galleries/<gallery_id>/media/bulk-upload/
    Handles concurrent chunked uploads, deduplication, and quota tracking.
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, gallery_id=None, pk=None):
        target_gallery_id = gallery_id or pk
        if not target_gallery_id:
            return Response({"detail": "Gallery ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Resolve gallery and enforce ownership
        gallery_query = Gallery.objects.filter(id=target_gallery_id)
        is_admin = getattr(request.user, 'is_staff', False) or getattr(request.user, 'is_superuser', False)
        if not is_admin:
            if hasattr(Gallery, 'user'):
                gallery_query = gallery_query.filter(user=request.user)
            elif hasattr(Gallery, 'photographer'):
                profile = getattr(request.user, 'photographer_profile', None) or getattr(request.user, 'photographer', None)
                if profile:
                    gallery_query = gallery_query.filter(photographer=profile)
                else:
                    gallery_query = gallery_query.filter(photographer__user=request.user)

        gallery = gallery_query.first()
        if not gallery:
            return Response({"detail": "Gallery not found or unauthorized."}, status=status.HTTP_404_NOT_FOUND)

        # 2. Gather files from request (support 'photos', 'videos', or 'files')
        files = (
            request.FILES.getlist('photos') or
            request.FILES.getlist('videos') or
            request.FILES.getlist('files')
        )
        if not files:
            for single_key in ['photo', 'video', 'file']:
                if single_key in request.FILES:
                    files = [request.FILES[single_key]]
                    break

        if not files:
            return Response({"detail": "No files provided in upload payload."}, status=status.HTTP_400_BAD_REQUEST)

        section_title = (request.data.get('section_title') or 'HIGHLIGHTS').strip().upper()
        media_type = (request.data.get('type') or 'photo').strip().lower()

        # 3. Check Storage Quota
        incoming_batch_bytes = sum(getattr(f, 'size', 0) for f in files)
        is_quota_ok, quota_error = BulkMediaUploadService.validate_storage_quota(request.user, incoming_batch_bytes)
        if not is_quota_ok:
            return Response({
                "error_code": "STORAGE_LIMIT_EXCEEDED",
                "detail": quota_error,
                "upgrade_required": True,
            }, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        # 4. Process Section
        section = GallerySection.objects.filter(gallery=gallery, title__iexact=section_title).first()
        if not section:
            section = GallerySection.objects.create(gallery=gallery, title=section_title)

        # 5. Ingest and Deduplicate Files
        created_media_records: List[GalleryMedia] = []
        new_records: List[GalleryMedia] = []
        uploaded_bytes_total = 0

        # Retrieve existing file hashes in this gallery/section to prevent duplicates
        existing_hashes = set(
            gallery.media_items.filter(deleted_at__isnull=True)
            .exclude(file_hash__isnull=True)
            .exclude(file_hash='')
            .values_list('file_hash', flat=True)
        )

        with transaction.atomic():
            for uploaded_file in files:
                file_hash = BulkMediaUploadService.calculate_file_hash(uploaded_file)

                # Skip duplication if already uploaded in a previous paused/interrupted batch
                if file_hash in existing_hashes:
                    existing_item = gallery.media_items.filter(deleted_at__isnull=True, file_hash=file_hash).first()
                    if existing_item:
                        created_media_records.append(existing_item)
                        continue

                # Generate clean filename & storage path
                name_root, ext = os.path.splitext(uploaded_file.name)
                clean_name = f"{slugify(name_root)}_{uuid.uuid4().hex[:8]}{ext.lower()}"
                storage_path = f"galleries/{gallery.id}/{section_title.lower()}/{clean_name}"

                # Save original asset
                saved_path = default_storage.save(storage_path, uploaded_file)
                asset_url = default_storage.url(saved_path)

                # Generate lightweight thumbnail & web preview
                thumb_url, preview_url, width, height = (
                    BulkMediaUploadService.generate_thumbnails(uploaded_file)
                    if media_type == 'photo' else ("", "", 0, 0)
                )

                media_obj = GalleryMedia(
                    gallery=gallery,
                    section=section,
                    section_title=section_title,
                    media_type=media_type,
                    title=name_root.replace('_', ' ').replace('-', ' ').title(),
                    file_size=uploaded_file.size,
                    original_filename=uploaded_file.name,
                    storage_key=saved_path,
                    original_storage_key=saved_path,
                    preview_storage_key=preview_url or saved_path,
                    thumbnail_storage_key=thumb_url or saved_path,
                    width=width or 1920,
                    height=height or 1080,
                    file_hash=file_hash,
                )
                created_media_records.append(media_obj)
                new_records.append(media_obj)
                uploaded_bytes_total += uploaded_file.size
                existing_hashes.add(file_hash)

            # 6. Bulk Create new database records
            if new_records:
                GalleryMedia.objects.bulk_create(new_records)

            # 7. Update photographer & subscription storage quota tracking
            profile = getattr(gallery, 'photographer', None)
            if profile and hasattr(profile, 'storage_used_bytes') and uploaded_bytes_total > 0:
                profile.storage_used_bytes = (profile.storage_used_bytes or 0) + uploaded_bytes_total
                profile.save(update_fields=['storage_used_bytes'])

            sub = getattr(request.user, 'subscription', None)
            if sub and hasattr(sub, 'storage_used_bytes') and uploaded_bytes_total > 0:
                sub.storage_used_bytes = (sub.storage_used_bytes or 0) + uploaded_bytes_total
                sub.save(update_fields=['storage_used_bytes'])

        # 8. Async offload face embeddings / high-res derivatives if configured
        if process_media_derivatives_and_faces_task and run_or_queue_task:
            for m in new_records:
                try:
                    run_or_queue_task(process_media_derivatives_and_faces_task, str(m.id))
                except Exception:
                    pass

        # 9. Format clean JSON response
        response_items = [
            {
                "id": str(m.id),
                "gallery": str(gallery.id),
                "url": m.url or getattr(m, 'storage_key', ''),
                "thumbnail_url": m.thumbnail_url or m.url or getattr(m, 'storage_key', ''),
                "preview_url": m.preview_url or m.url or getattr(m, 'storage_key', ''),
                "title": m.title,
                "type": getattr(m, 'type', media_type),
                "width": getattr(m, 'width', 0) or 0,
                "height": getattr(m, 'height', 0) or 0,
                "file_size": getattr(m, 'file_size', 0) or 0,
                "section_title": m.section_title or section_title,
                "created_at": m.created_at.isoformat() if hasattr(m, 'created_at') and m.created_at else None,
            }
            for m in created_media_records
        ]

        return Response({
            "message": f"Successfully uploaded {len(new_records)} new file(s)",
            "total_uploaded": len(created_media_records),
            "section_title": section_title,
            "media": response_items,
        }, status=status.HTTP_201_CREATED)


class GalleryUploadResumeStatusView(APIView):
    """
    GET /api/galleries/<gallery_id>/upload-status/?section_title=HIGHLIGHTS
    Returns list of already uploaded file hashes & names so the client can resume without re-sending.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, gallery_id=None, pk=None):
        target_gallery_id = gallery_id or pk
        gallery_query = Gallery.objects.filter(id=target_gallery_id)
        is_admin = getattr(request.user, 'is_staff', False) or getattr(request.user, 'is_superuser', False)
        if not is_admin:
            if hasattr(Gallery, 'user'):
                gallery_query = gallery_query.filter(user=request.user)
            elif hasattr(Gallery, 'photographer'):
                profile = getattr(request.user, 'photographer_profile', None) or getattr(request.user, 'photographer', None)
                if profile:
                    gallery_query = gallery_query.filter(photographer=profile)
                else:
                    gallery_query = gallery_query.filter(photographer__user=request.user)

        gallery = gallery_query.first()
        if not gallery:
            return Response({"detail": "Gallery not found or unauthorized."}, status=status.HTTP_404_NOT_FOUND)

        section_title = request.query_params.get('section_title', '').strip().upper()
        qs = gallery.media_items.filter(deleted_at__isnull=True)
        if section_title:
            qs = qs.filter(section_title__iexact=section_title)

        existing_files = [
            {
                "id": str(m.id),
                "title": m.title or m.original_filename,
                "file_size": m.file_size,
                "file_hash": m.file_hash,
                "url": m.url,
            }
            for m in qs
        ]

        return Response({
            "gallery_id": str(gallery.id),
            "section_title": section_title,
            "existing_count": len(existing_files),
            "files": existing_files,
        }, status=status.HTTP_200_OK)


class BulkUploadEventMediaView(APIView):
    """
    POST /api/events/<event_id>/media/bulk-upload/
    Handles concurrent chunked uploads, deduplication, and quota tracking for Live Events.
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, event_id=None, pk=None):
        target_event_id = event_id or pk
        if not LiveEvent:
            return Response({"detail": "LiveEvents app not enabled."}, status=status.HTTP_501_NOT_IMPLEMENTED)

        event_query = LiveEvent.objects.filter(id=target_event_id)
        if not (request.user.is_staff or request.user.is_superuser):
            event_query = event_query.filter(photographer=request.user)

        event = event_query.first()
        if not event:
            return Response({"detail": "Event not found or unauthorized."}, status=status.HTTP_404_NOT_FOUND)

        files = (
            request.FILES.getlist('photos') or
            request.FILES.getlist('videos') or
            request.FILES.getlist('files')
        )
        if not files:
            for single_key in ['photo', 'video', 'file']:
                if single_key in request.FILES:
                    files = [request.FILES[single_key]]
                    break

        if not files:
            return Response({"detail": "No files provided in upload payload."}, status=status.HTTP_400_BAD_REQUEST)

        section_title = (request.data.get('section_title') or 'HIGHLIGHTS').strip().upper()
        media_type = (request.data.get('type') or 'photo').strip().lower()

        # Quota verification
        incoming_batch_bytes = sum(getattr(f, 'size', 0) for f in files)
        is_quota_ok, quota_error = BulkMediaUploadService.validate_storage_quota(request.user, incoming_batch_bytes)
        if not is_quota_ok:
            return Response({
                "error_code": "STORAGE_LIMIT_EXCEEDED",
                "detail": quota_error,
                "upgrade_required": True,
            }, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        existing_hashes = set(
            event.media.exclude(file_hash__isnull=True)
            .exclude(file_hash='')
            .values_list('file_hash', flat=True)
        )

        created_media_records: List[EventMedia] = []
        new_records: List[EventMedia] = []
        uploaded_bytes_total = 0

        with transaction.atomic():
            for uploaded_file in files:
                file_hash = BulkMediaUploadService.calculate_file_hash(uploaded_file)

                if file_hash in existing_hashes:
                    existing_item = event.media.filter(file_hash=file_hash).first()
                    if existing_item:
                        created_media_records.append(existing_item)
                        continue

                name_root, ext = os.path.splitext(uploaded_file.name)
                clean_name = f"{slugify(name_root)}_{uuid.uuid4().hex[:8]}{ext.lower()}"
                storage_path = f"events/{event.id}/{section_title.lower()}/{clean_name}"

                saved_path = default_storage.save(storage_path, uploaded_file)
                asset_url = default_storage.url(saved_path)

                thumb_url, preview_url, width, height = (
                    BulkMediaUploadService.generate_thumbnails(uploaded_file)
                    if media_type == 'photo' else ("", "", 0, 0)
                )

                media_obj = EventMedia(
                    event=event,
                    original_filename=uploaded_file.name,
                    file=saved_path,
                    file_url=asset_url,
                    thumbnail_url=thumb_url or asset_url,
                    section_title=section_title,
                    width=width or 1920,
                    height=height or 1080,
                    media_type=media_type,
                    file_size=uploaded_file.size,
                    file_hash=file_hash,
                )
                created_media_records.append(media_obj)
                new_records.append(media_obj)
                uploaded_bytes_total += uploaded_file.size
                existing_hashes.add(file_hash)

            if new_records:
                EventMedia.objects.bulk_create(new_records)

        response_items = [
            {
                "id": str(m.id),
                "event": str(event.id),
                "url": m.url,
                "thumbnail_url": m.thumbnail_url or m.url,
                "preview_url": m.preview_url or m.url,
                "title": m.original_filename,
                "type": m.type,
                "width": m.width,
                "height": m.height,
                "file_size": m.file_size,
                "section_title": m.section_title or section_title,
                "created_at": m.created_at.isoformat() if hasattr(m, 'created_at') and m.created_at else None,
            }
            for m in created_media_records
        ]

        return Response({
            "message": f"Successfully uploaded {len(new_records)} new file(s)",
            "total_uploaded": len(created_media_records),
            "section_title": section_title,
            "media": response_items,
        }, status=status.HTTP_201_CREATED)


class EventUploadResumeStatusView(APIView):
    """
    GET /api/events/<event_id>/upload-status/?section_title=HIGHLIGHTS
    Returns list of already uploaded file hashes & names so the client can resume without re-sending.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, event_id=None, pk=None):
        target_event_id = event_id or pk
        if not LiveEvent:
            return Response({"detail": "LiveEvents app not enabled."}, status=status.HTTP_501_NOT_IMPLEMENTED)

        event_query = LiveEvent.objects.filter(id=target_event_id)
        if not (request.user.is_staff or request.user.is_superuser):
            event_query = event_query.filter(photographer=request.user)

        event = event_query.first()
        if not event:
            return Response({"detail": "Event not found or unauthorized."}, status=status.HTTP_404_NOT_FOUND)

        section_title = request.query_params.get('section_title', '').strip().upper()
        qs = event.media.all()
        if section_title:
            qs = qs.filter(section_title__iexact=section_title)

        existing_files = [
            {
                "id": str(m.id),
                "title": m.original_filename,
                "file_size": m.file_size,
                "file_hash": m.file_hash,
                "url": m.url,
            }
            for m in qs
        ]

        return Response({
            "event_id": str(event.id),
            "section_title": section_title,
            "existing_count": len(existing_files),
            "files": existing_files,
        }, status=status.HTTP_200_OK)

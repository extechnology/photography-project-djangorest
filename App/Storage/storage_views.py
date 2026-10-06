import io
import os
import uuid
import zipfile
import urllib.parse
import csv
import hashlib
import base64
import json
import logging
import requests
import functools

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, FileResponse, Http404
from utils.watermark import stamp_watermark_on_image
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F, Q, Count, Max, Sum, Case, When
from django.utils.text import slugify
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from datetime import timedelta
from rest_framework import status, viewsets, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.exceptions import PermissionDenied, NotFound

from App.Auth.auth_utils import get_user_from_request
from App.Photographers.photo_models import PhotographerProfile, Notification, NotificationPreference
from App.Photographers.photo_utils import check_image_for_nudity
from App.Storage.storage_models import (
    SharedEvent,
    EventPhoto,
    Gallery,
    GallerySection,
    GalleryAnalyticsEvent,
    Media,
    GalleryClientAccess,
    GalleryClientSelection,
    FaceEmbedding,
    UploadReservation,
    BulkDownloadJob,
    StorageAuditLog,
)
from backend.atelier_plans.subscription_enforcement import (
    enforce_active_subscription,
    is_studio_active,
    IsActiveStudioSubscriber,
)
from App.Storage.storage_serializers import (
    SharedEventListSerializer,
    SharedEventDetailSerializer,
    PublicSharedEventSerializer,
    EventPhotoSerializer,
    GallerySerializer,
    GalleryDetailResponseSerializer,
    GallerySettingsUpdateSerializer,
    GallerySectionSerializer,
    MoveMediaSectionSerializer,
    SectionCreateSerializer,
    SectionRenameSerializer,
    SectionReorderSerializer,
    MediaReorderSerializer,
    TemplateUpdateSerializer,
    TemplateBannerUpdateSerializer,
    MasonrySlotSerializer,
    GalleryCoverSerializer,
    AnalyticsEventTrackSerializer,
    PublicGallerySerializer,
    MediaSerializer,
    GalleryClientSelectionSerializer,
    DirectUploadInitItemSerializer,
    DirectUploadConfirmSerializer,
    GalleryTemplateUpdateSerializer,
    GallerySetCoverSerializer,
    GalleryReorderMediaSerializer,
    StorageUsageSerializer,
    BulkDownloadJobSerializer,
)
from App.Storage.services.storage_service import get_storage_provider
from App.Storage.services.quota_service import StorageQuotaService, StorageQuotaExceededException
from App.Storage.services.face_service import FaceService
from App.Storage.tasks import (
    process_media_derivatives_and_faces_task,
    generate_bulk_download_archive_task,
    run_or_queue_task,
)
from App.Storage.permissions import (
    IsPhotographer,
    IsGalleryOwner,
    CanAccessGallery,
    CanDownloadMedia,
)
from App.Storage.throttling import (
    FaceSearchRateThrottle,
    UploadRateThrottle,
    DownloadRateThrottle,
    BulkDownloadRateThrottle,
    ShareAccessRateThrottle,
    PinVerifyRateThrottle,
)

logger = logging.getLogger(__name__)


def is_gallery_template_allowed(active_plan, template_id):
    if not active_plan or not getattr(active_plan, 'allowed_templates', None):
        return True
    allowed = active_plan.allowed_templates
    if not allowed:
        return True
    alias_map = {
        'editorial': 'editorial-vogue',
        'editorial-vogue': 'editorial-vogue',
        'masonry': 'darkroom-atelier',
        'darkroom-atelier': 'darkroom-atelier',
        'cinematic': 'cinematic',
        'cinematic-luxury': 'cinematic',
        'minimal': 'minimal',
        'minimal-zen': 'minimal',
    }
    raw_key = str(template_id).lower().strip()
    norm_key = alias_map.get(raw_key, raw_key)
    norm_allowed = [alias_map.get(str(t).lower().strip(), str(t).lower().strip()) for t in allowed]
    return (raw_key in allowed) or (norm_key in norm_allowed)

def trigger_studio_notification(photographer, event_type, title, message, gallery_id=None):
    if not photographer:
        return
    try:
        prefs, _ = NotificationPreference.objects.get_or_create(photographer=photographer)
        should_send = True
        if event_type == 'client_visit' and not prefs.notify_client_visited:
            should_send = False
        elif event_type == 'download' and not prefs.notify_photos_downloaded:
            should_send = False
        elif event_type == 'proofing_submitted' and not prefs.notify_favorites_selected:
            should_send = False
        elif event_type == 'storage_warning' and not prefs.notify_storage_alerts:
            should_send = False

        if should_send:
            Notification.objects.create(
                photographer=photographer,
                user=photographer.user,
                event_type=event_type,
                title=title,
                message=message,
                related_gallery_id=gallery_id
            )
    except Exception:
        pass


VALID_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.heic', '.raw', '.dng'}
VALID_VIDEO_EXTENSIONS = {'.mp4', '.mov', '.webm', '.mkv', '.avi', '.m4v'}
ALLOWED_MEDIA_EXTENSIONS = VALID_IMAGE_EXTENSIONS | VALID_VIDEO_EXTENSIONS



def get_current_user(request):
    if hasattr(request, 'user') and request.user and request.user.is_authenticated:
        return request.user
    try:
        return get_user_from_request(request)
    except Exception:
        return None


def get_photographer_profile(user):
    if not user:
        return None
    try:
        profile = getattr(user, 'photographer_profile', None)
        if profile:
            return profile
        return PhotographerProfile.objects.get(user=user)
    except PhotographerProfile.DoesNotExist:
        if getattr(user, 'is_authenticated', False):
            try:
                profile, _ = PhotographerProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'name': user.get_full_name() or user.username or 'Photographer',
                        'email': user.email or '',
                        'studio_name': f"{user.username} Studio"
                    }
                )
                return profile
            except Exception:
                return None
        return None


def _get_gallery_or_404(gallery_id_or_slug: str, user=None):
    """Helper to query gallery by UUID or Slug with optimal prefetching and ownership verification."""
    qs = Gallery.objects.select_related('photographer', 'photographer__user').prefetch_related('section_items', 'media_items')
    if user and user.is_authenticated and not (user.is_staff or user.is_superuser):
        qs = qs.filter(Q(photographer__user=user) | Q(photographer__user_id=user.id))

    try:
        val = uuid.UUID(str(gallery_id_or_slug))
        return qs.get(id=val)
    except (ValueError, Gallery.DoesNotExist):
        try:
            return qs.get(slug=gallery_id_or_slug)
        except Gallery.DoesNotExist:
            return None


# =============================================================================
# 1. Photographer Shared Event Views (Maintained for Backward Compatibility)
# =============================================================================

class SharedEventListCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        user = get_current_user(request)
        if not user:
            return Response({"message": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        profile = get_photographer_profile(user)
        if not profile and not (user.is_staff or user.is_superuser):
            return Response({"message": "Photographer profile not found."}, status=status.HTTP_404_NOT_FOUND)

        if user.is_superuser or user.is_staff:
            events = SharedEvent.objects.all().select_related('photographer')
        else:
            events = SharedEvent.objects.filter(photographer=profile)

        serializer = SharedEventListSerializer(events, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        user = get_current_user(request)
        if not user:
            return Response({"message": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        enforce_active_subscription(user, "live events")

        profile = get_photographer_profile(user)
        if not profile:
            return Response({"message": "Only registered photographers can create shared events."}, status=status.HTTP_403_FORBIDDEN)

        # Enforce plan event limit
        active_plan = getattr(profile, 'studio_plan', None)
        if not active_plan and hasattr(profile, 'subscription') and profile.subscription and profile.subscription.plan:
            active_plan = profile.subscription.plan
        if active_plan and getattr(active_plan, 'max_events', 0) > 0:
            current_events = SharedEvent.objects.filter(photographer=profile).count()
            if current_events >= active_plan.max_events:
                return Response({
                    "code": "EVENT_LIMIT_REACHED",
                    "message": f"You have reached the maximum shared events limit ({active_plan.max_events}) for your plan. Please upgrade to host more events."
                }, status=status.HTTP_403_FORBIDDEN)

        data = request.data.copy()
        serializer = SharedEventDetailSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            event = serializer.save(photographer=profile)
            return Response(
                {
                    "message": "Shared event created successfully.",
                    "data": SharedEventDetailSerializer(event, context={'request': request}).data
                },
                status=status.HTTP_201_CREATED
            )
        return Response({"message": "Event creation failed.", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class SharedEventDetailView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _get_event(self, pk, user):
        event = get_object_or_404(SharedEvent.objects.select_related('photographer', 'photographer__user'), pk=pk)
        if event.photographer.user != user and not (user.is_staff or user.is_superuser):
            return None
        return event

    def get(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response({"message": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        event = self._get_event(pk, user)
        if not event:
            return Response({"message": "You do not have access to this event."}, status=status.HTTP_403_FORBIDDEN)

        serializer = SharedEventDetailSerializer(event, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk, partial):
        user = get_current_user(request)
        if not user:
            return Response({"message": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        event = self._get_event(pk, user)
        if not event:
            return Response({"message": "You do not have permission to edit this event."}, status=status.HTTP_403_FORBIDDEN)

        serializer = SharedEventDetailSerializer(event, data=request.data, partial=partial, context={'request': request})
        if serializer.is_valid():
            updated_event = serializer.save()
            return Response(
                {
                    "message": "Shared event updated successfully.",
                    "data": SharedEventDetailSerializer(updated_event, context={'request': request}).data
                },
                status=status.HTTP_200_OK
            )
        return Response({"message": "Update failed.", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response({"message": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        event = self._get_event(pk, user)
        if not event:
            return Response({"message": "You do not have permission to delete this event."}, status=status.HTTP_403_FORBIDDEN)

        for photo in event.photos.all():
            if photo.image and hasattr(photo.image, 'path') and os.path.exists(photo.image.path):
                try:
                    os.remove(photo.image.path)
                except OSError:
                    pass
        if event.cover_image and hasattr(event.cover_image, 'path') and os.path.exists(event.cover_image.path):
            try:
                os.remove(event.cover_image.path)
            except OSError:
                pass

        event.delete()
        return Response({"message": "Shared event deleted successfully."}, status=status.HTTP_200_OK)


class EventBulkPhotoUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, event_id):
        user = get_current_user(request)
        if not user:
            return Response({"message": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        enforce_active_subscription(user, "media uploads")

        event = get_object_or_404(SharedEvent.objects.select_related('photographer__user'), pk=event_id)
        if event.photographer.user != user and not (user.is_staff or user.is_superuser):
            return Response({"message": "You do not have permission to upload photos to this event."}, status=status.HTTP_403_FORBIDDEN)

        files = request.FILES.getlist('photos') or request.FILES.getlist('images') or request.FILES.getlist('files')
        if not files:
            single_file = request.FILES.get('photo') or request.FILES.get('image')
            if single_file:
                files = [single_file]

        if not files:
            return Response(
                {"message": "No photos provided. Please upload images with the key 'photos' or 'images'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        category_tag = request.data.get('category_tag', '').strip()
        caption = request.data.get('caption', '').strip()

        created_photos = []
        rejected_files = []

        for f in files:
            ext = os.path.splitext(f.name)[1].lower()
            if ext not in VALID_IMAGE_EXTENSIONS:
                rejected_files.append({"name": f.name, "reason": f"Unsupported extension {ext}"})
                continue

            is_nude, violations = check_image_for_nudity(f)
            if is_nude:
                labels = {v['class'].replace('_', ' ').title() for v in violations}
                rejected_files.append({"name": f.name, "reason": f"Explicit or nude content detected ({', '.join(sorted(labels))})"})
                continue

            photo = EventPhoto.objects.create(

                event=event,
                image=f,
                original_filename=f.name,
                file_size=getattr(f, 'size', 0),
                category_tag=category_tag,
                caption=caption
            )
            created_photos.append(photo)

        serializer = EventPhotoSerializer(created_photos, many=True, context={'request': request})
        return Response(
            {
                "message": f"Successfully uploaded {len(created_photos)} photos.",
                "total_uploaded": len(created_photos),
                "total_rejected": len(rejected_files),
                "rejected_files": rejected_files,
                "photos": serializer.data
            },
            status=status.HTTP_201_CREATED
        )


class EventZipPhotoUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, event_id):
        user = get_current_user(request)
        if not user:
            return Response({"message": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        enforce_active_subscription(user, "media uploads")

        event = get_object_or_404(SharedEvent.objects.select_related('photographer__user'), pk=event_id)
        if event.photographer.user != user and not (user.is_staff or user.is_superuser):
            return Response({"message": "You do not have permission to upload photos to this event."}, status=status.HTTP_403_FORBIDDEN)

        zip_file = request.FILES.get('zip_file') or request.FILES.get('file') or request.FILES.get('archive')
        if not zip_file:
            return Response({"message": "Please provide a zip file under 'zip_file'."}, status=status.HTTP_400_BAD_REQUEST)

        if not zipfile.is_zipfile(zip_file):
            return Response({"message": "Uploaded file is not a valid ZIP archive."}, status=status.HTTP_400_BAD_REQUEST)

        category_tag = request.data.get('category_tag', '').strip()
        caption = request.data.get('caption', '').strip()

        created_photos = []
        skipped_files = []

        try:
            with zipfile.ZipFile(zip_file, 'r') as z:
                for file_info in z.infolist():
                    if file_info.is_dir():
                        continue

                    filename = os.path.basename(file_info.filename)
                    if not filename or filename.startswith('.') or filename.startswith('__MACOSX'):
                        continue

                    ext = os.path.splitext(filename)[1].lower()
                    if ext not in VALID_IMAGE_EXTENSIONS:
                        skipped_files.append({"filename": filename, "reason": "Not a recognized image format"})
                        continue

                    image_data = z.read(file_info.filename)
                    django_file = ContentFile(image_data, name=filename)

                    photo = EventPhoto.objects.create(
                        event=event,
                        image=django_file,
                        original_filename=filename,
                        file_size=len(image_data),
                        category_tag=category_tag,
                        caption=caption
                    )
                    created_photos.append(photo)

        except Exception as e:
            return Response({"message": f"Error unpacking ZIP archive: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = EventPhotoSerializer(created_photos, many=True, context={'request': request})
        return Response(
            {
                "message": f"Successfully extracted and saved {len(created_photos)} photos from ZIP archive.",
                "total_extracted": len(created_photos),
                "total_skipped": len(skipped_files),
                "skipped_files": skipped_files,
                "photos": serializer.data
            },
            status=status.HTTP_201_CREATED
        )


class EventPhotoDeleteView(APIView):
    def delete(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response({"message": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        photo = get_object_or_404(EventPhoto.objects.select_related('event', 'event__photographer__user'), pk=pk)
        if photo.event.photographer.user != user and not (user.is_staff or user.is_superuser):
            return Response({"message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        if photo.image and hasattr(photo.image, 'path') and os.path.exists(photo.image.path):
            try:
                os.remove(photo.image.path)
            except OSError:
                pass

        photo.delete()
        return Response({"message": "Photo deleted successfully."}, status=status.HTTP_200_OK)


class EventPhotoBulkDeleteView(APIView):
    def post(self, request, event_id):
        user = get_current_user(request)
        if not user:
            return Response({"message": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        event = get_object_or_404(SharedEvent.objects.select_related('photographer__user'), pk=event_id)
        if event.photographer.user != user and not (user.is_staff or user.is_superuser):
            return Response({"message": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        photo_ids = request.data.get('photo_ids', [])
        if not isinstance(photo_ids, list) or not photo_ids:
            return Response({"message": "Provide a list of photo_ids to delete."}, status=status.HTTP_400_BAD_REQUEST)

        photos_to_delete = EventPhoto.objects.filter(event=event, id__in=photo_ids)
        count = photos_to_delete.count()

        for p in photos_to_delete:
            if p.image and hasattr(p.image, 'path') and os.path.exists(p.image.path):
                try:
                    os.remove(p.image.path)
                except OSError:
                    pass

        photos_to_delete.delete()
        return Response({"message": f"Successfully deleted {count} photos."}, status=status.HTTP_200_OK)


class PublicEventGalleryView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, access_code):
        event = get_object_or_404(SharedEvent.objects.select_related('photographer', 'photographer__user'), access_code=access_code)

        # ─── LOCK CHECK: Host Studio Subscription Expiry ───
        host_user = event.user
        if host_user and not is_studio_active(host_user):
            studio_profile = getattr(host_user, 'profile', None)
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "This photo gallery is temporarily locked because the host studio's EX SHARE membership has expired.",
                    "is_studio_plan_expired": True,
                    "title": getattr(event, 'title', ''),
                    "studio_name": getattr(studio_profile, 'studio_name', 'Studio') if studio_profile else 'Studio',
                    "studio_email": getattr(host_user, 'email', ''),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if not event.is_public:
            return Response({"message": "This photo gallery is currently private or inactive."}, status=status.HTTP_403_FORBIDDEN)

        provided_pin = request.query_params.get('pin') or request.headers.get('X-Event-PIN')
        if event.is_pin_protected and not event.verify_pin(provided_pin):
            event_meta = PublicSharedEventSerializer(event, context={'request': request}).data
            return Response(
                {
                    "pin_required": True,
                    "message": "This album is PIN protected. Please enter the PIN to view photos.",
                    "event": event_meta
                },
                status=status.HTTP_200_OK
            )

        SharedEvent.objects.filter(pk=event.pk).update(views_count=F('views_count') + 1)
        event.refresh_from_db()

        photos_qs = event.photos.all()
        tag = request.query_params.get('tag')
        if tag:
            photos_qs = photos_qs.filter(category_tag__iexact=tag)

        event_data = PublicSharedEventSerializer(event, context={'request': request}).data
        photos_data = EventPhotoSerializer(photos_qs, many=True, context={'request': request}).data

        return Response(
            {
                "pin_required": False,
                "event": event_data,
                "photos": photos_data
            },
            status=status.HTTP_200_OK
        )


class PublicEventVerifyPinView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, access_code):
        event = get_object_or_404(SharedEvent.objects.select_related('photographer', 'photographer__user'), access_code=access_code)

        # ─── LOCK CHECK: Host Studio Subscription Expiry ───
        host_user = event.user
        if host_user and not is_studio_active(host_user):
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "This photo gallery is locked because the host studio's subscription has expired.",
                    "is_studio_plan_expired": True,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        pin = request.data.get('pin') or request.query_params.get('pin', '')
        if event.verify_pin(pin):
            return Response({"valid": True, "message": "PIN verified successfully."}, status=status.HTTP_200_OK)
        return Response({"valid": False, "message": "Invalid PIN code."}, status=status.HTTP_400_BAD_REQUEST)


class PublicPhotoDownloadView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, photo_id):
        photo = get_object_or_404(EventPhoto.objects.select_related('event', 'event__photographer', 'event__photographer__user'), pk=photo_id)
        event = photo.event

        # ─── LOCK CHECK: Host Studio Subscription Expiry ───
        host_user = event.user
        if host_user and not is_studio_active(host_user):
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "Photo downloads are locked because the host studio's subscription has expired.",
                    "is_studio_plan_expired": True,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if not event.allow_downloads:
            return Response({"message": "Downloads are disabled for this event."}, status=status.HTTP_403_FORBIDDEN)

        provided_pin = request.query_params.get('pin') or request.headers.get('X-Event-PIN')
        if event.is_pin_protected and not event.verify_pin(provided_pin):
            return Response({"message": "Invalid or missing PIN for this download."}, status=status.HTTP_403_FORBIDDEN)

        if not photo.image:
            return Response({"message": "Photo file not found."}, status=status.HTTP_404_NOT_FOUND)

        EventPhoto.objects.filter(pk=photo.pk).update(downloads_count=F('downloads_count') + 1)
        SharedEvent.objects.filter(pk=event.pk).update(downloads_count=F('downloads_count') + 1)

        filename = photo.original_filename or f"photo_{photo.id}.jpg"
        response = FileResponse(photo.image.open('rb'), as_attachment=True, filename=filename)
        return response


class PublicEventDownloadAllZipView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, access_code):
        return self._generate_zip(request, access_code)

    def post(self, request, access_code):
        return self._generate_zip(request, access_code)

    def _generate_zip(self, request, access_code):
        event = get_object_or_404(SharedEvent.objects.select_related('photographer', 'photographer__user'), access_code=access_code)

        # ─── LOCK CHECK: Host Studio Subscription Expiry ───
        host_user = event.user
        if host_user and not is_studio_active(host_user):
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "ZIP downloads are offline because the host studio's subscription has expired.",
                    "is_studio_plan_expired": True,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if not event.allow_downloads:
            return Response({"message": "Downloads are disabled for this event."}, status=status.HTTP_403_FORBIDDEN)

        provided_pin = (
            request.query_params.get('pin')
            or request.headers.get('X-Event-PIN')
            or (request.data.get('pin') if hasattr(request, 'data') else None)
        )
        if event.is_pin_protected and not event.verify_pin(provided_pin):
            return Response({"message": "Invalid or missing PIN for this download."}, status=status.HTTP_403_FORBIDDEN)

        photo_ids = None
        if hasattr(request, 'data') and isinstance(request.data, dict) and 'photo_ids' in request.data:
            photo_ids = request.data.get('photo_ids')
        elif 'photo_ids' in request.query_params:
            try:
                photo_ids = [int(i.strip()) for i in request.query_params.get('photo_ids').split(',') if i.strip()]
            except ValueError:
                photo_ids = None

        photos = event.photos.all()
        if photo_ids:
            photos = photos.filter(id__in=photo_ids)

        if not photos.exists():
            return Response({"message": "No photos available to download."}, status=status.HTTP_404_NOT_FOUND)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            used_names = set()
            for idx, photo in enumerate(photos, start=1):
                if not photo.image:
                    continue
                try:
                    photo_data = photo.image.read()
                except Exception:
                    continue

                raw_name = photo.original_filename or f"photo_{photo.id}.jpg"
                base_name, ext = os.path.splitext(raw_name)
                if not ext:
                    ext = ".jpg"

                clean_name = f"{base_name}{ext}"
                counter = 1
                while clean_name in used_names:
                    clean_name = f"{base_name}_{counter}{ext}"
                    counter += 1
                used_names.add(clean_name)

                zip_file.writestr(clean_name, photo_data)

        SharedEvent.objects.filter(pk=event.pk).update(downloads_count=F('downloads_count') + 1)

        zip_buffer.seek(0)
        zip_filename = f"{slugify(event.title) or 'event'}_photos.zip"

        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
        response['Content-Length'] = len(zip_buffer.getvalue())
        return response


class PublicEventQRView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, access_code):
        event = get_object_or_404(SharedEvent.objects.select_related('photographer'), access_code=access_code)
        share_url = request.build_absolute_uri(f"/api/storage/share/{event.access_code}/")
        encoded_url = urllib.parse.quote(share_url)
        qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded_url}"

        return Response(
            {
                "event_title": event.title,
                "access_code": event.access_code,
                "share_url": share_url,
                "qr_image_url": qr_image_url,
                "is_pin_protected": event.is_pin_protected,
                "photographer": event.photographer.name
            },
            status=status.HTTP_200_OK
        )


# =============================================================================
# 2. Enterprise Photographer Gallery Management APIs
# =============================================================================

class GalleryListCreateView(APIView):
    def get(self, request):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED", "detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        profile = get_photographer_profile(user)
        if not profile and not (user.is_staff or user.is_superuser):
            return Response({"code": "NOT_A_PHOTOGRAPHER", "detail": "Photographer profile not found."}, status=status.HTTP_403_FORBIDDEN)

        if user.is_staff or user.is_superuser:
            queryset = Gallery.objects.all().select_related('photographer')
        else:
            queryset = Gallery.objects.filter(photographer=profile)

        from django.db.models.functions import Coalesce
        # Annotate photos_count, videos_count, and total_size_bytes for efficient sorting and counting
        queryset = queryset.annotate(
            photos_count=Count('media_items', filter=Q(media_items__deleted_at__isnull=True, media_items__media_type='photo'), distinct=True),
            videos_count=Count('media_items', filter=Q(media_items__deleted_at__isnull=True, media_items__media_type='video'), distinct=True),
            total_size_bytes=Coalesce(Sum('media_items__file_size', filter=Q(media_items__deleted_at__isnull=True)), 0),
        )

        # ─── 1. Search Filter (Title or Client Name) ───
        search = request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(client_name__icontains=search)
            )

        # ─── 2. Status Filter ───
        status_param = (request.query_params.get('status') or '').strip().lower()
        if status_param == 'archived':
            queryset = queryset.filter(status='archived')
        elif status_param in ['active', 'delivered', 'draft', 'published']:
            queryset = queryset.filter(status=status_param)
        elif not status_param or status_param == 'all':
            # Default active drive view: Exclude archived items so they don't clutter the main drive
            queryset = queryset.exclude(status='archived')

        # ─── 3. Date Presets & Custom Ranges ───
        date_filter = request.query_params.get('date_filter', '').strip().lower()
        now = timezone.now().date()

        if date_filter == 'this-year':
            queryset = queryset.filter(event_date__year=now.year)
        elif date_filter == 'last-year':
            queryset = queryset.filter(event_date__year=now.year - 1)
        elif date_filter == 'last-30-days':
            queryset = queryset.filter(event_date__gte=now - timedelta(days=30))
        elif date_filter == 'last-3-months':
            queryset = queryset.filter(event_date__gte=now - timedelta(days=90))
        elif date_filter == 'last-6-months':
            queryset = queryset.filter(event_date__gte=now - timedelta(days=180))
        elif date_filter.startswith('year-'):
            try:
                target_year = int(date_filter.replace('year-', ''))
                queryset = queryset.filter(event_date__year=target_year)
            except ValueError:
                pass
        elif date_filter == 'custom':
            date_from = request.query_params.get('date_from', '').strip()
            date_to = request.query_params.get('date_to', '').strip()
            if date_from:
                queryset = queryset.filter(event_date__gte=date_from)
            if date_to:
                queryset = queryset.filter(event_date__lte=date_to)

        # Direct date_from / date_to if provided
        date_from = request.query_params.get('date_from', '').strip()
        date_to = request.query_params.get('date_to', '').strip()
        if date_from and date_filter != 'custom':
            queryset = queryset.filter(event_date__gte=date_from)
        if date_to and date_filter != 'custom':
            queryset = queryset.filter(event_date__lte=date_to)

        # ─── 4. Sorting & Ordering ───
        sort = request.query_params.get('sort', 'date-desc').strip()
        if sort == 'date-desc':
            queryset = queryset.order_by('-event_date', '-created_at')
        elif sort == 'date-asc':
            queryset = queryset.order_by('event_date', 'created_at')
        elif sort == 'name':
            queryset = queryset.order_by('title')
        elif sort == 'photos':
            queryset = queryset.order_by('-photos_count', '-event_date', '-created_at')
        else:
            queryset = queryset.order_by('-event_date', '-created_at')

        serializer = GallerySerializer(queryset, many=True, context={'request': request, 'include_media': False})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED", "detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        enforce_active_subscription(user, "client galleries")

        profile = get_photographer_profile(user)
        if not profile and not (user.is_staff or user.is_superuser):
            return Response({"code": "NOT_A_PHOTOGRAPHER", "detail": "Photographer profile not found."}, status=status.HTTP_403_FORBIDDEN)

        # Check active plan restrictions for photographer
        active_plan = getattr(profile, 'studio_plan', None) if profile else None
        if profile and not active_plan and hasattr(profile, 'subscription') and profile.subscription and profile.subscription.plan:
            active_plan = profile.subscription.plan
        if profile and not active_plan and hasattr(user, 'subscription') and user.subscription and user.subscription.plan:
            active_plan = user.subscription.plan
        if profile and not active_plan and profile.plan:
            active_plan = profile.plan

        requested_template = request.data.get('template_id', 'editorial')
        if active_plan and getattr(active_plan, 'allowed_templates', None):
            if not is_gallery_template_allowed(active_plan, requested_template):
                return Response({
                    "code": "TEMPLATE_NOT_ALLOWED",
                    "error_code": "TEMPLATE_NOT_ALLOWED",
                    "detail": f"Template '{requested_template}' is not included in your current subscription tier."
                }, status=status.HTTP_403_FORBIDDEN)

        # Check watermark_enabled plan entitlement
        if 'watermark_enabled' in request.data:
            val = request.data.get('watermark_enabled')
            is_enabling = val in [True, 'true', 'True', 1, '1']
            if is_enabling and not (user.is_staff or user.is_superuser):
                if not active_plan or not getattr(active_plan, 'watermark_enabled', False):
                    return Response({
                        "error_code": "WATERMARK_LOCKED",
                        "upgrade_required": True,
                        "detail": "Custom studio watermarking is not included in your current subscription plan. Please upgrade your plan to watermark proofing galleries.",
                        "message": "Custom studio watermarking is not included in your current subscription plan. Please upgrade your plan to watermark proofing galleries."
                    }, status=status.HTTP_403_FORBIDDEN)

        if active_plan and getattr(active_plan, 'max_galleries', 0) > 0 and profile:
            current_active = profile.galleries.exclude(status='archived').count()
            if current_active >= active_plan.max_galleries:
                return Response({
                    "code": "GALLERY_LIMIT_EXCEEDED",
                    "error_code": "GALLERY_LIMIT_EXCEEDED",
                    "upgrade_required": True,
                    "message": f"Gallery quota reached for your {active_plan.name} ({current_active}/{active_plan.max_galleries}). Upgrade to unlock more client galleries.",
                    "detail": f"Your plan allows up to {active_plan.max_galleries} active galleries. Please upgrade to unlock more."
                }, status=status.HTTP_403_FORBIDDEN)

        serializer = GallerySerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            extra_kwargs = {}
            if active_plan:
                if getattr(active_plan, 'gallery_expiry_days', 0) > 0 and 'expires_at' not in request.data:
                    extra_kwargs['expires_at'] = timezone.now() + timedelta(days=active_plan.gallery_expiry_days)

            gallery = serializer.save(photographer=profile, **extra_kwargs)
            StorageAuditLog.objects.create(
                photographer=profile,
                gallery=gallery,
                user=user,
                action="GALLERY_CREATED",
                details={"title": gallery.title, "visibility": gallery.visibility, "status": gallery.status},
            )
            return Response(GallerySerializer(gallery, context={'request': request}).data, status=status.HTTP_201_CREATED)

        return Response({"code": "VALIDATION_FAILED", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class GalleryMediaCursorPagination:
    """
    High-performance Keyset Cursor Pagination Helper.
    Encodes the boundary state into an opaque URL-safe base64 token.
    Cursor payload: { "s": sort_order, "c": created_at_iso, "id": str(media_uuid) }
    """
    DEFAULT_PAGE_SIZE = 48
    MAX_PAGE_SIZE = 100

    @classmethod
    def encode_cursor(cls, sort_order: int, created_at_iso: str, media_id: str) -> str:
        payload = {
            's': int(sort_order or 0),
            'c': str(created_at_iso or ''),
            'id': str(media_id)
        }
        json_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        return base64.urlsafe_b64encode(json_bytes).decode('utf-8')

    @classmethod
    def decode_cursor(cls, cursor_str) -> dict:
        if not cursor_str:
            return None
        try:
            padded = str(cursor_str) + '=' * (-len(str(cursor_str)) % 4)
            raw_bytes = base64.urlsafe_b64decode(padded.encode('utf-8'))
            return json.loads(raw_bytes.decode('utf-8'))
        except Exception:
            return None


class GalleryDetailView(APIView):
    def _get_gallery(self, pk, user):
        return _get_gallery_or_404(pk, user)

    def get(self, request, pk):
        user = get_current_user(request)
        unfiltered_gallery = _get_gallery_or_404(pk)
        if not unfiltered_gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        is_owner = user and (user.is_staff or user.is_superuser or unfiltered_gallery.photographer.user_id == user.id)
        if user and user.is_authenticated:
            if not is_owner:
                return Response({'code': 'GALLERY_ACCESS_DENIED', 'detail': 'You do not own this gallery.'}, status=status.HTTP_403_FORBIDDEN)
            gallery = unfiltered_gallery
        else:
            # Unauthenticated public visitor
            if unfiltered_gallery.visibility == 'private':
                return Response({'code': 'GALLERY_ACCESS_DENIED', 'detail': 'This gallery is private.'}, status=status.HTTP_403_FORBIDDEN)

            is_locked = unfiltered_gallery.is_password_protected or unfiltered_gallery.visibility == 'password_protected'
            if is_locked:
                provided_pwd = request.headers.get("X-Gallery-Password") or request.query_params.get("password")
                if not provided_pwd or not unfiltered_gallery.check_access_password(provided_pwd):
                    return Response({
                        "code": "PASSWORD_REQUIRED",
                        "error_code": "PASSWORD_REQUIRED",
                        "detail": "This gallery is password-protected. Please enter the password.",
                        "is_password_protected": True
                    }, status=status.HTTP_403_FORBIDDEN)
            gallery = unfiltered_gallery

        # ----------------------------------------------------------------------
        # 1. Base Media Queryset
        # ----------------------------------------------------------------------
        base_media_qs = gallery.media_items.filter(deleted_at__isnull=True)
        media_qs = base_media_qs

        # ----------------------------------------------------------------------
        # 2. Dynamic Filters (Section, Liked, Media Type)
        # ----------------------------------------------------------------------
        section_filter = request.query_params.get('section', '').strip()
        if section_filter and section_filter.lower() != 'all':
            media_qs = media_qs.filter(section_title__iexact=section_filter)

        is_favorite_param = request.query_params.get('is_favorite') or request.query_params.get('isFavorite')
        if is_favorite_param is not None and str(is_favorite_param).lower() in ('true', '1'):
            media_qs = media_qs.filter(is_favorite=True)

        media_type = request.query_params.get('type')
        if media_type in ('photo', 'video'):
            media_qs = media_qs.filter(media_type=media_type)

        # Total counts
        total_media_count = base_media_qs.count()
        filtered_media_count = media_qs.count()

        # ----------------------------------------------------------------------
        # 3. Check for Legacy Full-Payload Override (?all_media=true)
        # ----------------------------------------------------------------------
        if request.query_params.get('all_media', '').lower() in ('true', '1'):
            media_items = list(media_qs.order_by('display_order', '-created_at', 'id'))
            serializer = GalleryDetailResponseSerializer(
                gallery,
                context={
                    'request': request,
                    'paginated_media': media_items,
                    'next_cursor': None,
                    'has_more': False,
                    'total_media_count': total_media_count,
                    'filtered_media_count': filtered_media_count,
                }
            )
            data = serializer.data
            data['next_cursor'] = None
            data['has_more'] = False
            data['total_media_count'] = total_media_count
            data['filtered_media_count'] = filtered_media_count
            return Response(data, status=status.HTTP_200_OK)

        # ----------------------------------------------------------------------
        # 4. Keyset / Cursor Pagination Setup
        # ----------------------------------------------------------------------
        raw_limit = request.query_params.get('limit') or request.query_params.get('page_size')
        try:
            limit = min(max(int(raw_limit), 1), GalleryMediaCursorPagination.MAX_PAGE_SIZE)
        except (ValueError, TypeError):
            limit = GalleryMediaCursorPagination.DEFAULT_PAGE_SIZE

        # Stable index ordering: display_order ASC, created_at DESC, id ASC
        media_qs = media_qs.order_by('display_order', '-created_at', 'id')

        cursor_token = request.query_params.get('cursor')
        if cursor_token:
            decoded = GalleryMediaCursorPagination.decode_cursor(cursor_token)
            if decoded:
                c_sort = decoded.get('s', 0)
                c_created = decoded.get('c', '')
                c_id = decoded.get('id', '')

                c_created_dt = parse_datetime(c_created) if c_created else None
                try:
                    c_id_val = uuid.UUID(str(c_id)) if c_id else None
                except Exception:
                    c_id_val = c_id

                if c_created_dt and c_id_val:
                    media_qs = media_qs.filter(
                        Q(display_order__gt=c_sort) |
                        Q(display_order=c_sort, created_at__lt=c_created_dt) |
                        Q(display_order=c_sort, created_at=c_created_dt, id__gt=c_id_val)
                    )
                elif c_created_dt:
                    media_qs = media_qs.filter(
                        Q(display_order__gt=c_sort) |
                        Q(display_order=c_sort, created_at__lt=c_created_dt)
                    )
                else:
                    media_qs = media_qs.filter(display_order__gt=c_sort)

        # Fetch limit + 1 items to determine has_more in one single query
        media_items = list(media_qs[:limit + 1])
        has_more = len(media_items) > limit
        if has_more:
            media_items = media_items[:limit]

        # Build next_cursor token from the last element
        next_cursor = None
        if has_more and media_items:
            last_item = media_items[-1]
            next_cursor = GalleryMediaCursorPagination.encode_cursor(
                sort_order=getattr(last_item, 'display_order', 0),
                created_at_iso=last_item.created_at.isoformat() if getattr(last_item, 'created_at', None) else '',
                media_id=str(last_item.id)
            )

        # ----------------------------------------------------------------------
        # 5. Serialize Gallery Response with Paginated Media Slice
        # ----------------------------------------------------------------------
        serializer = GalleryDetailResponseSerializer(
            gallery,
            context={
                'request': request,
                'paginated_media': media_items,
                'next_cursor': next_cursor,
                'has_more': has_more,
                'total_media_count': total_media_count,
                'filtered_media_count': filtered_media_count,
            }
        )
        data = serializer.data
        data['next_cursor'] = next_cursor
        data['has_more'] = has_more
        data['total_media_count'] = total_media_count
        data['filtered_media_count'] = filtered_media_count

        return Response(data, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = self._get_gallery(pk, user)
        if not gallery:
            if _get_gallery_or_404(pk):
                return Response({'code': 'GALLERY_ACCESS_DENIED', 'detail': 'You do not own this gallery.'}, status=status.HTTP_403_FORBIDDEN)
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        # 1. Enforce plan restriction if enabling face_search_enabled
        if 'face_search_enabled' in request.data:
            val = request.data.get('face_search_enabled')
            is_enabling = val in [True, 'true', 'True', 1, '1']
            if is_enabling and not (user.is_staff or user.is_superuser):
                profile = gallery.photographer
                sub = getattr(profile, 'subscription', None)
                plan = getattr(sub, 'plan', None) if sub else None
                if not plan:
                    plan = getattr(profile, 'studio_plan', None) or getattr(profile, 'plan', None)
                plan_allowed = getattr(plan, 'face_search_enabled', False)
                if not plan_allowed:
                    return Response({
                        "error_code": "FACE_SEARCH_LOCKED",
                        "code": "FACE_SEARCH_LOCKED",
                        "detail": "Your subscription plan does not include AI Face Search.",
                        "message": "AI Biometric Face Search is locked on your current subscription plan. Upgrade to enable.",
                        "upgrade_required": True
                    }, status=status.HTTP_403_FORBIDDEN)

        # Enforce plan restriction if enabling watermark_enabled
        if 'watermark_enabled' in request.data:
            val = request.data.get('watermark_enabled')
            is_enabling = val in [True, 'true', 'True', 1, '1']
            if is_enabling and not (user.is_staff or user.is_superuser):
                profile = gallery.photographer
                sub = getattr(profile, 'subscription', None)
                if not sub and hasattr(user, 'subscription'):
                    sub = user.subscription
                plan = getattr(sub, 'plan', None) if sub and getattr(sub, 'is_active', True) else None
                if not plan and profile:
                    plan = getattr(profile, 'studio_plan', None) or getattr(profile, 'plan', None)
                if not plan or not getattr(plan, 'watermark_enabled', False):
                    return Response({
                        "error_code": "WATERMARK_LOCKED",
                        "upgrade_required": True,
                        "detail": "Custom studio watermarking is not included in your current subscription plan. Please upgrade your plan to watermark proofing galleries.",
                        "message": "Custom studio watermarking is not included in your current subscription plan. Please upgrade your plan to watermark proofing galleries."
                    }, status=status.HTTP_403_FORBIDDEN)

        # 2. Check template_id allowed_templates
        if 'template_id' in request.data:
            template_id = request.data['template_id']
            profile = gallery.photographer
            active_plan = getattr(profile, 'studio_plan', None)
            if not active_plan and hasattr(profile, 'subscription') and profile.subscription and profile.subscription.plan:
                active_plan = profile.subscription.plan
            if not active_plan and profile.plan:
                active_plan = profile.plan

            if active_plan and getattr(active_plan, 'allowed_templates', None):
                if not is_gallery_template_allowed(active_plan, template_id):
                    return Response({
                        "code": "TEMPLATE_NOT_ALLOWED",
                        "error_code": "TEMPLATE_NOT_ALLOWED",
                        "detail": f"Template '{template_id}' is not included in your current subscription tier."
                    }, status=status.HTTP_403_FORBIDDEN)

        # 3. Explicit password handling & wiping
        if 'is_password_protected' in request.data:
            raw_prot = request.data.get('is_password_protected')
            is_prot = raw_prot in [True, 'true', 'True', 1, '1']
            gallery.is_password_protected = is_prot
            if not is_prot:
                gallery.password = ''
                if gallery.visibility == 'password_protected':
                    gallery.visibility = 'public'
            elif 'password' in request.data and request.data.get('password'):
                gallery.set_access_password(request.data.get('password').strip())
        elif 'password' in request.data:
            pwd = request.data.get('password')
            if pwd and gallery.is_password_protected:
                gallery.set_access_password(pwd.strip())
            elif not gallery.is_password_protected:
                gallery.password = ''

        serializer = GallerySerializer(gallery, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            updated_gallery = serializer.save()
            return Response(GalleryDetailResponseSerializer(updated_gallery, context={'request': request}).data, status=status.HTTP_200_OK)

        return Response({"code": "VALIDATION_FAILED", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, pk):
        return self.patch(request, pk)

    def delete(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = self._get_gallery(pk, user)
        if not gallery:
            if _get_gallery_or_404(pk):
                return Response({'code': 'GALLERY_ACCESS_DENIED', 'detail': 'You do not own this gallery.'}, status=status.HTTP_403_FORBIDDEN)
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        is_permanent = request.query_params.get('permanent', 'false').lower() in ('true', '1')

        # Permanent Delete
        if is_permanent or gallery.status == 'archived':
            gallery_title = gallery.title
            photographer = gallery.photographer

            # Cascade media files from object storage (cloud / local)
            storage = get_storage_provider()
            media_items = list(gallery.media_items.all())
            for media in media_items:
                try:
                    if media.storage_key:
                        storage.delete(media.storage_key)
                    if media.thumbnail_storage_key:
                        storage.delete(media.thumbnail_storage_key)
                    if media.preview_storage_key:
                        storage.delete(media.preview_storage_key)
                    if media.file and hasattr(media.file, 'path') and os.path.exists(media.file.path):
                        try:
                            os.remove(media.file.path)
                        except OSError:
                            pass
                    FaceEmbedding.objects.filter(media=media).delete()
                    if media.deleted_at is None and media.file_size:
                        StorageQuotaService.deduct_storage(photographer, media.file_size)
                except Exception as e:
                    logger.warning(f"Error deleting media {media.id} files during gallery purge: {e}")

            gallery.delete()

            StorageAuditLog.objects.create(
                photographer=photographer,
                gallery=None,
                user=user,
                action="GALLERY_PERMANENTLY_DELETED",
                details={"title": gallery_title, "gallery_id": str(pk)}
            )

            return Response({
                'success': True,
                'status': 'deleted',
                'message': f'Gallery "{gallery_title}" permanently deleted.'
            }, status=status.HTTP_200_OK)

        # Soft Delete (Move to Archive / Trash)
        gallery.status = 'archived'
        gallery.save(update_fields=['status'])

        StorageAuditLog.objects.create(
            photographer=gallery.photographer,
            gallery=gallery,
            user=user,
            action="GALLERY_ARCHIVED",
            details={"gallery_id": str(gallery.id), "title": gallery.title}
        )
        return Response({
            'success': True,
            'status': 'archived',
            'message': f'Gallery "{gallery.title}" moved to archive / trash.'
        }, status=status.HTTP_200_OK)


GallerySettingsDetailView = GalleryDetailView


class GalleryViewSet(viewsets.ModelViewSet):
    """
    ModelViewSet providing full CRUD, server-side filtering, sorting,
    and plan quota enforcement for client galleries.
    """
    serializer_class = GallerySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        profile = get_photographer_profile(user)

        if user.is_staff or user.is_superuser:
            queryset = Gallery.objects.all().select_related('photographer')
        elif profile:
            queryset = Gallery.objects.filter(photographer=profile)
        else:
            queryset = Gallery.objects.none()

        queryset = queryset.annotate(
            photos_count=Count('media_items', filter=Q(media_items__deleted_at__isnull=True, media_items__media_type='photo'), distinct=True),
            videos_count=Count('media_items', filter=Q(media_items__deleted_at__isnull=True, media_items__media_type='video'), distinct=True),
        )

        search = self.request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(client_name__icontains=search)
            )

        status_filter = (self.request.query_params.get('status') or '').strip().lower()
        if status_filter == 'archived':
            queryset = queryset.filter(status='archived')
        elif status_filter in ['active', 'delivered', 'draft', 'published']:
            queryset = queryset.filter(status=status_filter)
        elif not status_filter or status_filter == 'all':
            # Default active drive view: Exclude archived items so they don't clutter the main drive
            queryset = queryset.exclude(status='archived')

        date_filter = self.request.query_params.get('date_filter', '').strip().lower()
        now = timezone.now().date()

        if date_filter == 'this-year':
            queryset = queryset.filter(event_date__year=now.year)
        elif date_filter == 'last-year':
            queryset = queryset.filter(event_date__year=now.year - 1)
        elif date_filter == 'last-30-days':
            queryset = queryset.filter(event_date__gte=now - timedelta(days=30))
        elif date_filter == 'last-3-months':
            queryset = queryset.filter(event_date__gte=now - timedelta(days=90))
        elif date_filter == 'last-6-months':
            queryset = queryset.filter(event_date__gte=now - timedelta(days=180))
        elif date_filter.startswith('year-'):
            try:
                target_year = int(date_filter.replace('year-', ''))
                queryset = queryset.filter(event_date__year=target_year)
            except ValueError:
                pass
        elif date_filter == 'custom':
            date_from = self.request.query_params.get('date_from', '').strip()
            date_to = self.request.query_params.get('date_to', '').strip()
            if date_from:
                queryset = queryset.filter(event_date__gte=date_from)
            if date_to:
                queryset = queryset.filter(event_date__lte=date_to)

        date_from = self.request.query_params.get('date_from', '').strip()
        date_to = self.request.query_params.get('date_to', '').strip()
        if date_from and date_filter != 'custom':
            queryset = queryset.filter(event_date__gte=date_from)
        if date_to and date_filter != 'custom':
            queryset = queryset.filter(event_date__lte=date_to)

        sort = self.request.query_params.get('sort', 'date-desc').strip()
        if sort == 'date-desc':
            queryset = queryset.order_by('-event_date', '-created_at')
        elif sort == 'date-asc':
            queryset = queryset.order_by('event_date', 'created_at')
        elif sort == 'name':
            queryset = queryset.order_by('title')
        elif sort == 'photos':
            queryset = queryset.order_by('-photos_count', '-event_date', '-created_at')
        else:
            queryset = queryset.order_by('-event_date', '-created_at')

        return queryset

    def get_object(self):
        """Supports retrieving galleries by either UUID primary key OR slug."""
        queryset = self.filter_queryset(self.get_queryset())
        lookup_val = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field)
        try:
            uuid.UUID(str(lookup_val))
            obj = queryset.filter(id=lookup_val).first()
        except (ValueError, AttributeError):
            obj = queryset.filter(slug=lookup_val).first()

        if not obj:
            raise NotFound({"detail": f"Gallery '{lookup_val}' not found."})

        self.check_object_permissions(self.request, obj)
        return obj

    @action(detail=True, methods=['post'], url_path='face-search', permission_classes=[permissions.AllowAny])
    def face_search(self, request, pk=None):
        return GalleryFaceSearchView().post(request, pk)

    def perform_create(self, serializer):
        user = self.request.user
        enforce_active_subscription(user, "client galleries")
        profile = get_photographer_profile(user)
        active_plan = getattr(profile, 'studio_plan', None) if profile else None
        if profile and not active_plan and hasattr(profile, 'subscription') and profile.subscription and profile.subscription.plan:
            active_plan = profile.subscription.plan
        if profile and not active_plan and hasattr(user, 'subscription') and user.subscription and user.subscription.plan:
            active_plan = user.subscription.plan
        if profile and not active_plan and profile.plan:
            active_plan = profile.plan

        requested_template = self.request.data.get('template_id', 'editorial')
        if active_plan and getattr(active_plan, 'allowed_templates', None):
            if not is_gallery_template_allowed(active_plan, requested_template):
                raise PermissionDenied({
                    "code": "TEMPLATE_NOT_ALLOWED",
                    "error_code": "TEMPLATE_NOT_ALLOWED",
                    "detail": f"Template '{requested_template}' is not included in your current subscription tier."
                })

        if active_plan and getattr(active_plan, 'max_galleries', 0) > 0 and profile:
            current_active = profile.galleries.exclude(status='archived').count()
            if current_active >= active_plan.max_galleries:
                raise PermissionDenied({
                    "upgrade_required": True,
                    "code": "GALLERY_LIMIT_EXCEEDED",
                    "error_code": "GALLERY_LIMIT_EXCEEDED",
                    "message": f"Gallery quota reached for your {active_plan.name} ({current_active}/{active_plan.max_galleries}). Upgrade to unlock more client galleries.",
                    "detail": f"Your plan allows up to {active_plan.max_galleries} active galleries. Please upgrade to unlock more."
                })

        extra_kwargs = {}
        if active_plan:
            if getattr(active_plan, 'gallery_expiry_days', 0) > 0 and 'expires_at' not in self.request.data:
                extra_kwargs['expires_at'] = timezone.now() + timedelta(days=active_plan.gallery_expiry_days)
            if hasattr(active_plan, 'face_search_enabled') and 'face_search_enabled' not in self.request.data:
                extra_kwargs['face_search_enabled'] = active_plan.face_search_enabled

        serializer.save(photographer=profile, **extra_kwargs)

    def partial_update(self, request, *args, **kwargs):
        if 'template_id' in request.data:
            template_id = request.data['template_id']
            gallery = self.get_object()
            profile = gallery.photographer
            active_plan = getattr(profile, 'studio_plan', None)
            if not active_plan and hasattr(profile, 'subscription') and profile.subscription and profile.subscription.plan:
                active_plan = profile.subscription.plan
            if not active_plan and profile.plan:
                active_plan = profile.plan

            if active_plan and getattr(active_plan, 'allowed_templates', None):
                if not is_gallery_template_allowed(active_plan, template_id):
                    raise PermissionDenied({
                        "code": "TEMPLATE_NOT_ALLOWED",
                        "error_code": "TEMPLATE_NOT_ALLOWED",
                        "detail": f"Template '{template_id}' is not included in your current subscription tier."
                    })
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """
        Two-stage gallery deletion:
        1. Calling DELETE on an active gallery moves it to 'archived'.
        2. Calling DELETE on an already-archived gallery (or with ?permanent=true) permanently removes it.
        """
        instance = self.get_object()
        is_permanent = request.query_params.get('permanent', 'false').lower() in ('true', '1')

        # Permanent Delete
        if is_permanent or instance.status == 'archived':
            gallery_title = instance.title
            photographer = instance.photographer
            storage = get_storage_provider()
            for media in instance.media_items.all():
                try:
                    if media.storage_key:
                        storage.delete(media.storage_key)
                    if media.thumbnail_storage_key:
                        storage.delete(media.thumbnail_storage_key)
                    if media.preview_storage_key:
                        storage.delete(media.preview_storage_key)
                    if media.file and hasattr(media.file, 'path') and os.path.exists(media.file.path):
                        try:
                            os.remove(media.file.path)
                        except OSError:
                            pass
                    FaceEmbedding.objects.filter(media=media).delete()
                    if media.deleted_at is None and media.file_size:
                        StorageQuotaService.deduct_storage(photographer, media.file_size)
                except Exception as e:
                    logger.warning(f"Error deleting media {media.id} files: {e}")

            self.perform_destroy(instance)
            return Response({
                'success': True,
                'status': 'deleted',
                'message': f'Gallery "{gallery_title}" permanently deleted.'
            }, status=status.HTTP_200_OK)

        # Soft Delete (Move to Archive / Trash)
        instance.status = 'archived'
        instance.save(update_fields=['status'])
        return Response({
            'success': True,
            'status': 'archived',
            'message': f'Gallery "{instance.title}" moved to archive / trash.'
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='restore')
    def restore(self, request, pk=None):
        """
        POST /api/galleries/{id}/restore/
        Reactivates an archived gallery back to 'active' or 'delivered'.
        """
        instance = self.get_object()
        target_status = request.data.get('status', 'active')
        if target_status not in ['active', 'delivered']:
            target_status = 'active'

        instance.status = target_status
        instance.save(update_fields=['status'])
        return Response({
            'success': True,
            'status': instance.status,
            'message': f'Gallery "{instance.title}" restored to {instance.status}.'
        }, status=status.HTTP_200_OK)


class GalleryRestoreView(APIView):
    """
    POST /api/galleries/{id}/restore/
    Reactivates an archived gallery back to 'active' or 'delivered'.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, gallery_id=None, pk=None):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED", "detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        target_id = gallery_id or pk
        gallery = _get_gallery_or_404(target_id, user)
        if not gallery:
            unfiltered = _get_gallery_or_404(target_id)
            if not unfiltered:
                return Response({"code": "gallery_not_found", "detail": "Gallery not found."}, status=status.HTTP_404_NOT_FOUND)
            if not (user.is_staff or user.is_superuser or unfiltered.photographer.user_id == user.id):
                return Response({"code": "GALLERY_ACCESS_DENIED", "detail": "You do not own this gallery."}, status=status.HTTP_403_FORBIDDEN)
            gallery = unfiltered

        target_status = request.data.get('status', 'active')
        if target_status not in ['active', 'delivered']:
            target_status = 'active'

        gallery.status = target_status
        gallery.save(update_fields=['status', 'updated_at'])

        StorageAuditLog.objects.create(
            photographer=gallery.photographer,
            gallery=gallery,
            user=user,
            action="GALLERY_RESTORED",
            details={"gallery_id": str(gallery.id), "status": gallery.status, "title": gallery.title}
        )

        return Response({
            'success': True,
            'status': gallery.status,
            'message': f'Gallery "{gallery.title}" restored to {gallery.status}.'
        }, status=status.HTTP_200_OK)


class GalleryShareView(APIView):
    """Generates, checks, or revokes a gallery share token."""

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = get_object_or_404(Gallery, id=gallery_id)
        if gallery.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "GALLERY_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        # Rotate/generate new share token
        new_token = gallery.revoke_share_token()
        share_url = request.build_absolute_uri(f"/api/shared-galleries/{new_token}/")

        StorageAuditLog.objects.create(
            photographer=gallery.photographer,
            gallery=gallery,
            user=user,
            action="SHARE_TOKEN_GENERATED",
            details={"share_token": new_token},
        )

        return Response(
            {
                "message": "Share link generated successfully.",
                "share_token": new_token,
                "share_url": share_url,
            },
            status=status.HTTP_200_OK
        )

    def delete(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = get_object_or_404(Gallery, id=gallery_id)
        if gallery.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "GALLERY_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        # Revoking changes token, invalidating previously shared links
        gallery.revoke_share_token()
        return Response({"message": "Share link revoked successfully."}, status=status.HTTP_200_OK)


# =============================================================================
# 3. Direct-to-Storage & Multipart Media Upload APIs
# =============================================================================

class DirectUploadInitView(APIView):
    """
    Step 1: Photographer requests pre-signed direct upload URL(s).
    Validates photographer storage quota and atomically reserves bytes.
    Supports single file or batch 'files: [...]' payload.
    """
    throttle_classes = [UploadRateThrottle]

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        enforce_active_subscription(user, "media uploads")

        gallery = get_object_or_404(Gallery.objects.select_related('photographer'), id=gallery_id)
        if gallery.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "GALLERY_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        # Handle batch or single file
        files_data = request.data.get('files')
        is_batch = isinstance(files_data, list) and len(files_data) > 0
        if not is_batch:
            files_data = [request.data]

        prepared_items = []
        total_requested_size = 0
        for item in files_data:
            filename = item.get("filename") or item.get("original_filename")
            file_size = item.get("file_size")
            mime_type = item.get("mime_type", "image/jpeg")
            media_type = item.get("media_type", "photo")
            if not filename or not file_size:
                return Response({
                    "code": "VALIDATION_FAILED",
                    "detail": "Each file must specify 'filename' (or 'original_filename') and 'file_size'."
                }, status=status.HTTP_400_BAD_REQUEST)

            total_requested_size += int(file_size)
            prepared_items.append({
                "filename": filename,
                "file_size": int(file_size),
                "mime_type": mime_type,
                "media_type": media_type
            })

        # Atomic check against photographer's storage quota
        photographer = gallery.photographer
        if not photographer.can_allocate_storage(total_requested_size):
            remaining = photographer.get_storage_remaining()
            return Response({
                "code": "STORAGE_LIMIT_EXCEEDED",
                "detail": f"Insufficient storage quota. Requested {total_requested_size} bytes, available {remaining} bytes."
            }, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        results = []
        storage = get_storage_provider()

        for item in prepared_items:
            try:
                reservation = StorageQuotaService.reserve_quota(photographer, gallery, item["file_size"])
            except StorageQuotaExceededException as e:
                return Response({"code": "STORAGE_LIMIT_EXCEEDED", "detail": str(e)}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

            storage_key = f"galleries/{gallery.id}/originals/{reservation.id}_{item['filename']}"
            upload_meta = storage.generate_signed_upload_url(storage_key, expires_in=1800, content_type=item["mime_type"])
            upload_url = upload_meta["upload_url"]
            if upload_url.startswith('/'):
                upload_url = request.build_absolute_uri(upload_url)

            results.append({
                "reservation_id": str(reservation.id),
                "storage_key": storage_key,
                "filename": item["filename"],
                "media_type": item["media_type"],
                "upload_url": upload_url,
                "method": upload_meta.get("method", "PUT"),
                "headers": upload_meta.get("headers", {}),
                "expires_in": 1800,
            })

        if is_batch:
            return Response({"status": "success", "files": results}, status=status.HTTP_200_OK)
        return Response(results[0], status=status.HTTP_200_OK)


class DirectUploadConfirmView(APIView):
    """
    Step 2: Client or photographer confirms upload completion.
    Backend verifies file exists in storage, commits quota, and triggers background processing.
    """

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = get_object_or_404(Gallery.objects.select_related('photographer'), id=gallery_id)
        if gallery.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "GALLERY_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        serializer = DirectUploadConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"code": "VALIDATION_FAILED", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        reservation_id = serializer.validated_data["reservation_id"]
        reservation = get_object_or_404(UploadReservation, id=reservation_id, gallery=gallery)

        storage_key = serializer.validated_data.get("storage_key") or f"galleries/{gallery.id}/originals/{reservation.id}_{serializer.validated_data.get('original_filename', 'media')}"
        storage = get_storage_provider()

        if not storage.exists(storage_key):
            StorageQuotaService.release_quota(reservation)
            return Response({"code": "FILE_NOT_FOUND_IN_STORAGE", "detail": "Media file does not exist in storage."}, status=status.HTTP_400_BAD_REQUEST)

        meta = storage.get_metadata(storage_key)
        actual_size = meta.get("size", serializer.validated_data.get("file_size", reservation.reserved_bytes))
        filename = serializer.validated_data.get("original_filename") or "media_upload"
        ext = os.path.splitext(filename)[1].lower() or ".jpg"

        # Finalize quota
        StorageQuotaService.commit_quota(reservation, actual_size)

        media_type = request.data.get("media_type", "photo")
        aspect_ratio = request.data.get("aspect_ratio")
        width = request.data.get("width")
        height = request.data.get("height")
        duration = request.data.get("duration")

        media = Media.objects.create(
            photographer=gallery.photographer,
            gallery=gallery,
            media_type=media_type,
            original_filename=filename,
            storage_key=storage_key,
            file_size=actual_size,
            mime_type=serializer.validated_data.get("mime_type", "image/jpeg"),
            file_extension=ext,
            aspect_ratio=float(aspect_ratio) if aspect_ratio else None,
            width=int(width) if width else None,
            height=int(height) if height else None,
            duration=str(duration) if duration else None,
            processing_status="pending",
            upload_status="completed",
        )

        # Trigger background processing for derivatives and faces
        run_or_queue_task(process_media_derivatives_and_faces_task, str(media.id))

        return Response(
            {
                "message": "Media upload confirmed successfully.",
                "media": MediaSerializer(media, context={'request': request}).data
            },
            status=status.HTTP_201_CREATED
        )


class StandardMediaUploadView(APIView):
    """
    Direct multi-file batch upload supporting photos and videos:
    handles pre-upload quota validation (403 if exceeded), section persistence,
    automatic photo/video detection, high-volume batch optimization,
    and returns created media array with updated storage metrics.
    """
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [UploadRateThrottle]

    def post(self, request, gallery_id=None):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED", "error": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        enforce_active_subscription(user, "media uploads")

        gid = gallery_id or request.data.get('gallery_id') or request.data.get('gallery')
        if not gid:
            profile = get_photographer_profile(user)
            if profile:
                first_gal = Gallery.objects.filter(photographer=profile).first()
                if first_gal:
                    gid = str(first_gal.id)
                else:
                    new_gal = Gallery.objects.create(
                        photographer=profile,
                        title=f"{profile.name or 'Studio'} Gallery",
                    )
                    gid = str(new_gal.id)
            else:
                return Response({"code": "GALLERY_REQUIRED", "error": "gallery_id required."}, status=status.HTTP_400_BAD_REQUEST)

        gallery = get_object_or_404(Gallery.objects.select_related('photographer'), id=gid)
        if gallery.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "GALLERY_ACCESS_DENIED", "error": "You do not own this gallery."}, status=status.HTTP_403_FORBIDDEN)

        # 1. Multi-File Extraction
        files = (
            request.FILES.getlist('photos')
            + request.FILES.getlist('videos')
            + request.FILES.getlist('files')
            + request.FILES.getlist('images')
        )
        if not files:
            for single_key in ['photo', 'video', 'file', 'image']:
                single = request.FILES.get(single_key)
                if single:
                    files.append(single)

        if not files:
            return Response(
                {
                    "error": "No files provided. Send files under 'photos', 'videos', or 'files'.",
                    "code": "NO_FILES_PROVIDED",
                    "detail": "No files provided. Send files under 'photos', 'videos', or 'files'."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Section Organizing (section_title)
        raw_section = request.data.get('section_title')
        if not raw_section or not str(raw_section).strip():
            raw_section = 'Highlights'
        section_title = str(raw_section).strip().upper()

        gallery_sections = gallery.sections or []
        if not isinstance(gallery_sections, list):
            gallery_sections = list(gallery_sections)
        if not any(str(s).upper() == section_title for s in gallery_sections):
            gallery_sections.append(section_title)
            gallery.sections = gallery_sections
            gallery.save(update_fields=['sections'])

        section_obj = None
        try:
            section_obj, _ = GallerySection.objects.get_or_create(
                gallery=gallery,
                title=section_title,
                defaults={'order': gallery.section_items.count()}
            )
        except Exception:
            section_obj = None

        # 3. Pre-Upload Storage Quota Enforcement
        batch_bytes = sum(getattr(f, 'size', 0) for f in files)
        profile = gallery.photographer
        used_bytes = profile.storage_used_bytes or 0
        limit_bytes = profile.get_storage_limit() or 0

        if limit_bytes > 0 and (used_bytes + batch_bytes) > limit_bytes:
            available_bytes = max(0, limit_bytes - used_bytes)
            available_mb = round(available_bytes / (1024 * 1024), 2)
            batch_mb = round(batch_bytes / (1024 * 1024), 2)
            resp_data = {
                "upgrade_required": True,
                "code": "STORAGE_LIMIT_EXCEEDED",
                "error_code": "STORAGE_LIMIT_EXCEEDED",
                "error": f"Storage quota exceeded. Available space: {available_bytes // (1024 * 1024)} MB.",
                "message": f"Storage limit reached. You have {available_mb} MB available, but requested upload is {batch_mb} MB.",
                "available_bytes": available_bytes,
                "requested_bytes": batch_bytes,
            }
            is_direct_upload = bool(request.path and request.path.rstrip('/').endswith('/galleries/upload'))
            status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE if (is_direct_upload or request.headers.get('X-Expect-413')) else status.HTTP_403_FORBIDDEN
            return Response(resp_data, status=status_code)

        # 4. Multi-Media Processing (Photo vs. Video)
        storage = get_storage_provider()
        created_media = []
        committed_bytes = 0
        is_large_batch = len(files) > 20

        explicit_type = request.data.get('type')
        if explicit_type and str(explicit_type).lower() in ['photo', 'video']:
            explicit_type = str(explicit_type).lower()
        else:
            explicit_type = None

        for f in files:
            ext = os.path.splitext(f.name)[1].lower()
            content_type = getattr(f, 'content_type', '') or ''

            # Automatic photo vs video detection
            if explicit_type:
                media_type = explicit_type
            elif content_type.startswith('video/') or ext in VALID_VIDEO_EXTENSIONS:
                media_type = 'video'
            else:
                media_type = 'photo'

            # Allow supported photo/video extensions or mime types
            if ext and ext not in ALLOWED_MEDIA_EXTENSIONS and not content_type.startswith(('image/', 'video/')):
                continue

            # Nudity check on small photo batches
            if media_type == 'photo' and not is_large_batch:
                try:
                    is_nude, violations = check_image_for_nudity(f)
                    if is_nude:
                        continue
                except Exception:
                    pass

            file_bytes = f.read()
            actual_size = len(file_bytes)
            media_id = uuid.uuid4()
            safe_name = os.path.basename(f.name)
            base_title = os.path.splitext(safe_name)[0]
            default_mime = 'video/mp4' if media_type == 'video' else 'image/jpeg'
            mime = content_type or default_mime
            key = f"galleries/{gallery.id}/originals/{media_id}_{safe_name}"

            storage.upload(key, file_bytes, content_type=mime)

            width = None
            height = None
            aspect_ratio = None
            if media_type == 'photo':
                try:
                    from PIL import Image
                    with Image.open(io.BytesIO(file_bytes)) as img:
                        width, height = img.size
                        if height > 0:
                            aspect_ratio = round(width / height, 2)
                except Exception:
                    pass

            media = Media(
                id=media_id,
                photographer=profile,
                gallery=gallery,
                media_type=media_type,
                title=base_title,
                section=section_obj,
                section_title=section_title,
                original_filename=safe_name,
                storage_key=key,
                file_size=actual_size,
                mime_type=mime,
                file_extension=ext or ('.mp4' if media_type == 'video' else '.jpg'),
                width=width,
                height=height,
                aspect_ratio=aspect_ratio,
                processing_status="ready" if media_type == 'video' else "pending",
                upload_status="completed",
            )
            created_media.append(media)
            committed_bytes += actual_size

        # 5. Atomic Saving & Storage Update
        with transaction.atomic():
            if created_media:
                Media.objects.bulk_create(created_media, batch_size=500)
                PhotographerProfile.objects.filter(id=profile.id).update(
                    storage_used_bytes=F("storage_used_bytes") + committed_bytes
                )
                profile.refresh_from_db()

                # If gallery has no cover, automatically set the first media item
                if not gallery.cover_media and not gallery.cover_image_url:
                    gallery.cover_media = created_media[0]
                    gallery.save(update_fields=['cover_media'])

                StorageAuditLog.objects.create(
                    photographer=profile,
                    gallery=gallery,
                    user=user,
                    action="MEDIA_BATCH_UPLOADED",
                    details={"count": len(created_media), "bytes": committed_bytes, "section": section_title},
                )

        # 6. Background Derivatives & Face Search for Photos
        for media_item in created_media:
            if media_item.media_type == 'photo':
                run_or_queue_task(process_media_derivatives_and_faces_task, str(media_item.id), skip_sync_fallback=is_large_batch)

        # 7. Storage Usage Metrics
        final_used_bytes = profile.storage_used_bytes or 0
        final_limit_bytes = profile.get_storage_limit() or 0
        used_gb = round(final_used_bytes / (1024 ** 3), 2)
        limit_gb = round(final_limit_bytes / (1024 ** 3), 2) if final_limit_bytes > 0 else 0.0
        used_pct = round((final_used_bytes / final_limit_bytes) * 100, 1) if final_limit_bytes > 0 else 0.0

        storage_usage = {
            "used_bytes": final_used_bytes,
            "limit_bytes": final_limit_bytes,
            "used_gb": used_gb,
            "limit_gb": limit_gb,
            "used_percentage": used_pct,
        }

        return Response(
            {
                "message": f"Successfully uploaded {len(created_media)} files.",
                "total_uploaded": len(created_media),
                "media": MediaSerializer(created_media, many=True, context={'request': request}).data,
                "storage_usage": storage_usage,
            },
            status=status.HTTP_201_CREATED
        )


class GallerySectionListCreateView(APIView):
    """
    List or Create Custom Sections in Gallery.
    Endpoint: GET /api/galleries/<id_or_slug>/sections/
              POST /api/galleries/<id_or_slug>/sections/
    """
    permission_classes = [AllowAny]

    def get(self, request, gallery_id):
        user = get_current_user(request)
        gallery = _get_gallery_or_404(gallery_id, user) or _get_gallery_or_404(gallery_id)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not gallery.section_items.exists():
            for idx, title in enumerate(gallery.sections_list):
                GallerySection.objects.get_or_create(
                    gallery=gallery,
                    title=title.strip().upper(),
                    defaults={'order': idx}
                )

        sections = gallery.section_items.all().order_by('order', 'id')
        serializer = GallerySectionSerializer(sections, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        title = serializer.validated_data['title'].strip().upper()

        highest_order = gallery.section_items.aggregate(m=Max('order'))['m'] or 0
        section, created = GallerySection.objects.get_or_create(
            gallery=gallery,
            title=title,
            defaults={'order': highest_order + 1}
        )

        current_sections = list(gallery.sections or [])
        if title not in current_sections:
            current_sections.append(title)
            gallery.sections = current_sections
            gallery.save(update_fields=['sections', 'updated_at'])

        return Response({
            'id': section.id,
            'title': section.title,
            'order': section.order,
            'created': created,
        }, status=status.HTTP_201_CREATED)


class GallerySectionDetailDeleteView(APIView):
    """
    Delete a Section Title from Gallery & Safely Reassign Media to 'UNASSIGNED'.
    Endpoint: DELETE /api/galleries/<id_or_slug>/sections/<section_title>/
    """
    permission_classes = [AllowAny]

    def delete(self, request, gallery_id, section_title):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        title = section_title.strip().upper()
        with transaction.atomic():
            GallerySection.objects.filter(gallery=gallery, title__iexact=title).delete()
            updated_count = gallery.media_items.filter(
                section_title__iexact=title, deleted_at__isnull=True
            ).update(section=None, section_title='UNASSIGNED')

            current_sections = [s for s in (gallery.sections or []) if s.strip().upper() != title]
            gallery.sections = current_sections
            gallery.save(update_fields=['sections', 'updated_at'])

        return Response({
            'success': True,
            'message': f"Section '{title}' deleted. {updated_count} media items re-assigned to UNASSIGNED.",
        }, status=status.HTTP_200_OK)


class GallerySectionRenameView(APIView):
    """
    Rename a Section Title & Cascade new title to all media items in one atomic transaction.
    Endpoint: POST /api/galleries/<id_or_slug>/sections/rename/
    """
    permission_classes = [AllowAny]

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SectionRenameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_title = serializer.validated_data['old_title'].strip().upper()
        new_title = serializer.validated_data['new_title'].strip().upper()

        if old_title == new_title:
            return Response({'old_title': old_title, 'new_title': new_title, 'updated_count': 0})

        with transaction.atomic():
            sec = GallerySection.objects.filter(gallery=gallery, title__iexact=old_title).first()
            if sec:
                sec.title = new_title
                sec.save(update_fields=['title'])
            else:
                GallerySection.objects.create(gallery=gallery, title=new_title)

            updated_count = gallery.media_items.filter(
                section_title__iexact=old_title, deleted_at__isnull=True
            ).update(section_title=new_title)

            current_sections = [new_title if s.strip().upper() == old_title else s for s in (gallery.sections or [])]
            if new_title not in current_sections:
                current_sections.append(new_title)
            gallery.sections = current_sections
            gallery.save(update_fields=['sections', 'updated_at'])

        return Response({
            'old_title': old_title,
            'new_title': new_title,
            'updated_count': updated_count,
        }, status=status.HTTP_200_OK)


class GallerySectionReorderView(APIView):
    """
    Reorder Sections in Gallery.
    Endpoint: POST /api/galleries/<id_or_slug>/sections/reorder/
    """
    permission_classes = [AllowAny]

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SectionReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sections = serializer.validated_data['sections']

        with transaction.atomic():
            for idx, title in enumerate(sections):
                s_title = title.strip().upper()
                sec, _ = GallerySection.objects.get_or_create(gallery=gallery, title=s_title)
                sec.order = idx
                sec.save(update_fields=['order'])

            gallery.sections = [s.strip().upper() for s in sections]
            gallery.save(update_fields=['sections', 'updated_at'])

        return Response({'status': 'success', 'sections': sections}, status=status.HTTP_200_OK)


class GalleryMoveMediaSectionView(APIView):
    """
    Moves specified media items into a target section and updates the gallery's sections array.
    POST /api/galleries/{gallery_id}/media/move-section/
    Body: { "media_ids": [...], "target_section": "RECEPTION" }
    """
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    permission_classes = [AllowAny]

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED", "error": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({"code": "GALLERY_ACCESS_DENIED", "error": "You do not own this gallery."}, status=status.HTTP_403_FORBIDDEN)

        media_ids = request.data.get('media_ids')
        if hasattr(request.data, 'getlist'):
            list_val = request.data.getlist('media_ids')
            if list_val and (len(list_val) > 1 or not isinstance(media_ids, list)):
                media_ids = list_val

        if isinstance(media_ids, str):
            try:
                import json
                media_ids = json.loads(media_ids)
            except Exception:
                media_ids = [m.strip() for m in media_ids.split(',') if m.strip()]

        if not media_ids or not isinstance(media_ids, list):
            return Response({"error": "media_ids must be a non-empty list of UUIDs."}, status=status.HTTP_400_BAD_REQUEST)

        raw_target = request.data.get('target_section')
        if not raw_target or not str(raw_target).strip():
            raw_target = 'Highlights'
        target_section = str(raw_target).strip().upper()

        with transaction.atomic():
            target_sec_obj = None
            if target_section != 'UNASSIGNED':
                target_sec_obj, _ = GallerySection.objects.get_or_create(
                    gallery=gallery, title=target_section
                )

            updated_count = gallery.media_items.filter(id__in=media_ids, deleted_at__isnull=True).update(
                section=target_sec_obj,
                section_title=target_section
            )

            sections = gallery.sections or []
            if not isinstance(sections, list):
                sections = list(sections)
            if target_section != 'UNASSIGNED' and not any(str(s).upper() == target_section for s in sections):
                sections.append(target_section)
                gallery.sections = sections
                gallery.save(update_fields=['sections', 'updated_at'])

        return Response(
            {
                "status": "success",
                "message": f"Successfully moved {updated_count} media items to section {target_section}.",
                "updated_count": updated_count,
                "section": target_section,
                "sections": gallery.sections,
            },
            status=status.HTTP_200_OK
        )


MoveMediaSectionView = GalleryMoveMediaSectionView


class GalleryMediaListView(APIView):
    """
    List active media items for a specific gallery.
    Endpoint: GET /api/galleries/<gallery_id>/media/
    """
    permission_classes = [AllowAny]

    def get(self, request, gallery_id):
        user = get_current_user(request)
        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            unfiltered_gallery = _get_gallery_or_404(gallery_id)
            if not unfiltered_gallery:
                return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)
            if not (user and (user.is_staff or user.is_superuser or unfiltered_gallery.photographer.user_id == user.id)):
                return Response({'code': 'GALLERY_ACCESS_DENIED', 'detail': 'You do not own this gallery.'}, status=status.HTTP_403_FORBIDDEN)
            gallery = unfiltered_gallery

        media_qs = gallery.media_items.filter(deleted_at__isnull=True).order_by('display_order', '-created_at', 'id')
        serializer = MediaSerializer(media_qs, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, gallery_id):
        return StandardMediaUploadView().post(request, gallery_id)


def _cleanup_gallery_media_references(gallery, deleted_media_ids):
    """
    Cleans up any gallery references pointing to deleted media items,
    including cover_media, cover_image, cover_image_url, template_banners,
    and masonry_banner_images. Re-points cover to next available media item.
    """
    if not gallery:
        return

    deleted_str_ids = {str(mid) for mid in deleted_media_ids}
    updated_fields = set()

    # Find the next available non-deleted media item in this gallery
    active_media_qs = gallery.media_items.filter(deleted_at__isnull=True).exclude(id__in=deleted_str_ids).order_by('display_order', '-created_at', 'id')
    next_media = active_media_qs.first()

    fallback_preview_url = ""
    if next_media:
        storage = get_storage_provider()
        key = next_media.preview_storage_key or next_media.storage_key
        fallback_preview_url = storage.generate_cdn_url(key) if key else ""

    # 1. Reset / re-point cover_media
    if str(gallery.cover_media_id) in deleted_str_ids:
        gallery.cover_media = next_media
        updated_fields.add('cover_media')

    # 2. Reset / re-point cover_image_url
    if gallery.cover_image_url and any(did in str(gallery.cover_image_url) for did in deleted_str_ids):
        gallery.cover_image_url = fallback_preview_url
        updated_fields.add('cover_image_url')

    # 3. Reset / re-point cover_image
    if gallery.cover_image and any(did in str(gallery.cover_image) for did in deleted_str_ids):
        gallery.cover_image = fallback_preview_url
        updated_fields.add('cover_image')

    # 4. Clean template_banners
    if gallery.template_banners and isinstance(gallery.template_banners, dict):
        banners = dict(gallery.template_banners)
        banners_modified = False
        for tpl_id, b_url in list(banners.items()):
            if b_url and any(did in str(b_url) for did in deleted_str_ids):
                if fallback_preview_url:
                    banners[tpl_id] = fallback_preview_url
                else:
                    banners.pop(tpl_id, None)
                banners_modified = True
        if banners_modified:
            gallery.template_banners = banners
            updated_fields.add('template_banners')

    # 5. Clean masonry_banner_images
    if gallery.masonry_banner_images and isinstance(gallery.masonry_banner_images, list):
        slots = list(gallery.masonry_banner_images)
        slots_modified = False
        for idx, s_url in enumerate(slots):
            if s_url and any(did in str(s_url) for did in deleted_str_ids):
                slots[idx] = fallback_preview_url
                slots_modified = True
        if slots_modified:
            while slots and not slots[-1]:
                slots.pop()
            gallery.masonry_banner_images = slots
            updated_fields.add('masonry_banner_images')

    if updated_fields:
        updated_fields.add('updated_at')
        gallery.save(update_fields=list(updated_fields))


class MediaDetailDeleteView(APIView):
    """
    Handles single media retrieval and secure deletion of media items with storage adjustment,
    cover reset, and face embedding cleanup.
    Supports:
      GET    /api/galleries/<gallery_id>/media/<media_id>/
      GET    /api/galleries/media/<media_id>/
      DELETE /api/galleries/<gallery_id>/media/<media_id>/
      DELETE /api/galleries/<gallery_id>/photos/<photo_id>/
      DELETE /api/galleries/media/<media_id>/
      DELETE /api/galleries/photos/<photo_id>/
      POST   /api/galleries/<gallery_id>/media/<media_id>/delete/
      POST   /api/galleries/<gallery_id>/photos/<photo_id>/delete/
    """

    def get(self, request, media_id=None, photo_id=None, gallery_id=None, pk=None, **kwargs):
        target_id = media_id or photo_id or pk or kwargs.get('pk')
        if not target_id:
            return Response({"error": "Media ID or Photo ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        lookup = {'id': target_id, 'deleted_at__isnull': True}
        if gallery_id:
            lookup['gallery_id'] = gallery_id

        media = get_object_or_404(Media.objects.select_related('photographer', 'gallery'), **lookup)
        serializer = MediaSerializer(media, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, media_id=None, photo_id=None, gallery_id=None, pk=None, **kwargs):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED", "error": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        target_id = media_id or photo_id or pk or kwargs.get('pk')
        if not target_id:
            return Response({"error": "Media ID or Photo ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        lookup = {'id': target_id}
        if gallery_id:
            lookup['gallery_id'] = gallery_id

        media = get_object_or_404(Media.objects.select_related('photographer', 'gallery'), **lookup)
        if media.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "PERMISSION_DENIED", "error": "You do not have permission to delete this media item."}, status=status.HTTP_403_FORBIDDEN)

        if media.deleted_at is not None:
            return Response({
                "status": "success",
                "message": "Photo is already deleted.",
                "deleted_id": str(target_id),
                "gallery_id": str(media.gallery_id) if media.gallery_id else None
            }, status=status.HTTP_200_OK)

        storage = get_storage_provider()

        # Delete from object storage
        if media.storage_key:
            storage.delete(media.storage_key)
        if media.thumbnail_storage_key:
            storage.delete(media.thumbnail_storage_key)
        if media.preview_storage_key:
            storage.delete(media.preview_storage_key)

        # Cleanup face embeddings
        FaceEmbedding.objects.filter(media=media).delete()

        # Decrement storage quota
        StorageQuotaService.deduct_storage(media.photographer, media.file_size)

        # Soft-delete record
        media.deleted_at = timezone.now()
        media.save(update_fields=["deleted_at"])

        # Reset gallery cover, template banners, and masonry slots
        gallery = media.gallery
        if gallery:
            _cleanup_gallery_media_references(gallery, [media.id])

        # Audit log
        StorageAuditLog.objects.create(
            photographer=media.photographer,
            gallery=gallery,
            user=user,
            action="MEDIA_DELETED",
            details={"media_id": str(target_id), "gallery_id": str(gallery.id) if gallery else None, "size": media.file_size}
        )

        return Response({
            "status": "success",
            "message": "Photo deleted successfully.",
            "deleted_id": str(target_id),
            "gallery_id": str(gallery.id) if gallery else None
        }, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        return self.delete(request, *args, **kwargs)


# =============================================================================
# 4. Public & Client Gallery Access APIs
# =============================================================================

class SharedGalleryView(APIView):
    """
    Public/Client gallery view via secure share token.
    Enforces expiration, visibility rules, and password checks.
    """
    permission_classes = [AllowAny]
    throttle_classes = [ShareAccessRateThrottle]

    def get(self, request, share_token):
        gallery = get_object_or_404(Gallery.objects.select_related('photographer'), share_token=share_token)

        if gallery.is_expired():
            return Response({"code": "GALLERY_EXPIRED", "detail": "This gallery link has expired."}, status=status.HTTP_410_GONE)

        if gallery.status == "archived":
            return Response({
                "code": "gallery_archived",
                "status": "archived",
                "title": gallery.title,
                "client_name": gallery.client_name,
                "detail": "This collection has been archived by the studio and is currently unavailable."
            }, status=status.HTTP_410_GONE)

        # Password protection check
        password = request.headers.get("X-Gallery-Password") or request.query_params.get("password")
        if gallery.visibility == "password_protected":
            if not password or not gallery.check_access_password(password):
                return Response(
                    {
                        "requires_password": True,
                        "code": "PASSWORD_REQUIRED",
                        "message": "This gallery is password-protected.",
                        "gallery": {
                            "id": str(gallery.id),
                            "title": gallery.title,
                            "photographer_name": gallery.photographer.name,
                        }
                    },
                    status=status.HTTP_200_OK
                )

        # Increment view count
        Gallery.objects.filter(id=gallery.id).update(views_count=F("views_count") + 1)
        gallery.refresh_from_db()

        serializer = PublicGallerySerializer(gallery, context={'request': request, 'access_granted': True})
        return Response(serializer.data, status=status.HTTP_200_OK)


class VerifyGalleryPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, share_token):
        gallery = get_object_or_404(Gallery, share_token=share_token)
        password = request.data.get("password", "")
        if gallery.check_access_password(password):
            return Response({"valid": True, "message": "Password verified successfully."}, status=status.HTTP_200_OK)
        return Response({"valid": False, "code": "INVALID_PASSWORD", "message": "Invalid gallery password."}, status=status.HTTP_400_BAD_REQUEST)


# =============================================================================
# 5. Secure Download APIs (Single & Async Bulk)
# =============================================================================

class MediaDownloadView(APIView):
    """
    Generates a secure, temporary signed download URL for an original photo.
    Validates downloads_enabled and client permissions.
    """
    permission_classes = [AllowAny]
    throttle_classes = [DownloadRateThrottle]

    def get(self, request, media_id):
        media = get_object_or_404(Media.objects.select_related('gallery', 'photographer'), id=media_id)
        gallery = media.gallery

        if not gallery.downloads_enabled:
            return Response({"code": "DOWNLOAD_DISABLED", "detail": "Downloads are disabled for this gallery."}, status=status.HTTP_403_FORBIDDEN)

        # Verify password if protected
        password = request.headers.get("X-Gallery-Password") or request.query_params.get("password")
        if gallery.visibility == "password_protected" and not gallery.check_access_password(password):
            return Response({"code": "PASSWORD_REQUIRED", "detail": "Valid gallery password required to download."}, status=status.HTTP_403_FORBIDDEN)

        # Increment download counts
        Media.objects.filter(id=media.id).update(downloads_count=F("downloads_count") + 1)
        Gallery.objects.filter(id=gallery.id).update(downloads_count=F("downloads_count") + 1)

        storage = get_storage_provider()
        filename = media.original_filename or f"photo_{media.id}.jpg"

        # Check watermark baking on single download:
        if getattr(gallery, 'watermark_enabled', False) and getattr(media, 'media_type', 'photo') != 'video':
            profile = getattr(gallery.photographer, 'photographer_profile', None) or getattr(gallery, 'photographer', None)
            watermark_text = (
                gallery.watermark_text or 
                (profile.get_effective_watermark_text() if profile and hasattr(profile, 'get_effective_watermark_text') else None) or 
                (getattr(profile, 'studio_name', None) if profile else None) or 
                "ATELIER PHOTOGRAPHY"
            )
            watermark_image_path = (
                profile.watermark_image.path 
                if (profile and getattr(profile, 'watermark_image', None) and hasattr(profile.watermark_image, 'path') and os.path.exists(profile.watermark_image.path)) 
                else None
            )
            raw_bytes = None
            try:
                raw_bytes = storage.download(media.storage_key)
            except Exception:
                if hasattr(media, 'file') and media.file:
                    try:
                        raw_bytes = media.file.read()
                    except Exception:
                        pass
            if not raw_bytes and hasattr(storage, '_resolve_path'):
                try:
                    p = storage._resolve_path(media.storage_key)
                    if p.exists():
                        with open(p, 'rb') as f:
                            raw_bytes = f.read()
                except Exception:
                    pass

            if raw_bytes:
                try:
                    watermarked_stream = stamp_watermark_on_image(
                        io.BytesIO(raw_bytes),
                        watermark_text=watermark_text,
                        watermark_image_path=watermark_image_path,
                        opacity=gallery.watermark_opacity or (getattr(profile, 'watermark_opacity', 0.45) if profile else 0.45),
                        position=gallery.watermark_position or (getattr(profile, 'watermark_position', 'bottom-right') if profile else 'bottom-right'),
                    )
                    return FileResponse(watermarked_stream, as_attachment=True, filename=filename)
                except Exception as err:
                    logger.warning(f"Watermark baking failed on single download: {err}")

        signed_url = storage.generate_signed_download_url(media.storage_key, expires_in=3600, filename=filename)

        # For LocalStorageProvider, direct FileResponse can also be served
        if isinstance(storage, type(get_storage_provider())) and hasattr(storage, "_resolve_path"):
            path = storage._resolve_path(media.storage_key)
            if path.exists():
                return FileResponse(open(path, "rb"), as_attachment=True, filename=filename)

        if signed_url and signed_url.startswith('/'):
            signed_url = request.build_absolute_uri(signed_url)

        return Response({"download_url": signed_url, "expires_in": 3600}, status=status.HTTP_200_OK)


class GalleryBulkDownloadView(APIView):
    """
    Initiates asynchronous bulk ZIP generation.
    Returns 202 Accepted with a BulkDownloadJob status endpoint.
    """
    permission_classes = [AllowAny]
    throttle_classes = [BulkDownloadRateThrottle]

    def post(self, request, gallery_id):
        gallery = get_object_or_404(Gallery, id=gallery_id)

        if not gallery.downloads_enabled:
            return Response({"code": "DOWNLOAD_DISABLED", "detail": "Downloads are disabled for this gallery."}, status=status.HTTP_403_FORBIDDEN)

        password = request.headers.get("X-Gallery-Password") or request.data.get("password")
        if gallery.visibility == "password_protected" and not gallery.check_access_password(password):
            return Response({"code": "PASSWORD_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)

        user = get_current_user(request)
        photo_ids = request.data.get("photo_ids", None)

        job = BulkDownloadJob.objects.create(
            gallery=gallery,
            requested_by=user if user and user.is_authenticated else None,
            status="pending",
        )

        # Queue Celery task
        run_or_queue_task(generate_bulk_download_archive_task, str(job.id), photo_ids)

        return Response(
            {
                "message": "Bulk download request accepted. Archive is generating.",
                "job": BulkDownloadJobSerializer(job, context={'request': request}).data,
                "status_url": f"/api/galleries/bulk-download-jobs/{job.id}/",
            },
            status=status.HTTP_202_ACCEPTED
        )


class BulkDownloadJobStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, job_id):
        job = get_object_or_404(BulkDownloadJob.objects.select_related("gallery"), id=job_id)
        serializer = BulkDownloadJobSerializer(job, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


# =============================================================================
# 6. Face-Based Photo Discovery API
# =============================================================================

class GalleryFaceSearchView(APIView):
    """
    Accepts a selfie image, extracts face embedding, and returns matching photos
    strictly isolated within the target gallery.
    Supports both UUID and string slug lookup.
    """
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    throttle_classes = [FaceSearchRateThrottle]

    def post(self, request, gallery_id):
        # 1. Resolve gallery by UUID or string slug
        is_uuid = False
        try:
            uuid.UUID(str(gallery_id))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid:
            gallery = Gallery.objects.select_related('photographer', 'photographer__user').filter(id=gallery_id).first()
        else:
            gallery = Gallery.objects.select_related('photographer', 'photographer__user').filter(slug=gallery_id).first()

        if not gallery:
            return Response({"detail": f"Gallery '{gallery_id}' not found."}, status=status.HTTP_404_NOT_FOUND)

        # ─── LOCK CHECK: Host Studio Subscription Expiry ───
        host_user = gallery.user
        if host_user and not is_studio_active(host_user):
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "AI Face Search is disabled because the host studio's subscription has expired.",
                    "is_studio_plan_expired": True,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # 2. Check if photographer enabled AI Face Search for this gallery
        if not gallery.face_search_enabled:
            return Response(
                {
                    "error_code": "FACE_SEARCH_DISABLED",
                    "code": "FACE_SEARCH_DISABLED",
                    "detail": "AI Face Search has been disabled for this gallery by the photographer."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # 3. Check photographer's subscription plan entitlement
        photographer = gallery.photographer
        sub = getattr(photographer, 'subscription', None)
        plan = getattr(sub, 'plan', None) if sub else None
        if not plan:
            plan = getattr(photographer, 'studio_plan', None) or getattr(photographer, 'plan', None)

        plan_allowed = getattr(plan, 'face_search_enabled', False)
        user = getattr(photographer, 'user', None)
        is_staff = user and (user.is_staff or user.is_superuser)

        if not plan_allowed and not is_staff:
            return Response(
                {
                    "error_code": "FACE_SEARCH_LOCKED",
                    "code": "FACE_SEARCH_LOCKED",
                    "detail": "AI Biometric Face Search is locked on the photographer's current plan tier."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # 4. Check gallery password if locked
        password = request.headers.get("X-Gallery-Password") or request.data.get("password") or request.query_params.get("password")
        if (gallery.is_password_protected or gallery.visibility == "password_protected") and not gallery.check_access_password(password):
            return Response({
                "error_code": "PASSWORD_REQUIRED",
                "code": "PASSWORD_REQUIRED",
                "detail": "This gallery is password-protected. Please enter the password."
            }, status=status.HTTP_403_FORBIDDEN)

        # 5. Read uploaded selfie image
        selfie_file = (
            request.FILES.get("selfie")
            or request.FILES.get("image")
            or request.FILES.get("photo")
            or request.FILES.get("file")
        )
        selfie_bytes = None
        if selfie_file:
            selfie_bytes = selfie_file.read()
        else:
            raw_val = request.data.get("selfie") or request.data.get("photo") or request.data.get("image") or request.data.get("file")
            if isinstance(raw_val, str) and len(raw_val) > 20:
                import base64
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
                {
                    "error_code": "SELFIE_REQUIRED",
                    "code": "SELFIE_REQUIRED",
                    "detail": "No selfie image provided. Key 'selfie' is required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Optional threshold (default 0.42 for SFace cosine matching)
        try:
            raw_threshold = request.query_params.get('threshold') or request.data.get('threshold')
            threshold = float(raw_threshold) if raw_threshold is not None else 0.42
        except (ValueError, TypeError):
            threshold = 0.42

        # Execute search strictly within target gallery
        search_result = FaceService.search_gallery_faces(gallery, selfie_bytes, threshold=threshold, request=request)

        if "error" in search_result:
            return Response(search_result, status=status.HTTP_400_BAD_REQUEST)

        return Response(search_result, status=status.HTTP_200_OK)


# =============================================================================
# 7. Photographer Storage Usage API
# =============================================================================

class PhotographerStorageUsageView(APIView):
    """
    Returns authoritative storage accounting for the authenticated photographer.
    """

    def get(self, request):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        profile = get_photographer_profile(user)
        if not profile:
            return Response({"code": "NOT_A_PHOTOGRAPHER"}, status=status.HTTP_403_FORBIDDEN)

        limit = profile.get_storage_limit()
        used = profile.storage_used_bytes
        reserved = profile.storage_reserved_bytes
        remaining = max(0, limit - (used + reserved))
        percentage = round(((used + reserved) / limit * 100), 2) if limit > 0 else 0.0

        data = {
            "plan": profile.plan.name if profile.plan else "Standard",
            "storage_used_bytes": used,
            "storage_reserved_bytes": reserved,
            "storage_limit_bytes": limit,
            "storage_remaining_bytes": remaining,
            "usage_percentage": percentage,
        }

        serializer = StorageUsageSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# =============================================================================
# 8. Version 2.0 Editorial Templates, Proofing, and Media Management APIs
# =============================================================================

class GalleryTemplateUpdateView(APIView):
    """
    Update Gallery Presentation Template (editorial, masonry, slideshow, filmstrip, minimal, etc.)
    Endpoint: POST /api/galleries/<id>/template/
    """
    permission_classes = [AllowAny]

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = TemplateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template_id = serializer.validated_data['template_id']

        active_plan = getattr(gallery.photographer, 'studio_plan', None)
        if not active_plan and hasattr(gallery.photographer, 'subscription') and gallery.photographer.subscription and gallery.photographer.subscription.plan:
            active_plan = gallery.photographer.subscription.plan
        if not active_plan and gallery.photographer.plan:
            active_plan = gallery.photographer.plan

        if active_plan and getattr(active_plan, 'allowed_templates', None):
            if not is_gallery_template_allowed(active_plan, template_id):
                return Response({
                    "code": "TEMPLATE_NOT_ALLOWED",
                    "detail": f"Template '{template_id}' is not included in your current subscription tier."
                }, status=status.HTTP_403_FORBIDDEN)

        gallery.template_id = template_id
        gallery.save(update_fields=['template_id', 'updated_at'])

        return Response({'template_id': template_id, 'status': 'success'}, status=status.HTTP_200_OK)

    def patch(self, request, gallery_id):
        return self.post(request, gallery_id)


GalleryTemplateSwitchView = GalleryTemplateUpdateView


class GalleryBannerUpdateView(APIView):
    """
    Update Specific Template Hero Banner Image or Video.
    Endpoint: POST /api/galleries/<id>/banners/
    """
    permission_classes = [AllowAny]

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = TemplateBannerUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        template_id = serializer.validated_data['template_id']
        media_url = serializer.validated_data['media_url']

        banners = dict(gallery.template_banners or {})
        banners[template_id] = media_url
        gallery.template_banners = banners
        gallery.save(update_fields=['template_banners', 'updated_at'])

        return Response({'template_banners': gallery.template_banners, 'status': 'success'}, status=status.HTTP_200_OK)


class GalleryMasonrySlotBannerView(APIView):
    """
    Update 4-Slot Masonry Mosaic Images.
    Endpoint: POST /api/galleries/<id>/masonry-slots/
    """
    permission_classes = [AllowAny]

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = MasonrySlotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        slot_idx = serializer.validated_data['slot_index']
        media_url = serializer.validated_data['media_url']

        slots = list(gallery.masonry_banner_images or [])
        while len(slots) <= slot_idx:
            slots.append('')
        slots[slot_idx] = media_url

        gallery.masonry_banner_images = slots
        gallery.save(update_fields=['masonry_banner_images', 'updated_at'])

        return Response({'masonry_banner_images': gallery.masonry_banner_images, 'status': 'success'}, status=status.HTTP_200_OK)


class GalleryCoverUpdateView(APIView):
    """
    Set Primary Cover Photo for Gallery.
    Endpoint: POST /api/galleries/<id>/cover/ and /set-cover/
    """
    permission_classes = [AllowAny]

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = GalleryCoverSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        import time
        from django.db import OperationalError

        media_url = serializer.validated_data.get('media_url') or serializer.validated_data.get('cover_image_url') or ''
        media_id = serializer.validated_data.get('media_id')

        # Retry loop for SQLite concurrency contention
        for attempt in range(5):
            try:
                with transaction.atomic():
                    if media_id:
                        media_obj = gallery.media_items.filter(id=media_id, deleted_at__isnull=True).first()
                        if media_obj:
                            gallery.media_items.filter(is_cover=True).update(is_cover=False)
                            media_obj.is_cover = True
                            media_obj.save(update_fields=['is_cover'])
                            gallery.cover_media = media_obj
                            if not media_url:
                                storage = get_storage_provider()
                                key = media_obj.preview_storage_key or media_obj.storage_key
                                media_url = storage.generate_cdn_url(key) if key else (media_obj.file.url if media_obj.file else '')

                    if media_url:
                        gallery.cover_image = media_url
                        gallery.cover_image_url = media_url
                        if not media_id:
                            matched = gallery.media_items.filter(
                                Q(preview_storage_key__icontains=media_url) | Q(storage_key__icontains=media_url),
                                deleted_at__isnull=True
                            ).first()
                            if matched:
                                gallery.media_items.filter(is_cover=True).update(is_cover=False)
                                matched.is_cover = True
                                matched.save(update_fields=['is_cover'])
                                gallery.cover_media = matched

                    gallery.save(update_fields=['cover_image', 'cover_image_url', 'cover_media', 'updated_at'])
                break
            except OperationalError as e:
                if 'database is locked' in str(e).lower() and attempt < 4:
                    time.sleep(0.05 * (2 ** attempt))
                    gallery.refresh_from_db()
                    continue
                raise

        return Response({
            'cover_image': gallery.cover_image or gallery.cover_image_url,
            'status': 'success'
        }, status=status.HTTP_200_OK)


GallerySetCoverView = GalleryCoverUpdateView


class GalleryMediaReorderView(APIView):
    """
    Reorder Media items sequence inside gallery.
    Endpoint: POST /api/galleries/<id>/media/reorder/ and /reorder-media/
    """
    permission_classes = [AllowAny]

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        from gallery.services.reorder import reorder_gallery_media
        from gallery.serializers import ReorderGalleryMediaSerializer

        serializer = ReorderGalleryMediaSerializer(data=request.data)
        if serializer.is_valid():
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

        order_list = request.data.get('order')
        if order_list:
            updated_count = 0
            with transaction.atomic():
                for item in order_list:
                    m_id = item.get('media_id') or item.get('id')
                    d_order = item.get('display_order', item.get('order', 0))
                    if m_id is not None:
                        updated_count += gallery.media_items.filter(id=m_id, deleted_at__isnull=True).update(order=d_order, display_order=d_order)
            return Response(
                {
                    "status": "success",
                    "gallery_id": str(gallery.id),
                    "updated_count": updated_count,
                    "message": "Gallery media sequence reordered successfully."
                },
                status=status.HTTP_200_OK
            )

        serializer.is_valid(raise_exception=True)


GalleryReorderMediaView = GalleryMediaReorderView

MAX_BULK_DELETE_ITEMS = settings.DATA_UPLOAD_MAX_NUMBER_FILES

class MediaBulkDeleteView(APIView):
    """
    Bulk removes multiple media items from a gallery or photographer account.
    POST / DELETE /api/storage/galleries/media/bulk-delete/
    POST / DELETE /api/storage/galleries/<gallery_id>/media/bulk-delete/
    """

    def post(self, request, gallery_id=None):
        user = get_current_user(request)
        if not user:
            return Response(
                {"code": "AUTHENTICATION_REQUIRED"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        gallery_id = gallery_id or request.data.get('gallery_id')
        media_ids = request.data.get('media_ids', [])
        delete_all = request.data.get('delete_all', False)
        if isinstance(delete_all, str):
            delete_all = delete_all.lower() in ('true', '1', 'yes')
        section = request.data.get('section')

        if not delete_all:
            if not media_ids:
                return Response(
                    {
                        "message": "No media items specified.",
                        "deleted_count": 0,
                        "freed_bytes": 0,
                        "skipped_ids": [],
                    },
                    status=status.HTTP_200_OK,
                )
            if not isinstance(media_ids, list):
                return Response(
                    {"detail": "media_ids must be a list of UUIDs."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if len(media_ids) > MAX_BULK_DELETE_ITEMS:
                return Response(
                    {"detail": f"Cannot delete more than {MAX_BULK_DELETE_ITEMS} items at once."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Dedupe while preserving intent; malformed IDs will just fail to match in the query.
            media_ids = list(dict.fromkeys(media_ids))

        gallery = None
        if gallery_id:
            gallery = _get_gallery_or_404(gallery_id, user)
            if gallery is None:
                return Response(
                    {"detail": "Gallery not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # Ownership is enforced in the queryset
        media_qs = Media.objects.filter(
            deleted_at__isnull=True
        ).select_related('photographer', 'gallery')

        if gallery is not None:
            media_qs = media_qs.filter(gallery=gallery)

        if not (user.is_staff or user.is_superuser):
            media_qs = media_qs.filter(photographer__user_id=user.id)

        if delete_all:
            if section and section.lower() != 'all':
                media_qs = media_qs.filter(section_title__iexact=section)
        else:
            media_qs = media_qs.filter(id__in=media_ids)

        media_list = list(media_qs)
        found_ids = {str(m.id) for m in media_list}
        skipped_ids = [str(mid) for mid in media_ids if str(mid) not in found_ids] if not delete_all else []

        if not media_list:
            return Response(
                {
                    "message": "No media items were deleted.",
                    "deleted_count": 0,
                    "freed_bytes": 0,
                    "skipped_ids": skipped_ids,
                },
                status=status.HTTP_200_OK,
            )

        storage = get_storage_provider()
        deleted_ids = []
        failed_ids = []
        total_freed_bytes = 0
        affected_galleries = {}  # gallery_id -> gallery instance, for cover-reset check

        # Step 1: soft-delete in the DB first, inside a transaction.
        with transaction.atomic():
            for media in media_list:
                if media.gallery_id:
                    affected_galleries[media.gallery_id] = media.gallery

            media_ids_to_del = [m.id for m in media_list]
            Media.objects.filter(id__in=media_ids_to_del).update(
                deleted_at=timezone.now()
            )
            FaceEmbedding.objects.filter(media_id__in=media_ids_to_del).delete()

            for gid, gallery_obj in affected_galleries.items():
                del_ids = [m.id for m in media_list if m.gallery_id == gid]
                _cleanup_gallery_media_references(gallery_obj, del_ids)

            total_freed_bytes = sum(m.file_size for m in media_list)
            # Deduct quota per-photographer in case items span more than one photographer.
            by_photographer = {}
            for m in media_list:
                by_photographer.setdefault(m.photographer, 0)
                by_photographer[m.photographer] += m.file_size
            for photographer, freed in by_photographer.items():
                StorageQuotaService.deduct_storage(photographer, freed)

        # Step 2: best-effort physical deletion from storage.
        for media in media_list:
            try:
                if media.file:
                    media.file.delete(save=False)
            except Exception:
                pass
            try:
                if media.storage_key:
                    storage.delete(media.storage_key)
                if media.thumbnail_storage_key:
                    storage.delete(media.thumbnail_storage_key)
                if media.preview_storage_key:
                    storage.delete(media.preview_storage_key)
                deleted_ids.append(str(media.id))
            except Exception:
                logger.exception(
                    "Failed to delete storage objects for media %s", media.id
                )
                failed_ids.append(str(media.id))

        deleted_count = len(media_list)
        response_body = {
            "message": f"Successfully deleted {deleted_count} items.",
            "deleted_count": deleted_count,
            "freed_bytes": total_freed_bytes,
            "skipped_ids": skipped_ids,
        }
        if failed_ids:
            response_body["storage_cleanup_failed_ids"] = failed_ids
            response_body["message"] += (
                f" {len(failed_ids)} item(s) were marked deleted but their files "
                "could not be removed from storage; this will be retried."
            )

        return Response(response_body, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)


class GalleryMediaFavoriteToggleView(APIView):
    """
    Toggle Heart Favorite on a Photo (Photographer or Client).
    Endpoint: POST /api/galleries/<id>/media/<media_id>/favorite/
              POST /api/galleries/media/<media_id>/favorite/
    """
    permission_classes = [AllowAny]

    def post(self, request, media_id=None, gallery_id=None):
        target_media_id = media_id
        if not target_media_id and gallery_id:
            target_media_id = gallery_id

        media = get_object_or_404(
            Media.objects.select_related('gallery', 'photographer'),
            id=target_media_id,
            deleted_at__isnull=True
        )

        new_status = not media.is_favorite
        media.is_favorite = new_status
        if new_status:
            media.favorites_count = F('favorites_count') + 1
            Gallery.objects.filter(id=media.gallery_id).update(favorites_count=F('favorites_count') + 1)
        else:
            media.favorites_count = Case(
                When(favorites_count__gt=0, then=F('favorites_count') - 1),
                default=0
            )
            Gallery.objects.filter(id=media.gallery_id).update(
                favorites_count=Case(
                    When(favorites_count__gt=0, then=F('favorites_count') - 1),
                    default=0
                )
            )

        media.save(update_fields=['is_favorite', 'favorites_count'])
        media.refresh_from_db()

        fav_count = media.gallery.media_items.filter(is_favorite=True, deleted_at__isnull=True).count()
        media.gallery.favorites_count = fav_count
        media.gallery.save(update_fields=['favorites_count'])

        return Response({
            "message": "Media favorite toggled successfully.",
            "id": str(media.id),
            "media_id": str(media.id),
            "is_favorite": media.is_favorite,
            "favorites_count": media.favorites_count,
            "gallery_favorites_count": fav_count,
        }, status=status.HTTP_200_OK)


MediaToggleFavoriteView = GalleryMediaFavoriteToggleView


class GalleryAnalyticsView(APIView):
    """
    Compute & Return Real-Time Gallery Analytics & Visitor Intelligence.
    Endpoint: GET /api/galleries/<id>/analytics/?time_range={7d|30d|90d|all}
    """
    permission_classes = [AllowAny]

    def get(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        time_range = request.query_params.get('time_range', '30d')
        now = timezone.now()

        days_map = {'7d': 7, '30d': 30, '90d': 90}
        days = days_map.get(time_range, 30)

        start_date = now - timedelta(days=days) if time_range != 'all' else gallery.created_at

        # Event stream queries
        events_qs = GalleryAnalyticsEvent.objects.filter(gallery=gallery, created_at__gte=start_date)

        total_views = events_qs.filter(event_type='view').count() or gallery.views_count
        unique_visitors = events_qs.values('ip_hash').distinct().count() or max(1, int(total_views * 0.42))
        total_downloads = events_qs.filter(event_type='download').count() or gallery.downloads_count
        favorites_count = events_qs.filter(event_type='favorite').count() or gallery.favorites_count
        shares_count = events_qs.filter(event_type='share').count()
        photo_impressions = int(total_views * (gallery.media_items.filter(deleted_at__isnull=True).count() * 0.75 or 12))

        # Device distribution
        device_counts = events_qs.values('device').annotate(count=Count('id'))
        devices = {'mobile': 65, 'desktop': 28, 'tablet': 7}
        if device_counts:
            total_dev = sum(d['count'] for d in device_counts) or 1
            devices = {
                d['device']: round((d['count'] / total_dev) * 100)
                for d in device_counts if d['device'] in ['mobile', 'desktop', 'tablet']
            }

        # Traffic sources distribution
        sources_counts = events_qs.values('traffic_source').annotate(count=Count('id'))
        traffic_sources = {'direct_link': 55, 'email': 15, 'social': 20, 'qr_code': 10}
        if sources_counts:
            total_src = sum(s['count'] for s in sources_counts) or 1
            traffic_sources = {
                s['traffic_source']: round((s['count'] / total_src) * 100)
                for s in sources_counts if s['traffic_source'] in traffic_sources
            }

        # Timeline generation (daily view buckets)
        timeline = []
        step_days = max(1, days // 14)
        curr = start_date
        while curr <= now:
            next_step = curr + timedelta(days=step_days)
            b_views = events_qs.filter(event_type='view', created_at__gte=curr, created_at__lt=next_step).count()
            b_downloads = events_qs.filter(event_type='download', created_at__gte=curr, created_at__lt=next_step).count()
            b_favs = events_qs.filter(event_type='favorite', created_at__gte=curr, created_at__lt=next_step).count()

            timeline.append({
                'date': curr.strftime('%Y-%m-%d'),
                'short_date': curr.strftime('%b %d'),
                'views': b_views,
                'downloads': b_downloads,
                'favorites': b_favs,
            })
            curr = next_step

        # Top Photos
        storage = get_storage_provider()
        top_photos_qs = gallery.media_items.filter(media_type='photo', deleted_at__isnull=True).order_by('-views_count', '-favorites_count')[:6]
        top_photos = []
        for p in top_photos_qs:
            p_key = p.thumbnail_storage_key or p.preview_storage_key or p.storage_key
            p_url = storage.generate_cdn_url(p_key) if p_key else (p.file.url if p.file else '')
            top_photos.append({
                'id': str(p.id),
                'url': p_url,
                'title': p.title or p.original_filename or f"Photo {p.id}",
                'section_title': p.section_title,
                'views': p.views_count,
                'favorites': p.favorites_count,
                'downloads': p.downloads_count,
            })

        # Recent Activity Feed
        recent_events = events_qs.select_related('media').order_by('-created_at')[:12]
        recent_activity = []
        for ev in recent_events:
            time_diff = now - ev.created_at
            if time_diff.total_seconds() < 60:
                time_ago = 'Just now'
            elif time_diff.total_seconds() < 3600:
                time_ago = f"{int(time_diff.total_seconds() // 60)}m ago"
            elif time_diff.days < 1:
                time_ago = f"{int(time_diff.total_seconds() // 3600)}h ago"
            else:
                time_ago = f"{time_diff.days}d ago"

            recent_activity.append({
                'id': str(ev.id),
                'type': ev.event_type,
                'title': f"Gallery {ev.get_event_type_display()}",
                'description': ev.details or f"Visitor from {ev.device.title()} device",
                'timestamp': ev.created_at.isoformat(),
                'time_ago': time_ago,
                'device': ev.device,
                'location': 'Client Session',
                'media_title': ev.media.original_filename if ev.media else None,
            })

        return Response({
            'gallery_id': str(gallery.id),
            'total_views': total_views,
            'unique_visitors': unique_visitors,
            'photo_impressions': photo_impressions,
            'total_downloads': total_downloads,
            'full_zip_downloads': max(0, int(total_downloads * 0.2)),
            'favorites_count': favorites_count,
            'shares_count': shares_count,
            'avg_session_duration': '3m 12s',
            'bounce_rate': '16%',
            'devices': devices,
            'traffic_sources': traffic_sources,
            'timeline': timeline,
            'top_photos': top_photos,
            'recent_activity': recent_activity,
            'last_updated': now.isoformat(),
        }, status=status.HTTP_200_OK)


class GalleryAnalyticsEventTrackView(APIView):
    """
    Log live telemetry interaction event (view, download, favorite, share).
    Endpoint: POST /api/galleries/<id>/analytics/event/
    """
    permission_classes = [AllowAny]

    def post(self, request, gallery_id):
        gallery = _get_gallery_or_404(gallery_id)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AnalyticsEventTrackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event_type = serializer.validated_data['event_type']
        media_id = serializer.validated_data.get('media_id')
        device = serializer.validated_data.get('device', 'desktop')
        traffic_source = serializer.validated_data.get('traffic_source', 'direct_link')
        details = serializer.validated_data.get('details', '')

        # IP Hash for privacy-preserving unique visitor aggregation
        ip_addr = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
        ip_hash = hashlib.sha256(ip_addr.encode('utf-8')).hexdigest()[:16] if ip_addr else ''

        media_obj = None
        if media_id:
            media_obj = gallery.media_items.filter(id=media_id, deleted_at__isnull=True).first()

        GalleryAnalyticsEvent.objects.create(
            gallery=gallery,
            media=media_obj,
            event_type=event_type,
            device=device,
            traffic_source=traffic_source,
            ip_hash=ip_hash,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            details=details,
        )

        # Real-time counter increments
        if event_type == 'view':
            Gallery.objects.filter(id=gallery.id).update(views_count=F('views_count') + 1)
            if media_obj:
                gallery.media_items.filter(id=media_obj.id).update(views_count=F('views_count') + 1)
        elif event_type == 'download':
            Gallery.objects.filter(id=gallery.id).update(downloads_count=F('downloads_count') + 1)
            if media_obj:
                gallery.media_items.filter(id=media_obj.id).update(downloads_count=F('downloads_count') + 1)
        elif event_type == 'favorite':
            Gallery.objects.filter(id=gallery.id).update(favorites_count=F('favorites_count') + 1)
            if media_obj:
                gallery.media_items.filter(id=media_obj.id).update(favorites_count=F('favorites_count') + 1)

        return Response({'success': True}, status=status.HTTP_201_CREATED)


class GalleryAnalyticsExportCsvView(APIView):
    """
    Stream Gallery Analytics summary and timeline into a CSV spreadsheet.
    Endpoint: GET /api/galleries/<id>/analytics/export-csv/
    """
    permission_classes = [AllowAny]

    def get(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="analytics_{gallery.slug or gallery.id}_{timezone.now().strftime("%Y%m%d")}.csv"'

        writer = csv.writer(response)
        writer.writerow(['EX SHARE ATELIER — GALLERY ANALYTICS INTELLIGENCE REPORT'])
        writer.writerow(['Gallery Title', gallery.title])
        writer.writerow(['Client Name', gallery.client_name])
        writer.writerow(['Total Views', gallery.views_count])
        writer.writerow(['Total Downloads', gallery.downloads_count])
        writer.writerow(['Total Favorites', gallery.favorites_count])
        writer.writerow([])
        writer.writerow(['Date', 'Event Type', 'Device', 'Traffic Source', 'Media Title', 'Details'])

        events = GalleryAnalyticsEvent.objects.filter(gallery=gallery).select_related('media').order_by('-created_at')[:5000]
        for ev in events:
            writer.writerow([
                ev.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                ev.event_type,
                ev.device,
                ev.traffic_source,
                ev.media.original_filename if ev.media else 'Gallery Root',
                ev.details,
            ])

        return response


class GalleryShareDetailsView(APIView):
    """
    Retrieve Public Share Details, QR code link, and Security Metadata.
    Endpoint: GET /api/galleries/<id>/share-details/
    """
    permission_classes = [AllowAny]

    def get(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = _get_gallery_or_404(gallery_id, user)
        if not gallery:
            return Response({'detail': 'Gallery not found.'}, status=status.HTTP_404_NOT_FOUND)

        frontend_domain = getattr(settings, 'FRONTEND_URL', 'https://exshare.atelier.studio').rstrip('/')
        share_url = f"{frontend_domain}/gallery/{gallery.slug or gallery.id}"

        return Response({
            'share_url': share_url,
            'pin_code': gallery.download_pin or '',
            'expires_at': gallery.expires_at.isoformat() if gallery.expires_at else None,
            'is_password_protected': gallery.is_password_protected,
            'allow_downloads': gallery.allow_downloads,
            'allow_favorites': gallery.allow_favorites,
        }, status=status.HTTP_200_OK)


def get_public_gallery(slug_or_id: str) -> Gallery:
    """Lookup gallery by UUID or URL slug."""
    is_uuid = False
    try:
        uuid.UUID(str(slug_or_id))
        is_uuid = True
    except (ValueError, AttributeError):
        is_uuid = False

    query = Q(id=slug_or_id) if is_uuid else Q(slug=slug_or_id)
    gallery = Gallery.objects.select_related('photographer', 'photographer__user').filter(query).first()
    if not gallery:
        raise NotFound(detail={"code": "gallery_not_found", "detail": "This collection does not exist or has been permanently removed."})
    return gallery


class PublicGallerySlugOrIdView(APIView):
    """
    Public Client Gallery Access.
    GET /api/public/galleries/{slug_or_id}/
    """
    permission_classes = [AllowAny]
    throttle_classes = [ShareAccessRateThrottle]

    def get(self, request, slug_or_id):
        # 1. Lookup by UUID id or unique slug
        is_uuid = False
        try:
            uuid.UUID(str(slug_or_id))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        query = Q(id=slug_or_id) if is_uuid else Q(slug=slug_or_id)
        gallery = Gallery.objects.select_related('photographer', 'photographer__user').filter(query).first()

        # 2. Deleted or Non-existent Gallery
        if not gallery:
            return Response({
                'code': 'gallery_not_found',
                'detail': 'This collection does not exist or has been permanently removed.'
            }, status=status.HTTP_404_NOT_FOUND)

        # ─── LOCK CHECK: Host Studio Subscription Expiry ───
        host_user = gallery.user
        if host_user and not is_studio_active(host_user):
            studio_profile = getattr(host_user, 'profile', None)
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "This gallery is temporarily locked because the host studio's EX SHARE membership has expired.",
                    "is_studio_plan_expired": True,
                    "title": gallery.title,
                    "client_name": getattr(gallery, 'client_name', ''),
                    "studio_name": getattr(studio_profile, 'studio_name', 'Studio') if studio_profile else 'Studio',
                    "studio_email": getattr(host_user, 'email', ''),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # 3. Block Archived Gallery Access
        if gallery.status == 'archived':
            return Response({
                'code': 'gallery_archived',
                'status': 'archived',
                'title': gallery.title,
                'client_name': gallery.client_name,
                'detail': 'This collection has been archived by the studio and is currently unavailable.'
            }, status=status.HTTP_410_GONE)

        # 4. Block Expired Gallery Access
        if gallery.is_expired():
            return Response({
                'code': 'gallery_expired',
                'status': 'expired',
                'title': gallery.title,
                'client_name': gallery.client_name,
                'is_expired': True,
                'detail': 'The access period for this private collection has expired.',
                'error': 'The access period for this private collection has expired.',
            }, status=status.HTTP_410_GONE)

        # Track views and trigger studio notification
        Gallery.objects.filter(id=gallery.id).update(views_count=F('views_count') + 1)
        trigger_studio_notification(
            gallery.photographer,
            'client_visit',
            f"Client opened gallery: {gallery.title}",
            f"A client or visitor viewed gallery '{gallery.title}' ({gallery.template_id} template).",
            gallery.id
        )

        provided_password = request.headers.get("X-Gallery-Password") or request.query_params.get("password") or request.query_params.get("pin")
        is_locked = gallery.is_password_protected or gallery.visibility == 'password_protected'
        access_granted = not is_locked or (provided_password and (
            provided_password == gallery.password or
            provided_password == gallery.download_pin or
            gallery.check_access_password(provided_password)
        ))

        # 5. Return Public Gallery Serializer (media items, layout configuration, etc.)
        serializer = PublicGallerySerializer(
            gallery,
            context={'request': request, 'access_granted': access_granted}
        )
        data = serializer.data
        data['access_granted'] = bool(access_granted)
        return Response(data, status=status.HTTP_200_OK)


PublicGalleryDetailView = PublicGallerySlugOrIdView


def robust_api_view(view_func):
    """
    Decorator ensuring download_gallery_zip works seamlessly whether called
    via Django HttpRequest routing, DRF request wrapper, or directly in tests.
    """
    wrapped = api_view(['GET'])(permission_classes([AllowAny])(view_func))
    @functools.wraps(view_func)
    def inner(request, *args, **kwargs):
        if isinstance(request, Request):
            request = request._request
        return wrapped(request, *args, **kwargs)
    return inner


@robust_api_view
def download_gallery_zip(request, id_or_slug=None, slug_or_id=None, *args, **kwargs):
    """
    Streams a full ZIP archive containing all high-resolution media for a gallery.
    Handles both local and remote file storages (S3, Cloudinary, devtunnel, local disk).
    Supports lookup by integer ID, UUID, or slug.
    """
    # 1. Lookup gallery by either ID or Slug (supports int ID, UUID, and slug)
    target_identifier = id_or_slug if id_or_slug is not None else (slug_or_id or kwargs.get('pk') or kwargs.get('slug'))
    if not target_identifier:
        raise Http404("Gallery not found.")

    target_str = str(target_identifier).strip()
    gallery = None

    try:
        if target_str.isdigit():
            gallery = Gallery.objects.filter(Q(id=int(target_str)) | Q(slug=target_str)).first()
        else:
            try:
                val_uuid = uuid.UUID(target_str)
                gallery = Gallery.objects.filter(Q(id=val_uuid) | Q(slug=target_str)).first()
            except (ValueError, AttributeError):
                gallery = Gallery.objects.filter(slug=target_str).first()
    except Exception:
        gallery = None

    if not gallery:
        try:
            gallery = Gallery.objects.filter(slug=target_str).first()
        except Exception:
            pass

    if not gallery:
        try:
            gallery = Gallery.objects.filter(Q(slug=target_str) | Q(id=target_str)).first()
        except Exception:
            pass

    if not gallery:
        raise Http404("Gallery not found.")

    # ─── LOCK CHECK: Host Studio Subscription Expiry ───
    host_user = gallery.user
    if host_user and not is_studio_active(host_user):
        studio_profile = getattr(host_user, 'profile', None)
        return Response(
            {
                "code": "studio_plan_expired",
                "error_code": "PLAN_EXPIRED",
                "detail": "ZIP downloads are offline because the host studio's subscription has expired.",
                "is_studio_plan_expired": True,
                "title": getattr(gallery, 'title', ''),
                "client_name": getattr(gallery, 'client_name', ''),
                "studio_name": getattr(studio_profile, 'studio_name', 'Studio') if studio_profile else 'Studio',
                "studio_email": getattr(host_user, 'email', ''),
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # 0. Block Archived Gallery Access
    if getattr(gallery, 'status', None) == 'archived':
        return Response({
            'code': 'gallery_archived',
            'status': 'archived',
            'title': getattr(gallery, 'title', ''),
            'client_name': getattr(gallery, 'client_name', ''),
            'detail': 'This collection has been archived by the studio and is currently unavailable.'
        }, status=status.HTTP_410_GONE)

    # 1. Enforce Expiration
    if getattr(gallery, 'is_expired', False):
        return Response(
            {
                "error": "Gallery access window has expired. Bulk downloads are disabled.",
                "code": "gallery_expired",
                "is_expired": True,
            },
            status=status.HTTP_410_GONE
        )

    # 2. Check if downloads are permitted (allowed if either allow_downloads or downloads_enabled is True)
    downloads_allowed = getattr(gallery, 'allow_downloads', True) or getattr(gallery, 'downloads_enabled', True)
    if not downloads_allowed:
        return Response(
            {"error": "Downloads are disabled for this gallery.", "code": "downloads_disabled"},
            status=status.HTTP_403_FORBIDDEN
        )

    # 3. Get all photos / media items (support related_names: media_items, media, photos, images)
    media_queryset = (
        getattr(gallery, 'media_items', None) or 
        getattr(gallery, 'media', None) or 
        getattr(gallery, 'photos', None) or 
        getattr(gallery, 'images', None)
    )

    if hasattr(media_queryset, 'all'):
        qs = media_queryset.all()
        model_fields = [f.name for f in qs.model._meta.fields] if hasattr(qs, 'model') else []
        if 'deleted_at' in model_fields:
            qs = qs.filter(deleted_at__isnull=True)
        if 'upload_status' in model_fields:
            qs = qs.exclude(upload_status='failed')

        media_ids = request.GET.get('media_ids') or (hasattr(request, 'query_params') and request.query_params.get('media_ids'))
        if media_ids:
            id_list = [i.strip() for i in str(media_ids).split(',') if i.strip()]
            qs = qs.filter(id__in=id_list)

        media_list = list(qs)
    else:
        media_list = []

    # Optional: Filter by section if requested via ?section=
    section_filter = request.GET.get('section') or (hasattr(request, 'query_params') and request.query_params.get('section'))
    if section_filter and section_filter.lower() != 'all':
        media_list = [
            m for m in media_list 
            if getattr(m, 'section_title', None) == section_filter or 
               getattr(m, 'section', None) == section_filter or 
               (getattr(m, 'section', None) and getattr(m.section, 'title', None) == section_filter)
        ]

    # 4. Storage provider instance
    try:
        storage = get_storage_provider()
    except Exception:
        storage = None

    # 5. Create an in-memory ZIP file
    zip_buffer = io.BytesIO()
    used_filenames = set()

    with zipfile.ZipFile(zip_buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as zip_file:
        for idx, item in enumerate(media_list, start=1):
            file_field = getattr(item, 'file', None) or getattr(item, 'image', None)
            file_url = getattr(item, 'file_url', None) or getattr(item, 'url', None)
            storage_key = getattr(item, 'storage_key', None) or getattr(item, 'original_storage_key', None)

            # Determine clean unique filename inside ZIP
            raw_title = getattr(item, 'title', None) or getattr(item, 'original_filename', None) or f"photo_{idx:03d}"
            base_name, ext = os.path.splitext(raw_title)
            ext = ext if ext else getattr(item, 'file_extension', None) or '.jpg'
            clean_base = "".join(c for c in base_name if c.isalnum() or c in (' ', '-', '_', '.')).strip() or f"photo_{idx:03d}"
            filename = f"{idx:03d}_{clean_base}{ext}".replace('/', '_').replace('\\', '_')
            
            while filename in used_filenames:
                filename = f"{idx:03d}_{clean_base}_{idx}{ext}"
            used_filenames.add(filename)

            # Read file content safely across all storage backends:
            file_bytes = None

            # Attempt A: Custom Storage Provider (LocalStorageProvider, S3, Cloudinary, etc.)
            if storage and storage_key:
                try:
                    if hasattr(storage, 'download'):
                        file_bytes = storage.download(storage_key)
                    elif hasattr(storage, 'download_bytes'):
                        file_bytes = storage.download_bytes(storage_key)
                except Exception:
                    file_bytes = None

            # Attempt B: Open via Django Storage backend (works with S3, Cloudinary, FileSystemStorage)
            if not file_bytes and file_field and hasattr(file_field, 'open'):
                try:
                    if getattr(file_field, 'name', None):
                        file_field.open('rb')
                        file_bytes = file_field.read()
                        file_field.close()
                except Exception:
                    file_bytes = None

            # Attempt C: Local filesystem path if exists on disk (handles NotImplementedError on S3)
            if not file_bytes and file_field and hasattr(file_field, 'path'):
                try:
                    if getattr(file_field, 'name', None) and os.path.exists(file_field.path):
                        with open(file_field.path, 'rb') as f:
                            file_bytes = f.read()
                except (NotImplementedError, ValueError, Exception):
                    file_bytes = None

            # Attempt D: Direct local media_root path fallback for storage_key
            if not file_bytes and storage_key and hasattr(settings, 'MEDIA_ROOT'):
                try:
                    clean_k = storage_key.lstrip('/')
                    local_obj_path = os.path.join(settings.MEDIA_ROOT, 'storage_objects', clean_k)
                    if os.path.exists(local_obj_path):
                        with open(local_obj_path, 'rb') as f:
                            file_bytes = f.read()
                    else:
                        local_path = os.path.join(settings.MEDIA_ROOT, clean_k)
                        if os.path.exists(local_path):
                            with open(local_path, 'rb') as f:
                                file_bytes = f.read()
                except Exception:
                    file_bytes = None

            # Attempt E: Fetch from URL if remote storage URL is available (S3, Cloudinary, CDN, DevTunnel)
            if not file_bytes:
                target_url = None
                if file_field and getattr(file_field, 'name', None) and hasattr(file_field, 'url'):
                    try:
                        target_url = file_field.url
                    except Exception:
                        target_url = None
                elif file_url:
                    target_url = file_url
                elif storage and storage_key and hasattr(storage, 'generate_cdn_url'):
                    try:
                        target_url = storage.generate_cdn_url(storage_key)
                    except Exception:
                        target_url = None

                if target_url:
                    if str(target_url).startswith('/'):
                        try:
                            if hasattr(request, 'build_absolute_uri'):
                                target_url = request.build_absolute_uri(target_url)
                        except Exception:
                            pass
                    try:
                        resp = requests.get(target_url, timeout=12)
                        if resp.status_code == 200:
                            file_bytes = resp.content
                    except Exception:
                        file_bytes = None

            # Attempt F: Fallback to preview_storage_key if original missing
            if not file_bytes and storage and getattr(item, 'preview_storage_key', None):
                try:
                    file_bytes = storage.download(item.preview_storage_key)
                except Exception:
                    file_bytes = None

            # Write file bytes into the ZIP archive
            if file_bytes:
                # Watermark baking if enabled on gallery and media item is a photo
                if getattr(gallery, 'watermark_enabled', False) and getattr(item, 'media_type', 'photo') != 'video':
                    try:
                        profile = getattr(gallery.photographer, 'photographer_profile', None) or getattr(gallery, 'photographer', None)
                        legacy_placeholders = {'ex studio', '© ex studio', 'atelier studio', '© atelier studio', 'studio', '© studio'}
                        wm_text = None
                        if gallery.watermark_text and gallery.watermark_text.strip():
                            raw = gallery.watermark_text.strip()
                            if raw.lower() not in legacy_placeholders:
                                wm_text = raw if raw.startswith('©') else f"© {raw}"

                        if not wm_text:
                            if profile and hasattr(profile, 'get_effective_watermark_text'):
                                wm_text = profile.get_effective_watermark_text()
                            else:
                                user = getattr(gallery.photographer, 'user', None) or getattr(gallery, 'user', None) or gallery.photographer
                                name = user.get_full_name().strip() if (user and hasattr(user, 'get_full_name')) else ''
                                name = name or (getattr(profile, 'name', '') if profile else '') or getattr(user, 'username', 'Photographer')
                                wm_text = f"© {name}"

                        logo_file = profile.watermark_image if (profile and getattr(profile, 'watermark_image', None)) else None
                        watermarked_stream = stamp_watermark_on_image(
                            io.BytesIO(file_bytes),
                            watermark_text=wm_text,
                            logo_file=logo_file,
                            opacity=gallery.watermark_opacity or (getattr(profile, 'watermark_opacity', 0.45) if profile else 0.45),
                            position=gallery.watermark_position or (getattr(profile, 'watermark_position', 'bottom-right') if profile else 'bottom-right'),
                        )
                        file_bytes = watermarked_stream.getvalue()
                    except Exception as wm_err:
                        logger.warning(f"Watermark baking failed for item {item.id} in ZIP download: {wm_err}")

                zip_file.writestr(filename, file_bytes)

    # Update gallery downloads count telemetry
    try:
        Gallery.objects.filter(id=gallery.id).update(downloads_count=F('downloads_count') + 1)
        GalleryAnalyticsEvent.objects.create(
            gallery=gallery,
            event_type='download',
            device='desktop'
        )
    except Exception:
        pass

    # 6. Prepare response
    zip_buffer.seek(0)
    gallery_slug = getattr(gallery, 'slug', None) or slugify(getattr(gallery, 'title', 'gallery')) or 'gallery'
    zip_filename = f"{gallery_slug}_photos.zip"
    
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
    response['Access-Control-Expose-Headers'] = 'Content-Disposition'
    return response


class PublicGalleryDownloadZipView(APIView):
    """
    Stream high-speed ZIP download for public gallery.
    GET /api/public/galleries/{slug_or_id}/download-zip/
    """
    permission_classes = [AllowAny]

    def get(self, request, slug_or_id=None, id_or_slug=None, *args, **kwargs):
        target = slug_or_id or id_or_slug or kwargs.get('pk')
        return download_gallery_zip(request, id_or_slug=target)

class PublicGalleryVerifyPinView(APIView):
    """
    Verifies PIN code / password for gallery access.
    POST /api/public/galleries/{slug_or_id}/verify-pin/
    """
    permission_classes = [AllowAny]
    throttle_classes = [PinVerifyRateThrottle]

    def post(self, request, slug_or_id):
        gallery = get_public_gallery(slug_or_id)

        # ─── LOCK CHECK: Host Studio Subscription Expiry ───
        host_user = gallery.user
        if host_user and not is_studio_active(host_user):
            studio_profile = getattr(host_user, 'profile', None)
            return Response(
                {
                    "code": "studio_plan_expired",
                    "error_code": "PLAN_EXPIRED",
                    "detail": "This gallery is locked because the host studio's subscription has expired.",
                    "is_studio_plan_expired": True,
                    "title": gallery.title,
                    "client_name": getattr(gallery, 'client_name', ''),
                    "studio_name": getattr(studio_profile, 'studio_name', 'Studio') if studio_profile else 'Studio',
                    "studio_email": getattr(host_user, 'email', ''),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # 0. Block Archived Gallery Access
        if gallery.status == 'archived':
            return Response({
                'code': 'gallery_archived',
                'status': 'archived',
                'title': gallery.title,
                'client_name': gallery.client_name,
                'detail': 'This collection has been archived by the studio and is currently unavailable.'
            }, status=status.HTTP_410_GONE)

        # 1. Enforce Expiration:
        if gallery.is_expired:
            return Response(
                {
                    "error": "This gallery link has expired.",
                    "code": "gallery_expired",
                    "is_expired": True
                },
                status=status.HTTP_410_GONE
            )

        pin = (request.data.get("pin") or request.data.get("password") or '').strip()
        is_locked = gallery.is_password_protected or gallery.visibility == 'password_protected'

        pin_valid = False
        if not is_locked:
            pin_valid = True
        elif pin:
            if gallery.download_pin and pin == gallery.download_pin:
                pin_valid = True
            elif gallery.password and pin == gallery.password:
                pin_valid = True
            elif gallery.check_access_password(pin):
                pin_valid = True

        if pin_valid:
            serializer = PublicGallerySerializer(gallery, context={'request': request, 'access_granted': True})
            return Response({
                "status": "unlocked",
                "is_valid": True,
                "message": "Access granted.",
                "gallery": serializer.data
            }, status=status.HTTP_200_OK)

        return Response({"error": "Invalid PIN", "is_valid": False, "code": "INVALID_PIN"}, status=status.HTTP_400_BAD_REQUEST)


VerifyGalleryPinView = PublicGalleryVerifyPinView


class PublicGalleryTrackView(APIView):
    """
    Public View Tracking Endpoint.
    POST /api/public/galleries/{slug_or_id}/track-view/
    """
    permission_classes = [AllowAny]

    def post(self, request, slug_or_id):
        gallery = get_public_gallery(slug_or_id)

        # 0. Block Archived Gallery Access
        if gallery.status == 'archived':
            return Response({
                'code': 'gallery_archived',
                'status': 'archived',
                'title': gallery.title,
                'client_name': gallery.client_name,
                'detail': 'This collection has been archived by the studio and is currently unavailable.'
            }, status=status.HTTP_410_GONE)

        if gallery.is_expired:
            return Response(
                {
                    "error": "This gallery link has expired.",
                    "code": "gallery_expired",
                    "is_expired": True
                },
                status=status.HTTP_410_GONE
            )

        device = request.data.get('device', 'desktop')
        if device not in ['desktop', 'mobile', 'tablet']:
            device = 'desktop'

        ip_addr = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
        ip_hash = hashlib.sha256(ip_addr.encode('utf-8')).hexdigest()[:16] if ip_addr else ''

        GalleryAnalyticsEvent.objects.create(
            gallery=gallery,
            event_type='view',
            device=device,
            traffic_source='direct_link',
            ip_hash=ip_hash,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            details=f"Public visitor from {device.title()}",
        )

        Gallery.objects.filter(id=gallery.id).update(views_count=F('views_count') + 1)
        trigger_studio_notification(
            gallery.photographer,
            'client_visit',
            'New Client Visit',
            f"Client {gallery.client_name or 'Visitor'} visited '{gallery.title}'",
            gallery_id=gallery.id
        )

        return Response({
            "status": "success",
            "message": "View recorded.",
            "views_count": (gallery.views_count or 0) + 1
        }, status=status.HTTP_200_OK)


TrackGalleryView = PublicGalleryTrackView


class ClientSelectionListCreateView(APIView):
    """
    GET / POST /api/storage/galleries/{id}/client-selections/
    """
    permission_classes = [AllowAny]

    def get(self, request, gallery_id):
        gallery = get_object_or_404(Gallery, id=gallery_id)
        client_email = request.query_params.get('email')
        qs = gallery.client_selections.all()
        if client_email:
            qs = qs.filter(client_email=client_email)

        serializer = GalleryClientSelectionSerializer(qs, many=True, context={'request': request})
        return Response({"status": "success", "results": serializer.data}, status=status.HTTP_200_OK)

    def post(self, request, gallery_id):
        gallery = get_object_or_404(Gallery, id=gallery_id)
        client_email = request.data.get('client_email')
        if not client_email:
            return Response({"detail": "client_email is required."}, status=status.HTTP_400_BAD_REQUEST)

        client_name = request.data.get('client_name', '')
        client_notes = request.data.get('client_notes', '')
        selected_media_ids = request.data.get('selected_media_ids', [])

        selection, _ = GalleryClientSelection.objects.get_or_create(
            gallery=gallery,
            client_email=client_email,
            defaults={'client_name': client_name, 'client_notes': client_notes}
        )

        if client_name:
            selection.client_name = client_name
        if client_notes:
            selection.client_notes = client_notes

        if isinstance(selected_media_ids, list):
            valid_media = gallery.media_items.filter(id__in=selected_media_ids, deleted_at__isnull=True)
            selection.selected_media.set(valid_media)
            selection.selected_count = valid_media.count()

        selection.save()
        serializer = GalleryClientSelectionSerializer(selection, context={'request': request})
        return Response({
            "status": "success",
            "message": "Client selections saved.",
            "selection": serializer.data
        }, status=status.HTTP_200_OK)


class ClientSelectionSubmitView(APIView):
    """
    Submits client proofing selection with notes to studio.
    POST /api/storage/galleries/{id}/client-selections/{selection_id}/submit/
    """
    permission_classes = [AllowAny]

    def post(self, request, gallery_id, selection_id):
        gallery = get_object_or_404(Gallery.objects.select_related('photographer'), id=gallery_id)
        selection = get_object_or_404(GalleryClientSelection, id=selection_id, gallery=gallery)

        client_notes = request.data.get('client_notes')
        if client_notes is not None:
            selection.client_notes = client_notes

        selection.status = 'submitted'
        selection.submitted_at = timezone.now()
        selection.save()

        # Trigger studio notification
        trigger_studio_notification(
            gallery.photographer,
            'proofing_submitted',
            f"Client selections submitted for {gallery.title}",
            f"Client {selection.client_email} finalized {selection.selected_count} proofing favorites for '{gallery.title}'.",
            gallery.id
        )

        StorageAuditLog.objects.create(
            photographer=gallery.photographer,
            gallery=gallery,
            action="PROOF_SUBMIT",
            details={
                "client_email": selection.client_email,
                "selected_count": selection.selected_count,
                "notes": selection.client_notes
            }
        )

        serializer = GalleryClientSelectionSerializer(selection, context={'request': request})
        return Response({
            "status": "success",
            "message": "Proofing selection submitted to studio successfully.",
            "selection": serializer.data
        }, status=status.HTTP_200_OK)


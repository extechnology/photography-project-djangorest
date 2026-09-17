import io
import os
import zipfile
import urllib.parse
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, FileResponse
from django.core.files.base import ContentFile
from django.db.models import F
from django.utils.text import slugify
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from App.Auth.auth_utils import get_user_from_request
from App.Photographers.photo_models import PhotographerProfile, Notification, NotificationPreference
from App.Photographers.photo_utils import check_image_for_nudity
from App.Storage.storage_models import (

    SharedEvent,
    EventPhoto,
    Gallery,
    Media,
    GalleryClientAccess,
    GalleryClientSelection,
    FaceEmbedding,
    UploadReservation,
    BulkDownloadJob,
    StorageAuditLog,
)
from App.Storage.storage_serializers import (
    SharedEventListSerializer,
    SharedEventDetailSerializer,
    PublicSharedEventSerializer,
    EventPhotoSerializer,
    GallerySerializer,
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


VALID_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}



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
        return PhotographerProfile.objects.get(user=user)
    except PhotographerProfile.DoesNotExist:
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

        profile = get_photographer_profile(user)
        if not profile:
            return Response({"message": "Only registered photographers can create shared events."}, status=status.HTTP_403_FORBIDDEN)

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
        event = get_object_or_404(SharedEvent.objects.select_related('photographer'), access_code=access_code)
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
        event = get_object_or_404(SharedEvent, access_code=access_code)
        pin = request.data.get('pin') or request.query_params.get('pin', '')
        if event.verify_pin(pin):
            return Response({"valid": True, "message": "PIN verified successfully."}, status=status.HTTP_200_OK)
        return Response({"valid": False, "message": "Invalid PIN code."}, status=status.HTTP_400_BAD_REQUEST)


class PublicPhotoDownloadView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, photo_id):
        photo = get_object_or_404(EventPhoto.objects.select_related('event'), pk=photo_id)
        event = photo.event

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
        event = get_object_or_404(SharedEvent, access_code=access_code)
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
            galleries = Gallery.objects.all().select_related('photographer')
        else:
            galleries = Gallery.objects.filter(photographer=profile)

        serializer = GallerySerializer(galleries, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED", "detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        profile = get_photographer_profile(user)
        if not profile and not (user.is_staff or user.is_superuser):
            return Response({"code": "NOT_A_PHOTOGRAPHER", "detail": "Photographer profile not found."}, status=status.HTTP_403_FORBIDDEN)

        serializer = GallerySerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            gallery = serializer.save(photographer=profile)
            StorageAuditLog.objects.create(
                photographer=profile,
                gallery=gallery,
                user=user,
                action="GALLERY_CREATED",
                details={"title": gallery.title, "visibility": gallery.visibility},
            )
            return Response(GallerySerializer(gallery, context={'request': request}).data, status=status.HTTP_201_CREATED)

        return Response({"code": "VALIDATION_FAILED", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class GalleryDetailView(APIView):
    def _get_gallery(self, pk, user):
        gallery = get_object_or_404(Gallery.objects.select_related('photographer', 'photographer__user'), pk=pk)
        if gallery.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return None
        return gallery

    def get(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = self._get_gallery(pk, user)
        if not gallery:
            return Response({"code": "GALLERY_ACCESS_DENIED", "detail": "You do not own this gallery."}, status=status.HTTP_403_FORBIDDEN)

        serializer = GallerySerializer(gallery, context={'request': request})
        data = serializer.data

        # Include media items for photographer management
        media_items = gallery.media_items.filter(deleted_at__isnull=True).order_by('-created_at')
        data['media'] = MediaSerializer(media_items, many=True, context={'request': request}).data
        return Response(data, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = self._get_gallery(pk, user)
        if not gallery:
            return Response({"code": "GALLERY_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        serializer = GallerySerializer(gallery, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            updated_gallery = serializer.save()
            return Response(GallerySerializer(updated_gallery, context={'request': request}).data, status=status.HTTP_200_OK)

        return Response({"code": "VALIDATION_FAILED", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = self._get_gallery(pk, user)
        if not gallery:
            return Response({"code": "GALLERY_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        # Soft delete / archive policy
        gallery.status = "archived"
        gallery.save(update_fields=["status"])
        return Response({"message": "Gallery archived successfully."}, status=status.HTTP_200_OK)


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

            results.append({
                "reservation_id": str(reservation.id),
                "storage_key": storage_key,
                "filename": item["filename"],
                "media_type": item["media_type"],
                "upload_url": upload_meta["upload_url"],
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
    Direct multi-file upload through Django view: handles quota reservation,
    direct storage saving, and background queueing.
    """
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [UploadRateThrottle]

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = get_object_or_404(Gallery.objects.select_related('photographer'), id=gallery_id)
        if gallery.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "GALLERY_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        files = request.FILES.getlist('photos') or request.FILES.getlist('images') or request.FILES.getlist('files')
        if not files:
            single = request.FILES.get('photo') or request.FILES.get('image')
            if single:
                files = [single]

        if not files:
            return Response({"code": "NO_FILES_PROVIDED", "detail": "Upload image files under 'photos'."}, status=status.HTTP_400_BAD_REQUEST)

        total_bytes = sum(getattr(f, 'size', 0) for f in files)
        profile = gallery.photographer

        # Quota check
        try:
            reservation = StorageQuotaService.reserve_quota(profile, gallery, total_bytes)
        except StorageQuotaExceededException as e:
            return Response({"code": "STORAGE_LIMIT_EXCEEDED", "detail": str(e)}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        storage = get_storage_provider()
        created_media = []
        committed_bytes = 0

        for f in files:
            ext = os.path.splitext(f.name)[1].lower()
            if ext not in VALID_IMAGE_EXTENSIONS:
                continue

            is_nude, violations = check_image_for_nudity(f)
            if is_nude:
                continue

            file_bytes = f.read()

            actual_size = len(file_bytes)
            key = f"galleries/{gallery.id}/originals/{f.name}"
            storage.upload(key, file_bytes, content_type=getattr(f, 'content_type', 'image/jpeg'))

            media = Media.objects.create(
                photographer=profile,
                gallery=gallery,
                original_filename=f.name,
                storage_key=key,
                file_size=actual_size,
                mime_type=getattr(f, 'content_type', 'image/jpeg'),
                file_extension=ext,
                processing_status="pending",
                upload_status="completed",
            )
            created_media.append(media)
            committed_bytes += actual_size

            # Trigger processing
            run_or_queue_task(process_media_derivatives_and_faces_task, str(media.id))

        StorageQuotaService.commit_quota(reservation, committed_bytes)

        return Response(
            {
                "message": f"Successfully uploaded {len(created_media)} files.",
                "total_uploaded": len(created_media),
                "media": MediaSerializer(created_media, many=True, context={'request': request}).data,
            },
            status=status.HTTP_201_CREATED
        )


class MediaDetailDeleteView(APIView):
    """Handles secure deletion of media items with storage adjustment and face embedding cleanup."""

    def delete(self, request, media_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        media = get_object_or_404(Media.objects.select_related('photographer', 'gallery'), id=media_id)
        if media.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "PERMISSION_DENIED"}, status=status.HTTP_403_FORBIDDEN)

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

        return Response({"message": "Media deleted successfully."}, status=status.HTTP_200_OK)


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
            return Response({"code": "GALLERY_ARCHIVED", "detail": "This gallery is no longer available."}, status=status.HTTP_404_NOT_FOUND)

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
        signed_url = storage.generate_signed_download_url(media.storage_key, expires_in=3600, filename=filename)

        # For LocalStorageProvider, direct FileResponse can also be served
        if isinstance(storage, type(get_storage_provider())) and hasattr(storage, "_resolve_path"):
            path = storage._resolve_path(media.storage_key)
            if path.exists():
                return FileResponse(open(path, "rb"), as_attachment=True, filename=filename)

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
                "job": BulkDownloadJobSerializer(job).data,
                "status_url": f"/api/galleries/bulk-download-jobs/{job.id}/",
            },
            status=status.HTTP_202_ACCEPTED
        )


class BulkDownloadJobStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, job_id):
        job = get_object_or_404(BulkDownloadJob.objects.select_related("gallery"), id=job_id)
        serializer = BulkDownloadJobSerializer(job)
        return Response(serializer.data, status=status.HTTP_200_OK)


# =============================================================================
# 6. Face-Based Photo Discovery API
# =============================================================================

class GalleryFaceSearchView(APIView):
    """
    Accepts a selfie image, extracts face embedding, and returns matching photos
    strictly isolated within the target gallery.
    """
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [FaceSearchRateThrottle]

    def post(self, request, gallery_id):
        gallery = get_object_or_404(Gallery, id=gallery_id)

        if not gallery.face_search_enabled:
            return Response({"code": "FACE_SEARCH_DISABLED", "detail": "Face search is disabled for this gallery."}, status=status.HTTP_403_FORBIDDEN)

        password = request.headers.get("X-Gallery-Password") or request.data.get("password")
        if gallery.visibility == "password_protected" and not gallery.check_access_password(password):
            return Response({"code": "PASSWORD_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)

        selfie = request.FILES.get("selfie") or request.FILES.get("image") or request.FILES.get("file")
        if not selfie:
            return Response({"code": "SELFIE_REQUIRED", "detail": "Upload a selfie image under 'selfie'."}, status=status.HTTP_400_BAD_REQUEST)

        # Read into memory
        selfie_bytes = selfie.read()

        # Execute search strictly within target gallery
        search_result = FaceService.search_gallery_faces(gallery, selfie_bytes)

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

class GalleryTemplateSwitchView(APIView):
    """
    Switches the layout template ('editorial'|'masonry'|'cinematic'|'minimal')
    PATCH /api/storage/galleries/{id}/template/
    """
    def patch(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = get_object_or_404(Gallery.objects.select_related('photographer', 'photographer__plan'), id=gallery_id)
        if gallery.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "GALLERY_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        serializer = GalleryTemplateUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        template_id = serializer.validated_data['template_id']

        # Verify against photographer plan permissions if restricted
        if gallery.photographer.plan and gallery.photographer.plan.allowed_templates:
            if template_id not in gallery.photographer.plan.allowed_templates:
                return Response({
                    "code": "TEMPLATE_NOT_ALLOWED",
                    "detail": f"Template '{template_id}' is not included in your current subscription tier."
                }, status=status.HTTP_403_FORBIDDEN)

        gallery.template_id = template_id
        gallery.save(update_fields=['template_id'])

        return Response({
            "message": f"Gallery template switched to {template_id}",
            "template_id": gallery.template_id
        }, status=status.HTTP_200_OK)


class GallerySetCoverView(APIView):
    """
    Assigns a specific media item or cover image URL as gallery cover.
    POST /api/storage/galleries/{id}/set-cover/
    """
    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = get_object_or_404(Gallery, id=gallery_id)
        if gallery.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "GALLERY_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        serializer = GallerySetCoverSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        media_id = serializer.validated_data.get('media_id')
        cover_image_url = serializer.validated_data.get('cover_image_url')

        if media_id:
            media = get_object_or_404(Media, id=media_id, gallery=gallery)
            # Reset is_cover on other media items
            gallery.media_items.filter(is_cover=True).update(is_cover=False)
            media.is_cover = True
            media.save(update_fields=['is_cover'])
            gallery.cover_media = media
            gallery.save(update_fields=['cover_media'])
        elif cover_image_url:
            gallery.cover_image_url = cover_image_url
            gallery.save(update_fields=['cover_image_url'])

        return Response({
            "message": "Cover media updated successfully.",
            "gallery_id": str(gallery.id),
            "cover_image": GallerySerializer(gallery).data.get('cover_image')
        }, status=status.HTTP_200_OK)


class GalleryReorderMediaView(APIView):
    """
    Reorders media items inside a gallery.
    POST /api/storage/galleries/{id}/reorder-media/
    """
    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = get_object_or_404(Gallery, id=gallery_id)
        if gallery.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "GALLERY_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        serializer = GalleryReorderMediaSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        order_list = serializer.validated_data['order']
        updated = 0
        for item in order_list:
            m_id = item.get('media_id') or item.get('id')
            d_order = item.get('display_order', 0)
            if m_id is not None:
                Media.objects.filter(id=m_id, gallery=gallery).update(display_order=d_order)
                updated += 1

        return Response({
            "message": f"Successfully reordered {updated} media items."
        }, status=status.HTTP_200_OK)


class MediaBulkDeleteView(APIView):
    """
    Bulk removes multiple media items from a gallery.
    POST /api/storage/galleries/media/bulk-delete/
    """
    def post(self, request):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        media_ids = request.data.get('media_ids', [])
        if not isinstance(media_ids, list) or not media_ids:
            return Response({"detail": "media_ids must be a non-empty list of UUIDs."}, status=status.HTTP_400_BAD_REQUEST)

        media_qs = Media.objects.filter(id__in=media_ids, deleted_at__isnull=True).select_related('photographer')
        deleted_count = 0
        total_freed_bytes = 0

        storage = get_storage_provider()
        for media in media_qs:
            if media.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
                continue

            if media.storage_key:
                storage.delete(media.storage_key)
            if media.thumbnail_storage_key:
                storage.delete(media.thumbnail_storage_key)
            if media.preview_storage_key:
                storage.delete(media.preview_storage_key)

            FaceEmbedding.objects.filter(media=media).delete()
            StorageQuotaService.deduct_storage(media.photographer, media.file_size)
            total_freed_bytes += media.file_size

            media.deleted_at = timezone.now()
            media.save(update_fields=['deleted_at'])
            deleted_count += 1

        return Response({
            "message": f"Successfully deleted {deleted_count} media items.",
            "deleted_count": deleted_count,
            "freed_bytes": total_freed_bytes
        }, status=status.HTTP_200_OK)


class MediaToggleFavoriteView(APIView):
    """
    Toggles is_favorite flag for studio starred media.
    POST /api/storage/galleries/media/{media_id}/favorite/
    """
    def post(self, request, media_id):
        media = get_object_or_404(Media.objects.select_related('gallery', 'photographer'), id=media_id)
        
        # Toggle favorite
        media.is_favorite = not media.is_favorite
        media.save(update_fields=['is_favorite'])

        # Update gallery favorites count
        gallery = media.gallery
        fav_count = gallery.media_items.filter(is_favorite=True, deleted_at__isnull=True).count()
        gallery.favorites_count = fav_count
        gallery.save(update_fields=['favorites_count'])

        return Response({
            "message": "Media favorite toggled successfully.",
            "media_id": str(media.id),
            "is_favorite": media.is_favorite,
            "gallery_favorites_count": fav_count
        }, status=status.HTTP_200_OK)


class PublicGallerySlugOrIdView(APIView):
    """
    Public / guest view of gallery by slug or UUID.
    GET /api/storage/public/galleries/{slug_or_id}/
    """
    permission_classes = [AllowAny]
    throttle_classes = [ShareAccessRateThrottle]

    def get(self, request, slug_or_id):
        gallery = None
        try:
            gallery = Gallery.objects.select_related('photographer').get(id=slug_or_id)
        except Exception:
            pass

        if not gallery:
            gallery = get_object_or_404(Gallery.objects.select_related('photographer'), slug=slug_or_id)

        if gallery.is_expired():
            return Response({"code": "GALLERY_EXPIRED", "detail": "This gallery has expired."}, status=status.HTTP_410_GONE)

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
        access_granted = not is_locked or (provided_password and gallery.check_access_password(provided_password))

        serializer = PublicGallerySerializer(
            gallery,
            context={'request': request, 'access_granted': access_granted}
        )
        data = serializer.data
        data['access_granted'] = bool(access_granted)
        return Response(data, status=status.HTTP_200_OK)


class PublicGalleryVerifyPinView(APIView):
    """
    Verifies PIN code / password for gallery access.
    POST /api/storage/public/galleries/{slug_or_id}/verify-pin/
    """
    permission_classes = [AllowAny]
    throttle_classes = [PinVerifyRateThrottle]

    def post(self, request, slug_or_id):
        gallery = None
        try:
            gallery = Gallery.objects.select_related('photographer').get(id=slug_or_id)
        except Exception:
            pass

        if not gallery:
            gallery = get_object_or_404(Gallery.objects.select_related('photographer'), slug=slug_or_id)

        pin = request.data.get("pin") or request.data.get("password")
        if not pin:
            return Response({"code": "PIN_REQUIRED", "detail": "Please provide 'pin' or 'password'."}, status=status.HTTP_400_BAD_REQUEST)

        if not gallery.check_access_password(pin):
            return Response({"code": "INVALID_PIN", "detail": "Incorrect PIN or password."}, status=status.HTTP_403_FORBIDDEN)

        serializer = PublicGallerySerializer(gallery, context={'request': request, 'access_granted': True})
        return Response({
            "status": "success",
            "message": "Access granted.",
            "gallery": serializer.data
        }, status=status.HTTP_200_OK)


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


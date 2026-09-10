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
from App.Photographers.photo_models import PhotographerProfile
from App.Storage.storage_models import (
    SharedEvent,
    EventPhoto,
    Gallery,
    Media,
    GalleryClientAccess,
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
    DirectUploadInitSerializer,
    DirectUploadConfirmSerializer,
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
)

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
    Step 1: Photographer requests pre-signed direct upload URL.
    Validates photographer storage quota and atomically reserves bytes.
    """
    throttle_classes = [UploadRateThrottle]

    def post(self, request, gallery_id):
        user = get_current_user(request)
        if not user:
            return Response({"code": "AUTHENTICATION_REQUIRED"}, status=status.HTTP_401_UNAUTHORIZED)

        gallery = get_object_or_404(Gallery.objects.select_related('photographer'), id=gallery_id)
        if gallery.photographer.user_id != user.id and not (user.is_staff or user.is_superuser):
            return Response({"code": "GALLERY_ACCESS_DENIED"}, status=status.HTTP_403_FORBIDDEN)

        serializer = DirectUploadInitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"code": "VALIDATION_FAILED", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        file_size = serializer.validated_data["file_size"]
        filename = serializer.validated_data["original_filename"]
        mime_type = serializer.validated_data["mime_type"]

        # Atomic quota reservation
        try:
            reservation = StorageQuotaService.reserve_quota(gallery.photographer, gallery, file_size)
        except StorageQuotaExceededException as e:
            return Response(
                {"code": "STORAGE_LIMIT_EXCEEDED", "detail": str(e)},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )

        storage_key = f"galleries/{gallery.id}/originals/{reservation.id}_{filename}"
        storage = get_storage_provider()
        upload_meta = storage.generate_signed_upload_url(storage_key, expires_in=1800, content_type=mime_type)

        return Response(
            {
                "reservation_id": str(reservation.id),
                "storage_key": storage_key,
                "upload_url": upload_meta["upload_url"],
                "method": upload_meta.get("method", "PUT"),
                "headers": upload_meta.get("headers", {}),
                "expires_in": 1800,
            },
            status=status.HTTP_200_OK
        )


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

        storage_key = serializer.validated_data["storage_key"]
        storage = get_storage_provider()

        if not storage.exists(storage_key):
            StorageQuotaService.release_quota(reservation)
            return Response({"code": "FILE_NOT_FOUND_IN_STORAGE", "detail": "Media file does not exist in storage."}, status=status.HTTP_400_BAD_REQUEST)

        meta = storage.get_metadata(storage_key)
        actual_size = meta.get("size", serializer.validated_data["file_size"])
        filename = serializer.validated_data["original_filename"]
        ext = os.path.splitext(filename)[1].lower() or ".jpg"

        # Finalize quota
        StorageQuotaService.commit_quota(reservation, actual_size)

        media = Media.objects.create(
            photographer=gallery.photographer,
            gallery=gallery,
            original_filename=filename,
            storage_key=storage_key,
            file_size=actual_size,
            mime_type=serializer.validated_data["mime_type"],
            file_extension=ext,
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

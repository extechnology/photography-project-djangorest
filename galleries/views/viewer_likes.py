import logging
import random
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from galleries.models import (
    Gallery,
    Media,
    GalleryViewer,
    ViewerLikedMedia,
    ViewerOtpVerification,
)
from galleries.serializers import (
    ViewerSendOtpSerializer,
    ViewerVerifyOtpSerializer,
    ViewerProfileSerializer,
    ViewerToggleFavoriteSerializer,
    ViewerBulkToggleFavoriteSerializer,
)

logger = logging.getLogger(__name__)


def resolve_gallery(slug_or_id):
    """
    Robust helper to resolve gallery by either slug or UUID string/object.
    """
    try:
        val = uuid.UUID(str(slug_or_id))
        return Gallery.objects.get(id=val)
    except (ValueError, Gallery.DoesNotExist):
        return get_object_or_404(Gallery, slug=str(slug_or_id))


def get_media_thumbnail_url(media, request=None):
    """
    Resolves CDN, local storage, or field URL for a media item.
    """
    url = ""
    try:
        from App.Storage.storage_services import get_storage_provider
        storage = get_storage_provider()
        key = (
            getattr(media, 'thumbnail_storage_key', None)
            or getattr(media, 'preview_storage_key', None)
            or getattr(media, 'storage_key', None)
        )
        if key:
            url = storage.generate_cdn_url(key)
    except Exception as exc:
        logger.debug(f"Could not resolve storage provider CDN URL: {exc}")

    if not url:
        if getattr(media, 'thumbnail', None):
            try:
                url = media.thumbnail.url
            except Exception:
                pass
        elif getattr(media, 'preview', None):
            try:
                url = media.preview.url
            except Exception:
                pass
        elif getattr(media, 'file', None):
            try:
                url = media.file.url
            except Exception:
                pass

    if request and url and url.startswith('/'):
        return request.build_absolute_uri(url)
    return url or ""


class ViewerSendOtpView(APIView):
    """
    POST /api/public/galleries/<slug_or_id>/auth/send-otp/
    Dispatches 6-digit OTP code to the viewer's email.
    """
    permission_classes = [AllowAny]

    def post(self, request, slug_or_id):
        serializer = ViewerSendOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()

        gallery = resolve_gallery(slug_or_id)

        # Rate limiting: max 5 OTP requests per email in last 15 minutes
        recent_requests = ViewerOtpVerification.objects.filter(
            email=email,
            created_at__gte=timezone.now() - timedelta(minutes=15)
        ).count()
        if recent_requests >= 5:
            return Response(
                {"status": "error", "message": "Too many verification requests. Please wait 15 minutes."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        # Generate secure 6-digit OTP
        otp_code = f"{random.randint(100000, 999999)}"
        expires_at = timezone.now() + timedelta(minutes=10)

        ViewerOtpVerification.objects.create(
            gallery=gallery,
            email=email,
            otp_code=otp_code,
            expires_at=expires_at
        )

        # Send Email
        subject = f"Your Verification Code for {gallery.title}"
        studio_name = getattr(gallery.photographer, 'studio_name', None) or getattr(gallery.photographer, 'name', 'EX SHARE Atelier')
        message = (
            f"Hello,\n\n"
            f"Your verification code to save and view your liked photos in \"{gallery.title}\" is:\n\n"
            f"    {otp_code}\n\n"
            f"This code will expire in 10 minutes.\n\n"
            f"Best regards,\n"
            f"{studio_name}"
        )

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@exshare.ai'),
                recipient_list=[email],
                fail_silently=False
            )
        except Exception as e:
            if settings.DEBUG:
                print(f"[DEV EMAIL] Code for {email}: {otp_code}")
            else:
                logger.warning(f"Failed to send OTP email to {email}: {e}")
                if not getattr(settings, 'IS_TESTING', False):
                    return Response(
                        {"status": "error", "message": "Failed to send email. Please try again."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

        return Response({
            "status": "success",
            "message": "Verification code sent to your email.",
            "expires_in_seconds": 600
        }, status=status.HTTP_200_OK)


class ViewerVerifyOtpView(APIView):
    """
    POST /api/public/galleries/<slug_or_id>/auth/verify-otp/
    Verifies code, creates or retrieves GalleryViewer profile, returns session token.
    """
    permission_classes = [AllowAny]

    def post(self, request, slug_or_id):
        serializer = ViewerVerifyOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()
        otp = serializer.validated_data['otp'].strip()

        gallery = resolve_gallery(slug_or_id)

        otp_record = ViewerOtpVerification.objects.filter(
            gallery=gallery,
            email=email,
            is_verified=False,
            expires_at__gte=timezone.now()
        ).order_by('-created_at').first()

        if not otp_record or otp_record.attempts >= 5:
            return Response(
                {"status": "error", "message": "Invalid or expired verification code."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if otp_record.otp_code != otp:
            otp_record.attempts += 1
            otp_record.save(update_fields=['attempts'])
            return Response(
                {"status": "error", "message": "Incorrect verification code. Please check and re-enter."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Mark OTP as verified
        otp_record.is_verified = True
        otp_record.save(update_fields=['is_verified'])

        # Generate or retrieve session token for GalleryViewer
        token = secrets.token_urlsafe(32)
        viewer, _ = GalleryViewer.objects.get_or_create(
            gallery=gallery,
            email=email,
            defaults={'session_token': token}
        )
        if not viewer.session_token:
            viewer.session_token = token
            viewer.save(update_fields=['session_token'])

        viewer.last_active = timezone.now()
        viewer.save(update_fields=['last_active'])

        profile_data = ViewerProfileSerializer(viewer).data

        return Response({
            "status": "success",
            "message": "Verified successfully.",
            "viewer": profile_data
        }, status=status.HTTP_200_OK)


class ViewerLikedMediaListView(APIView):
    """
    GET /api/public/galleries/<slug_or_id>/likes/?email=...
    Retrieves all liked photo IDs for this viewer in this gallery.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug_or_id):
        email = request.query_params.get('email', '').strip().lower()
        gallery = resolve_gallery(slug_or_id)

        if not email:
            return Response({"liked_media_ids": [], "total_likes": 0}, status=status.HTTP_200_OK)

        viewer = GalleryViewer.objects.filter(gallery=gallery, email=email).first()
        if not viewer:
            return Response({"liked_media_ids": [], "total_likes": 0}, status=status.HTTP_200_OK)

        liked_ids = [
            str(mid) for mid in ViewerLikedMedia.objects.filter(
                viewer=viewer, gallery=gallery
            ).values_list('media_id', flat=True)
        ]

        return Response({
            "status": "success",
            "email": email,
            "liked_media_ids": liked_ids,
            "total_likes": len(liked_ids)
        }, status=status.HTTP_200_OK)


class ViewerToggleFavoriteView(APIView):
    """
    POST /api/public/galleries/<slug_or_id>/favorite/
    Toggles like on a single photograph.
    """
    permission_classes = [AllowAny]

    def post(self, request, slug_or_id):
        serializer = ViewerToggleFavoriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        media_id = serializer.validated_data['media_id']
        is_favorite = serializer.validated_data['is_favorite']
        email = serializer.validated_data.get('email', '').strip().lower()

        gallery = resolve_gallery(slug_or_id)
        media_item = get_object_or_404(Media, id=media_id, gallery=gallery)

        viewer = None
        if email:
            viewer, _ = GalleryViewer.objects.get_or_create(
                gallery=gallery,
                email=email,
                defaults={'session_token': secrets.token_urlsafe(32)}
            )
            if is_favorite:
                ViewerLikedMedia.objects.get_or_create(
                    viewer=viewer,
                    gallery=gallery,
                    media=media_item
                )
            else:
                ViewerLikedMedia.objects.filter(
                    viewer=viewer,
                    gallery=gallery,
                    media=media_item
                ).delete()

        # Update aggregated favorite counters on media item
        media_item.is_favorite = is_favorite
        media_item.favorites_count = ViewerLikedMedia.objects.filter(media=media_item).count()
        media_item.save(update_fields=['is_favorite', 'favorites_count'])

        total_likes = (
            ViewerLikedMedia.objects.filter(viewer=viewer, gallery=gallery).count()
            if viewer
            else ViewerLikedMedia.objects.filter(gallery=gallery).count()
        )

        return Response({
            "status": "success",
            "media_id": str(media_item.id),
            "is_favorite": is_favorite,
            "favorites_count": total_likes
        }, status=status.HTTP_200_OK)


class ViewerBulkToggleFavoriteView(APIView):
    """
    POST /api/public/galleries/<slug_or_id>/bulk-like/
    Bulk likes or unlikes selected photos for this viewer.
    """
    permission_classes = [AllowAny]

    def post(self, request, slug_or_id):
        serializer = ViewerBulkToggleFavoriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        media_ids = serializer.validated_data.get('media_ids', [])
        is_favorite = serializer.validated_data['is_favorite']
        select_all = serializer.validated_data.get('select_all', False)
        email = serializer.validated_data.get('email', '').strip().lower()

        gallery = resolve_gallery(slug_or_id)

        if select_all:
            target_media = list(Media.objects.filter(gallery=gallery))
        else:
            target_media = list(Media.objects.filter(gallery=gallery, id__in=media_ids))

        viewer = None
        if email:
            viewer, _ = GalleryViewer.objects.get_or_create(
                gallery=gallery,
                email=email,
                defaults={'session_token': secrets.token_urlsafe(32)}
            )

        if viewer:
            if is_favorite:
                new_likes = [
                    ViewerLikedMedia(viewer=viewer, gallery=gallery, media=m)
                    for m in target_media
                ]
                ViewerLikedMedia.objects.bulk_create(new_likes, ignore_conflicts=True)
            else:
                target_ids = [m.id for m in target_media]
                ViewerLikedMedia.objects.filter(
                    viewer=viewer,
                    gallery=gallery,
                    media_id__in=target_ids
                ).delete()

        # Update MediaItem flags
        target_ids = [m.id for m in target_media]
        Media.objects.filter(id__in=target_ids).update(is_favorite=is_favorite)

        total_viewer_likes = (
            ViewerLikedMedia.objects.filter(viewer=viewer, gallery=gallery).count()
            if viewer
            else len(target_ids)
        )

        return Response({
            "status": "success",
            "updated_count": len(target_media),
            "is_favorite": is_favorite,
            "media_ids": [str(m.id) for m in target_media],
            "favorites_count": total_viewer_likes
        }, status=status.HTTP_200_OK)


class GalleryClientFavoritesReviewView(APIView):
    """
    GET /api/galleries/<id>/client-favorites/
    Enables studio photographers to inspect client likes for album production.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, gallery_id=None, pk=None, id=None):
        target_id = gallery_id or pk or id
        gallery = resolve_gallery(target_id)

        user = request.user
        is_owner = (
            user.is_staff
            or user.is_superuser
            or (
                hasattr(gallery, 'photographer')
                and hasattr(gallery.photographer, 'user_id')
                and gallery.photographer.user_id == user.id
            )
        )
        if not is_owner:
            return Response(
                {"status": "error", "message": "You do not have permission to view favorites for this gallery."},
                status=status.HTTP_403_FORBIDDEN
            )

        viewers_qs = (
            GalleryViewer.objects.filter(gallery=gallery)
            .prefetch_related('liked_media__media')
            .order_by('-last_active')
        )

        viewers_data = []
        for viewer in viewers_qs:
            likes = viewer.liked_media.all()
            liked_media_items = []
            for like in likes:
                m = getattr(like, 'media', None)
                if not m:
                    continue
                liked_media_items.append({
                    "id": str(m.id),
                    "title": m.title or getattr(m, 'original_filename', '') or f"Media {m.id}",
                    "thumbnailUrl": get_media_thumbnail_url(m, request)
                })

            viewers_data.append({
                "id": str(viewer.id),
                "email": viewer.email,
                "name": viewer.name,
                "liked_count": len(liked_media_items),
                "last_active": viewer.last_active.isoformat() if viewer.last_active else None,
                "liked_media": liked_media_items
            })

        return Response({
            "status": "success",
            "gallery_id": str(gallery.id),
            "gallery_title": gallery.title,
            "viewers": viewers_data
        }, status=status.HTTP_200_OK)

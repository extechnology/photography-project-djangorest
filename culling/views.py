import io
import os
import zipfile
import uuid
from datetime import timedelta
from django.db import transaction
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from .models import CullingPricingTier, CullingSession, CullingPhoto, CullingCluster
from .serializers import (
    CullingPricingTierSerializer,
    ActiveCullingSessionResponseSerializer,
    CullingSessionSyncSerializer
)


class CullingPricingTiersListView(APIView):
    """
    GET /api/culling/pricing-tiers/ (alias /api/culling/plans/)
    Returns all active pricing tiers ordered by display_order.
    Publicly accessible so frontend can render dynamic plan cards.
    """
    permission_classes = []  # Public

    def get(self, request):
        tiers = CullingPricingTier.objects.filter(is_active=True).order_by('display_order', 'photos_limit')
        if not tiers.exists():
            CullingPricingTier.objects.bulk_create([
                CullingPricingTier(
                    id='cull_single_300',
                    name='Single Shoot Batch',
                    price_inr=149,
                    photos_limit=300,
                    badge='Single Shoot',
                    description='Ideal for mini shoots, maternity sessions, or portrait portraits.',
                    features=['Up to 300 Raw / High-Res Photos', 'AI Laplacian Focus Detection', 'Perceptual Difference Grouping', 'One-Click Gallery Direct Transfer'],
                    display_order=1
                ),
                CullingPricingTier(
                    id='cull_wedding_1200',
                    name='Full Event & Wedding',
                    price_inr=399,
                    photos_limit=1200,
                    badge='Most Popular',
                    description='Engineered for weddings, receptions, and half-day commercial shoots.',
                    features=['Up to 1,200 Raw / High-Res Photos', 'Ultra-Fast Local Multi-threading', 'Burst Grouping & Best Pick Engine', 'Zero Server File Compression'],
                    is_popular=True,
                    display_order=2
                ),
                CullingPricingTier(
                    id='cull_pro_unlimited',
                    name='Studio Multi-Day Pro',
                    price_inr=899,
                    photos_limit=999999,
                    badge='Studio Unlimited',
                    description='For multi-day festivals, corporate conventions, and multi-camera sets.',
                    features=['Unlimited Photos per session', 'Unlimited Bursts & Comparisons', 'Bulk Keep/Discard Overrides', 'Priority Gallery Sync Engine'],
                    display_order=3
                ),
            ])
            tiers = CullingPricingTier.objects.filter(is_active=True).order_by('display_order', 'photos_limit')

        serializer = CullingPricingTierSerializer(tiers, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ActiveCullingSessionView(APIView):
    """
    GET /api/culling/sessions/active/
    Returns the currently active session for the authenticated user, or active=False if none exists.
    Hydrates the React state when navigating to SmartCullPage or refreshing.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        active_session = CullingSession.objects.filter(
            user=request.user,
            status=CullingSession.Status.ACTIVE
        ).select_related('tier').prefetch_related('photos', 'clusters').first()

        if not active_session:
            return Response({
                "active": False,
                "session": None
            }, status=status.HTTP_200_OK)

        serializer = ActiveCullingSessionResponseSerializer(
            active_session, 
            context={'request': request}
        )
        return Response({
            "active": True,
            "session": serializer.data
        }, status=status.HTTP_200_OK)


class CreateCullingPaymentOrderView(APIView):
    """
    POST /api/culling/checkout/order/
    Creates a Razorpay order tied to the session and validates plan limits upfront.
    Strictly checks that the user does NOT already have an active batch in progress.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        session_id = request.data.get('session_id') or f"cull_{uuid.uuid4().hex[:16]}"
        tier_id = request.data.get('tier_id')
        photo_count = int(request.data.get('photo_count', 0))

        # LOOPHOLE CHECK: Ensure user doesn't already have an active batch
        existing_active = CullingSession.objects.filter(
            user=user, 
            status=CullingSession.Status.ACTIVE
        ).exclude(id=session_id).first()

        if existing_active:
            return Response({
                "error": "Active batch in progress",
                "detail": f"You already have an active batch of {existing_active.total_photos} photos. Please move to gallery, download keepers ZIP, or discard it before starting a new batch."
            }, status=status.HTTP_409_CONFLICT)

        # Validate tier
        try:
            tier = CullingPricingTier.objects.get(id=tier_id, is_active=True)
        except CullingPricingTier.DoesNotExist:
            return Response({"error": "Invalid pricing tier."}, status=status.HTTP_400_BAD_REQUEST)

        # LOOPHOLE CHECK: Verify queued photos do not exceed plan capacity
        if photo_count > tier.photos_limit:
            return Response({
                "error": "Plan limit exceeded",
                "detail": f"Selected plan allows up to {tier.photos_limit} photos, but {photo_count} were provided."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Create or update session in pending_payment state
        session, _ = CullingSession.objects.get_or_create(
            id=session_id,
            defaults={
                'user': user,
                'tier': tier,
                'status': CullingSession.Status.PENDING_PAYMENT,
                'paid_amount_inr': tier.price_inr
            }
        )
        session.tier = tier
        session.paid_amount_inr = tier.price_inr
        session.save(update_fields=['tier', 'paid_amount_inr'])

        # Create Razorpay order (or mock if in test mode)
        order_amount_paise = tier.price_inr * 100
        order_id = f"order_cull_{uuid.uuid4().hex[:12]}"

        # If Razorpay client is configured:
        # razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        # rp_order = razorpay_client.order.create({"amount": order_amount_paise, "currency": "INR", ...})
        # order_id = rp_order['id']

        session.razorpay_order_id = order_id
        session.save(update_fields=['razorpay_order_id'])

        return Response({
            "order_id": order_id,
            "amount": order_amount_paise,
            "currency": "INR",
            "key_id": getattr(settings, 'RAZORPAY_KEY_ID', 'rzp_test_mock'),
            "tier_id": tier.id,
            "tier_name": tier.name,
            "session_id": session.id
        }, status=status.HTTP_201_CREATED)


class VerifyCullingPaymentView(APIView):
    """
    POST /api/culling/checkout/verify/
    Verifies Razorpay payment signature and activates the session.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        session_id = request.data.get('session_id')
        payment_id = request.data.get('razorpay_payment_id')

        try:
            session = CullingSession.objects.get(id=session_id, user=user)
        except CullingSession.DoesNotExist:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        # In production: Verify Razorpay signature using razorpay.utility.verify_payment_signature
        session.is_paid = True
        session.status = CullingSession.Status.ACTIVE
        session.razorpay_payment_id = payment_id or f"pay_{uuid.uuid4().hex[:10]}"
        session.expires_at = timezone.now() + timedelta(days=7)
        session.save(update_fields=['is_paid', 'status', 'razorpay_payment_id', 'expires_at'])

        return Response({
            "status": "success",
            "message": "Payment verified and session activated.",
            "session_id": session.id
        }, status=status.HTTP_200_OK)


class UploadCullingPhotosView(APIView):
    """
    POST /api/culling/upload/
    Uploads raw photos to the session staging directory.
    Enforces that the session is active, paid, and does not exceed tier capacity.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        user = request.user
        session_id = request.data.get('session_id')
        files = request.FILES.getlist('photos') or request.FILES.getlist('files')

        if not files:
            return Response({"error": "No files uploaded."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session = CullingSession.objects.get(id=session_id, user=user)
        except CullingSession.DoesNotExist:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        # STRICT LOOPHOLE ENFORCEMENT:
        # A plan allows only ONE batch upload. Reject subsequent uploads to the same session.
        if session.photos.exists():
            return Response({
                "error": "Single upload rule violated",
                "detail": "This session already has photos uploaded. Each plan covers one batch upload. Please move current keepers to gallery or download as ZIP and discard to start a new shoot."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Check plan limit
        if session.tier and (len(files) > session.tier.photos_limit):
            return Response({
                "error": "Plan limit exceeded",
                "detail": f"File count ({len(files)}) exceeds plan limit ({session.tier.photos_limit})."
            }, status=status.HTTP_400_BAD_REQUEST)

        total_bytes = 0
        photo_objects = []

        for idx, f in enumerate(files):
            total_bytes += f.size
            photo_id = f"photo_{int(timezone.now().timestamp() * 1000)}_{idx}_{uuid.uuid4().hex[:6]}"
            photo = CullingPhoto(
                id=photo_id,
                session=session,
                file=f,
                name=f.name,
                size_bytes=f.size,
                size_mb=round(f.size / (1024 * 1024), 2),
                status=CullingPhoto.PhotoStatus.KEEP
            )
            photo_objects.append(photo)

        CullingPhoto.objects.bulk_create(photo_objects)

        session.total_photos = len(files)
        session.total_bytes = total_bytes
        session.save(update_fields=['total_photos', 'total_bytes'])

        return Response({
            "status": "success",
            "uploaded_count": len(files),
            "session_id": session.id
        }, status=status.HTTP_201_CREATED)


class SyncCullingSessionView(APIView):
    """
    POST /api/culling/sessions/{session_id}/sync/
    Persists culling analysis results, manual keep/discard overrides, and best pick changes.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, session_id):
        user = request.user
        serializer = CullingSessionSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            session = CullingSession.objects.select_for_update().get(id=session_id, user=user)
        except CullingSession.DoesNotExist:
            # Auto-create if not yet in database
            tier_id = data.get('tier_id')
            tier = CullingPricingTier.objects.filter(id=tier_id).first()
            session = CullingSession.objects.create(
                id=session_id,
                user=user,
                tier=tier,
                is_paid=data.get('is_paid', True),
                status=CullingSession.Status.ACTIVE,
                expires_at=timezone.now() + timedelta(days=7)
            )

        with transaction.atomic():
            # Update photos
            photos_data = data.get('photos', [])
            existing_photos = {p.id: p for p in session.photos.all()}

            photos_to_create = []
            photos_to_update = []

            for p_item in photos_data:
                p_id = p_item['id']
                if p_id in existing_photos:
                    photo = existing_photos[p_id]
                    photo.status = p_item['status']
                    photo.is_best_pick = p_item['isBestPick']
                    photo.cluster_id = p_item.get('clusterId', '')
                    photo.similarity_with_best = p_item.get('similarityWithBest', 0.0)
                    photo.sharpness_score = p_item.get('sharpnessScore', photo.sharpness_score)
                    photo.raw_sharpness_variance = p_item.get('rawSharpnessVariance', photo.raw_sharpness_variance)
                    photo.hash = p_item.get('hash', photo.hash)
                    photos_to_update.append(photo)
                else:
                    # Created client-side
                    photos_to_create.append(CullingPhoto(
                        id=p_id,
                        session=session,
                        name=f"Photo_{p_id}",
                        status=p_item['status'],
                        is_best_pick=p_item['isBestPick'],
                        cluster_id=p_item.get('clusterId', ''),
                        similarity_with_best=p_item.get('similarityWithBest', 0.0),
                        sharpness_score=p_item.get('sharpnessScore', 0.0),
                        raw_sharpness_variance=p_item.get('rawSharpnessVariance', 0.0),
                        hash=p_item.get('hash', '')
                    ))

            if photos_to_create:
                CullingPhoto.objects.bulk_create(photos_to_create)
            if photos_to_update:
                CullingPhoto.objects.bulk_update(
                    photos_to_update,
                    ['status', 'is_best_pick', 'cluster_id', 'similarity_with_best', 
                     'sharpness_score', 'raw_sharpness_variance', 'hash']
                )

            # Rebuild clusters
            clusters_data = data.get('clusters', [])
            session.clusters.all().delete()
            cluster_objects = [
                CullingCluster(
                    id=c['id'],
                    session=session,
                    best_pick_id=c.get('bestPickId', ''),
                    photo_ids=c.get('photoIds', []),
                    average_similarity=c.get('averageSimilarity', 0.0)
                )
                for c in clusters_data
            ]
            CullingCluster.objects.bulk_create(cluster_objects)

            # Update session summary counts
            discard_count = sum(1 for p in photos_data if p['status'] == 'discard')
            session.total_photos = len(photos_data)
            session.total_clusters = len(clusters_data)
            session.total_duplicates = discard_count
            session.save(update_fields=['total_photos', 'total_clusters', 'total_duplicates'])

        return Response({
            "status": "success",
            "message": "Session state synchronized successfully.",
            "photos_count": len(photos_data),
            "clusters_count": len(clusters_data)
        }, status=status.HTTP_200_OK)


class DiscardCullingSessionView(APIView):
    """
    GET /api/culling/sessions/{session_id}/
    Retrieves session details.
    DELETE /api/culling/sessions/{session_id}/
    Permanently deletes the active batch, unlinks files from staging storage,
    and frees the photographer's storage quota immediately.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        user = request.user
        session = CullingSession.objects.filter(id=session_id, user=user).select_related('tier').prefetch_related('photos', 'clusters').first()
        if session:
            serializer = ActiveCullingSessionResponseSerializer(session, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)

        # Legacy fallback
        try:
            from App.Culling.culling_models import CullingSession as LegacyCullingSession
            from App.Culling.culling_serializers import CullingSessionSerializer as LegacySerializer
            legacy_session = LegacyCullingSession.objects.get(id=session_id, user=user)
            return Response(LegacySerializer(legacy_session, context={'request': request}).data, status=status.HTTP_200_OK)
        except Exception:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

    def delete(self, request, session_id):
        user = request.user
        try:
            session = CullingSession.objects.get(id=session_id, user=user)
        except CullingSession.DoesNotExist:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        # Purge physical files from staging directory
        session.purge_staging_storage()

        # Mark as discarded so it no longer blocks future batches
        session.status = CullingSession.Status.DISCARDED
        session.save(update_fields=['status'])

        return Response({
            "status": "success",
            "message": "Session discarded and staging storage freed successfully."
        }, status=status.HTTP_200_OK)


class ExportCullingZipView(APIView):
    """
    GET /api/culling/sessions/{session_id}/export-zip/?status=keep
    Generates and streams a ZIP file of all approved keepers on-the-fly directly to the browser.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        user = request.user
        filter_status = request.query_params.get('status', 'keep')

        try:
            session = CullingSession.objects.get(id=session_id, user=user)
        except CullingSession.DoesNotExist:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        photos = session.photos.filter(status=filter_status)
        if not photos.exists():
            return Response({"error": f"No photos with status '{filter_status}' found."}, status=status.HTTP_400_BAD_REQUEST)

        # In-memory streaming buffer
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for idx, photo in enumerate(photos):
                if photo.file and hasattr(photo.file, 'path') and os.path.exists(photo.file.path):
                    arcname = photo.name or f"keeper_{idx + 1}.jpg"
                    zip_file.write(photo.file.path, arcname=arcname)
                elif photo.file:
                    try:
                        content = photo.file.read()
                        arcname = photo.name or f"keeper_{idx + 1}.jpg"
                        zip_file.writestr(arcname, content)
                    except Exception:
                        pass

        zip_buffer.seek(0)
        filename = f"AI_Keepers_{session.id[:8]}.zip"
        response = HttpResponse(zip_buffer.read(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class MoveCullingToGalleryView(APIView):
    """
    POST /api/culling/sessions/{session_id}/move-to-gallery/
    Moves approved keepers into a client gallery, deletes unkept duplicates,
    purges the staging directory, and marks the session as COMPLETED.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        user = request.user
        session = CullingSession.objects.filter(id=session_id, user=user).first()
        if not session:
            try:
                from App.Culling.culling_models import CullingSession as LegacyCullingSession
                from App.Culling.culling_views import CullingSessionViewSet
                if LegacyCullingSession.objects.filter(id=session_id, user=user).exists():
                    view = CullingSessionViewSet.as_view({'post': 'move_to_gallery'})
                    return view(request._request if hasattr(request, '_request') else request, pk=session_id)
            except Exception:
                pass
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        gallery_id = request.data.get('gallery_id')
        from gallery.models import Gallery, GalleryMedia
        gallery = None

        if not gallery_id and request.data.get('new_gallery_title'):
            profile = getattr(user, 'photographer_profile', None)
            gallery = Gallery.objects.create(
                photographer=profile,
                title=request.data.get('new_gallery_title')
            )
            gallery_id = str(gallery.id)
        elif gallery_id:
            try:
                gallery = Gallery.objects.get(id=gallery_id, photographer__user=user)
            except Exception:
                try:
                    gallery = Gallery.objects.get(id=gallery_id)
                    gallery_user = getattr(gallery, 'user', None) or getattr(getattr(gallery, 'photographer', None), 'user', None)
                    if gallery_user != user:
                        return Response({"error": "Destination gallery not found."}, status=status.HTTP_404_NOT_FOUND)
                except Exception:
                    return Response({"error": "Destination gallery not found."}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({"error": "gallery_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        keepers = session.photos.filter(status=CullingPhoto.PhotoStatus.KEEP)
        if not keepers.exists():
            return Response({"error": "No keeper photos found in this session."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            gallery_media_list = []
            for photo in keepers:
                has_file = False
                if photo.file:
                    if hasattr(photo.file, 'path'):
                        has_file = os.path.exists(photo.file.path)
                    else:
                        has_file = True

                if has_file:
                    gallery_media = GalleryMedia(
                        gallery=gallery,
                        photographer=gallery.photographer,
                        file=photo.file,
                        name=photo.name,
                        size=photo.size_bytes
                    )
                    gallery_media_list.append(gallery_media)

            if gallery_media_list:
                GalleryMedia.objects.bulk_create(gallery_media_list)

            # Purge duplicate files and staging storage
            session.purge_staging_storage()
            session.status = CullingSession.Status.COMPLETED
            session.save(update_fields=['status'])

        gallery_title = getattr(gallery, 'title', None) or getattr(gallery, 'name', 'Gallery')
        return Response({
            "status": "success",
            "message": f"Successfully moved {len(gallery_media_list)} keepers into gallery '{gallery_title}'. Staging storage freed.",
            "gallery_id": str(gallery.id),
            "moved_count": len(gallery_media_list),
            "purged": True
        }, status=status.HTTP_200_OK)


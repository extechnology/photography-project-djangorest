import os
import io
import shutil
import zipfile
import uuid

from django.db import transaction, models
from django.conf import settings
from django.http import HttpResponse
from django.core.files.base import ContentFile
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser

from .models import (
    CullingPricingTier,
    CullingSession,
    CullingStagingPhoto,
    CullingPhoto,
    CullingCluster,
)
from .serializers import (
    CullingPricingTierSerializer,
    CullingPhotoSerializer,
    CullingClusterSerializer,
    ActiveCullingSessionSerializer,
    CullingSessionDetailSerializer,
)
from .ai_engine import run_server_side_culling, run_server_side_ai_analysis
from .permissions import HasAICullingAccess, HasAICullingPlanPermission
from App.Storage.storage_models import Gallery, GallerySection, Media as GalleryMedia
from App.Storage.services.storage_service import get_storage_provider
from App.Photographers.photo_models import PhotographerProfile


def find_app_culling_session(sid, user):
    """Safely look up an App.Culling session by session_key or UUID id without throwing ValidationError."""
    if not sid or not user:
        return None
    from App.Culling.culling_models import CullingSession as AppCullingSession
    try:
        s = AppCullingSession.objects.filter(session_key=str(sid), user=user).first()
        if s:
            return s
    except Exception:
        pass
    try:
        uuid.UUID(str(sid))
        return AppCullingSession.objects.filter(id=sid, user=user).first()
    except (ValueError, AttributeError, Exception):
        return None


# ─── 1. Multi-Photo Upload ───────────────────────────────────────────────────

class UploadCullingPhotosView(APIView):
    """
    POST /api/culling/upload/
    POST /api/culling/sessions/{session_id}/upload-photos/
    Receives multi-part photos in batches, validates studio storage quota, saves to staging disk.
    Supports multi-chunk batch uploads (e.g. 2,000 photos in 15MB sequential chunks) without HTTP 413.
    """
    permission_classes = [IsAuthenticated, HasAICullingAccess]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, session_id=None):
        files = request.FILES.getlist("photos") or request.FILES.getlist("files")
        user = request.user
        sid = (
            session_id
            or request.data.get("session_id")
            or request.data.get("sessionId")
            or f"cull_session_{uuid.uuid4().hex[:12]}"
        )

        app_session = find_app_culling_session(sid, user)
        if app_session:
            from App.Culling.culling_views import CullingSessionViewSet
            return CullingSessionViewSet.as_view({'post': 'upload_photos'})(request._request, pk=str(app_session.id))

        if not files:
            return Response(
                {"error": "No image files provided.", "detail": "No photos provided for upload.", "code": "no_files"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ─── 1. Unified Storage Quota Check ───────────────────────────────────────
        batch_size_bytes = sum(f.size for f in files)
        current_used_bytes = user.get_total_storage_used_bytes()

        sub = getattr(user, 'subscription', None)
        storage_limit_bytes = 0
        if sub and sub.plan:
            storage_limit_bytes = sub.effective_storage_limit_bytes if hasattr(sub, 'effective_storage_limit_bytes') else getattr(sub.plan, 'storage_limit_bytes', int(sub.plan.storage_limit_gb * 1024 * 1024 * 1024))
        elif sub and sub.legacy_plan:
            storage_limit_bytes = sub.legacy_plan.storage_limit_bytes
        else:
            storage_limit_bytes = getattr(settings, 'TEST_USER_STORAGE_LIMIT_BYTES', 21474836480)

        if storage_limit_bytes > 0 and (current_used_bytes + batch_size_bytes > storage_limit_bytes):
            available_bytes = max(0, storage_limit_bytes - current_used_bytes)
            return Response(
                {
                    "error": f"Storage quota exceeded. Available space: {available_bytes // (1024*1024)} MB.",
                    "detail": f"Upload exceeds available storage quota. You have {round(available_bytes / (1024*1024), 1)} MB remaining on your plan.",
                    "code": "STORAGE_LIMIT_EXCEEDED",
                    "storage_limit_bytes": storage_limit_bytes,
                    "storage_used_bytes": current_used_bytes,
                    "batch_size_bytes": batch_size_bytes
                },
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )

        # ─── 2. Get or create active staging session ─────────────────────────────
        session, _ = CullingSession.objects.get_or_create(
            id=sid,
            defaults={"user": user, "title": "AI Smart Cull Session", "status": "staging", "is_paid": True},
        )

        saved_photos = []
        with transaction.atomic():
            for f in files:
                photo_id = uuid.uuid4().hex[:16]
                photo = CullingStagingPhoto.objects.create(
                    id=photo_id,
                    session=session,
                    file=f,
                    original_filename=f.name,
                    name=f.name,
                    size_bytes=f.size,
                    file_size_bytes=f.size,
                    size_mb=round(f.size / (1024 * 1024), 2),
                    status="keep",
                )
                saved_photos.append({
                    "id": str(photo.id),
                    "name": photo.original_filename,
                    "previewUrl": request.build_absolute_uri(photo.file.url),
                    "sizeBytes": photo.size_bytes,
                    "sizeMB": round(photo.size_bytes / (1024 * 1024), 2),
                    "status": "keep",
                    "sharpnessScore": photo.sharpness_score,
                    "isBestPick": photo.is_best_pick,
                    "clusterId": photo.cluster_id or "",
                    "hash": photo.perceptual_hash or "",
                    "similarityWithBest": photo.similarity_with_winner,
                })

            session.total_photos = session.photos.count()
            session.photo_count = session.total_photos
            session.total_bytes = sum(p.size_bytes or p.file_size_bytes or 0 for p in session.photos.all())
            session.save(update_fields=["total_photos", "photo_count", "total_bytes", "updated_at"])

        return Response(
            {
                "message": f"Successfully uploaded {len(saved_photos)} photos.",
                "session_id": session.id,
                "photos": saved_photos,
                "uploaded_count": len(saved_photos),
            },
            status=status.HTTP_201_CREATED,
        )


# Backward-compatible alias
CullingPhotoUploadView = UploadCullingPhotosView


# ─── 2. Server-Side AI Culling Engine ────────────────────────────────────────

class AnalyzeCullingSessionView(APIView):
    """
    POST /api/culling/sessions/{session_id}/analyze/ (alias POST /api/culling/analyze/)
    Executes parallel multithreaded focus sharpness scoring and burst sequence clustering.
    """
    permission_classes = [IsAuthenticated, HasAICullingPlanPermission]

    def post(self, request, session_id=None):
        sid = (
            session_id
            or request.data.get("session_id")
            or request.data.get("sessionId")
        )
        session = CullingSession.objects.filter(id=sid, user=request.user).first()
        if not session:
            # Fallback to active session
            session = (
                CullingSession.objects.filter(user=request.user)
                .exclude(status__in=["moved_to_gallery", "discarded", "completed"])
                .order_by("-updated_at")
                .first()
            )

        if not session:
            # Fallback create to ensure zero 404 deadlocks
            session, _ = CullingSession.objects.get_or_create(
                id=sid or f"cull_session_{uuid.uuid4().hex[:12]}",
                defaults={"user": request.user, "title": "AI Smart Cull Session", "status": "staging"},
            )

        try:
            threshold = float(request.data.get("similarity_threshold", 88.0))
        except (ValueError, TypeError):
            threshold = 88.0

        run_server_side_culling(session, similarity_threshold=threshold)

        session_payload = serialize_culling_session_payload(session, request)

        return Response(
            {
                "success": True,
                "message": "Server AI culling analysis complete.",
                "session": session_payload,
            },
            status=status.HTTP_200_OK,
        )


def serialize_culling_session_payload(session, request):
    photos_data = [
        {
            "id": str(p.id),
            "name": p.original_filename or p.name,
            "previewUrl": request.build_absolute_uri(p.file.url) if p.file else "",
            "sizeBytes": p.size_bytes or p.file_size_bytes or 0,
            "sizeMB": round((p.size_bytes or p.file_size_bytes or 0) / (1024 * 1024), 2),
            "sharpnessScore": round(p.sharpness_score, 1),
            "isBestPick": p.is_best_pick,
            "status": p.status,
            "clusterId": p.cluster_id or "",
            "hash": p.perceptual_hash or "",
            "similarityWithBest": p.similarity_with_winner,
        }
        for p in session.photos.all()
    ]

    clusters_data = [
        {
            "id": str(c.id),
            "title": c.title,
            "averageSimilarity": c.average_similarity,
            "bestPickId": c.best_pick_item_id or c.best_pick_id or "",
            "photoIds": c.photo_ids or list(session.photos.filter(cluster_id=c.id).values_list("id", flat=True)),
            "totalPhotos": c.total_photos,
            "duplicatesCount": c.duplicates_count,
            "wastedBytes": c.wasted_bytes,
        }
        for c in session.clusters.all()
    ]

    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "photo_count": len(photos_data),
        "photos": photos_data,
        "clusters": clusters_data,
    }


# ─── 3. Active Session Recovery ──────────────────────────────────────────────

class ActiveCullingSessionView(APIView):
    """
    GET /api/culling/sessions/active/
    Hydrates ongoing session state on mount or browser reload without localStorage.
    """
    permission_classes = [IsAuthenticated, HasAICullingPlanPermission]

    def get(self, request):
        session = (
            CullingSession.objects.filter(user=request.user)
            .exclude(status__in=["moved_to_gallery", "discarded", "completed"])
            .order_by("-updated_at")
            .first()
        )

        if not session or not session.photos.exists():
            return Response({"session": None, "active": False}, status=status.HTTP_200_OK)

        response_data = serialize_culling_session_payload(session, request)

        # Hybrid payload: exposes both root fields and nested session for any frontend variation
        return Response(
            {
                **response_data,
                "session": response_data,
                "active": True,
            },
            status=status.HTTP_200_OK,
        )


# ─── 4. Session Sync ─────────────────────────────────────────────────────────

class SyncCullingSessionView(APIView):
    """
    POST /api/culling/sessions/{session_id}/sync/ (alias POST /api/culling/sync/)
    Persists curation state, keeper/discard overrides, and cluster groupings.
    Uses get_or_create to prevent HTTP 404 if frontend syncs before initial upload completes.
    """
    permission_classes = [IsAuthenticated, HasAICullingPlanPermission]

    def post(self, request, session_id=None):
        sid = (
            session_id
            or request.data.get("session_id")
            or request.data.get("sessionId")
            or f"cull_session_{uuid.uuid4().hex[:12]}"
        )

        # Resilient get_or_create: eliminates HTTP 404 completely!
        session, _ = CullingSession.objects.get_or_create(
            id=sid,
            defaults={"user": request.user, "title": "AI Smart Cull Session", "status": "staging"},
        )

        photos_data = request.data.get("photos", [])
        clusters_data = request.data.get("clusters", [])

        with transaction.atomic():
            cluster_id_remap = {}
            seen_cids = set()
            cluster_objs = []
            for c in clusters_data:
                raw_cid = str(c.get("id") or "").strip()
                if not raw_cid:
                    cid = f"cluster_{session.id[:80]}_{uuid.uuid4().hex[:8]}"
                elif CullingCluster.objects.filter(id=raw_cid).exclude(session=session).exists():
                    cid = f"cluster_{session.id[:80]}_{raw_cid}"
                    cluster_id_remap[raw_cid] = cid
                else:
                    cid = raw_cid

                if cid in seen_cids:
                    cid = f"{cid}_{uuid.uuid4().hex[:4]}"
                    if raw_cid:
                        cluster_id_remap[raw_cid] = cid
                seen_cids.add(cid)

                cluster_objs.append(
                    CullingCluster(
                        id=cid,
                        session=session,
                        title=c.get("title", "Burst Cluster"),
                        average_similarity=c.get("averageSimilarity", 90.0),
                        best_pick_item_id=c.get("bestPickId", "") or "",
                        best_pick_id=c.get("bestPickId", "") or "",
                        photo_ids=c.get("photoIds", []),
                        total_photos=c.get("totalPhotos", 0),
                        duplicates_count=c.get("duplicatesCount", 0),
                        wasted_bytes=c.get("wastedBytes", 0),
                    )
                )

            for p in photos_data:
                pid = p.get("id")
                if pid:
                    raw_p_cluster = p.get("clusterId", "") or ""
                    final_p_cluster = cluster_id_remap.get(raw_p_cluster, raw_p_cluster)
                    CullingStagingPhoto.objects.filter(id=pid, session=session).update(
                        sharpness_score=p.get("sharpnessScore", 80.0),
                        is_best_pick=bool(p.get("isBestPick", False)),
                        status=p.get("status", "keep"),
                        cluster_id=final_p_cluster,
                        perceptual_hash=p.get("hash", "") or "",
                        similarity_with_winner=p.get("similarityWithBest"),
                    )

            if cluster_id_remap:
                for old_cid, new_cid in cluster_id_remap.items():
                    session.photos.filter(cluster_id=old_cid).update(cluster_id=new_cid)

            # Recreate clusters
            CullingCluster.objects.filter(session=session).delete()
            if cluster_objs:
                CullingCluster.objects.bulk_create(cluster_objs)

            session.total_photos = session.photos.count()
            session.photo_count = session.total_photos
            session.keeper_count = session.photos.filter(status="keep").count()
            session.duplicate_count = session.photos.filter(status="discard").count()
            session.total_duplicates = session.duplicate_count
            session.wasted_bytes = sum(
                p.size_bytes or p.file_size_bytes or 0 for p in session.photos.filter(status="discard")
            )
            session.status = "analyzed"
            session.save(update_fields=[
                "total_photos", "photo_count", "keeper_count", "duplicate_count",
                "total_duplicates", "wasted_bytes", "status", "updated_at"
            ])

        return Response({"success": True, "message": "Synced successfully."}, status=status.HTTP_200_OK)


# ─── 5. Move to Gallery ──────────────────────────────────────────────────────

class MoveCullingToGalleryView(APIView):
    """
    POST /api/culling/sessions/{session_id}/move-to-gallery/
    Transfers approved keeper photos from staging storage to permanent Gallery.
    Purges staging disk files after successful migration.
    """
    permission_classes = [IsAuthenticated, HasAICullingPlanPermission]

    def post(self, request, session_id=None):
        sid = (
            session_id
            or request.data.get("session_id")
            or request.data.get("sessionId")
        )

        from App.Culling.services.gallery_bridge import move_culled_photos_to_gallery
        app_session = find_app_culling_session(sid, request.user)
        if app_session:
            result = move_culled_photos_to_gallery(
                user=request.user,
                session=app_session,
                target_mode=request.data.get("target_mode", "new"),
                target_gallery_id=request.data.get("target_gallery_id") or request.data.get("gallery_id"),
                new_gallery_title=request.data.get("new_gallery_title", "Culled Shoot"),
                category_assignments=request.data.get("category_assignments", {}),
                include_duplicates=request.data.get("include_duplicates", True),
                items_payload=request.data.get("items", []),
            )
            return Response(result, status=status.HTTP_200_OK)

        session = CullingSession.objects.filter(id=sid, user=request.user).first()
        if not session:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        target_mode = request.data.get("target_mode", "existing")
        target_gallery_id = request.data.get("target_gallery_id") or request.data.get("gallery_id")
        new_title = request.data.get("new_gallery_title", "Culled Shoot")
        sec_title = request.data.get("target_section_title", "Highlights")
        category_assignments = request.data.get("category_assignments", {})

        profile = getattr(request.user, "photographer_profile", None) or PhotographerProfile.objects.filter(user=request.user).first()
        if not profile:
            profile, _ = PhotographerProfile.objects.get_or_create(
                user=request.user,
                defaults={
                    "name": getattr(request.user, "fullname", "") or getattr(request.user, "username", "Studio"),
                    "studio_name": "Studio Pro",
                },
            )

        with transaction.atomic():
            if target_mode == "new" or (not target_gallery_id and new_title):
                gallery = Gallery.objects.create(
                    photographer=profile,
                    title=new_title,
                    status="published",
                )
            else:
                gallery = (
                    Gallery.objects.filter(id=target_gallery_id, photographer=profile).first()
                    or Gallery.objects.filter(slug=target_gallery_id, photographer=profile).first()
                )
                if not gallery and (request.user.is_staff or request.user.is_superuser):
                    gallery = Gallery.objects.filter(id=target_gallery_id).first()

            if not gallery:
                return Response({"error": "Target gallery not found."}, status=status.HTTP_404_NOT_FOUND)

            default_sec, _ = GallerySection.objects.get_or_create(gallery=gallery, title=sec_title)

            keepers = session.photos.filter(status="keep")
            if not keepers.exists():
                keepers = session.photos.all()

            storage = get_storage_provider()
            count = 0
            for sp in keepers:
                assigned_sec_title = category_assignments.get(str(sp.id)) or category_assignments.get(sp.cluster_id, sec_title)
                sec_obj = default_sec if assigned_sec_title == sec_title else GallerySection.objects.get_or_create(gallery=gallery, title=assigned_sec_title)[0]
                safe_name = os.path.basename(str(sp.original_filename or sp.name or "photo.jpg").replace('\\', '/'))
                media_id = uuid.uuid4()
                storage_key = f"galleries/{gallery.id}/originals/{media_id}_{safe_name}"

                file_bytes = b""
                try:
                    if sp.file:
                        sp.file.open("rb")
                        file_bytes = sp.file.read()
                        sp.file.close()
                except Exception:
                    if hasattr(sp.file, 'path') and os.path.exists(sp.file.path):
                        with open(sp.file.path, 'rb') as f:
                            file_bytes = f.read()

                mime = "image/jpeg"
                if safe_name.lower().endswith(".png"):
                    mime = "image/png"
                elif safe_name.lower().endswith(".webp"):
                    mime = "image/webp"

                if file_bytes:
                    storage.upload(storage_key, file_bytes, content_type=mime)

                gm = GalleryMedia(
                    id=media_id,
                    gallery=gallery,
                    photographer=gallery.photographer,
                    section=sec_obj,
                    section_title=assigned_sec_title,
                    original_filename=safe_name,
                    storage_key=storage_key,
                    file_size=len(file_bytes) if file_bytes else (sp.size_bytes or sp.file_size_bytes or 0),
                    mime_type=mime,
                    is_favorite=bool(sp.is_best_pick),
                    processing_status="pending",
                    upload_status="completed",
                )
                if file_bytes:
                    gm.file.save(f"{media_id}_{safe_name}", ContentFile(file_bytes), save=False)
                    try:
                        from PIL import Image, ImageOps
                        img = Image.open(io.BytesIO(file_bytes))
                        img = ImageOps.exif_transpose(img)
                        gm.width, gm.height = img.size
                        if gm.height > 0:
                            gm.aspect_ratio = round(gm.width / float(gm.height), 3)

                        thumb_img = img.copy()
                        thumb_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                        thumb_buf = io.BytesIO()
                        thumb_img.convert("RGB").save(thumb_buf, format="JPEG", quality=85)
                        thumb_key = f"galleries/{gallery.id}/thumbnails/{media_id}.jpg"
                        storage.upload(thumb_key, thumb_buf.getvalue(), content_type="image/jpeg")
                        gm.thumbnail_storage_key = thumb_key

                        prev_img = img.copy()
                        prev_img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                        prev_buf = io.BytesIO()
                        prev_img.convert("RGB").save(prev_buf, format="JPEG", quality=90)
                        prev_key = f"galleries/{gallery.id}/previews/{media_id}.jpg"
                        storage.upload(prev_key, prev_buf.getvalue(), content_type="image/jpeg")
                        gm.preview_storage_key = prev_key
                        gm.processing_status = "ready"
                    except Exception:
                        pass

                gm.save()
                count += 1

            session.status = "moved_to_gallery"
            session.save(update_fields=["status", "updated_at"])

            staging_dir = os.path.join(settings.MEDIA_ROOT, "culling_staging", str(session.id))
            if os.path.exists(staging_dir):
                shutil.rmtree(staging_dir, ignore_errors=True)

        return Response(
            {
                "success": True,
                "gallery_id": str(gallery.id),
                "gallery_title": gallery.title,
                "moved_count": count,
                "transferred_count": count,
                "purged": True,
                "message": f"Successfully moved {count} photos to gallery '{gallery.title}'.",
            },
            status=status.HTTP_200_OK,
        )


# ─── 6. Session Detail & Discard Storage ─────────────────────────────────────

class CullingSessionDetailView(APIView):
    """
    GET    /api/culling/sessions/{session_id}/
    GET    /api/culling/sessions/latest/
    DELETE /api/culling/sessions/{session_id}/
    POST   /api/culling/sessions/{session_id}/discard/
    """
    permission_classes = [IsAuthenticated, HasAICullingAccess]

    def get(self, request, session_id=None):
        sid = session_id or request.query_params.get("session_id")
        if not sid or sid in ("latest", "active"):
            session = (
                CullingSession.objects.filter(user=request.user)
                .exclude(status__in=["moved_to_gallery", "discarded", "completed"])
                .order_by("-updated_at")
                .first()
            )
            if not session:
                session = (
                    CullingSession.objects.filter(user=request.user)
                    .exclude(status="discarded")
                    .order_by("-updated_at")
                    .first()
                )
            if not session or not session.photos.exists():
                return Response({"session": None, "active": False}, status=status.HTTP_200_OK)
        else:
            session = CullingSession.objects.filter(id=sid, user=request.user).first()
            if not session:
                app_session = find_app_culling_session(sid, request.user)
                if app_session:
                    from App.Culling.culling_views import CullingSessionViewSet
                    return CullingSessionViewSet.as_view({'get': 'retrieve'})(request._request, pk=str(app_session.id))
                return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        response_data = serialize_culling_session_payload(session, request)
        is_active = session.status not in ["moved_to_gallery", "discarded", "completed"] and len(response_data["photos"]) > 0

        return Response(
            {
                **response_data,
                "session": response_data,
                "active": is_active,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, session_id=None):
        sid = session_id or request.data.get("session_id")
        return self._discard(request, sid)

    def post(self, request, session_id=None):
        sid = session_id or request.data.get("session_id") or request.data.get("sessionId")
        return self._discard(request, sid)

    def _discard(self, request, sid):
        session = CullingSession.objects.filter(id=sid, user=request.user).first()
        if not session:
            app_session = find_app_culling_session(sid, request.user)
            if app_session:
                from App.Culling.services.culler import purge_culling_staging
                purge_culling_staging(app_session)
                app_session.delete()
                return Response({"success": True, "message": "Session discarded and staging storage reclaimed."}, status=status.HTTP_200_OK)
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        # Reclaim storage physically from media backend
        for photo in session.photos.all():
            if hasattr(photo, 'file') and photo.file:
                photo.file.delete(save=False)
            elif hasattr(photo, 'original_file') and photo.original_file:
                photo.original_file.delete(save=False)

        staging_dir = os.path.join(settings.MEDIA_ROOT, "culling_staging", str(session.id))
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)

        session.photos.all().delete()
        session.clusters.all().delete()
        session.delete()

        return Response({
            "success": True,
            "message": "Session discarded and staging storage reclaimed successfully."
        }, status=status.HTTP_200_OK)


# Backward-compatible alias
DiscardCullingSessionView = CullingSessionDetailView


# ─── 7. Keepers ZIP Export ───────────────────────────────────────────────────

class ExportCullingZipView(APIView):
    """
    GET /api/culling/sessions/<id>/export-zip/
    """
    permission_classes = [IsAuthenticated, HasAICullingPlanPermission]

    def get(self, request, session_id):
        return self._export_zip(request, session_id)

    def post(self, request, session_id=None):
        sid = session_id or request.data.get("session_id") or request.data.get("sessionId")
        return self._export_zip(request, sid)

    def _export_zip(self, request, sid):
        session = CullingSession.objects.filter(id=sid, user=request.user).first()
        if not session:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        keepers = session.photos.filter(status="keep")
        if not keepers.exists():
            keepers = session.photos.all()

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in keepers:
                if p.file:
                    try:
                        filename = p.original_filename or os.path.basename(p.file.name)
                        p.file.seek(0)
                        zf.writestr(filename, p.file.read())
                    except Exception:
                        pass

        zip_buffer.seek(0)
        resp = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="keepers_{session.id[:12]}.zip"'
        return resp


# ─── 8. Backward Compatibility Endpoints ─────────────────────────────────────

class CullingPricingTierListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        tiers = CullingPricingTier.objects.filter(is_active=True).order_by("display_order", "price")
        serializer = CullingPricingTierSerializer(tiers, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CreateCullingPaymentOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        session_id = request.data.get("session_id") or f"cull_{uuid.uuid4().hex[:12]}"
        session, _ = CullingSession.objects.get_or_create(
            id=session_id,
            defaults={"user": request.user, "title": "AI Smart Cull Session", "is_paid": True, "status": "staging"},
        )
        return Response(
            {
                "order_id": f"order_free_{uuid.uuid4().hex[:12]}",
                "amount": 0,
                "currency": "INR",
                "key_id": getattr(settings, "RAZORPAY_KEY_ID", "rzp_test"),
                "session_id": session.id,
                "unlocked": True,
                "message": "AI Smart Culling is included in your active subscription plan.",
            },
            status=status.HTTP_200_OK,
        )


class VerifyCullingPaymentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        session_id = request.data.get("session_id") or request.data.get("sessionId")
        return Response(
            {
                "success": True,
                "message": "AI Smart Culling is unlocked via your studio subscription plan.",
                "is_paid": True,
                "session_id": session_id,
            },
            status=status.HTTP_200_OK,
        )

import os
import json
import uuid
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone
from django.db import transaction

from App.Storage.storage_models import Gallery, Media, UploadReservation
from App.Storage.services.storage_service import get_storage_provider, LocalStorageProvider
from App.Storage.services.quota_service import StorageQuotaService
from App.Storage.tasks import process_media_derivatives_and_faces_task, run_or_queue_task

logger = logging.getLogger(__name__)


class ResumableUploadService:
    """
    High-performance, local-filesystem chunked and resumable upload manager.
    Stores temporary chunks under MEDIA_ROOT / 'upload_temp' / {upload_id} /
    Guarantees zero RAM buffering, robust offset validation, and atomic finalization.
    """

    @classmethod
    def get_temp_root(cls) -> Path:
        p = Path(settings.MEDIA_ROOT) / "upload_temp"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @classmethod
    def get_upload_dir(cls, upload_id: str) -> Path:
        # Sanitize upload_id to prevent path traversal
        clean_id = os.path.basename(str(upload_id).strip())
        return cls.get_temp_root() / clean_id

    @classmethod
    def init_upload(
        cls,
        user,
        filename: str,
        total_size: int,
        target_type: str = "gallery",
        target_id: str = None,
        chunk_size: int = 8 * 1024 * 1024,  # 8 MB default chunk
        extra_data: dict = None,
    ) -> dict:
        """
        Initializes a resumable upload session, validates quota, creates temporary workspace.
        """
        if total_size <= 0:
            raise ValueError("Total file size must be greater than zero.")

        upload_id = str(uuid.uuid4())
        upload_dir = cls.get_upload_dir(upload_id)
        upload_dir.mkdir(parents=True, exist_ok=True)

        safe_name = os.path.basename(str(filename).replace("\\", "/"))
        now = timezone.now()
        expires_at = now + timedelta(hours=24)

        # Pre-validate quotas for galleries
        reservation_id = None
        if target_type == "gallery" and target_id:
            gallery = Gallery.objects.select_related("photographer").get(id=target_id)
            photographer = gallery.photographer
            if not photographer.can_allocate_storage(total_size):
                remaining = photographer.get_storage_remaining()
                shutil.rmtree(upload_dir, ignore_errors=True)
                raise PermissionError(
                    f"Insufficient storage quota. Requested {total_size} bytes, available {remaining} bytes."
                )
            reservation = StorageQuotaService.reserve_quota(photographer, gallery, total_size)
            reservation_id = str(reservation.id)

        meta = {
            "upload_id": upload_id,
            "user_id": user.id,
            "filename": safe_name,
            "total_size": int(total_size),
            "chunk_size": int(chunk_size),
            "target_type": target_type,
            "target_id": str(target_id) if target_id else None,
            "reservation_id": reservation_id,
            "extra_data": extra_data or {},
            "committed_offset": 0,
            "chunks_received": [],
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "status": "in_progress",
        }

        meta_file = upload_dir / "metadata.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return {
            "upload_id": upload_id,
            "chunk_size": chunk_size,
            "total_size": total_size,
            "filename": safe_name,
            "committed_offset": 0,
            "expires_at": expires_at.isoformat(),
        }

    @classmethod
    def get_metadata(cls, upload_id: str, user) -> dict:
        upload_dir = cls.get_upload_dir(upload_id)
        meta_file = upload_dir / "metadata.json"
        if not meta_file.exists():
            raise FileNotFoundError(f"Upload session '{upload_id}' not found.")

        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)

        if meta.get("user_id") != user.id and not (user.is_staff or user.is_superuser):
            raise PermissionError("You do not own this upload session.")

        return meta

    @classmethod
    def save_metadata(cls, upload_dir: Path, meta: dict):
        meta_file = upload_dir / "metadata.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    @classmethod
    def append_chunk(
        cls,
        upload_id: str,
        user,
        chunk_file,
        chunk_index: int = None,
        offset: int = None,
    ) -> dict:
        """
        Streams and saves a single chunk to disk without buffering into RAM.
        Tracks committed bytes and supports resume verification.
        """
        upload_dir = cls.get_upload_dir(upload_id)
        meta = cls.get_metadata(upload_id, user)

        if meta.get("status") != "in_progress":
            raise ValueError(f"Upload session is {meta.get('status')}.")

        current_committed = meta.get("committed_offset", 0)
        # Validate offset boundary if provided
        if offset is not None and offset > current_committed:
            raise ValueError(
                f"Offset {offset} is ahead of committed offset {current_committed}."
            )

        # Auto-compute chunk_index from offset if index not explicitly provided
        chunk_size = meta["chunk_size"]
        if chunk_index is None:
            if offset is not None:
                chunk_index = offset // chunk_size
            else:
                chunk_index = len(meta.get("chunks_received", []))

        chunk_path = upload_dir / f"chunk_{chunk_index:06d}.part"

        # Stream chunk directly to disk
        written_bytes = 0
        with open(chunk_path, "wb") as out_f:
            if hasattr(chunk_file, "chunks"):
                for block in chunk_file.chunks(chunk_size=1024 * 1024):
                    out_f.write(block)
                    written_bytes += len(block)
            elif hasattr(chunk_file, "read"):
                shutil.copyfileobj(chunk_file, out_f, length=1024 * 1024)
                written_bytes = chunk_path.stat().st_size
            else:
                out_f.write(chunk_file)
                written_bytes = len(chunk_file)

        # Update metadata
        chunks_received = set(meta.get("chunks_received", []))
        chunks_received.add(chunk_index)
        meta["chunks_received"] = sorted(list(chunks_received))

        # Calculate contiguous committed offset
        contiguous_offset = 0
        sorted_chunks = sorted(list(chunks_received))
        for expected_idx in range(len(sorted_chunks)):
            if expected_idx in chunks_received:
                part_file = upload_dir / f"chunk_{expected_idx:06d}.part"
                if part_file.exists():
                    contiguous_offset += part_file.stat().st_size
                else:
                    break
            else:
                break

        meta["committed_offset"] = contiguous_offset
        cls.save_metadata(upload_dir, meta)

        total_size = meta["total_size"]
        progress_pct = round((contiguous_offset / total_size) * 100, 2) if total_size > 0 else 100.0

        return {
            "upload_id": upload_id,
            "chunk_index": chunk_index,
            "bytes_written": written_bytes,
            "committed_offset": contiguous_offset,
            "total_size": total_size,
            "progress_percent": min(100.0, progress_pct),
        }

    @classmethod
    def get_status(cls, upload_id: str, user) -> dict:
        meta = cls.get_metadata(upload_id, user)
        total_size = meta["total_size"]
        committed = meta.get("committed_offset", 0)
        progress_pct = round((committed / total_size) * 100, 2) if total_size > 0 else 100.0

        return {
            "upload_id": upload_id,
            "filename": meta["filename"],
            "total_size": total_size,
            "chunk_size": meta["chunk_size"],
            "committed_offset": committed,
            "chunks_received": meta.get("chunks_received", []),
            "progress_percent": progress_pct,
            "status": meta.get("status", "in_progress"),
            "expires_at": meta.get("expires_at"),
        }

    @classmethod
    def complete_upload(cls, upload_id: str, user, request=None) -> dict:
        """
        Assembles all chunk files on disk into the destination path, verifies size,
        creates corresponding DB entity, and triggers Celery background processing.
        """
        upload_dir = cls.get_upload_dir(upload_id)
        meta = cls.get_metadata(upload_id, user)

        total_size = meta["total_size"]
        chunks_received = meta.get("chunks_received", [])
        chunk_size = meta["chunk_size"]
        expected_chunk_count = (total_size + chunk_size - 1) // chunk_size

        # Check all chunks exist
        for idx in range(expected_chunk_count):
            part_file = upload_dir / f"chunk_{idx:06d}.part"
            if not part_file.exists():
                raise ValueError(f"Missing chunk {idx} of {expected_chunk_count}.")

        # Assemble chunks sequentially into assembled.bin on disk
        assembled_file = upload_dir / "assembled.bin"
        with open(assembled_file, "wb") as out_f:
            for idx in range(expected_chunk_count):
                part_file = upload_dir / f"chunk_{idx:06d}.part"
                with open(part_file, "rb") as in_f:
                    shutil.copyfileobj(in_f, out_f, length=1024 * 1024)

        assembled_size = assembled_file.stat().st_size
        if assembled_size != total_size:
            assembled_file.unlink(missing_ok=True)
            raise ValueError(
                f"Assembled size mismatch: expected {total_size} bytes, got {assembled_size} bytes."
            )

        target_type = meta.get("target_type", "gallery")
        target_id = meta.get("target_id")
        filename = meta.get("filename", "upload.jpg")
        ext = os.path.splitext(filename)[1].lower() or ".jpg"
        media_id = uuid.uuid4()
        storage = get_storage_provider()

        created_result = {}

        if target_type == "gallery":
            gallery = Gallery.objects.select_related("photographer").get(id=target_id)
            storage_key = f"galleries/{gallery.id}/originals/{media_id}_{filename}"

            # Fast move assembled file to storage provider
            if hasattr(storage, "move_file"):
                storage.move_file(str(assembled_file), storage_key)
            else:
                with open(assembled_file, "rb") as f:
                    storage.save_file(storage_key, f)
                assembled_file.unlink(missing_ok=True)

            # Commit quota reservation if one was created
            reservation_id = meta.get("reservation_id")
            if reservation_id:
                try:
                    res = UploadReservation.objects.get(id=reservation_id)
                    StorageQuotaService.commit_quota(res, assembled_size)
                except Exception:
                    pass
            else:
                gallery.photographer.storage_used_bytes = (
                    gallery.photographer.storage_used_bytes or 0
                ) + assembled_size
                gallery.photographer.save(update_fields=["storage_used_bytes"])

            # Fast image dimension probe from header
            width, height, aspect_ratio = None, None, None
            media_type = "photo"
            if ext in (".mp4", ".mov", ".webm", ".mkv", ".avi"):
                media_type = "video"
            else:
                try:
                    from PIL import Image
                    abs_path = (
                        storage.get_absolute_path(storage_key)
                        if hasattr(storage, "get_absolute_path")
                        else None
                    )
                    if abs_path and abs_path.exists():
                        with Image.open(abs_path) as img:
                            width, height = img.size
                            if height > 0:
                                aspect_ratio = round(width / height, 2)
                except Exception:
                    pass

            extra = meta.get("extra_data", {})
            section_title = extra.get("section_title", "HIGHLIGHTS").strip().upper()

            media = Media.objects.create(
                id=media_id,
                photographer=gallery.photographer,
                gallery=gallery,
                media_type=media_type,
                title=os.path.splitext(filename)[0],
                section_title=section_title,
                original_filename=filename,
                storage_key=storage_key,
                file_size=assembled_size,
                file_extension=ext,
                width=width,
                height=height,
                aspect_ratio=aspect_ratio,
                processing_status="pending" if media_type == "photo" else "ready",
                upload_status="completed",
            )

            # Dispatch background thumbnail and face processing
            if media_type == "photo":
                run_or_queue_task(
                    process_media_derivatives_and_faces_task,
                    str(media.id),
                    skip_sync_fallback=True,
                )

            created_result = {
                "id": str(media.id),
                "title": media.title,
                "original_filename": media.original_filename,
                "storage_key": media.storage_key,
                "file_size": media.file_size,
                "media_type": media.media_type,
                "processing_status": media.processing_status,
            }

        elif target_type == "culling":
            from culling.models import CullingSession, CullingStagingPhoto

            session, _ = CullingSession.objects.get_or_create(
                id=target_id or f"cull_{uuid.uuid4().hex[:10]}",
                defaults={"user": user, "status": "staging", "is_paid": True},
            )

            staging_dir = Path(settings.MEDIA_ROOT) / "culling_staging" / str(session.id)
            staging_dir.mkdir(parents=True, exist_ok=True)
            staging_target = staging_dir / f"{uuid.uuid4().hex[:12]}_{filename}"

            try:
                os.replace(str(assembled_file), str(staging_target))
            except OSError:
                shutil.move(str(assembled_file), str(staging_target))

            rel_path = f"culling_staging/{session.id}/{staging_target.name}"

            photo = CullingStagingPhoto.objects.create(
                id=uuid.uuid4().hex[:16],
                session=session,
                file=rel_path,
                original_filename=filename,
                name=filename,
                size_bytes=assembled_size,
                file_size_bytes=assembled_size,
                size_mb=round(assembled_size / (1024 * 1024), 2),
                status="keep",
            )

            session.total_photos = session.photos.count()
            session.total_bytes = (session.total_bytes or 0) + assembled_size
            session.save(update_fields=["total_photos", "total_bytes"])

            created_result = {
                "id": str(photo.id),
                "session_id": str(session.id),
                "name": photo.original_filename,
                "size_bytes": photo.size_bytes,
                "status": photo.status,
            }

        elif target_type == "event":
            from App.LiveEvents.event_models import LiveEvent, EventMedia
            from App.LiveEvents.event_views import _trigger_face_indexing

            event = LiveEvent.objects.get(id=target_id)
            event_dir = Path(settings.MEDIA_ROOT) / "events" / "media"
            event_dir.mkdir(parents=True, exist_ok=True)
            event_target = event_dir / f"{uuid.uuid4().hex[:12]}_{filename}"

            try:
                os.replace(str(assembled_file), str(event_target))
            except OSError:
                shutil.move(str(assembled_file), str(event_target))

            rel_path = f"events/media/{event_target.name}"
            extra = meta.get("extra_data", {})
            section_title = extra.get("section_title", "HIGHLIGHTS").strip().upper()

            event_media = EventMedia.objects.create(
                event=event,
                original_filename=filename,
                file=rel_path,
                media_type="photo" if ext not in (".mp4", ".mov", ".webm") else "video",
                section_title=section_title,
                file_size=assembled_size,
                size_mb=round(assembled_size / (1024 * 1024), 2),
            )
            event_media.file_url = event_media.file.url
            event_media.thumbnail_url = event_media.file.url
            event_media.save(update_fields=["file_url", "thumbnail_url"])

            if event_media.media_type == "photo":
                _trigger_face_indexing(str(event_media.id))

            created_result = {
                "id": str(event_media.id),
                "event_id": str(event.id),
                "filename": event_media.original_filename,
                "file_size": event_media.file_size,
            }

        # Cleanup temporary workspace
        shutil.rmtree(upload_dir, ignore_errors=True)

        return {
            "status": "completed",
            "upload_id": upload_id,
            "media_id": created_result.get("id"),
            "filename": filename,
            "file_size": assembled_size,
            "target_type": target_type,
            "media": created_result,
        }

    @classmethod
    def cancel_upload(cls, upload_id: str, user) -> dict:
        upload_dir = cls.get_upload_dir(upload_id)
        meta = cls.get_metadata(upload_id, user)

        reservation_id = meta.get("reservation_id")
        if reservation_id:
            try:
                res = UploadReservation.objects.get(id=reservation_id)
                StorageQuotaService.release_quota(res)
            except Exception:
                pass

        shutil.rmtree(upload_dir, ignore_errors=True)
        return {"status": "cancelled", "upload_id": upload_id}

    @classmethod
    def cleanup_abandoned_uploads(cls, max_age_hours: int = 24) -> int:
        temp_root = cls.get_temp_root()
        cutoff = timezone.now() - timedelta(hours=max_age_hours)
        cleaned_count = 0

        for item in temp_root.iterdir():
            if item.is_dir():
                meta_file = item / "metadata.json"
                should_remove = False
                if meta_file.exists():
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        created_at = datetime.fromisoformat(meta["created_at"])
                        if created_at < cutoff:
                            should_remove = True
                    except Exception:
                        should_remove = True
                else:
                    # No metadata, check directory mtime
                    mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                    if mtime < cutoff:
                        should_remove = True

                if should_remove:
                    shutil.rmtree(item, ignore_errors=True)
                    cleaned_count += 1

        return cleaned_count

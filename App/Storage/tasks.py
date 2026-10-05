import io
import os
import zipfile
from datetime import timedelta
from PIL import Image, ImageOps
from django.utils import timezone
from celery import shared_task

from App.Storage.storage_models import Media, Gallery, BulkDownloadJob, UploadReservation
from App.Storage.services.storage_service import get_storage_provider
from App.Storage.services.face_service import FaceService
from App.Storage.services.watermark_service import WatermarkService
from utils.watermark import stamp_watermark_on_image


def run_or_queue_task(task_func, *args, **kwargs):
    """
    Executes task asynchronously via Celery if available, or falls back to
    immediate synchronous execution if Celery broker is unavailable.
    """
    skip_sync = kwargs.pop('skip_sync_fallback', False)
    try:
        return task_func.delay(*args, **kwargs)
    except Exception:
        if skip_sync:
            return None
        # Fallback to direct synchronous execution
        return task_func(*args, **kwargs)



@shared_task
def process_media_derivatives_and_faces_task(media_id_str: str):
    """
    Generates preview/thumbnail derivatives, applies studio watermarking,
    and detects face embeddings asynchronously.
    """
    try:
        media = Media.objects.select_related('photographer', 'gallery').get(id=media_id_str)
    except Media.DoesNotExist:
        return

    media.processing_status = "processing"
    media.save(update_fields=["processing_status"])

    storage = get_storage_provider()

    try:
        data = storage.download(media.storage_key)

        if media.media_type == 'video':
            # For video assets, assign default duration and dimensions if not provided
            if not media.duration:
                media.duration = "02:30"
            media.processing_status = "ready"
            media.save()
            return

        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)

        # Record dimensions & aspect ratio
        media.width, media.height = img.size
        if media.height > 0:
            media.aspect_ratio = round(media.width / float(media.height), 3)

        # 1. Generate Thumbnail (max 300x300 px)
        thumb_img = img.copy()
        thumb_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
        thumb_buf = io.BytesIO()
        thumb_img.convert("RGB").save(thumb_buf, format="JPEG", quality=85)
        thumb_key = f"galleries/{media.gallery_id}/thumbnails/{media.id}.jpg"
        storage.upload(thumb_key, thumb_buf.getvalue(), content_type="image/jpeg")
        media.thumbnail_storage_key = thumb_key

        # 2. Generate Preview (max 1200x1200 px) & Apply Watermark if enabled
        prev_img = img.copy()
        prev_img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)

        # Apply studio typography or PNG logo watermark if configured
        if getattr(media.photographer, 'enable_watermark', False):
            prev_img = WatermarkService.apply_watermark(prev_img, media.photographer)

        prev_buf = io.BytesIO()
        prev_img.convert("RGB").save(prev_buf, format="JPEG", quality=90)
        prev_key = f"galleries/{media.gallery_id}/previews/{media.id}.jpg"
        storage.upload(prev_key, prev_buf.getvalue(), content_type="image/jpeg")
        media.preview_storage_key = prev_key

        # 3. Detect and index faces if enabled for this gallery
        if getattr(media.gallery, 'face_search_enabled', True):
            FaceService.process_and_index_media_faces(media, data)

        media.processing_status = "ready"
        media.save()

    except Exception:
        media.processing_status = "failed"
        media.save(update_fields=["processing_status"])


@shared_task
def apply_watermark_to_preview_task(media_id_str: str):
    """Re-applies watermark to an existing preview image."""
    return process_media_derivatives_and_faces_task(media_id_str)


@shared_task
def generate_bulk_download_archive_task(job_id_str: str, photo_ids: list = None):
    """
    Compiles an asynchronous ZIP archive of master or selected gallery media.
    """
    try:
        job = BulkDownloadJob.objects.select_related("gallery").get(id=job_id_str)
    except BulkDownloadJob.DoesNotExist:
        return

    job.status = "processing"
    job.progress_percent = 5
    job.save(update_fields=["status", "progress_percent"])

    gallery = job.gallery
    photos_qs = Media.objects.filter(gallery=gallery, deleted_at__isnull=True)
    if photo_ids:
        photos_qs = photos_qs.filter(id__in=photo_ids)
        job.download_type = 'selected_subset'

    total_count = photos_qs.count()
    if total_count == 0:
        job.status = "failed"
        job.error_message = "No media files found to bundle."
        job.save(update_fields=["status", "error_message"])
        return

    storage = get_storage_provider()
    zip_buffer = io.BytesIO()

    try:
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
            used_filenames = set()
            processed_count = 0

            for media in photos_qs:
                try:
                    file_bytes = storage.download(media.storage_key)
                except Exception:
                    continue

                filename = media.original_filename or f"media_{media.id}.jpg"
                base, ext = os.path.splitext(filename)
                clean_name = filename
                counter = 1
                while clean_name in used_filenames:
                    clean_name = f"{base}_{counter}{ext}"
                    counter += 1
                used_filenames.add(clean_name)

                # Bake watermark if enabled on gallery
                if getattr(gallery, 'watermark_enabled', False) and getattr(media, 'media_type', 'photo') != 'video':
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
                    except Exception:
                        pass

                z.writestr(clean_name, file_bytes)
                processed_count += 1
                job.progress_percent = min(90, 5 + int((processed_count / total_count) * 85))
                job.save(update_fields=["progress_percent"])

        zip_bytes = zip_buffer.getvalue()
        archive_key = f"archives/{gallery.id}/{job.id}.zip"
        storage.upload(archive_key, zip_bytes, content_type="application/zip")

        job.status = "ready"
        job.progress_percent = 100
        job.archive_storage_key = archive_key
        job.selected_count = len(used_filenames)
        job.file_size = len(zip_bytes)
        job.expires_at = timezone.now() + timedelta(hours=24)
        job.save()

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        job.save(update_fields=["status", "error_message"])


@shared_task
def generate_selective_bulk_zip_task(job_id_str: str, media_ids: list):
    """Compiles a selective ZIP archive of only chosen favorites/proofs."""
    return generate_bulk_download_archive_task(job_id_str, photo_ids=media_ids)


@shared_task
def cleanup_expired_reservations_and_jobs_task():
    """
    Prunes expired upload reservations and temporary bulk download zip files.
    """
    now = timezone.now()

    # Expire pending upload reservations
    UploadReservation.objects.filter(status="pending", expires_at__lt=now).update(status="expired")

    # Prune expired download jobs
    expired_jobs = BulkDownloadJob.objects.filter(status="ready", expires_at__lt=now)
    storage = get_storage_provider()
    for j in expired_jobs:
        if j.archive_storage_key:
            try:
                storage.delete(j.archive_storage_key)
            except Exception:
                pass
        j.status = "expired"
        j.save(update_fields=["status"])

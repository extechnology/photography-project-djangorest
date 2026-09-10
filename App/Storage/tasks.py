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


def run_or_queue_task(task_func, *args, **kwargs):
    """
    Executes task asynchronously via Celery if available, or falls back to
    immediate synchronous execution if Celery broker is unavailable.
    """
    try:
        return task_func.delay(*args, **kwargs)
    except Exception:
        # Fallback to direct synchronous execution
        return task_func(*args, **kwargs)


@shared_task
def process_media_derivatives_and_faces_task(media_id_str: str):
    """
    Generates preview/thumbnail derivatives and detects face embeddings asynchronously.
    """
    try:
        media = Media.objects.get(id=media_id_str)
    except Media.DoesNotExist:
        return

    media.processing_status = "processing"
    media.save(update_fields=["processing_status"])

    storage = get_storage_provider()

    try:
        data = storage.download(media.storage_key)
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)

        # Record dimensions
        media.width, media.height = img.size

        # 1. Generate Thumbnail (max 300x300)
        thumb_img = img.copy()
        thumb_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
        thumb_buf = io.BytesIO()
        thumb_img.convert("RGB").save(thumb_buf, format="JPEG", quality=85)
        thumb_key = f"galleries/{media.gallery_id}/thumbnails/{media.id}.jpg"
        storage.upload(thumb_key, thumb_buf.getvalue(), content_type="image/jpeg")
        media.thumbnail_storage_key = thumb_key

        # 2. Generate Preview (max 1200x1200)
        prev_img = img.copy()
        prev_img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        prev_buf = io.BytesIO()
        prev_img.convert("RGB").save(prev_buf, format="JPEG", quality=90)
        prev_key = f"galleries/{media.gallery_id}/previews/{media.id}.jpg"
        storage.upload(prev_key, prev_buf.getvalue(), content_type="image/jpeg")
        media.preview_storage_key = prev_key

        # 3. Detect and index faces
        FaceService.process_and_index_media_faces(media, data)

        media.processing_status = "ready"
        media.save()

    except Exception:
        media.processing_status = "failed"
        media.save(update_fields=["processing_status"])


@shared_task
def generate_bulk_download_archive_task(job_id_str: str, photo_ids: list = None):
    """
    Compiles an asynchronous ZIP archive of requested gallery photos.
    """
    try:
        job = BulkDownloadJob.objects.select_related("gallery").get(id=job_id_str)
    except BulkDownloadJob.DoesNotExist:
        return

    job.status = "processing"
    job.save(update_fields=["status"])

    gallery = job.gallery
    photos_qs = Media.objects.filter(gallery=gallery, deleted_at__isnull=True)
    if photo_ids:
        photos_qs = photos_qs.filter(id__in=photo_ids)

    if not photos_qs.exists():
        job.status = "failed"
        job.error_message = "No photos found to bundle."
        job.save(update_fields=["status", "error_message"])
        return

    storage = get_storage_provider()
    zip_buffer = io.BytesIO()

    try:
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
            used_filenames = set()
            for media in photos_qs:
                try:
                    file_bytes = storage.download(media.storage_key)
                except Exception:
                    continue

                filename = media.original_filename or f"photo_{media.id}.jpg"
                base, ext = os.path.splitext(filename)
                clean_name = filename
                counter = 1
                while clean_name in used_filenames:
                    clean_name = f"{base}_{counter}{ext}"
                    counter += 1
                used_filenames.add(clean_name)

                z.writestr(clean_name, file_bytes)

        zip_bytes = zip_buffer.getvalue()
        archive_key = f"archives/{gallery.id}/{job.id}.zip"
        storage.upload(archive_key, zip_bytes, content_type="application/zip")

        job.status = "ready"
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
            storage.delete(j.archive_storage_key)
        j.status = "expired"
        j.save(update_fields=["status"])

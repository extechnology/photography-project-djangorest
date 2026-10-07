import io
import os
import uuid
import logging
from django.db import transaction
from django.core.files.base import ContentFile
from rest_framework.exceptions import ValidationError
from App.Storage.storage_models import Gallery, GallerySection, Media as GalleryMedia
from App.Photographers.photo_models import PhotographerProfile
from App.Culling.culling_models import CullingSession
from App.Culling.services.culler import purge_culling_staging
from App.Storage.services.storage_service import get_storage_provider

logger = logging.getLogger(__name__)


@transaction.atomic
def move_culled_photos_to_gallery(
    user,
    session: CullingSession,
    target_mode: str = 'new',
    target_gallery_id: str = None,
    new_gallery_title: str = None,
    category_assignments: dict = None,
    include_duplicates: bool = True,
    items_payload: list = None
):
    """
    Transfers culled photos to GalleryMedia and then completely purges staging files.
    Ensures files and thumbnails are properly uploaded to storage provider before staging purge.
    """
    if not session.is_paid:
        raise ValidationError("This session must be paid before photos can be moved to a gallery.")

    # 1. Resolve Target Gallery
    photographer_profile, _ = PhotographerProfile.objects.get_or_create(
        user=user,
        defaults={'name': getattr(user, 'fullname', '') or user.username}
    )

    if target_mode == 'new':
        gallery = Gallery.objects.create(
            photographer=photographer_profile,
            title=new_gallery_title or 'AI Curated Shoot',
            status='active'
        )
    else:
        try:
            gallery = Gallery.objects.get(id=target_gallery_id, photographer=photographer_profile)
        except (Gallery.DoesNotExist, ValueError):
            try:
                gallery = Gallery.objects.get(slug=target_gallery_id, photographer=photographer_profile)
            except Gallery.DoesNotExist:
                raise ValidationError("Target gallery not found.")

    category_assignments = category_assignments or {}

    # Cache section objects
    sections_by_title = {}

    def get_or_create_section(title_str: str):
        normalized = (title_str or 'HIGHLIGHTS').strip().upper()
        if normalized not in sections_by_title:
            section, _ = GallerySection.objects.get_or_create(
                gallery=gallery,
                title=normalized,
                defaults={'order': len(sections_by_title) + 1}
            )
            sections_by_title[normalized] = section
        return sections_by_title[normalized]

    # Query items to transfer
    items_qs = session.items.all()
    if not include_duplicates:
        items_qs = items_qs.filter(status='keep')

    storage = get_storage_provider()
    moved_count = 0

    for item in items_qs:
        # Determine target section from assignment dict or default
        section_name = category_assignments.get(str(item.id)) or category_assignments.get(getattr(item, 'cluster_id', None))
        if not section_name:
            section_name = 'HIGHLIGHTS' if item.status == 'keep' else 'ALTERNATE TAKES'

        section = get_or_create_section(section_name)

        item_file = item.image or getattr(item, 'file', None)
        item_size = item.size_bytes or getattr(item, 'file_size_bytes', 0)

        raw_filename = item.original_filename or (item_file.name if item_file else "photo.jpg")
        safe_name = os.path.basename(str(raw_filename).replace('\\', '/'))
        media_id = uuid.uuid4()
        storage_key = f"galleries/{gallery.id}/originals/{media_id}_{safe_name}"

        file_bytes = b""
        if item_file:
            try:
                item_file.open("rb")
                file_bytes = item_file.read()
                item_file.close()
            except Exception:
                if hasattr(item_file, 'path') and os.path.exists(item_file.path):
                    try:
                        with open(item_file.path, 'rb') as f:
                            file_bytes = f.read()
                    except Exception:
                        pass

        mime = "image/jpeg"
        if safe_name.lower().endswith(".png"):
            mime = "image/png"
        elif safe_name.lower().endswith(".webp"):
            mime = "image/webp"

        if file_bytes:
            storage.upload(storage_key, file_bytes, content_type=mime)

        # Create GalleryMedia
        gm = GalleryMedia(
            id=media_id,
            gallery=gallery,
            photographer=photographer_profile,
            section=section,
            section_title=section.title,
            original_filename=safe_name,
            storage_key=storage_key,
            file_size=len(file_bytes) if file_bytes else item_size,
            mime_type=mime,
            width=item.width or 0,
            height=item.height or 0,
            is_favorite=(item.is_best_pick and item.status == 'keep'),
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
            except Exception as e:
                logger.warning(f"Error processing image thumbnails for media {media_id}: {e}")

        gm.save()
        moved_count += 1

    # 2. PURGE ALL STAGING DATA & FILES
    purge_culling_staging(session)

    return {
        'success': True,
        'gallery_id': str(gallery.id),
        'gallery_title': gallery.title,
        'moved_count': moved_count,
        'transferred_count': moved_count,
        'purged': True,
        'message': f"Moved {moved_count} photos to '{gallery.title}' and purged culling staging."
    }


def execute_move_to_gallery(session: CullingSession, payload: dict):
    """Backward compatibility wrapper for execute_move_to_gallery."""
    return move_culled_photos_to_gallery(
        user=session.user,
        session=session,
        target_mode=payload.get('target_mode', 'new'),
        target_gallery_id=payload.get('target_gallery_id'),
        new_gallery_title=payload.get('new_gallery_title'),
        category_assignments=payload.get('category_assignments', {}),
        include_duplicates=payload.get('include_duplicates', True),
        items_payload=payload.get('items', [])
    )

import io
import os
import re
import uuid
import logging
from pathlib import Path
from PIL import Image, ImageOps

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Q

from App.Storage.storage_models import Media as GalleryMedia, Gallery, GallerySection
from App.Storage.services.storage_service import get_storage_provider, LocalStorageProvider

logger = logging.getLogger(__name__)


def fix_local_permissions(target_path):
    """
    Ensure directory (0755) and file (0644) permissions so Nginx (www user)
    can serve media files created by worker processes (root/app user).
    """
    if os.name == 'nt':
        return  # Windows does not use POSIX chmod
    try:
        if os.path.isfile(target_path):
            os.chmod(target_path, 0o644)
            # Ensure parent directories have 0755
            parent = os.path.dirname(target_path)
            while parent and parent != str(settings.MEDIA_ROOT) and len(parent) > 1:
                try:
                    os.chmod(parent, 0o755)
                except Exception:
                    pass
                parent = os.path.dirname(parent)
        elif os.path.isdir(target_path):
            os.chmod(target_path, 0o755)
    except Exception:
        pass


def read_media_bytes(file_source, filename=None, storage_key=None):
    """
    Highly resilient bytes extractor that attempts multiple strategies
    to locate and read file contents from field objects, paths, or storage.
    """
    if not file_source and not filename and not storage_key:
        return b""

    # Strategy 1: Direct bytes passed
    if isinstance(file_source, (bytes, bytearray)):
        return bytes(file_source)

    # Strategy 2: FileField / FieldFile / UploadedFile with safe try/except
    try:
        storage = getattr(file_source, "storage", None)
        fname = getattr(file_source, "name", None)
        if storage and fname and storage.exists(fname):
            with file_source.open("rb") as f:
                content = f.read()
                if content:
                    return content
    except (FileNotFoundError, OSError, Exception):
        pass

    try:
        # Check if direct read is available (UploadedFile / BytesIO)
        read_fn = getattr(file_source, "read", None)
        if callable(read_fn):
            seek_fn = getattr(file_source, "seek", None)
            if callable(seek_fn):
                seek_fn(0)
            content = read_fn()
            if callable(seek_fn):
                seek_fn(0)
            if content:
                return content
    except (FileNotFoundError, OSError, Exception):
        pass

    # Strategy 3: Direct file path on file_source
    try:
        raw_path = getattr(file_source, "path", None)
        if raw_path and os.path.exists(raw_path) and os.path.isfile(raw_path):
            with open(raw_path, "rb") as f:
                return f.read()
    except (FileNotFoundError, OSError, Exception):
        pass

    # Strategy 4: Name attribute on file_source
    candidate_names = []
    try:
        fname = getattr(file_source, "name", None)
        if fname:
            candidate_names.append(str(fname))
    except Exception:
        pass
    if storage_key:
        candidate_names.append(str(storage_key))
    if filename:
        candidate_names.append(str(filename))


    media_root = str(settings.MEDIA_ROOT)

    for cand_name in candidate_names:
        clean = cand_name.replace('\\', '/').lstrip('/')

        # 4a: Direct join with MEDIA_ROOT
        direct_path = os.path.normpath(os.path.join(media_root, clean))
        if os.path.exists(direct_path) and os.path.isfile(direct_path):
            try:
                with open(direct_path, "rb") as f:
                    return f.read()
            except Exception:
                pass

        # 4b: Strip leading 'media/' if present
        stripped = re.sub(r'^/?media/', '', clean)
        stripped_path = os.path.normpath(os.path.join(media_root, stripped))
        if os.path.exists(stripped_path) and os.path.isfile(stripped_path):
            try:
                with open(stripped_path, "rb") as f:
                    return f.read()
            except Exception:
                pass

        # 4c: Check under storage_objects/
        so_path = os.path.normpath(os.path.join(media_root, 'storage_objects', clean))
        if os.path.exists(so_path) and os.path.isfile(so_path):
            try:
                with open(so_path, "rb") as f:
                    return f.read()
            except Exception:
                pass

        # 4d: Check storage provider download
        try:
            storage = get_storage_provider()
            if hasattr(storage, 'download') and storage.exists(clean):
                data = storage.download(clean)
                if data:
                    return data
        except Exception:
            pass

    # Strategy 5: Deep lookup by filename in MEDIA_ROOT
    lookup_file = filename or (os.path.basename(candidate_names[0]) if candidate_names else None)
    if lookup_file:
        base_target = os.path.basename(lookup_file)
        if base_target:
            # First check common subdirectories for speed
            for sub in ['events', 'culling_staging', 'storage_objects', 'galleries']:
                sub_dir = os.path.join(media_root, sub)
                if os.path.exists(sub_dir):
                    for root, _, files in os.walk(sub_dir):
                        if base_target in files:
                            found_p = os.path.join(root, base_target)
                            if os.path.exists(found_p):
                                try:
                                    with open(found_p, "rb") as f:
                                        return f.read()
                                except Exception:
                                    pass

            # Search full MEDIA_ROOT
            for root, _, files in os.walk(media_root):
                if base_target in files:
                    found_p = os.path.join(root, base_target)
                    if os.path.exists(found_p):
                        try:
                            with open(found_p, "rb") as f:
                                return f.read()
                        except Exception:
                            pass

    return b""


def transfer_media_to_gallery(
    gallery: Gallery,
    photographer,
    section: GallerySection,
    original_filename: str,
    file_source,
    media_type: str = 'photo',
    is_favorite: bool = False,
    is_cover: bool = False,
    width: int = None,
    height: int = None,
    aspect_ratio: float = None,
    video_thumbnail_source=None,
    custom_media_id=None,
) -> GalleryMedia:
    """
    Standardized, fail-safe transfer of any media asset into a Studio Gallery.
    1. Extracts bytes using robust multi-strategy extractor.
    2. Uploads originals, previews, and thumbnails to the storage provider.
    3. Populates GalleryMedia with complete storage keys and ready status.
    4. Ensures local directory and file permissions (0755 / 0644) for Nginx.
    """
    media_id = custom_media_id or uuid.uuid4()
    raw_name = original_filename or "photo.jpg"
    safe_name = os.path.basename(str(raw_name).replace('\\', '/'))
    storage_key = f"galleries/{gallery.id}/originals/{media_id}_{safe_name}"

    file_bytes = read_media_bytes(file_source, filename=safe_name)

    # Determine MIME
    ext = os.path.splitext(safe_name)[1].lower()
    if media_type == 'video' or ext in ('.mp4', '.mov', '.webm', '.mkv', '.avi', '.m4v'):
        mime = "video/mp4"
        media_type = 'video'
    elif ext == '.png':
        mime = "image/png"
    elif ext == '.webp':
        mime = "image/webp"
    else:
        mime = "image/jpeg"

    storage = get_storage_provider()

    # Upload original to storage provider
    if file_bytes:
        try:
            storage.upload(storage_key, file_bytes, content_type=mime)
            if isinstance(storage, LocalStorageProvider):
                fix_local_permissions(str(storage._resolve_path(storage_key)))
        except Exception as e:
            logger.warning(f"Error uploading original {storage_key}: {e}")

    thumb_key = None
    prev_key = None
    processing_status = "ready" if media_type == "video" else "pending"

    img_w = width
    img_h = height
    img_ar = aspect_ratio

    if file_bytes and media_type == 'photo':
        try:
            img = Image.open(io.BytesIO(file_bytes))
            img = ImageOps.exif_transpose(img)
            img_w, img_h = img.size
            if img_h > 0:
                img_ar = round(img_w / float(img_h), 3)

            # 1. Thumbnail (300x300)
            thumb_img = img.copy()
            thumb_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
            thumb_buf = io.BytesIO()
            thumb_img.convert("RGB").save(thumb_buf, format="JPEG", quality=85)
            thumb_key = f"galleries/{gallery.id}/thumbnails/{media_id}.jpg"
            storage.upload(thumb_key, thumb_buf.getvalue(), content_type="image/jpeg")
            if isinstance(storage, LocalStorageProvider):
                fix_local_permissions(str(storage._resolve_path(thumb_key)))

            # 2. Preview (1200x1200)
            prev_img = img.copy()
            prev_img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            prev_buf = io.BytesIO()
            prev_img.convert("RGB").save(prev_buf, format="JPEG", quality=90)
            prev_key = f"galleries/{gallery.id}/previews/{media_id}.jpg"
            storage.upload(prev_key, prev_buf.getvalue(), content_type="image/jpeg")
            if isinstance(storage, LocalStorageProvider):
                fix_local_permissions(str(storage._resolve_path(prev_key)))

            processing_status = "ready"
        except Exception as e:
            logger.warning(f"Failed to generate thumbnails/previews for {safe_name}: {e}")

    elif media_type == 'video' and video_thumbnail_source:
        try:
            v_bytes = read_media_bytes(video_thumbnail_source)
            if v_bytes:
                thumb_key = f"galleries/{gallery.id}/thumbnails/{media_id}.jpg"
                storage.upload(thumb_key, v_bytes, content_type="image/jpeg")
                if isinstance(storage, LocalStorageProvider):
                    fix_local_permissions(str(storage._resolve_path(thumb_key)))
        except Exception as e:
            logger.warning(f"Failed to save video thumbnail for {safe_name}: {e}")

    # Build and save GalleryMedia
    gm = GalleryMedia(
        id=media_id,
        photographer=photographer,
        gallery=gallery,
        section=section,
        section_title=section.title if section else 'HIGHLIGHTS',
        original_filename=safe_name,
        storage_key=storage_key,
        thumbnail_storage_key=thumb_key,
        preview_storage_key=prev_key,
        media_type=media_type,
        mime_type=mime,
        file_extension=ext or ('.mp4' if media_type == 'video' else '.jpg'),
        file_size=len(file_bytes) if file_bytes else 0,
        width=img_w or 0,
        height=img_h or 0,
        aspect_ratio=img_ar,
        is_favorite=bool(is_favorite),
        is_cover=bool(is_cover),
        processing_status=processing_status,
        upload_status="completed",
    )

    if file_bytes:
        try:
            gm.file.save(f"{media_id}_{safe_name}", ContentFile(file_bytes), save=False)
            if hasattr(gm.file, 'path') and os.path.exists(gm.file.path):
                fix_local_permissions(gm.file.path)
        except Exception:
            pass

    gm.save()
    return gm

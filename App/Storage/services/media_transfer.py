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

    # Strategy 3: Direct file path on file_source (local storage only)
    try:
        raw_path = getattr(file_source, "path", None)
        if raw_path and os.path.exists(raw_path) and os.path.isfile(raw_path):
            with open(raw_path, "rb") as f:
                return f.read()
    except (NotImplementedError, FileNotFoundError, OSError, ValueError, Exception):
        pass

    # Strategy 3b: Early R2/remote storage provider download via storage_key
    if storage_key:
        try:
            sp = get_storage_provider()
            if hasattr(sp, 'download') and sp.exists(str(storage_key).replace('\\', '/').lstrip('/')):
                data = sp.download(str(storage_key).replace('\\', '/').lstrip('/'))
                if data:
                    return data
        except Exception:
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
        clean = str(cand_name).replace('\\', '/').strip().lstrip('/')

        # 4a: Direct check if cand_name was already an absolute path
        if os.path.isabs(str(cand_name)) and os.path.exists(cand_name) and os.path.isfile(cand_name):
            try:
                with open(cand_name, "rb") as f:
                    return f.read()
            except Exception:
                pass

        # 4b: Direct join with MEDIA_ROOT
        direct_path = os.path.normpath(os.path.join(media_root, clean))
        if os.path.exists(direct_path) and os.path.isfile(direct_path):
            try:
                with open(direct_path, "rb") as f:
                    return f.read()
            except Exception:
                pass

        # 4c: Strip leading 'media/' if present
        stripped = re.sub(r'^/?media/', '', clean)
        stripped_path = os.path.normpath(os.path.join(media_root, stripped))
        if os.path.exists(stripped_path) and os.path.isfile(stripped_path):
            try:
                with open(stripped_path, "rb") as f:
                    return f.read()
            except Exception:
                pass

        # 4d: Check under storage_objects/
        so_path = os.path.normpath(os.path.join(media_root, 'storage_objects', clean))
        if os.path.exists(so_path) and os.path.isfile(so_path):
            try:
                with open(so_path, "rb") as f:
                    return f.read()
            except Exception:
                pass

        # 4e: If clean already had storage_objects/, check without it
        if clean.startswith("storage_objects/"):
            clean_no_so = clean[len("storage_objects/"):].lstrip('/')
            cand_p1 = os.path.normpath(os.path.join(media_root, 'storage_objects', clean_no_so))
            if os.path.exists(cand_p1) and os.path.isfile(cand_p1):
                try:
                    with open(cand_p1, "rb") as f:
                        return f.read()
                except Exception:
                    pass
            cand_p2 = os.path.normpath(os.path.join(media_root, clean_no_so))
            if os.path.exists(cand_p2) and os.path.isfile(cand_p2):
                try:
                    with open(cand_p2, "rb") as f:
                        return f.read()
                except Exception:
                    pass

        # 4f: Check storage provider download
        try:
            storage = get_storage_provider()
            if hasattr(storage, 'download') and storage.exists(clean):
                data = storage.download(clean)
                if data:
                    return data
        except Exception:
            pass

    # Strategy 5: Targeted lookup by filename in MEDIA_ROOT subdirectories
    lookup_file = filename or (os.path.basename(str(candidate_names[0]).replace('\\', '/')) if candidate_names else None)
    if lookup_file:
        base_target = os.path.basename(str(lookup_file).replace('\\', '/'))
        if base_target and len(base_target) > 3:
            # Check common subdirectories for speed
            for sub in ['galleries', 'storage_objects', 'events', 'culling_staging', 'previews', 'thumbnails']:
                sub_dir = os.path.join(media_root, sub)
                if os.path.exists(sub_dir):
                    for root, _, files in os.walk(sub_dir):
                        if base_target in files:
                            found_p = os.path.join(root, base_target)
                            if os.path.exists(found_p) and os.path.isfile(found_p):
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
    local_src_path = None

    # Check for direct local disk path (e.g. from culling_staging or events)
    try:
        if hasattr(file_source, 'path'):
            src_path = file_source.path
            if os.path.exists(src_path):
                local_src_path = src_path
    except (NotImplementedError, ValueError):
        pass

    if not local_src_path:
        if hasattr(file_source, 'name') and file_source.name:
            cand = os.path.join(settings.MEDIA_ROOT, str(file_source.name))
            if os.path.exists(cand) and os.path.isfile(cand):
                local_src_path = cand
        elif isinstance(file_source, (str, Path)) and os.path.exists(str(file_source)):
            local_src_path = str(file_source)

    file_size_bytes = 0
    file_bytes = None

    # FAST-PATH: Atomic or streaming transfer directly from disk (Zero RAM buffering)
    if local_src_path and isinstance(storage, LocalStorageProvider):
        try:
            target_dst = storage.get_absolute_path(storage_key)
            target_dst.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            # If staged in temporary culling_staging, move atomically
            if 'culling_staging' in str(local_src_path):
                try:
                    os.replace(str(local_src_path), str(target_dst))
                except OSError:
                    shutil.move(str(local_src_path), str(target_dst))
            else:
                shutil.copy2(str(local_src_path), str(target_dst))

            fix_local_permissions(str(target_dst))
            file_size_bytes = target_dst.stat().st_size
        except Exception as err:
            logger.warning(f"Fast disk transfer failed for {safe_name}, falling back to bytes: {err}")
            local_src_path = None

    if not file_size_bytes:
        # For R2/remote: stream the file directly if possible
        if local_src_path and not isinstance(storage, LocalStorageProvider):
            try:
                storage.move_file(local_src_path, storage_key)
                file_size_bytes = os.path.getsize(local_src_path) if os.path.exists(local_src_path) else 0
                # move_file already uploaded; read bytes only if needed for thumbnails
                if media_type == 'photo':
                    file_bytes = read_media_bytes(file_source, filename=safe_name, storage_key=storage_key)
            except Exception as e:
                logger.warning(f"R2 move_file failed for {safe_name}, falling back to bytes upload: {e}")
                local_src_path = None

    if not file_size_bytes:
        file_bytes = read_media_bytes(file_source, filename=safe_name)
        if not file_bytes and hasattr(file_source, 'read'):
            # Direct read from UploadedFile / file-like for R2 streaming
            try:
                if hasattr(file_source, 'seek'):
                    file_source.seek(0)
                file_bytes = file_source.read()
                if hasattr(file_source, 'seek'):
                    file_source.seek(0)
            except Exception:
                pass
        if file_bytes:
            file_size_bytes = len(file_bytes)
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

    if media_type == 'photo' and (local_src_path or file_bytes):
        try:
            from PIL import Image, ImageOps
            if local_src_path and isinstance(storage, LocalStorageProvider):
                target_dst = storage.get_absolute_path(storage_key)
                img = Image.open(str(target_dst))
            elif file_bytes:
                img = Image.open(io.BytesIO(file_bytes))
            else:
                # Download from R2 for thumbnail generation
                try:
                    dl_bytes = storage.download(storage_key)
                    img = Image.open(io.BytesIO(dl_bytes))
                    file_bytes = dl_bytes
                except Exception:
                    raise FileNotFoundError(f"Cannot read {storage_key} for thumbnail generation")

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
        original_storage_key=storage_key,
        file=storage_key,
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
            if isinstance(storage, LocalStorageProvider) and hasattr(gm.file, 'path'):
                try:
                    if os.path.exists(gm.file.path):
                        fix_local_permissions(gm.file.path)
                except (NotImplementedError, ValueError):
                    pass
        except Exception:
            pass

    gm.save()
    return gm

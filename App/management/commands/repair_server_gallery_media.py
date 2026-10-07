import io
import os
import re
import uuid
from PIL import Image, ImageOps
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files.base import ContentFile

from App.Storage.storage_models import Gallery, Media
from App.Storage.services.storage_service import get_storage_provider, LocalStorageProvider
from App.Storage.services.media_transfer import read_media_bytes, fix_local_permissions


class Command(BaseCommand):
    help = "Repairs missing or broken gallery originals, previews, and thumbnails on the server."

    def add_arguments(self, parser):
        parser.add_argument(
            "--gallery_id",
            type=str,
            default=None,
            help="Optional UUID of a specific gallery to repair. If omitted, checks all galleries.",
        )
        parser.add_argument(
            "--placeholder",
            action="store_true",
            default=False,
            help="Generate clean dark image placeholders for any orphan historical media whose source files were completely purged from disk.",
        )

    def handle(self, *args, **options):
        gallery_id = options.get("gallery_id")
        allow_placeholder = options.get("placeholder", False)
        storage = get_storage_provider()
        media_root = str(settings.MEDIA_ROOT)

        qs = Gallery.objects.all()
        if gallery_id:
            qs = qs.filter(id=gallery_id)

        total_galleries = qs.count()
        self.stdout.write(self.style.NOTICE(f"Scanning {total_galleries} gallery(s) for missing or broken media files..."))

        total_checked = 0
        total_repaired = 0
        total_failed = 0

        for gallery in qs:
            media_items = gallery.media_items.filter(deleted_at__isnull=True)
            for m in media_items:
                total_checked += 1
                needs_update = False

                safe_name = os.path.basename(str(m.original_filename or "photo.jpg").replace('\\', '/'))
                mid = m.id

                orig_key = m.storage_key or f"galleries/{gallery.id}/originals/{mid}_{safe_name}"
                thumb_key = m.thumbnail_storage_key or f"galleries/{gallery.id}/thumbnails/{mid}.jpg"
                prev_key = m.preview_storage_key or f"galleries/{gallery.id}/previews/{mid}.jpg"

                orig_exists = storage.exists(orig_key)
                thumb_exists = storage.exists(thumb_key)
                prev_exists = storage.exists(prev_key)

                # If everything exists, make sure local permissions are open for Nginx
                if orig_exists and thumb_exists and prev_exists:
                    if isinstance(storage, LocalStorageProvider):
                        fix_local_permissions(str(storage._resolve_path(orig_key)))
                        fix_local_permissions(str(storage._resolve_path(thumb_key)))
                        fix_local_permissions(str(storage._resolve_path(prev_key)))
                    continue

                # Locate raw bytes
                file_bytes = b""
                if orig_exists:
                    try:
                        file_bytes = storage.download(orig_key)
                    except Exception:
                        pass

                if not file_bytes:
                    file_bytes = read_media_bytes(m.file, filename=safe_name, storage_key=orig_key)

                if not file_bytes and allow_placeholder:
                    # Generate a clean dark aesthetic placeholder so UI never encounters a broken image
                    p_img = Image.new("RGB", (1200, 800), color=(24, 28, 36))
                    p_buf = io.BytesIO()
                    p_img.save(p_buf, format="JPEG", quality=85)
                    file_bytes = p_buf.getvalue()

                if not file_bytes:
                    total_failed += 1
                    self.stdout.write(self.style.WARNING(f"  [MISSING] Media {m.id} ({safe_name}): source bytes not found anywhere in MEDIA_ROOT."))
                    continue


                # Restore original
                ext = os.path.splitext(safe_name)[1].lower()
                mime = "video/mp4" if m.media_type == "video" else ("image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg"))

                if not orig_exists:
                    storage.upload(orig_key, file_bytes, content_type=mime)
                    m.storage_key = orig_key
                    needs_update = True

                if isinstance(storage, LocalStorageProvider):
                    fix_local_permissions(str(storage._resolve_path(orig_key)))

                # Generate thumbnail and preview for photos
                if m.media_type == "photo":
                    try:
                        img = Image.open(io.BytesIO(file_bytes))
                        img = ImageOps.exif_transpose(img)
                        m.width, m.height = img.size
                        if m.height > 0:
                            m.aspect_ratio = round(m.width / float(m.height), 3)

                        if not thumb_exists:
                            t_img = img.copy()
                            t_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                            t_buf = io.BytesIO()
                            t_img.convert("RGB").save(t_buf, format="JPEG", quality=85)
                            storage.upload(thumb_key, t_buf.getvalue(), content_type="image/jpeg")
                            m.thumbnail_storage_key = thumb_key
                            needs_update = True

                        if not prev_exists:
                            p_img = img.copy()
                            p_img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                            p_buf = io.BytesIO()
                            p_img.convert("RGB").save(p_buf, format="JPEG", quality=90)
                            storage.upload(prev_key, p_buf.getvalue(), content_type="image/jpeg")
                            m.preview_storage_key = prev_key
                            needs_update = True

                        if isinstance(storage, LocalStorageProvider):
                            fix_local_permissions(str(storage._resolve_path(thumb_key)))
                            fix_local_permissions(str(storage._resolve_path(prev_key)))

                        m.processing_status = "ready"
                        needs_update = True
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"  [THUMB_ERROR] Media {m.id}: {e}"))

                # Also populate FileField if empty
                if not m.file or not m.file.name:
                    try:
                        m.file.save(f"{mid}_{safe_name}", ContentFile(file_bytes), save=False)
                        needs_update = True
                    except Exception:
                        pass

                if needs_update:
                    m.save()
                    total_repaired += 1
                    self.stdout.write(self.style.SUCCESS(f"  [REPAIRED] Media {m.id} ({safe_name}) in gallery '{gallery.title}'"))

        # Fix overall storage_objects directory permissions
        if isinstance(storage, LocalStorageProvider):
            so_dir = os.path.join(media_root, "storage_objects")
            if os.path.exists(so_dir):
                fix_local_permissions(so_dir)
                for root, dirs, files in os.walk(so_dir):
                    for d in dirs:
                        fix_local_permissions(os.path.join(root, d))
                    for f in files:
                        fix_local_permissions(os.path.join(root, f))

        self.stdout.write(self.style.SUCCESS(
            f"\nFinished! Checked: {total_checked} | Repaired: {total_repaired} | Still Unresolved: {total_failed}"
        ))

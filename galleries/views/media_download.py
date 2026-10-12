import os
import io
import mimetypes
import logging
from django.http import HttpResponse, Http404, FileResponse
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework import status

from galleries.models import Gallery, Media as GalleryMedia
from utils.watermark import apply_watermark_to_image

logger = logging.getLogger(__name__)


def _read_media_raw_bytes(media, target_file=None):
    """
    Safely reads file bytes from FileField, storage key, local media directory, or remote URL.
    """
    # Strategy 1: Direct FileField / target_file reading (highest priority when target_file is provided, e.g. raw_file)
    if target_file:
        try:
            if hasattr(target_file, 'open'):
                target_file.open('rb')
                content = target_file.read()
                target_file.close()
                if content:
                    return content
            elif hasattr(target_file, 'read'):
                if hasattr(target_file, 'seek'):
                    target_file.seek(0)
                content = target_file.read()
                if content:
                    return content
        except Exception:
            pass

        if hasattr(target_file, 'path') and os.path.exists(target_file.path):
            try:
                with open(target_file.path, 'rb') as f:
                    return f.read()
            except Exception:
                pass

    storage_key = getattr(media, 'storage_key', None) or getattr(media, 'original_storage_key', None)
    clean_name = getattr(media, 'original_filename', None) or getattr(media, 'title', None)

    # Strategy 2: Custom Storage Provider (LocalStorageProvider, S3, etc.)
    if storage_key:
        try:
            from App.Storage.services.storage_service import get_storage_provider
            storage = get_storage_provider()
            if storage:
                if hasattr(storage, 'download') and storage.exists(storage_key):
                    data = storage.download(storage_key)
                    if data:
                        return data
                elif hasattr(storage, 'download_bytes'):
                    data = storage.download_bytes(storage_key)
                    if data:
                        return data
        except Exception:
            pass

    # Strategy 3: Resilient multi-strategy media reader
    try:
        from App.Storage.services.media_transfer import read_media_bytes
        data = read_media_bytes(target_file, filename=clean_name, storage_key=storage_key)
        if data:
            return data
    except Exception:
        pass

    # Strategy 4: Preview or thumbnail key fallback
    for alt_key_attr in ('preview_storage_key', 'thumbnail_storage_key'):
        alt_key = getattr(media, alt_key_attr, None)
        if alt_key:
            try:
                from App.Storage.services.media_transfer import read_media_bytes
                data = read_media_bytes(None, storage_key=alt_key)
                if data:
                    return data
            except Exception:
                pass

    # Strategy 5: Remote URL fallback
    target_url = getattr(media, 'file_url', None) or getattr(media, 'url', None)
    if not target_url and target_file and hasattr(target_file, 'url'):
        try:
            target_url = target_file.url
        except Exception:
            target_url = None

    if target_url:
        import requests
        target_str = str(target_url).lower()
        is_loopback = any(h in target_str for h in ('127.0.0.1', 'localhost', '0.0.0.0'))
        if not is_loopback and target_str.startswith(('http://', 'https://')):
            try:
                resp = requests.get(target_url, timeout=5)
                if resp.status_code == 200:
                    return resp.content
            except Exception:
                pass

    return None



class MediaDownloadView(APIView):
    """
    GET /api/galleries/media/<uuid:media_id>/download/?format=raw|jpeg&watermark=true|false
    
    Streams the image file directly with Content-Disposition: attachment.
    Guarantees that the browser downloads the file directly without opening in a new tab.
    """
    permission_classes = [AllowAny]

    def perform_content_negotiation(self, request, force=False):
        # Ignore ?format= query param so DRF doesn't treat it as format suffix negotiation
        renderers = self.get_renderers()
        return (renderers[0], renderers[0].media_type)

    def get(self, request, media_id):
        media = get_object_or_404(GalleryMedia.objects.select_related('gallery', 'photographer'), id=media_id)
        gallery = media.gallery


        # 1. Verify gallery allows downloads
        downloads_allowed = getattr(gallery, 'allow_downloads', True) or getattr(gallery, 'downloads_enabled', True)
        if not downloads_allowed:
            return HttpResponse("Downloads are disabled for this gallery", status=403)

        # Verify password if protected
        password = request.headers.get("X-Gallery-Password") or request.query_params.get("password")
        if getattr(gallery, 'visibility', 'public') == "password_protected" and hasattr(gallery, 'check_access_password'):
            if not gallery.check_access_password(password):
                return HttpResponse("Valid gallery password required to download.", status=403)

        format_choice = request.GET.get('format', 'original').lower()
        apply_watermark_param = request.GET.get('watermark', 'false').lower() == 'true'

        target_file = None
        is_raw = False

        # 2. Format Resolution: RAW vs JPEG / Master
        if format_choice == 'raw' and getattr(media, 'raw_file', None) and bool(media.raw_file):
            target_file = media.raw_file
            is_raw = True
        elif getattr(media, 'file', None) and bool(media.file):
            target_file = media.file
        elif getattr(media, 'preview', None) and bool(media.preview):
            target_file = media.preview

        # Increment download telemetry
        try:
            GalleryMedia.objects.filter(id=media_id).update(downloads_count=F('downloads_count') + 1)
            Gallery.objects.filter(id=gallery.id).update(downloads_count=F('downloads_count') + 1)
        except Exception:
            pass

        filename = media.original_filename or (os.path.basename(target_file.name) if target_file and hasattr(target_file, 'name') else f"photo_{media.id}.jpg")
        if not filename:
            filename = f"photo_{media.id}.jpg"

        clean_filename = os.path.basename(filename.replace('\\', '/'))
        base_name, ext = os.path.splitext(clean_filename)
        if not ext:
            ext = getattr(media, 'file_extension', '.jpg') or '.jpg'
        clean_filename = f"{base_name}{ext}"

        # 3. Read File Bytes
        file_bytes = _read_media_raw_bytes(media, target_file)

        if not file_bytes:
            # Fallback to direct file read if path is available
            if target_file and hasattr(target_file, 'path') and os.path.exists(target_file.path):
                with open(target_file.path, 'rb') as f:
                    file_bytes = f.read()

        if not file_bytes:
            raise Http404("Media file could not be located in storage.")

        # 4. If RAW file requested and no watermark requested, stream raw file directly
        watermark_active = (apply_watermark_param or getattr(gallery, 'watermark_enabled', False)) and not is_raw
        if is_raw or not watermark_active:
            content_type, _ = mimetypes.guess_type(clean_filename)
            content_type = content_type or (media.mime_type if hasattr(media, 'mime_type') and media.mime_type else 'application/octet-stream')

            response = HttpResponse(file_bytes, content_type=content_type)
            response['Content-Disposition'] = f'attachment; filename="{clean_filename}"'
            response['Content-Length'] = len(file_bytes)
            response['Access-Control-Allow-Origin'] = '*'
            response['Access-Control-Expose-Headers'] = 'Content-Disposition, Content-Length'
            return response

        # 5. Watermarked JPEG Delivery
        profile = getattr(gallery, 'photographer', None)
        if profile and hasattr(profile, 'photographer_profile'):
            profile = profile.photographer_profile

        wm_text = (
            getattr(gallery, 'watermark_text', None) or 
            (profile.get_effective_watermark_text() if profile and hasattr(profile, 'get_effective_watermark_text') else None) or 
            getattr(gallery, 'photographer_name', 'PHOTOGRAPHER') or 
            'PHOTOGRAPHER'
        )

        wm_image_path = None
        wm_image = getattr(gallery, 'watermark_image', None)
        if wm_image:
            if hasattr(wm_image, 'path') and os.path.exists(wm_image.path):
                wm_image_path = wm_image.path

        watermark_config = {
            'enabled': True,
            'type': getattr(gallery, 'watermark_type', None) or (getattr(profile, 'watermark_type', None) if profile else None) or 'text',
            'text': wm_text,
            'opacity': getattr(gallery, 'watermark_opacity', None) or (getattr(profile, 'watermark_opacity', 0.45) if profile else 0.45),
            'position': getattr(gallery, 'watermark_position', None) or (getattr(profile, 'watermark_position', 'bottom-right') if profile else 'bottom-right'),
            'font_color': getattr(gallery, 'watermark_font_color', None) or (getattr(profile, 'watermark_font_color', '#FFFFFF') if profile else '#FFFFFF'),
            'font_style': getattr(gallery, 'watermark_font_style', None) or (getattr(profile, 'watermark_font_style', 'serif') if profile else 'serif'),
            'image_path': wm_image_path,
            'watermark_image': wm_image,
        }

        processed_bytes = apply_watermark_to_image(file_bytes, watermark_config)

        # Ensure output filename ends with .jpg for watermarked JPEG
        output_filename = f"{base_name}.jpg"

        response = HttpResponse(processed_bytes, content_type='image/jpeg')
        response['Content-Disposition'] = f'attachment; filename="{output_filename}"'
        response['Content-Length'] = len(processed_bytes)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Expose-Headers'] = 'Content-Disposition, Content-Length'
        return response

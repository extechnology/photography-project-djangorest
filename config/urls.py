"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/culling/', include('culling.urls')),
    path('api/', include('gallery.urls')),
    path('api/', include('portfolio.urls')),
    path('api/', include('App.urls')),
]

import os
import re
import shutil
import logging
from django.views.static import serve
from django.urls import re_path
from django.http import HttpResponse, Http404

logger = logging.getLogger(__name__)


def try_recover_missing_media(path, document_root):
    """
    Resilient self-healing helper for media requests.
    If a file under /media/storage_objects/... or /media/... was moved or requested
    at a storage provider path but is not yet placed at that exact disk location,
    locates the source file from database Media/GalleryMedia records, alternative folders,
    or on-the-fly generates missing thumbnails/previews.
    """
    if not document_root or not path:
        return False

    target_full_path = os.path.normpath(os.path.join(document_root, path))
    if os.path.exists(target_full_path):
        return True

    clean_path = path.replace('\\', '/').lstrip('/')
    base_name = os.path.basename(clean_path)

    # 1. If requesting storage_objects/<key>
    if clean_path.startswith('storage_objects/'):
        key = clean_path[len('storage_objects/'):]
        # Check if the file exists directly under document_root without storage_objects/ prefix
        alt_path = os.path.normpath(os.path.join(document_root, key))
        if os.path.exists(alt_path) and os.path.isfile(alt_path):
            try:
                os.makedirs(os.path.dirname(target_full_path), exist_ok=True)
                shutil.copy2(alt_path, target_full_path)
                return True
            except Exception as e:
                logger.warning(f"Failed to copy alternate media from {alt_path}: {e}")

        # Check in App.Storage Media model
        try:
            from django.db.models import Q
            from App.Storage.storage_models import Media
            media_item = (
                Media.objects.filter(Q(storage_key=key) | Q(preview_storage_key=key) | Q(thumbnail_storage_key=key)).first()
            )
            if not media_item:
                match = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', key, re.I)
                if match:
                    media_item = Media.objects.filter(id=match.group(0)).first()

            if media_item:
                source_file = None
                if media_item.file and hasattr(media_item.file, 'path') and os.path.exists(media_item.file.path):
                    source_file = media_item.file.path
                else:
                    orig_key = getattr(media_item, 'storage_key', None)
                    if orig_key:
                        candidate = os.path.normpath(os.path.join(document_root, 'storage_objects', orig_key.lstrip('/')))
                        if os.path.exists(candidate):
                            source_file = candidate

                if not source_file or not os.path.exists(source_file):
                    fn = getattr(media_item, 'original_filename', None)
                    if not fn and '_' in base_name:
                        fn = base_name.split('_', 1)[-1]
                    if fn:
                        # Quick check in common media directories
                        for sub_folder in [
                            os.path.join(document_root, 'events', 'media'),
                            os.path.join(document_root, 'events', 'media', '2026', '10', '07'),
                            os.path.join(document_root, 'galleries'),
                            os.path.join(document_root, 'culling_staging'),
                            os.path.join(document_root, 'storage_objects'),
                        ]:
                            if os.path.exists(sub_folder):
                                for root, dirs, files in os.walk(sub_folder):
                                    if fn in files:
                                        source_file = os.path.join(root, fn)
                                        break
                                    for f in files:
                                        if f == fn or f.endswith('_' + fn):
                                            source_file = os.path.join(root, f)
                                            break
                                    if source_file:
                                        break
                            if source_file:
                                break

                        if not source_file:
                            for root, dirs, files in os.walk(document_root):
                                if fn in files:
                                    source_file = os.path.join(root, fn)
                                    break
                                for f in files:
                                    if f == fn or f.endswith('_' + fn):
                                        source_file = os.path.join(root, f)
                                        break
                                if source_file:
                                    break

                if source_file and os.path.exists(source_file):
                    os.makedirs(os.path.dirname(target_full_path), exist_ok=True)
                    from PIL import Image, ImageOps
                    try:
                        img = Image.open(source_file)
                        img = ImageOps.exif_transpose(img)

                        if '/thumbnails/' in clean_path or clean_path.endswith('_thumb.jpg'):
                            t_img = img.copy()
                            t_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                            t_img.convert('RGB').save(target_full_path, format='JPEG', quality=85)
                            return True
                        elif '/previews/' in clean_path or clean_path.endswith('_preview.jpg'):
                            p_img = img.copy()
                            p_img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                            p_img.convert('RGB').save(target_full_path, format='JPEG', quality=90)
                            return True
                        else:
                            shutil.copy2(source_file, target_full_path)
                            # Also proactively create thumbnail and preview if media_item exists
                            if media_item and media_item.gallery_id:
                                try:
                                    gid = media_item.gallery_id
                                    mid = media_item.id
                                    t_key = f'galleries/{gid}/thumbnails/{mid}.jpg'
                                    p_key = f'galleries/{gid}/previews/{mid}.jpg'
                                    t_full = os.path.join(document_root, 'storage_objects', t_key)
                                    p_full = os.path.join(document_root, 'storage_objects', p_key)
                                    os.makedirs(os.path.dirname(t_full), exist_ok=True)
                                    os.makedirs(os.path.dirname(p_full), exist_ok=True)

                                    if not os.path.exists(t_full):
                                        t_img = img.copy()
                                        t_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                                        t_img.convert('RGB').save(t_full, format='JPEG', quality=85)
                                    if not os.path.exists(p_full):
                                        p_img = img.copy()
                                        p_img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                                        p_img.convert('RGB').save(p_full, format='JPEG', quality=90)

                                    media_item.thumbnail_storage_key = t_key
                                    media_item.preview_storage_key = p_key
                                    media_item.processing_status = 'ready'
                                    media_item.save(update_fields=['thumbnail_storage_key', 'preview_storage_key', 'processing_status'])
                                except Exception:
                                    pass
                            return True
                    except Exception as err:
                        logger.warning(f"Error copying/transforming media from {source_file}: {err}")
                        shutil.copy2(source_file, target_full_path)
                        return True
        except Exception as e:
            logger.warning(f"Self-healing database lookup error for {key}: {e}")

    # 2. If requesting outside storage_objects/ but it exists under storage_objects/
    if not clean_path.startswith('storage_objects/'):
        so_path = os.path.normpath(os.path.join(document_root, 'storage_objects', clean_path))
        if os.path.exists(so_path) and os.path.isfile(so_path):
            try:
                os.makedirs(os.path.dirname(target_full_path), exist_ok=True)
                shutil.copy2(so_path, target_full_path)
                return True
            except Exception as e:
                logger.warning(f"Failed to copy from storage_objects to {target_full_path}: {e}")

    # 3. Fallback: match by UUID or filename
    base_name = os.path.basename(clean_path)
    lookup_names = []
    match_uuid = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', base_name, re.I)
    if match_uuid:
        lookup_names.append(match_uuid.group(0))
    if '_' in base_name:
        lookup_names.append(base_name.split('_', 1)[-1])

    for look_n in lookup_names:
        for root, dirs, files in os.walk(document_root):
            for f in files:
                if (look_n in f or f == look_n or f.endswith('_' + look_n)) and not f.endswith('.tmp'):
                    cand = os.path.join(root, f)
                    if cand != target_full_path and os.path.exists(cand):
                        try:
                            os.makedirs(os.path.dirname(target_full_path), exist_ok=True)
                            shutil.copy2(cand, target_full_path)
                            return True
                        except Exception:
                            pass
                    break

    return os.path.exists(target_full_path)


def serve_media_with_cors(request, path, document_root=None, show_indexes=False):
    if request.method == 'OPTIONS':
        response = HttpResponse()
    else:
        try:
            response = serve(request, path, document_root=document_root, show_indexes=show_indexes)
        except Http404:
            if try_recover_missing_media(path, document_root):
                response = serve(request, path, document_root=document_root, show_indexes=show_indexes)
            else:
                raise
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response['Access-Control-Allow-Headers'] = '*'
    return response


urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve_media_with_cors, {'document_root': settings.MEDIA_ROOT}),
]


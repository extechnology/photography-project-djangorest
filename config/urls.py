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


_failed_recovery_cache = {}

def try_recover_missing_media(path, document_root):
    """
    Resilient self-healing helper for media requests.
    Fast, bounded lookup with negative result TTL cache to eliminate runaway disk I/O.
    """
    if not document_root or not path:
        return False

    now_ts = timezone.now().timestamp()
    # Check negative lookup cache (30 second TTL)
    if path in _failed_recovery_cache:
        failed_time = _failed_recovery_cache[path]
        if now_ts - failed_time < 30.0:
            return False

    target_full_path = os.path.normpath(os.path.join(document_root, path))
    if os.path.exists(target_full_path):
        return True

    clean_path = path.replace('\\', '/').lstrip('/')
    base_name = os.path.basename(clean_path)

    # 1. If requesting storage_objects/<key>
    if clean_path.startswith('storage_objects/'):
        key = clean_path[len('storage_objects/'):]
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
                            return True
                    except Exception as err:
                        logger.warning(f"Error transforming media from {source_file}: {err}")
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

    success = os.path.exists(target_full_path)
    if not success:
        _failed_recovery_cache[path] = now_ts
        # Prune cache if over 1000 items
        if len(_failed_recovery_cache) > 1000:
            oldest = [k for k, v in _failed_recovery_cache.items() if now_ts - v > 60.0]
            for k in oldest:
                _failed_recovery_cache.pop(k, None)

    return success


def serve_media_with_cors(request, path, document_root=None, show_indexes=False):
    if request.method == 'OPTIONS':
        response = HttpResponse()
    else:
        clean_p = path.replace('\\', '/').lstrip('/')
        target_full_path = os.path.normpath(os.path.join(document_root, path)) if document_root else None

        # Nginx X-Accel-Redirect zero-copy optimization if enabled
        use_x_accel = getattr(settings, 'USE_X_ACCEL_REDIRECT', False) or request.headers.get('X-Accel-Support') == 'true'
        if use_x_accel and target_full_path and os.path.exists(target_full_path):
            import mimetypes
            mime, _ = mimetypes.guess_type(target_full_path)
            response = HttpResponse()
            response['X-Accel-Redirect'] = f"/protected_media/{clean_p}"
            response['Content-Type'] = mime or 'application/octet-stream'
            response['Cache-Control'] = 'public, max-age=86400, stale-while-revalidate=604800'
            response['Access-Control-Allow-Origin'] = '*'
            response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
            response['Access-Control-Allow-Headers'] = '*'
            return response

        try:
            response = serve(request, path, document_root=document_root, show_indexes=show_indexes)
        except Http404:
            if try_recover_missing_media(path, document_root):
                response = serve(request, path, document_root=document_root, show_indexes=show_indexes)
            else:
                raise

        # Add browser caching headers for image/video media
        response['Cache-Control'] = 'public, max-age=86400, stale-while-revalidate=604800'

    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response['Access-Control-Allow-Headers'] = '*'
    return response


urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve_media_with_cors, {'document_root': settings.MEDIA_ROOT}),
]


import logging
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from App.Storage.storage_views import download_gallery_zip

logger = logging.getLogger(__name__)


class GalleryZipDownloadView(APIView):
    """
    GET /api/public/galleries/<str:id_or_slug>/download-zip/?format=raw|jpeg&watermark=true|false
    and
    GET /api/galleries/<uuid:gallery_id>/download-zip/?format=raw|jpeg&watermark=true|false
    
    Streams the entire gallery or selective media in a compressed ZIP archive.
    Guarantees Content-Disposition: attachment so the browser directly downloads the file.
    Supports format=raw vs format=jpeg and optional watermarking.
    """
    permission_classes = [AllowAny]

    def perform_content_negotiation(self, request, force=False):
        renderers = self.get_renderers()
        return (renderers[0], renderers[0].media_type)

    def get(self, request, id_or_slug=None, gallery_id=None, slug_or_id=None, *args, **kwargs):
        target = gallery_id or id_or_slug or slug_or_id or kwargs.get('pk') or kwargs.get('slug')
        return download_gallery_zip(request, id_or_slug=target, *args, **kwargs)



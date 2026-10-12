from django.urls import path
from .views.media_download import MediaDownloadView
from .views.gallery_zip_download import GalleryZipDownloadView

urlpatterns = [
    # Single media item download with format selection
    path('api/galleries/media/<uuid:media_id>/download/', MediaDownloadView.as_view(), name='gallery-media-download'),
    path('galleries/media/<uuid:media_id>/download/', MediaDownloadView.as_view(), name='gallery-media-download-rel'),
    
    # Public gallery ZIP download with format selection
    path('api/public/galleries/<str:id_or_slug>/download-zip/', GalleryZipDownloadView.as_view(), name='public-gallery-download-zip'),
    path('public/galleries/<str:id_or_slug>/download-zip/', GalleryZipDownloadView.as_view(), name='public-gallery-download-zip-rel'),
    
    # Dashboard gallery ZIP download with format selection
    path('api/galleries/<uuid:gallery_id>/download-zip/', GalleryZipDownloadView.as_view(), name='gallery-download-zip'),
    path('galleries/<uuid:gallery_id>/download-zip/', GalleryZipDownloadView.as_view(), name='gallery-download-zip-rel'),
]

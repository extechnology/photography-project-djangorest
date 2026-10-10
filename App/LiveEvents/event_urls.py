from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .event_views import LiveEventViewSet, PublicEventDetailView, EventFaceSearchView
from galleries.views_upload import (
    BulkUploadEventMediaView,
    EventUploadResumeStatusView,
)

router = DefaultRouter()
router.register(r'events', LiveEventViewSet, basename='events')

urlpatterns = [
    # 1. Public Guest Portal (accessible via QR code link without authentication)
    path('public/events/<str:id_or_slug>/', PublicEventDetailView.as_view(), name='public-event-detail'),
    path('events/public/<str:id_or_slug>/', PublicEventDetailView.as_view(), name='events-public-detail'),
    path('events/<str:id_or_slug>/public/', PublicEventDetailView.as_view(), name='events-detail-public-direct'),

    # 2. Face search routes (UUID and string slug)
    path('events/<uuid:event_id>/face-search/', EventFaceSearchView.as_view(), name='event-face-search'),
    path('events/<str:event_id>/face-search/', EventFaceSearchView.as_view(), name='event-face-search-str'),

    # 3. Batch Bulk Upload & Resume Status
    path('events/<uuid:event_id>/media/bulk-upload/', BulkUploadEventMediaView.as_view(), name='event-media-bulk-upload-uuid'),
    path('events/<str:event_id>/media/bulk-upload/', BulkUploadEventMediaView.as_view(), name='event-media-bulk-upload'),
    path('events/<uuid:event_id>/upload-status/', EventUploadResumeStatusView.as_view(), name='event-upload-status-uuid'),
    path('events/<str:event_id>/upload-status/', EventUploadResumeStatusView.as_view(), name='event-upload-status'),

    # 4. Router actions (includes events/, events/counts/, events/<pk>/, tether, upload, etc.)
    path('', include(router.urls)),
]

from django.urls import path
from .views import (
    PublicGalleryDetailView,
    PublicGalleryPinVerifyView,
    PublicGalleryDownloadZipView,
    PublicEventDetailView,
    PublicEventFaceSearchView,
    PlanCheckoutView,
    PlanVerifyView,
)

urlpatterns = [
    # Public Gallery endpoints (No login required - locked when studio subscription expired)
    path('galleries/<str:slug_or_id>/public/', PublicGalleryDetailView.as_view(), name='public-gallery-detail'),
    path('galleries/<str:slug_or_id>/verify-pin/', PublicGalleryPinVerifyView.as_view(), name='public-gallery-verify-pin'),
    path('galleries/<str:slug_or_id>/download-zip/', PublicGalleryDownloadZipView.as_view(), name='public-gallery-download-zip'),

    # Public Event endpoints (No login required - locked when studio subscription expired)
    path('events/<str:slug_or_id>/public/', PublicEventDetailView.as_view(), name='public-event-detail'),
    path('events/<str:slug_or_id>/face-search/', PublicEventFaceSearchView.as_view(), name='public-event-face-search'),

    # Billing & Plan Renewal endpoints
    path('plans/checkout/', PlanCheckoutView.as_view(), name='plan-checkout'),
    path('plans/verify/', PlanVerifyView.as_view(), name='plan-verify'),
]

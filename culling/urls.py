from django.urls import path, include
from .views import (
    CullingPricingTiersListView,
    ActiveCullingSessionView,
    CreateCullingPaymentOrderView,
    VerifyCullingPaymentView,
    UploadCullingPhotosView,
    SyncCullingSessionView,
    DiscardCullingSessionView,
    ExportCullingZipView,
    MoveCullingToGalleryView
)

urlpatterns = [
    # Dynamic Pricing Plans (Public)
    path('pricing-tiers/', CullingPricingTiersListView.as_view(), name='culling-pricing-tiers'),
    path('plans/', CullingPricingTiersListView.as_view(), name='culling-plans'),

    # Active Session Hydration (Persists state across navigation)
    path('sessions/active/', ActiveCullingSessionView.as_view(), name='culling-active-session'),

    # Upfront Payment Order & Verification
    path('checkout/order/', CreateCullingPaymentOrderView.as_view(), name='culling-checkout-order'),
    path('checkout/verify/', VerifyCullingPaymentView.as_view(), name='culling-checkout-verify'),

    # Staging Media Upload
    path('upload/', UploadCullingPhotosView.as_view(), name='culling-upload-photos'),

    # Analysis State Sync (Best picks, keep/discard overrides)
    path('sessions/<str:session_id>/sync/', SyncCullingSessionView.as_view(), name='culling-session-sync'),

    # ZIP Export (must be before session detail route)
    path('sessions/<str:session_id>/export-zip/', ExportCullingZipView.as_view(), name='culling-export-zip'),

    # Atomic Move to Gallery & Storage Free (must be before session detail route)
    path('sessions/<str:session_id>/move-to-gallery/', MoveCullingToGalleryView.as_view(), name='culling-move-gallery'),

    # Discard Session & Free Storage
    path('sessions/<str:session_id>/', DiscardCullingSessionView.as_view(), name='culling-session-discard'),

    # Legacy routes fallback
    path('legacy/', include('App.Culling.culling_urls')),
]

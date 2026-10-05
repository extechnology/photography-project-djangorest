from django.urls import path
from .views import (
    CullingPricingTierListView,
    ActiveCullingSessionView,
    CullingPhotoUploadView,
    CreateCullingPaymentOrderView,
    VerifyCullingPaymentView,
    SyncCullingSessionView,
    MoveCullingToGalleryView,
    DiscardCullingSessionView,
    ExportCullingZipView,
)

urlpatterns = [
    # 1. Dynamic Pricing Plans (Public)
    path("plans/", CullingPricingTierListView.as_view(), name="culling-plans"),
    path("pricing-tiers/", CullingPricingTierListView.as_view(), name="culling-pricing-tiers"),

    # 2. Active Session Hydration (Persists state across navigation)
    path("sessions/active/", ActiveCullingSessionView.as_view(), name="culling-session-active"),

    # 3. Direct Photo Staging Upload
    path("upload/", CullingPhotoUploadView.as_view(), name="culling-upload"),

    # 4. Razorpay Checkout & Upfront Unlock
    path("checkout/order/", CreateCullingPaymentOrderView.as_view(), name="culling-checkout-order"),
    path("checkout/verify/", VerifyCullingPaymentView.as_view(), name="culling-checkout-verify"),

    # 5. Curation Decisions Sync
    path("sessions/<str:session_id>/sync/", SyncCullingSessionView.as_view(), name="culling-session-sync"),

    # 6. Move Curated Winners to Studio Gallery
    path("sessions/<str:session_id>/move-to-gallery/", MoveCullingToGalleryView.as_view(), name="culling-move-gallery"),

    # 7. ZIP Export of Keepers
    path("sessions/<str:session_id>/export-zip/", ExportCullingZipView.as_view(), name="culling-export-zip"),

    # 8. Discard Session & Purge Disk Storage
    path("sessions/<str:session_id>/", DiscardCullingSessionView.as_view(), name="culling-session-discard"),
]

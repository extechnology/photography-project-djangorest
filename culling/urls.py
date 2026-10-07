# culling/urls.py
from django.urls import path
from .views import (
    UploadCullingPhotosView,
    ActiveCullingSessionView,
    CullingSessionDetailView,
    AnalyzeCullingSessionView,
    SyncCullingSessionView,
    MoveCullingToGalleryView,
    DiscardCullingSessionView,
    ExportCullingZipView,
    CullingPricingTierListView,
    CreateCullingPaymentOrderView,
    VerifyCullingPaymentView,
)

urlpatterns = [
    # 1. Multi-photo staging upload
    path("upload/", UploadCullingPhotosView.as_view(), name="culling-upload"),
    path("upload", UploadCullingPhotosView.as_view(), name="culling-upload-noslash"),
    path("sessions/<str:session_id>/upload-photos/", UploadCullingPhotosView.as_view(), name="culling-session-upload-photos"),
    path("sessions/<str:session_id>/upload-photos", UploadCullingPhotosView.as_view(), name="culling-session-upload-photos-noslash"),

    # 2. Active & Latest session restoration
    path("sessions/active/", ActiveCullingSessionView.as_view(), name="culling-session-active"),
    path("sessions/active", ActiveCullingSessionView.as_view(), name="culling-session-active-noslash"),
    path("sessions/latest/", CullingSessionDetailView.as_view(), name="culling-session-latest"),
    path("sessions/latest", CullingSessionDetailView.as_view(), name="culling-session-latest-noslash"),

    # 3. Server-side AI analysis trigger
    path("sessions/<str:session_id>/analyze/", AnalyzeCullingSessionView.as_view(), name="culling-session-analyze"),
    path("sessions/<str:session_id>/analyze", AnalyzeCullingSessionView.as_view(), name="culling-session-analyze-noslash"),
    path("analyze/", AnalyzeCullingSessionView.as_view(), name="culling-analyze-direct"),
    path("analyze", AnalyzeCullingSessionView.as_view(), name="culling-analyze-direct-noslash"),

    # 4. Session sync & curation state
    path("sessions/<str:session_id>/sync/", SyncCullingSessionView.as_view(), name="culling-session-sync"),
    path("sessions/<str:session_id>/sync", SyncCullingSessionView.as_view(), name="culling-session-sync-noslash"),
    path("sync/", SyncCullingSessionView.as_view(), name="culling-sync-direct"),
    path("sync", SyncCullingSessionView.as_view(), name="culling-sync-direct-noslash"),

    # 5. Move approved keepers to permanent gallery
    path("sessions/<str:session_id>/move-to-gallery/", MoveCullingToGalleryView.as_view(), name="culling-move-gallery"),
    path("sessions/<str:session_id>/move-to-gallery", MoveCullingToGalleryView.as_view(), name="culling-move-gallery-noslash"),
    path("move-to-gallery/", MoveCullingToGalleryView.as_view(), name="culling-move-gallery-direct"),
    path("move-to-gallery", MoveCullingToGalleryView.as_view(), name="culling-move-gallery-direct-noslash"),

    # 6. Discard session and purge staging storage
    path("sessions/<str:session_id>/discard/", DiscardCullingSessionView.as_view(), name="culling-session-discard-post"),
    path("sessions/<str:session_id>/discard", DiscardCullingSessionView.as_view(), name="culling-session-discard-post-noslash"),
    path("sessions/<str:session_id>/", CullingSessionDetailView.as_view(), name="culling-session-detail"),
    path("sessions/<str:session_id>", CullingSessionDetailView.as_view(), name="culling-session-detail-noslash"),

    # 7. Keepers ZIP export
    path("sessions/<str:session_id>/export-zip/", ExportCullingZipView.as_view(), name="culling-export-zip"),
    path("sessions/<str:session_id>/export-zip", ExportCullingZipView.as_view(), name="culling-export-zip-noslash"),

    # 8. Legacy Plan queries & Checkout (Maintained for backward compatibility)
    path("plans/", CullingPricingTierListView.as_view(), name="culling-plans"),
    path("pricing-tiers/", CullingPricingTierListView.as_view(), name="culling-pricing-tiers"),
    path("checkout/order/", CreateCullingPaymentOrderView.as_view(), name="culling-checkout-order"),
    path("checkout/order", CreateCullingPaymentOrderView.as_view(), name="culling-checkout-order-noslash"),
    path("checkout/verify/", VerifyCullingPaymentView.as_view(), name="culling-checkout-verify"),
    path("checkout/verify", VerifyCullingPaymentView.as_view(), name="culling-checkout-verify-noslash"),
    path("verify/", VerifyCullingPaymentView.as_view(), name="culling-verify"),
    path("verify", VerifyCullingPaymentView.as_view(), name="culling-verify-noslash"),
]

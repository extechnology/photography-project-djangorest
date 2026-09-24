from django.urls import path
from .sub_views import (
    PlanListView,
    CurrentSubscriptionView,
    CheckoutView,
    VerifyPaymentView,
    CancelAutoRenewView,
    UpgradeSubscriptionView,
    RazorpayWebhookView,
    StorageAddonView,
)

urlpatterns = [
    # Studio Plans public catalog
    path('', PlanListView.as_view(), name='plans-list'),
    path('plans/', PlanListView.as_view(), name='plans-list-alt'),

    # Current subscription & live quota metrics
    path('current/', CurrentSubscriptionView.as_view(), name='subscription-current'),

    # Checkout, Payment Verification & Webhook
    path('checkout/', CheckoutView.as_view(), name='subscription-checkout'),
    path('verify/', VerifyPaymentView.as_view(), name='subscription-verify'),
    path('webhook/', RazorpayWebhookView.as_view(), name='subscription-webhook'),
    path('cancel/', CancelAutoRenewView.as_view(), name='subscription-cancel'),
    path('storage-addon/', StorageAddonView.as_view(), name='subscription-storage-addon'),

    # Backward compatibility
    path('upgrade/', UpgradeSubscriptionView.as_view(), name='subscription-upgrade'),
]
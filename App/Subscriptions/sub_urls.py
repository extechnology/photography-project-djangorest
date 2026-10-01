from django.urls import path
from .views_razorpay import (
    StudioPlansListView,
    CurrentSubscriptionView,
    PlanCheckoutView,
    PlanVerifyView,
    CancelAutoRenewView,
    ResumeSubscriptionView,
    StorageAddonView,
    RazorpayWebhookView,
)
from backend.atelier_plans.subscription_enforcement import PlanUpgradeView

# Aliases for backward compatibility
PlanListView = StudioPlansListView
CheckoutView = PlanCheckoutView
VerifyPaymentView = PlanVerifyView
UpgradeSubscriptionView = PlanUpgradeView

urlpatterns = [
    # Studio Plans public catalog
    path('', StudioPlansListView.as_view(), name='plans-list'),
    path('plans/', StudioPlansListView.as_view(), name='plans-list-alt'),

    # Current subscription & live quota metrics
    path('current/', CurrentSubscriptionView.as_view(), name='subscription-current'),

    # Checkout, Payment Verification & Webhook
    path('checkout/', PlanCheckoutView.as_view(), name='subscription-checkout'),
    path('verify/', PlanVerifyView.as_view(), name='subscription-verify'),
    path('webhook/', RazorpayWebhookView.as_view(), name='subscription-webhook'),
    path('cancel/', CancelAutoRenewView.as_view(), name='subscription-cancel'),
    path('resume/', ResumeSubscriptionView.as_view(), name='subscription-resume'),
    path('storage-addon/', StorageAddonView.as_view(), name='subscription-storage-addon'),

    # Plan Upgrade & Renewal Enforcement
    path('upgrade/', PlanUpgradeView.as_view(), name='subscription-upgrade'),
]
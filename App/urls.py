from django.urls import path, include
from App.Subscriptions.sub_views import VerifyPaymentView, RazorpayWebhookView

urlpatterns = [
    path('auth/', include('App.Auth.auth_urls')),
    path('photographers/', include('App.Photographers.photo_urls')),
    path('plans/', include('App.Subscriptions.sub_urls')),
    path('notifications/', include('backend.atelier_notifications.urls')),
    path('music/', include('App.Music.music_urls')),

    # Master Admin Dashboard (STRICT REQUIREMENT: PRESERVED)
    path('admin/dashboard/', include('backend.admin_dashboard.urls')),

    # Payments & Webhook Callbacks
    path('payments/verify/', VerifyPaymentView.as_view(), name='payment-verify-direct'),
    path('payments/razorpay/webhook/', RazorpayWebhookView.as_view(), name='payment-webhook-direct'),

    # Live Events & Galleries Media Management
    path('', include('App.LiveEvents.event_urls')),
    path('', include('App.Storage.storage_urls')),
]

from django.urls import path, include
from App.Subscriptions.sub_views import VerifyPaymentView, RazorpayWebhookView

urlpatterns = [
    path('auth/', include('App.Auth.auth_urls')),
    path('photographers/', include('App.Photographers.photo_urls')),
    path('plans/', include('App.Subscriptions.sub_urls')),
    path('subscriptions/', include('App.Subscriptions.sub_urls')),
    path('storage/', include('App.Storage.storage_urls')),
    path('payments/verify/', VerifyPaymentView.as_view(), name='payment-verify-direct'),
    path('payments/razorpay/webhook/', RazorpayWebhookView.as_view(), name='payment-webhook-direct'),

    # Direct routes matching REST specification
    path('', include('App.Storage.storage_urls')),
]


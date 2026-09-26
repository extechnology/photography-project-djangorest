from django.urls import path, include
from App.Subscriptions.sub_views import VerifyPaymentView, RazorpayWebhookView
from App.Photographers.photo_views import InquiryListCreateView, InquiryAnalyticsView, InquiryDetailView

urlpatterns = [
    path('auth/', include('App.Auth.auth_urls')),
    path('photographers/', include('App.Photographers.photo_urls')),
    path('plans/', include('App.Subscriptions.sub_urls')),
    path('subscriptions/', include('App.Subscriptions.sub_urls')),
    path('storage/', include('App.Storage.storage_urls')),
    path('payments/verify/', VerifyPaymentView.as_view(), name='payment-verify-direct'),
    path('payments/razorpay/webhook/', RazorpayWebhookView.as_view(), name='payment-webhook-direct'),

    # Direct routes matching REST specification
    path('inquiries/analytics/', InquiryAnalyticsView.as_view(), name='inquiry-analytics-direct'),
    path('inquiries/', InquiryListCreateView.as_view(), name='inquiry-list-create-direct'),
    path('inquiries/<str:pk>/', InquiryDetailView.as_view(), name='inquiry-detail-direct'),
    path('', include('App.Storage.storage_urls')),
]


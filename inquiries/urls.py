from django.urls import path
from .views import (
    PublicInquirySubmitView,
    PhotographerInquiriesListView,
    InquiryStatusUpdateView,
    InquiryAnalyticsView,
)

urlpatterns = [
    # ─── Public Submission Endpoints (No Auth) ───
    path('api/public/inquiries/', PublicInquirySubmitView.as_view(), name='public-inquiry-submit'),
    path('public/inquiries/', PublicInquirySubmitView.as_view(), name='public-inquiry-submit-rel'),

    # ─── Authenticated Workshop Endpoints (Requires Login) ───
    path('api/inquiries/analytics/', InquiryAnalyticsView.as_view(), name='inquiries-analytics'),
    path('inquiries/analytics/', InquiryAnalyticsView.as_view(), name='inquiries-analytics-rel'),

    path('api/inquiries/', PhotographerInquiriesListView.as_view(), name='photographer-inquiries-list'),
    path('inquiries/', PhotographerInquiriesListView.as_view(), name='photographer-inquiries-list-rel'),

    # Detail, Status Update, and Lead Deletion (GET, PATCH, DELETE)
    path('api/inquiries/<int:pk>/', InquiryStatusUpdateView.as_view(), name='inquiry-detail-update'),
    path('inquiries/<int:pk>/', InquiryStatusUpdateView.as_view(), name='inquiry-detail-update-rel'),
    path('api/inquiries/<str:pk>/', InquiryStatusUpdateView.as_view(), name='inquiry-detail-update-str'),
    path('inquiries/<str:pk>/', InquiryStatusUpdateView.as_view(), name='inquiry-detail-update-str-rel'),
]

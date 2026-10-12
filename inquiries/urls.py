from django.urls import path
from .views import (
    PublicInquirySubmitView,
    PhotographerInquiriesListView,
    InquiryStatusUpdateView,
    InquiryDeleteView,
    InquiryAnalyticsView,
)

urlpatterns = [
    # ─── Public Submission Endpoints (No Auth) ───
    path('api/public/inquiries/', PublicInquirySubmitView.as_view(), name='public-inquiry-submit'),
    path('api/public/inquiries', PublicInquirySubmitView.as_view(), name='public-inquiry-submit-noslash'),
    path('public/inquiries/', PublicInquirySubmitView.as_view(), name='public-inquiry-submit-rel'),
    path('public/inquiries', PublicInquirySubmitView.as_view(), name='public-inquiry-submit-rel-noslash'),

    # ─── Authenticated Workshop Endpoints (Requires Login) ───
    path('api/inquiries/analytics/', InquiryAnalyticsView.as_view(), name='inquiries-analytics'),
    path('api/inquiries/analytics', InquiryAnalyticsView.as_view(), name='inquiries-analytics-noslash'),
    path('inquiries/analytics/', InquiryAnalyticsView.as_view(), name='inquiries-analytics-rel'),
    path('inquiries/analytics', InquiryAnalyticsView.as_view(), name='inquiries-analytics-rel-noslash'),

    path('api/inquiries/', PhotographerInquiriesListView.as_view(), name='photographer-inquiries-list'),
    path('api/inquiries', PhotographerInquiriesListView.as_view(), name='photographer-inquiries-list-noslash'),
    path('inquiries/', PhotographerInquiriesListView.as_view(), name='photographer-inquiries-list-rel'),
    path('inquiries', PhotographerInquiriesListView.as_view(), name='photographer-inquiries-list-rel-noslash'),

    path('api/inquiries/<int:pk>/', InquiryStatusUpdateView.as_view(), name='inquiry-detail-update'),
    path('api/inquiries/<int:pk>', InquiryStatusUpdateView.as_view(), name='inquiry-detail-update-noslash'),
    path('inquiries/<int:pk>/', InquiryStatusUpdateView.as_view(), name='inquiry-detail-update-rel'),
    path('inquiries/<int:pk>', InquiryStatusUpdateView.as_view(), name='inquiry-detail-update-rel-noslash'),

    path('api/inquiries/<int:pk>/delete/', InquiryDeleteView.as_view(), name='inquiry-delete'),
    path('inquiries/<int:pk>/delete/', InquiryDeleteView.as_view(), name='inquiry-delete-rel'),
]

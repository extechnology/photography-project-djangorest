from django.urls import path
from .views import (
    PortfolioConfigView,
    PublicPortfolioDetailView,
    PortfolioWorkListCreateView,
    PortfolioWorkDetailView,
    PortfolioWorkPhotosView,
    PortfolioWorkPhotoDetailView,
    PublicInquiryCreateView,
    PortfolioInquiryListView,
    PortfolioInquiryDetailView,
    PortfolioInquiryAnalyticsView,
    PortfolioAnalyticsView,
    PublicPortfolioTrackView,
    PortfolioSubdomainAvailabilityView,
    PortfolioSubdomainClaimView,
    PublicTenantPortfolioSiteView,
    PublicTenantInquiryCreateView,
    PublicTenantTrackView,
)


urlpatterns = [
    # 1 & 2. Portfolio Configuration (Studio branding, templates, socials)
    path('portfolio/config/', PortfolioConfigView.as_view(), name='portfolio-config'),
    path('portfolio/config', PortfolioConfigView.as_view(), name='portfolio-config-noslash'),
    path('config/', PortfolioConfigView.as_view(), name='portfolio-config-direct'),
    path('config', PortfolioConfigView.as_view(), name='portfolio-config-direct-noslash'),

    # Portfolio Live Analytics (Visitor metrics, top projects, device breakdown)
    path('portfolio/analytics/', PortfolioAnalyticsView.as_view(), name='portfolio-analytics'),
    path('portfolio/analytics', PortfolioAnalyticsView.as_view(), name='portfolio-analytics-noslash'),
    path('analytics/', PortfolioAnalyticsView.as_view(), name='portfolio-analytics-direct'),
    path('analytics', PortfolioAnalyticsView.as_view(), name='portfolio-analytics-direct-noslash'),

    # 3. Public Showcase Retrieval & Visitor Tracking
    path('public/portfolio/<str:slug_or_id>/track-view/', PublicPortfolioTrackView.as_view(), name='public-portfolio-track-view'),
    path('public/portfolio/<str:slug_or_id>/track-view', PublicPortfolioTrackView.as_view(), name='public-portfolio-track-view-noslash'),
    path('portfolio/track-view/', PublicPortfolioTrackView.as_view(), name='portfolio-track-view-fallback'),
    path('portfolio/track-view', PublicPortfolioTrackView.as_view(), name='portfolio-track-view-fallback-noslash'),
    path('track-view/', PublicPortfolioTrackView.as_view(), name='portfolio-track-view-direct'),
    path('track-view', PublicPortfolioTrackView.as_view(), name='portfolio-track-view-direct-noslash'),
    path('public/portfolio/<str:photographer_slug>/', PublicPortfolioDetailView.as_view(), name='public-portfolio-detail'),
    path('public/portfolio/<str:photographer_slug>', PublicPortfolioDetailView.as_view(), name='public-portfolio-detail-noslash'),
    path('public/portfolio/<str:slug>/', PublicPortfolioDetailView.as_view(), name='public-portfolio'),
    path('public/portfolio/<str:slug>', PublicPortfolioDetailView.as_view(), name='public-portfolio-noslash'),
    path('tenant/portfolio/', PublicTenantPortfolioSiteView.as_view(), name='tenant-portfolio'),
    path('tenant/portfolio', PublicTenantPortfolioSiteView.as_view(), name='tenant-portfolio-noslash'),

    # 4 & 7. Portfolio Projects / Featured Works
    path('portfolio/projects/', PortfolioWorkListCreateView.as_view(), name='portfolio-projects'),
    path('portfolio/projects', PortfolioWorkListCreateView.as_view(), name='portfolio-projects-noslash'),
    path('projects/', PortfolioWorkListCreateView.as_view(), name='portfolio-projects-direct'),
    path('projects', PortfolioWorkListCreateView.as_view(), name='portfolio-projects-direct-noslash'),
    path('portfolio/projects/<int:work_id>/', PortfolioWorkDetailView.as_view(), name='portfolio-project-detail'),
    path('portfolio/projects/<int:work_id>', PortfolioWorkDetailView.as_view(), name='portfolio-project-detail-noslash'),
    path('projects/<int:work_id>/', PortfolioWorkDetailView.as_view(), name='portfolio-project-detail-direct'),
    path('projects/<int:work_id>', PortfolioWorkDetailView.as_view(), name='portfolio-project-detail-direct-noslash'),

    # 5 & 6. Project Photos (Expandable Event Highlight Gallery)
    path('portfolio/projects/<int:work_id>/photos/', PortfolioWorkPhotosView.as_view(), name='portfolio-project-photos'),
    path('portfolio/projects/<int:work_id>/photos', PortfolioWorkPhotosView.as_view(), name='portfolio-project-photos-noslash'),
    path('projects/<int:work_id>/photos/', PortfolioWorkPhotosView.as_view(), name='portfolio-project-photos-direct'),
    path('projects/<int:work_id>/photos', PortfolioWorkPhotosView.as_view(), name='portfolio-project-photos-direct-noslash'),
    path('portfolio/projects/<int:work_id>/photos/<int:photo_id>/', PortfolioWorkPhotoDetailView.as_view(), name='portfolio-project-photo-detail'),
    path('portfolio/projects/<int:work_id>/photos/<int:photo_id>', PortfolioWorkPhotoDetailView.as_view(), name='portfolio-project-photo-detail-noslash'),
    path('projects/<int:work_id>/photos/<int:photo_id>/', PortfolioWorkPhotoDetailView.as_view(), name='portfolio-project-photo-detail-direct'),
    path('projects/<int:work_id>/photos/<int:photo_id>', PortfolioWorkPhotoDetailView.as_view(), name='portfolio-project-photo-detail-direct-noslash'),

    # 8. Public Client Inquiry Submission
    path('public/inquiries/', PublicInquiryCreateView.as_view(), name='public-inquiries-create'),
    path('public/inquiries', PublicInquiryCreateView.as_view(), name='public-inquiries-create-noslash'),

    # 9, 10 & Analytics. Inquiries Pipeline & Lead CRM
    path('inquiries/analytics/', PortfolioInquiryAnalyticsView.as_view(), name='portfolio-inquiry-analytics'),
    path('inquiries/analytics', PortfolioInquiryAnalyticsView.as_view(), name='portfolio-inquiry-analytics-noslash'),
    path('inquiries/', PortfolioInquiryListView.as_view(), name='portfolio-inquiries-list'),
    path('inquiries', PortfolioInquiryListView.as_view(), name='portfolio-inquiries-list-noslash'),
    path('inquiries/<str:pk>/', PortfolioInquiryDetailView.as_view(), name='portfolio-inquiry-detail'),
    path('inquiries/<str:pk>', PortfolioInquiryDetailView.as_view(), name='portfolio-inquiry-detail-noslash'),

    # 11. Photographer Portfolio Subdomain Suite
    path('portfolio/subdomain/availability/', PortfolioSubdomainAvailabilityView.as_view(), name='portfolio-subdomain-availability'),
    path('portfolio/subdomain/availability', PortfolioSubdomainAvailabilityView.as_view(), name='portfolio-subdomain-availability-noslash'),
    path('portfolio/subdomain/', PortfolioSubdomainClaimView.as_view(), name='portfolio-subdomain-claim'),
    path('portfolio/subdomain', PortfolioSubdomainClaimView.as_view(), name='portfolio-subdomain-claim-noslash'),

    # 12. Public Host-Based Tenant Portfolio Site
    path('public/portfolio-site/', PublicTenantPortfolioSiteView.as_view(), name='public-tenant-portfolio-site'),
    path('public/portfolio-site', PublicTenantPortfolioSiteView.as_view(), name='public-tenant-portfolio-site-noslash'),
    path('public/portfolio-site/inquiries/', PublicTenantInquiryCreateView.as_view(), name='public-tenant-portfolio-inquiries'),
    path('public/portfolio-site/inquiries', PublicTenantInquiryCreateView.as_view(), name='public-tenant-portfolio-inquiries-noslash'),
    path('public/portfolio-site/track-view/', PublicTenantTrackView.as_view(), name='public-tenant-portfolio-track-view'),
    path('public/portfolio-site/track-view', PublicTenantTrackView.as_view(), name='public-tenant-portfolio-track-view-noslash'),
]


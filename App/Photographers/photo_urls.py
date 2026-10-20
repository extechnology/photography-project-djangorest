from django.urls import path
from .photo_views import (
    MyPhotographerProfileGetView,
    MyPhotographerAvatarUploadView,
    MyPhotographerWatermarkView,
    PhotographerOnboardingView,
)

urlpatterns = [
    # -------------------------------------------------------------------------
    # Photographer Profiles & Studio Branding (Frontend Contract)
    # -------------------------------------------------------------------------
    path('onboarding/', PhotographerOnboardingView.as_view(), name='photographer-onboarding'),
    path('profiles/me/', MyPhotographerProfileGetView.as_view(), name='profile-me-get'),
    path('profiles/me/avatar/', MyPhotographerAvatarUploadView.as_view(), name='profile-me-avatar'),
    path('profiles/me/watermark/', MyPhotographerWatermarkView.as_view(), name='profile-me-watermark'),
]


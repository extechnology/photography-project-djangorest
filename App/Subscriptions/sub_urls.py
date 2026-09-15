from django.urls import path
from .sub_views import (
    SubscriptionPlansListView,
    CurrentSubscriptionView,
    UpgradeSubscriptionView,
)

urlpatterns = [
    path('plans/', SubscriptionPlansListView.as_view(), name='subscription-plans-list'),
    path('current/', CurrentSubscriptionView.as_view(), name='subscription-current'),
    path('upgrade/', UpgradeSubscriptionView.as_view(), name='subscription-upgrade'),
]
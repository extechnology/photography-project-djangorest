from django.urls import path
from .views import (
    AdminTokenObtainPairView,
    AdminOverviewView,
    AdminDashboardOverviewView,
    AdminUsersListView,
    AdminPaymentsListView,
    AdminGrowthAnalyticsView,
)

urlpatterns = [
    path('', AdminOverviewView.as_view(), name='admin_dashboard_root'),
    path('token/', AdminTokenObtainPairView.as_view(), name='admin_dashboard_token'),
    path('overview/', AdminOverviewView.as_view(), name='admin_dashboard_overview'),
    path('users/', AdminUsersListView.as_view(), name='admin_dashboard_users'),
    path('payments/', AdminPaymentsListView.as_view(), name='admin_dashboard_payments'),
    path('growth/', AdminGrowthAnalyticsView.as_view(), name='admin_dashboard_growth'),
]

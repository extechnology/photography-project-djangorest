from django.urls import path
from .views import (
    NotificationListView,
    MarkNotificationReadView,
    MarkAllNotificationsReadView,
    NotificationDeleteView,
    ClearAllNotificationsView,
    NotificationSettingsView,
)

urlpatterns = [
    # 1. Preferences & Channel Settings
    path('settings/', NotificationSettingsView.as_view(), name='notification-settings'),
    path('notifications/settings/', NotificationSettingsView.as_view(), name='notification-settings-prefixed'),

    # 2. Studio Notification Operations
    path('', NotificationListView.as_view(), name='notification-list'),
    path('notifications/', NotificationListView.as_view(), name='notification-list-prefixed'),

    # Mark all read
    path('mark-all-read/', MarkAllNotificationsReadView.as_view(), name='notification-mark-all-read'),
    path('notifications/mark-all-read/', MarkAllNotificationsReadView.as_view(), name='notification-mark-all-read-prefixed'),

    # Clear all
    path('clear-all/', ClearAllNotificationsView.as_view(), name='notification-clear-all'),
    path('notifications/clear-all/', ClearAllNotificationsView.as_view(), name='notification-clear-all-prefixed'),

    # Single notification read & delete (UUID and string supported)
    path('<uuid:notification_id>/read/', MarkNotificationReadView.as_view(), name='notification-read-uuid'),
    path('notifications/<uuid:notification_id>/read/', MarkNotificationReadView.as_view(), name='notification-read-uuid-prefixed'),
    path('<str:notification_id>/read/', MarkNotificationReadView.as_view(), name='notification-read-str'),
    path('notifications/<str:notification_id>/read/', MarkNotificationReadView.as_view(), name='notification-read-str-prefixed'),

    path('<uuid:notification_id>/', NotificationDeleteView.as_view(), name='notification-delete-uuid'),
    path('notifications/<uuid:notification_id>/', NotificationDeleteView.as_view(), name='notification-delete-uuid-prefixed'),
    path('<str:notification_id>/', NotificationDeleteView.as_view(), name='notification-delete-str'),
    path('notifications/<str:notification_id>/', NotificationDeleteView.as_view(), name='notification-delete-str-prefixed'),
]

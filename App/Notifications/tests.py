import uuid
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from App.Auth.auth_models import User
from backend.atelier_notifications.views import (
    StudioNotification,
    StudioNotificationSettings,
    notify_inquiry_received,
    notify_gallery_published,
    notify_plan_activated,
    notify_plan_cancelled,
    notify_storage_alert,
    notify_event_activity,
    seed_initial_studio_notifications,
)


class StudioNotificationsAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="atelier_photographer",
            email="atelier_photographer@example.com",
            password="testpassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_get_notification_settings_default(self):
        """GET /api/notifications/settings/ auto-creates and returns default 12 preferences."""
        resp = self.client.get("/api/notifications/settings/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "success")
        settings = resp.data["settings"]

        self.assertTrue(settings["email_inquiries"])
        self.assertTrue(settings["inapp_inquiries"])
        self.assertTrue(settings["email_gallery_visited"])
        self.assertTrue(settings["email_gallery_download"])
        self.assertTrue(settings["inapp_gallery_activity"])
        self.assertTrue(settings["email_event_activity"])
        self.assertTrue(settings["inapp_event_activity"])
        self.assertTrue(settings["email_billing_alerts"])
        self.assertTrue(settings["inapp_billing_alerts"])
        self.assertTrue(settings["email_storage_warnings"])
        self.assertTrue(settings["inapp_storage_warnings"])
        self.assertTrue(settings["email_weekly_digest"])

    def test_patch_notification_settings(self):
        """PATCH /api/notifications/settings/ updates preferences partially."""
        resp = self.client.patch("/api/notifications/settings/", {
            "email_inquiries": False,
            "inapp_storage_warnings": False,
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "success")
        self.assertFalse(resp.data["settings"]["email_inquiries"])
        self.assertFalse(resp.data["settings"]["inapp_storage_warnings"])
        self.assertTrue(resp.data["settings"]["email_gallery_download"])

        # Verify database state
        settings = StudioNotificationSettings.objects.get(user=self.user)
        self.assertFalse(settings.email_inquiries)
        self.assertFalse(settings.inapp_storage_warnings)

    def test_seed_initial_studio_notifications(self):
        """seed_initial_studio_notifications populates contextual notifications for new studio."""
        seed_initial_studio_notifications(self.user)
        self.assertEqual(StudioNotification.objects.filter(user=self.user).count(), 3)

        resp = self.client.get("/api/notifications/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["total_count"], 3)
        self.assertEqual(resp.data["unread_count"], 3)
        self.assertEqual(len(resp.data["results"]), 3)

        # Calling again does not duplicate
        seed_initial_studio_notifications(self.user)
        self.assertEqual(StudioNotification.objects.filter(user=self.user).count(), 3)

    def test_notification_list_filtering_and_limits(self):
        """GET /api/notifications/ supports filtering by read status, type, and limits."""
        seed_initial_studio_notifications(self.user)

        # Mark one notification as read
        first = StudioNotification.objects.filter(user=self.user).first()
        first.is_read = True
        first.save()

        # Unread filter
        resp_unread = self.client.get("/api/notifications/?is_read=false")
        self.assertEqual(resp_unread.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp_unread.data["results"]), 2)

        # Read filter
        resp_read = self.client.get("/api/notifications/?is_read=true")
        self.assertEqual(resp_read.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp_read.data["results"]), 1)

        # Type filter
        resp_type = self.client.get("/api/notifications/?type=inquiry")
        self.assertEqual(resp_type.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp_type.data["results"]), 1)
        self.assertEqual(resp_type.data["results"][0]["type"], "inquiry")

        # Limit filter
        resp_limit = self.client.get("/api/notifications/?limit=1")
        self.assertEqual(resp_limit.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp_limit.data["results"]), 1)

    def test_serializer_camel_case_and_time_ago(self):
        """StudioNotificationSerializer provides client-friendly camelCase fields and time_ago."""
        notif = StudioNotification.objects.create(
            user=self.user,
            type="gallery",
            title="Gallery Live",
            message="Client gallery ready",
            action_url="/dashboard/gallery",
            action_label="Open",
        )
        resp = self.client.get("/api/notifications/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.data["results"][0]

        self.assertIn("time_ago", item)
        self.assertEqual(item["time_ago"], "Just now")
        self.assertEqual(item["isRead"], False)
        self.assertEqual(item["actionUrl"], "/dashboard/gallery")
        self.assertEqual(item["actionLabel"], "Open")
        self.assertEqual(item["description"], "Client gallery ready")
        self.assertIn("createdAt", item)

    def test_mark_single_notification_read(self):
        """POST /api/notifications/<id>/read/ marks notification read and decrements unread_count."""
        seed_initial_studio_notifications(self.user)
        notif = StudioNotification.objects.filter(user=self.user, is_read=False).first()

        resp = self.client.post(f"/api/notifications/{notif.id}/read/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "success")
        self.assertEqual(resp.data["unread_count"], 2)
        self.assertTrue(resp.data["notification"]["is_read"])

        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_all_notifications_read(self):
        """POST /api/notifications/mark-all-read/ marks all notifications read atomically."""
        seed_initial_studio_notifications(self.user)
        self.assertEqual(StudioNotification.objects.filter(user=self.user, is_read=False).count(), 3)

        resp = self.client.post("/api/notifications/mark-all-read/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["unread_count"], 0)
        self.assertEqual(resp.data["updated_count"], 3)

        self.assertEqual(StudioNotification.objects.filter(user=self.user, is_read=False).count(), 0)

    def test_delete_single_notification(self):
        """DELETE /api/notifications/<id>/ removes single notification."""
        seed_initial_studio_notifications(self.user)
        notif = StudioNotification.objects.filter(user=self.user).first()
        notif_id = notif.id

        resp = self.client.delete(f"/api/notifications/{notif_id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(StudioNotification.objects.filter(id=notif_id).exists())
        self.assertEqual(StudioNotification.objects.filter(user=self.user).count(), 2)

    def test_clear_all_notifications(self):
        """DELETE /api/notifications/clear-all/ purges all notifications for user."""
        seed_initial_studio_notifications(self.user)
        self.assertEqual(StudioNotification.objects.filter(user=self.user).count(), 3)

        resp = self.client.delete("/api/notifications/clear-all/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["unread_count"], 0)
        self.assertEqual(resp.data["total_count"], 0)
        self.assertEqual(StudioNotification.objects.filter(user=self.user).count(), 0)

    def test_trigger_functions_respect_settings(self):
        """Trigger functions respect granular photographer preferences."""
        # 1. notify_inquiry_received
        inq_notif = notify_inquiry_received(
            self.user,
            client_name="Elena Vance",
            event_type="Editorial",
            budget="$3,200",
            inquiry_id="inq-123"
        )
        self.assertIsNotNone(inq_notif)
        self.assertEqual(inq_notif.type, "inquiry")
        self.assertIn("Elena Vance", inq_notif.title)
        self.assertEqual(inq_notif.priority, "high")

        # Disable inapp inquiries
        settings = StudioNotificationSettings.objects.get(user=self.user)
        settings.inapp_inquiries = False
        settings.save()

        suppressed = notify_inquiry_received(self.user, client_name="Bob", event_type="Portrait")
        self.assertIsNone(suppressed)

        # 2. notify_gallery_published
        gal_notif = notify_gallery_published(self.user, "Vogue Autumn 2026", gallery_id="gal-456")
        self.assertIsNotNone(gal_notif)
        self.assertEqual(gal_notif.type, "gallery")
        self.assertEqual(gal_notif.action_url, "/dashboard/gallery/gal-456")

        # 3. notify_plan_activated
        plan_notif = notify_plan_activated(self.user, "Studio Premium Elite", duration_months=12)
        self.assertIsNotNone(plan_notif)
        self.assertEqual(plan_notif.type, "plan")
        self.assertIn("12 month(s)", plan_notif.message)

        # 4. notify_plan_cancelled
        expiry = timezone.now() + timedelta(days=90)
        cancel_notif = notify_plan_cancelled(self.user, "Studio Premium Elite", expiry)
        self.assertIsNotNone(cancel_notif)
        self.assertEqual(cancel_notif.priority, "high")
        self.assertEqual(cancel_notif.action_label, "Restart Membership")

        # 5. notify_storage_alert
        storage_notif = notify_storage_alert(self.user, pct_used=87, used_gb=174, limit_gb=200)
        self.assertIsNotNone(storage_notif)
        self.assertEqual(storage_notif.priority, "high")

        urgent_storage = notify_storage_alert(self.user, pct_used=96, used_gb=192, limit_gb=200)
        self.assertEqual(urgent_storage.priority, "urgent")

        # 6. notify_event_activity
        event_notif = notify_event_activity(
            self.user,
            event_title="Grand Ballroom Gala",
            guest_name="Kavita",
            photo_count=5
        )
        self.assertIsNotNone(event_notif)
        self.assertEqual(event_notif.type, "event")
        self.assertIn("5 new photo(s)", event_notif.message)
        self.assertIn("by Kavita", event_notif.message)

    def test_cookie_authentication_support(self):
        """Authenticated request using HTTP-only cookie access_token succeeds."""
        refresh = RefreshToken.for_user(self.user)
        access_token = str(refresh.access_token)

        cookie_client = APIClient()
        cookie_client.cookies['access_token'] = access_token

        resp = cookie_client.get("/api/notifications/settings/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "success")

    def test_unauthenticated_request_returns_401(self):
        """Unauthenticated request without token or cookie returns 401 Unauthorized."""
        anon_client = APIClient()
        resp = anon_client.get("/api/notifications/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

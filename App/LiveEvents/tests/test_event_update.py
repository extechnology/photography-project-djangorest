from datetime import timedelta, date
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from App.LiveEvents.event_models import LiveEvent
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import Plan, PhotographerSubscription

User = get_user_model()


class LiveEventUpdateTests(APITestCase):
    def setUp(self):
        # Photographer 1
        self.user1 = User.objects.create_user(
            username="event_photographer_1",
            email="photo1@test.com",
            password="securepassword123"
        )
        self.profile1 = PhotographerProfile.objects.create(
            user=self.user1,
            name="Studio Luxe",
            email=self.user1.email,
        )

        # Photographer 2
        self.user2 = User.objects.create_user(
            username="event_photographer_2",
            email="photo2@test.com",
            password="securepassword123"
        )
        self.profile2 = PhotographerProfile.objects.create(
            user=self.user2,
            name="Studio Rival",
            email=self.user2.email,
        )

        # Create a sample event owned by user 1
        self.event = LiveEvent.objects.create(
            photographer=self.user1,
            title="Initial Wedding Shoot",
            client_name="Initial Client",
            client_contact="+1 000-000-0000",
            event_type="wedding",
            status="upcoming",
            venue="Initial Grand Hall",
            city="Mumbai",
            description="Initial event description.",
            qr_duration_hours=4,
            qr_valid_from=timezone.now(),
        )

    def test_partial_update_event_details(self):
        """Photographer updates event details via PATCH /api/events/{id}/."""
        self.client.force_authenticate(user=self.user1)

        payload = {
            "title": "Royal Palace Wedding • Ananya & Kabir",
            "client_name": "Ananya & Kabir Sharma",
            "client_contact": "+1 (555) 234-5678",
            "event_type": "sangeet",
            "status": "live",
            "venue": "The Oberoi Udaivilas",
            "city": "Udaipur, Rajasthan",
            "description": "Main royal wedding ceremony and sunset reception.",
            "banner_url": "https://example.com/banner.jpg",
        }

        resp = self.client.patch(f"/api/events/{self.event.id}/", payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        data = resp.data
        self.assertEqual(data["title"], payload["title"])
        self.assertEqual(data["client_name"], payload["client_name"])
        self.assertEqual(data["client_contact"], payload["client_contact"])
        self.assertEqual(data["event_type"], payload["event_type"])
        self.assertEqual(data["status"], payload["status"])
        self.assertEqual(data["venue"], payload["venue"])
        self.assertEqual(data["city"], payload["city"])
        self.assertEqual(data["description"], payload["description"])
        self.assertEqual(data["banner_url"], payload["banner_url"])

        # Verify DB persisted
        self.event.refresh_from_db()
        self.assertEqual(self.event.title, payload["title"])
        self.assertEqual(self.event.event_type, "sangeet")
        self.assertEqual(self.event.status, "live")
        self.assertEqual(self.event.city, "Udaipur, Rajasthan")

    def test_qr_duration_recalculation(self):
        """Updating qr_duration_hours updates QR expiration window."""
        self.client.force_authenticate(user=self.user1)

        resp = self.client.patch(f"/api/events/{self.event.id}/", {
            "qr_duration_hours": 8,
            "pin_code": "4821",
            "allow_guest_uploads": True,
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        qr_settings = resp.data.get("qr_settings") or resp.data.get("qrSettings")
        self.assertIsNotNone(qr_settings)
        self.assertEqual(qr_settings["duration_hours"], 8)
        self.assertEqual(qr_settings["pin_code"], "4821")
        self.assertTrue(qr_settings["allow_guest_uploads"])
        self.assertTrue(qr_settings["is_active"])

        self.event.refresh_from_db()
        self.assertEqual(self.event.qr_duration_hours, 8)
        self.assertEqual(self.event.qr_pin_code, "4821")
        self.assertTrue(self.event.allow_guest_uploads)

    def test_future_scheduled_event_recalculates_expiration(self):
        """Modifying event_date and event_time to a future date recalculates QR expiration."""
        self.client.force_authenticate(user=self.user1)

        future_date = (timezone.localdate() + timedelta(days=30)).isoformat()
        resp = self.client.patch(f"/api/events/{self.event.id}/", {
            "event_date": future_date,
            "event_time": "18:30",
            "qr_duration_hours": 4,
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.event.refresh_from_db()
        self.assertEqual(str(self.event.event_date), future_date)
        self.assertEqual(self.event.event_time, "18:30")
        # Expiration must be after the future event start date
        self.assertTrue(self.event.qr_expires_at > timezone.now())

    def test_patch_by_slug(self):
        """Supports updating event via string slug."""
        self.client.force_authenticate(user=self.user1)

        resp = self.client.patch(f"/api/events/{self.event.slug}/", {
            "title": "Updated Via Slug",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["title"], "Updated Via Slug")

        self.event.refresh_from_db()
        self.assertEqual(self.event.title, "Updated Via Slug")

    def test_ownership_isolation(self):
        """Photographer cannot update another photographer's event."""
        self.client.force_authenticate(user=self.user2)

        resp = self.client.patch(f"/api/events/{self.event.id}/", {
            "title": "Unauthorized Modification",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # DB remains unchanged
        self.event.refresh_from_db()
        self.assertEqual(self.event.title, "Initial Wedding Shoot")

    def test_unauthenticated_patch_rejected(self):
        """Unauthenticated requests are rejected with 401."""
        self.client.logout()

        resp = self.client.patch(f"/api/events/{self.event.id}/", {
            "title": "Anonymous Update",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_two_stage_delete_and_list_includes_trash(self):
        """Moving to trash sets status='trash' and event remains in list for frontend in-memory counting."""
        self.client.force_authenticate(user=self.user1)

        # 1. Soft Delete: DELETE /api/events/{id}/
        del_resp = self.client.delete(f"/api/events/{self.event.id}/")
        self.assertEqual(del_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(del_resp.data.get("success"))
        self.assertFalse(del_resp.data.get("permanent"))
        self.assertEqual(del_resp.data.get("status"), "trash")

        self.event.refresh_from_db()
        self.assertEqual(self.event.status, "trash")
        self.assertTrue(self.event.is_archived)
        self.assertIsNotNone(self.event.deleted_at)

        # 2. List Events: GET /api/events/ MUST include the trashed event
        list_resp = self.client.get("/api/events/")
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        events_list = list_resp.data.get("results", list_resp.data)
        trashed_event_in_list = next((e for e in events_list if e["id"] == str(self.event.id)), None)
        self.assertIsNotNone(trashed_event_in_list)
        self.assertEqual(trashed_event_in_list["status"], "trash")

        # 3. Filter by ?status=trash
        trash_resp = self.client.get("/api/events/?status=trash")
        self.assertEqual(trash_resp.status_code, status.HTTP_200_OK)
        trash_list = trash_resp.data.get("results", trash_resp.data)
        self.assertTrue(any(e["id"] == str(self.event.id) for e in trash_list))

        # 4. Restore Event: POST /api/events/{id}/restore/
        restore_resp = self.client.post(f"/api/events/{self.event.id}/restore/", {
            "target_status": "live"
        }, format="json")
        self.assertEqual(restore_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(restore_resp.data["status"], "live")

        self.event.refresh_from_db()
        self.assertEqual(self.event.status, "live")
        self.assertFalse(self.event.is_archived)
        self.assertIsNone(self.event.deleted_at)

        # 5. Permanent Purge: DELETE /api/events/{id}/?permanent=true
        purge_resp = self.client.delete(f"/api/events/{self.event.id}/?permanent=true")
        self.assertEqual(purge_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(purge_resp.data.get("permanent"))
        self.assertFalse(LiveEvent.objects.filter(id=self.event.id).exists())

    def test_purge_expired_trash_events_command(self):
        """Management command purges events in trash for > 15 days."""
        from django.core.management import call_command
        # Create an event in trash for 20 days
        old_trash_event = LiveEvent.objects.create(
            photographer=self.user1,
            title="Ancient Trashed Event",
            status="trash",
            is_archived=True,
            deleted_at=timezone.now() - timedelta(days=20),
        )

        # Create a recently trashed event (2 days ago)
        recent_trash_event = LiveEvent.objects.create(
            photographer=self.user1,
            title="Recent Trashed Event",
            status="trash",
            is_archived=True,
            deleted_at=timezone.now() - timedelta(days=2),
        )

        call_command("purge_expired_trash_events")

        self.assertFalse(LiveEvent.objects.filter(id=old_trash_event.id).exists())
        self.assertTrue(LiveEvent.objects.filter(id=recent_trash_event.id).exists())


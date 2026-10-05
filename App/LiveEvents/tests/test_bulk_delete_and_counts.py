import io
import uuid
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from App.LiveEvents.event_models import LiveEvent, EventMedia
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import Plan, PhotographerSubscription

User = get_user_model()


def create_dummy_image(name="test.jpg", color="blue", size=(100, 100)):
    file_obj = io.BytesIO()
    image = Image.new("RGB", size, color=color)
    image.save(file_obj, format="JPEG")
    file_obj.seek(0)
    return SimpleUploadedFile(name, file_obj.read(), content_type="image/jpeg")


class LiveEventBulkDeleteAndCountsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="event_tester",
            email="event_tester@example.com",
            password="password123"
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Event Tester",
            email=self.user.email,
            studio_name="Event Studios",
            storage_used_bytes=5000000
        )
        self.plan = Plan.objects.create(
            id="event-pro-plan",
            name="Event Pro Plan",
            max_events=10,
            is_active=True
        )
        self.subscription = PhotographerSubscription.objects.create(
            photographer=self.profile,
            plan=self.plan,
            status="active"
        )
        self.client.force_authenticate(user=self.user)

        self.event = LiveEvent.objects.create(
            photographer=self.user,
            title="Corporate Gala 2026",
            slug="corporate-gala-2026",
            status="live"
        )

        # Create 5 photos: 2 in HIGHLIGHTS, 2 in CEREMONY, 1 in PARTY
        self.m1 = EventMedia.objects.create(
            event=self.event,
            original_filename="img1.jpg",
            file=create_dummy_image("img1.jpg"),
            section_title="HIGHLIGHTS",
            media_type="photo",
            file_size=100000
        )
        self.m2 = EventMedia.objects.create(
            event=self.event,
            original_filename="img2.jpg",
            file=create_dummy_image("img2.jpg"),
            section_title="HIGHLIGHTS",
            media_type="photo",
            file_size=150000
        )
        self.m3 = EventMedia.objects.create(
            event=self.event,
            original_filename="img3.jpg",
            file=create_dummy_image("img3.jpg"),
            section_title="CEREMONY",
            media_type="photo",
            file_size=200000
        )
        self.m4 = EventMedia.objects.create(
            event=self.event,
            original_filename="img4.jpg",
            file=create_dummy_image("img4.jpg"),
            section_title="CEREMONY",
            media_type="photo",
            file_size=250000
        )
        self.m5 = EventMedia.objects.create(
            event=self.event,
            original_filename="video1.mp4",
            file=SimpleUploadedFile("video1.mp4", b"dummy video content", content_type="video/mp4"),
            section_title="PARTY",
            media_type="video",
            file_size=300000
        )

    def test_get_event_detail_counts_and_section_breakdown(self):
        url = f"/api/events/{self.event.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data
        self.assertEqual(data["id"], str(self.event.id))
        self.assertEqual(data["title"], "Corporate Gala 2026")
        self.assertEqual(data["slug"], "corporate-gala-2026")
        self.assertEqual(data["total_media_count"], 5)
        self.assertEqual(data["photos_count"], 4)
        self.assertEqual(data["videos_count"], 1)

        # Verify section breakdown counts
        section_counts = data.get("section_counts", {})
        self.assertEqual(section_counts.get("HIGHLIGHTS"), 2)
        self.assertEqual(section_counts.get("CEREMONY"), 2)
        self.assertEqual(section_counts.get("PARTY"), 1)

        # Verify media list items contain type and size_bytes
        self.assertEqual(len(data["media"]), 5)
        first_media = data["media"][0]
        self.assertIn("type", first_media)
        self.assertIn("size_bytes", first_media)

    def test_get_event_with_all_media_and_section_filter(self):
        # Query with section filter
        url = f"/api/events/{self.event.slug}/?section=CEREMONY&all_media=true"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data
        self.assertEqual(data["total_media_count"], 5)  # Overall total preserved
        self.assertEqual(len(data["media"]), 2)
        for item in data["media"]:
            self.assertEqual(item["section_title"].upper(), "CEREMONY")

    def test_bulk_delete_specific_media_ids(self):
        url = f"/api/events/{self.event.id}/media/bulk-delete/"
        payload = {
            "media_ids": [str(self.m1.id), str(self.m2.id)]
        }
        initial_storage = self.profile.storage_used_bytes
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data["deleted_count"], 2)
        self.assertEqual(response.data["freed_bytes"], 250000)
        self.assertFalse(EventMedia.objects.filter(id__in=[self.m1.id, self.m2.id]).exists())
        self.assertEqual(self.event.media.count(), 3)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.storage_used_bytes, initial_storage - 250000)

    def test_bulk_delete_all_by_section(self):
        url = f"/api/events/{self.event.id}/media/bulk-delete/"
        payload = {
            "delete_all": True,
            "section": "CEREMONY"
        }
        initial_storage = self.profile.storage_used_bytes
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data["deleted_count"], 2)
        self.assertEqual(response.data["freed_bytes"], 450000)
        self.assertFalse(EventMedia.objects.filter(section_title="CEREMONY", event=self.event).exists())
        self.assertEqual(self.event.media.count(), 3)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.storage_used_bytes, initial_storage - 450000)

    def test_bulk_delete_all_event_media(self):
        url = f"/api/events/{self.event.id}/media/bulk-delete/"
        payload = {
            "delete_all": True
        }
        initial_storage = self.profile.storage_used_bytes
        total_event_bytes = 100000 + 150000 + 200000 + 250000 + 300000

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data["deleted_count"], 5)
        self.assertEqual(response.data["freed_bytes"], total_event_bytes)
        self.assertEqual(self.event.media.count(), 0)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.storage_used_bytes, initial_storage - total_event_bytes)

    def test_bulk_delete_collection_endpoint_with_event_id(self):
        url = "/api/events/media/bulk-delete/"
        payload = {
            "event_id": str(self.event.id),
            "media_ids": [str(self.m5.id)]
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["deleted_count"], 1)
        self.assertFalse(EventMedia.objects.filter(id=self.m5.id).exists())

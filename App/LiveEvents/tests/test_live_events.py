import io
import uuid
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from App.LiveEvents.event_models import LiveEvent, EventMedia, EventFaceEmbedding
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import Plan, PhotographerSubscription
from App.Storage.storage_models import Gallery, Media as GalleryMedia, GallerySection

User = get_user_model()


def create_dummy_image(name="test.jpg", color="blue", size=(200, 200)):
    file_obj = io.BytesIO()
    image = Image.new("RGB", size, color=color)
    image.save(file_obj, format="JPEG")
    file_obj.seek(0)
    return SimpleUploadedFile(name, file_obj.read(), content_type="image/jpeg")


class LiveEventEngineTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="test_photographer",
            email="photographer@test.com",
            password="securepassword123"
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Test Photographer",
            email=self.user.email,
            studio_name="Luxe Studios"
        )
        self.plan = Plan.objects.create(
            id="test-pro-plan",
            name="Test Pro Plan",
            max_events=2,
            is_active=True
        )
        self.subscription = PhotographerSubscription.objects.create(
            photographer=self.profile,
            plan=self.plan,
            status="active"
        )
        self.client.force_authenticate(user=self.user)

    def test_create_event_and_quota_enforcement(self):
        # 1. Create Event 1 (Success)
        res1 = self.client.post("/api/events/", {
            "title": "Royal Palace Wedding",
            "client_name": "Alexander & Victoria",
            "event_type": "wedding",
            "status": "live",
            "venue": "Palace Grounds",
            "qr_duration_hours": 48
        }, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res1.data["title"], "Royal Palace Wedding")
        self.assertIn("qrSettings", res1.data)
        self.assertIn("stats", res1.data)
        event1_id = res1.data["id"]

        # 2. Create Event 2 (Success - reaches max quota of 2)
        res2 = self.client.post("/api/events/", {
            "title": "Corporate Summit 2026",
            "client_name": "Tech Corp",
            "event_type": "corporate",
            "status": "upcoming",
            "venue": "Convention Center"
        }, format="json")
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)

        # 3. Create Event 3 (Should fail with 403 EVENT_LIMIT_EXCEEDED)
        res3 = self.client.post("/api/events/", {
            "title": "Fashion Week Gala",
            "event_type": "fashion"
        }, format="json")
        self.assertEqual(res3.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res3.data.get("error_code"), "EVENT_LIMIT_EXCEEDED")

    def test_list_status_filters_and_counts(self):
        e_live = LiveEvent.objects.create(
            photographer=self.user, title="Live Event", status="live"
        )
        e_upcoming = LiveEvent.objects.create(
            photographer=self.user, title="Upcoming Event", status="upcoming"
        )
        e_past = LiveEvent.objects.create(
            photographer=self.user, title="Past Event", status="completed"
        )
        e_trash = LiveEvent.objects.create(
            photographer=self.user, title="Trashed Event", status="trash", is_archived=True
        )

        # Tab counts
        res_counts = self.client.get("/api/events/counts/")
        self.assertEqual(res_counts.status_code, status.HTTP_200_OK)
        self.assertEqual(res_counts.data["live"], 1)
        self.assertEqual(res_counts.data["upcoming"], 1)
        self.assertEqual(res_counts.data["past"], 1)
        self.assertEqual(res_counts.data["trash"], 1)
        self.assertEqual(res_counts.data["all"], 3)

        # Filters
        res_live = self.client.get("/api/events/?status=live")
        self.assertEqual(len(res_live.data["results"] if "results" in res_live.data else res_live.data), 1)

        res_trash = self.client.get("/api/events/?status=trash")
        self.assertEqual(len(res_trash.data["results"] if "results" in res_trash.data else res_trash.data), 1)

    def test_tether_photo_ingestion(self):
        event = LiveEvent.objects.create(
            photographer=self.user, title="Gala Night", status="live"
        )
        dummy_img = create_dummy_image("shot_001.jpg", color="red")
        res = self.client.post(f"/api/events/{event.id}/tether/", {
            "photo": dummy_img,
            "section_title": "CEREMONY"
        }, format="multipart")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["original_filename"], "shot_001.jpg")
        self.assertEqual(res.data["sectionTitle"], "CEREMONY")
        self.assertTrue(EventMedia.objects.filter(event=event).exists())

        # Test deleting media item
        media_id = res.data["id"]
        del_res = self.client.delete(f"/api/events/{event.id}/media/{media_id}/")
        self.assertEqual(del_res.status_code, status.HTTP_200_OK)
        self.assertFalse(EventMedia.objects.filter(id=media_id).exists())

    def test_soft_delete_restore_and_permanent_delete(self):
        event = LiveEvent.objects.create(
            photographer=self.user, title="Birthday Bash", status="live"
        )
        # 1. Soft delete into trash
        del_res = self.client.delete(f"/api/events/{event.id}/")
        self.assertEqual(del_res.status_code, status.HTTP_200_OK)
        event.refresh_from_db()
        self.assertTrue(event.is_archived)
        self.assertEqual(event.status, "trash")

        # 2. Restore event back to upcoming
        restore_res = self.client.post(f"/api/events/{event.id}/restore/", {
            "target_status": "upcoming"
        }, format="json")
        self.assertEqual(restore_res.status_code, status.HTTP_200_OK)
        event.refresh_from_db()
        self.assertFalse(event.is_archived)
        self.assertEqual(event.status, "upcoming")

        # 3. Permanent delete with ?permanent=true
        perm_res = self.client.delete(f"/api/events/{event.id}/?permanent=true")
        self.assertEqual(perm_res.status_code, status.HTTP_200_OK)
        self.assertFalse(LiveEvent.objects.filter(id=event.id).exists())

    def test_move_event_to_gallery(self):
        event = LiveEvent.objects.create(
            photographer=self.user, title="Elite Fashion Soiree", status="completed"
        )
        dummy_img = create_dummy_image("model_1.jpg")
        media = EventMedia.objects.create(
            event=event,
            original_filename="model_1.jpg",
            file=dummy_img,
            section_title="RUNWAY",
            size_mb=2.5
        )

        res = self.client.post(f"/api/events/{event.id}/move-to-gallery/", {
            "target_mode": "new",
            "new_gallery_title": "Elite Fashion Drive Gallery",
            "category_assignments": {str(media.id): "STAGE"}
        }, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(Gallery.objects.filter(title="Elite Fashion Drive Gallery").exists())
        # Event is permanently deleted from LiveEvents
        self.assertFalse(LiveEvent.objects.filter(id=event.id).exists())
        # Media moved into GalleryMedia with mapped section
        self.assertTrue(GalleryMedia.objects.filter(section_title="STAGE").exists())

    def test_public_event_portal_strict_privacy(self):
        event = LiveEvent.objects.create(
            photographer=self.user,
            title="VIP Private Gala",
            client_name="High Profile Client",
            status="live"
        )
        dummy_img = create_dummy_image("confidential_guest.jpg")
        EventMedia.objects.create(
            event=event,
            original_filename="confidential_guest.jpg",
            file=dummy_img,
            section_title="VIP"
        )

        # Anonymous Guest Access
        self.client.logout()
        pub_res = self.client.get(f"/api/public/events/{event.slug}/")
        self.assertEqual(pub_res.status_code, status.HTTP_200_OK)
        # Check that event photos are STRICTLY omitted
        self.assertNotIn("media", pub_res.data)
        self.assertNotIn("photos", pub_res.data)
        self.assertEqual(pub_res.data["title"], "VIP Private Gala")
        self.assertIn("qrSettings", pub_res.data)
        self.assertFalse(pub_res.data["isExpired"])

    def test_biometric_face_search(self):
        event = LiveEvent.objects.create(
            photographer=self.user, title="Music Festival", status="live"
        )
        dummy_img = create_dummy_image("festival_crowd.jpg", color="blue")
        media = EventMedia.objects.create(
            event=event,
            original_filename="festival_crowd.jpg",
            file=dummy_img,
            section_title="STAGE"
        )

        # Ingest face embedding for media photo
        from App.LiveEvents.event_tasks import process_face_embeddings_task
        process_face_embeddings_task(str(media.id))

        self.client.logout()
        # Guest uploads selfie matching festival_crowd
        selfie_img = create_dummy_image("guest_selfie.jpg", color="blue")
        search_res = self.client.post(f"/api/events/{event.id}/face-search/", {
            "selfie": selfie_img
        }, format="multipart")

        self.assertEqual(search_res.status_code, status.HTTP_200_OK)
        self.assertIn("matched_media_ids", search_res.data)
        self.assertIn("total_matches", search_res.data)
        self.assertIn("confidence", search_res.data)
        # Since dummy image colors and dimensions align, matcher finds match
        self.assertGreaterEqual(search_res.data["total_matches"], 1)
        self.assertIn(str(media.id), search_res.data["matched_media_ids"])

    def test_slug_resolution_for_photographer_and_public(self):
        event = LiveEvent.objects.create(
            photographer=self.user,
            title="Sample Gala Party",
            slug="sample-e133fb",
            status="live"
        )

        # 1. Photographer retrieval by slug
        res_priv = self.client.get(f"/api/events/{event.slug}/")
        self.assertEqual(res_priv.status_code, status.HTTP_200_OK)
        self.assertEqual(res_priv.data["id"], str(event.id))
        self.assertEqual(res_priv.data["slug"], "sample-e133fb")

        # 2. Public portal retrieval by slug
        self.client.logout()
        res_pub = self.client.get(f"/api/public/events/{event.slug}/")
        self.assertEqual(res_pub.status_code, status.HTTP_200_OK)
        self.assertEqual(res_pub.data["slug"], "sample-e133fb")

    def test_video_tether_upload(self):
        event = LiveEvent.objects.create(
            photographer=self.user, title="Reel Event", status="live"
        )
        dummy_video = SimpleUploadedFile("highlight_reel.mp4", b"fake mp4 video bytes", content_type="video/mp4")
        res = self.client.post(f"/api/events/{event.id}/tether/", {
            "video": dummy_video,
            "section_title": "HIGHLIGHTS"
        }, format="multipart")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["original_filename"], "highlight_reel.mp4")
        self.assertEqual(res.data["sectionTitle"], "HIGHLIGHTS")
        self.assertTrue(EventMedia.objects.filter(event=event, original_filename="highlight_reel.mp4").exists())

    def test_batch_upload_photos_and_videos(self):
        event = LiveEvent.objects.create(
            photographer=self.user, title="Wedding Festival", status="live"
        )
        p1 = create_dummy_image("p1.jpg")
        p2 = create_dummy_image("p2.jpg")
        v1 = SimpleUploadedFile("v1.mp4", b"fake video bytes", content_type="video/mp4")

        res = self.client.post(f"/api/events/{event.slug}/upload/", {
            "photos": [p1, p2],
            "videos": [v1],
            "section_title": "CEREMONY"
        }, format="multipart")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["total_uploaded"], 3)
        self.assertEqual(len(res.data["media"]), 3)
        self.assertEqual(event.media.count(), 3)


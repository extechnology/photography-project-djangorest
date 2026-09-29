import io
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from App.utils import format_bytes_human
from App.LiveEvents.event_models import LiveEvent, EventMedia
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import Plan, PhotographerSubscription
from App.Storage.storage_models import Gallery, Media as GalleryMedia

User = get_user_model()


def create_dummy_image(name="test.jpg", color="blue", size=(200, 200)):
    file_obj = io.BytesIO()
    image = Image.new("RGB", size, color=color)
    image.save(file_obj, format="JPEG")
    file_obj.seek(0)
    return SimpleUploadedFile(name, file_obj.read(), content_type="image/jpeg")


class RealTimeStorageMetricsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="metrics_photographer",
            email="metrics@test.com",
            password="securepassword123"
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Metrics Photographer",
            email=self.user.email,
            studio_name="Metrics Studios"
        )
        self.plan = Plan.objects.create(
            id="metrics-unlimited-plan",
            name="Metrics Pro Plan",
            max_events=10,
            max_galleries=10,
            is_active=True
        )
        self.subscription = PhotographerSubscription.objects.create(
            photographer=self.profile,
            plan=self.plan,
            status="active"
        )
        self.client.force_authenticate(user=self.user)

    def test_format_bytes_human_utility(self):
        self.assertEqual(format_bytes_human(None), "0 MB")
        self.assertEqual(format_bytes_human(0), "0 MB")
        self.assertEqual(format_bytes_human(-100), "0 MB")
        self.assertEqual(format_bytes_human(500), "500 B")
        self.assertEqual(format_bytes_human(1024), "1.0 KB")
        self.assertEqual(format_bytes_human(1536), "1.5 KB")
        self.assertEqual(format_bytes_human(1024 * 1024), "1.0 MB")
        self.assertEqual(format_bytes_human(358875136), "342.2 MB")
        self.assertEqual(format_bytes_human(1024 * 1024 * 1024), "1.0 GB")
        self.assertEqual(format_bytes_human(1153433600), "1.07 GB")

    def test_gallery_storage_metrics_and_counts(self):
        # 1. Create Gallery
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Aarav & Ananya Wedding",
            client_name="Aarav Sharma"
        )

        # Initially empty
        self.assertEqual(gallery.total_size_bytes, 0)
        self.assertEqual(gallery.total_size_mb, 0.0)
        self.assertEqual(gallery.total_size_formatted, "0 MB")
        self.assertEqual(gallery.photos_count, 0)
        self.assertEqual(gallery.videos_count, 0)
        self.assertEqual(gallery.total_media_count, 0)

        # 2. Add 2 photos and 1 video to gallery
        photo1 = GalleryMedia.objects.create(
            photographer=self.profile,
            gallery=gallery,
            original_filename="photo1.jpg",
            media_type="photo",
            file_size=10485760,  # 10 MB
            display_order=1
        )
        photo2 = GalleryMedia.objects.create(
            photographer=self.profile,
            gallery=gallery,
            original_filename="photo2.jpg",
            media_type="photo",
            file_size=20971520,  # 20 MB
            display_order=2
        )
        video1 = GalleryMedia.objects.create(
            photographer=self.profile,
            gallery=gallery,
            original_filename="video1.mp4",
            media_type="video",
            file_size=52428800,  # 50 MB
            display_order=3
        )

        # Media properties
        self.assertEqual(photo1.size_mb, 10.0)
        self.assertEqual(photo2.size_mb, 20.0)
        self.assertEqual(video1.size_mb, 50.0)

        # Gallery properties
        self.assertEqual(gallery.photos_count, 2)
        self.assertEqual(gallery.videos_count, 1)
        self.assertEqual(gallery.total_media_count, 3)
        self.assertEqual(gallery.total_size_bytes, 83886080)  # 80 MB
        self.assertEqual(gallery.total_size_mb, 80.0)
        self.assertEqual(gallery.total_size_formatted, "80.0 MB")

        # Test GET /api/galleries/ (list)
        list_res = self.client.get("/api/galleries/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        g_data = next(g for g in list_res.data if g['id'] == str(gallery.id))
        self.assertEqual(g_data['photos_count'], 2)
        self.assertEqual(g_data['videos_count'], 1)
        self.assertEqual(g_data['total_media_count'], 3)
        self.assertEqual(g_data['total_size_bytes'], 83886080)
        self.assertEqual(g_data['total_size_mb'], 80.0)
        self.assertEqual(g_data['total_size_formatted'], "80.0 MB")

        # Test GET /api/galleries/{id}/ (detail)
        detail_res = self.client.get(f"/api/galleries/{gallery.id}/")
        self.assertEqual(detail_res.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_res.data['photos_count'], 2)
        self.assertEqual(detail_res.data['videos_count'], 1)
        self.assertEqual(detail_res.data['total_media_count'], 3)
        self.assertEqual(detail_res.data['total_size_bytes'], 83886080)
        self.assertEqual(detail_res.data['total_size_mb'], 80.0)
        self.assertEqual(detail_res.data['total_size_formatted'], "80.0 MB")

        # Test GET /api/galleries/{id}/media/
        media_res = self.client.get(f"/api/galleries/{gallery.id}/media/")
        self.assertEqual(media_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(media_res.data), 3)
        m0 = media_res.data[0]
        self.assertIn('file_size', m0)
        self.assertIn('size_mb', m0)

        # Test GET /api/public/galleries/{slug}/
        public_res = self.client.get(f"/api/public/galleries/{gallery.slug}/")
        self.assertEqual(public_res.status_code, status.HTTP_200_OK)
        self.assertEqual(public_res.data['photos_count'], 2)
        self.assertEqual(public_res.data['videos_count'], 1)
        self.assertEqual(public_res.data['total_media_count'], 3)
        self.assertEqual(public_res.data['total_size_bytes'], 83886080)
        self.assertEqual(public_res.data['total_size_mb'], 80.0)
        self.assertEqual(public_res.data['total_size_formatted'], "80.0 MB")

    def test_live_event_storage_metrics_and_counts(self):
        # 1. Create Live Event
        event = LiveEvent.objects.create(
            photographer=self.user,
            title="Zara & Dev Sangeet Night",
            client_name="Zara Patel",
            status="live"
        )

        # Initially empty
        self.assertEqual(event.total_size_bytes, 0)
        self.assertEqual(event.total_size_mb, 0.0)
        self.assertEqual(event.total_size_formatted, "0 MB")
        self.assertEqual(event.photos_count, 0)
        self.assertEqual(event.videos_count, 0)
        self.assertEqual(event.total_media_count, 0)

        # 2. Add media
        m1 = EventMedia.objects.create(
            event=event,
            original_filename="dance_photo1.jpg",
            media_type="photo",
            file_size=5242880,  # 5 MB
            size_mb=5.0
        )
        m2 = EventMedia.objects.create(
            event=event,
            original_filename="performance_clip.mp4",
            media_type="video",
            file_size=26214400,  # 25 MB
            size_mb=25.0
        )

        # Properties
        self.assertEqual(event.photos_count, 1)
        self.assertEqual(event.videos_count, 1)
        self.assertEqual(event.total_media_count, 2)
        self.assertEqual(event.total_size_bytes, 31457280)  # 30 MB
        self.assertEqual(event.total_size_mb, 30.0)
        self.assertEqual(event.total_size_formatted, "30.0 MB")

        # Test GET /api/events/ (list)
        list_res = self.client.get("/api/events/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        evt_list = list_res.data.get('results', list_res.data)
        evt_data = next(e for e in evt_list if e['id'] == str(event.id))
        self.assertEqual(evt_data['photos_count'], 1)
        self.assertEqual(evt_data['videos_count'], 1)
        self.assertEqual(evt_data['total_media_count'], 2)
        self.assertEqual(evt_data['total_size_bytes'], 31457280)
        self.assertEqual(evt_data['total_size_mb'], 30.0)
        self.assertEqual(evt_data['total_size_formatted'], "30.0 MB")

        # Test GET /api/events/{id}/ (detail)
        detail_res = self.client.get(f"/api/events/{event.id}/")
        self.assertEqual(detail_res.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_res.data['photos_count'], 1)
        self.assertEqual(detail_res.data['videos_count'], 1)
        self.assertEqual(detail_res.data['total_media_count'], 2)
        self.assertEqual(detail_res.data['total_size_bytes'], 31457280)
        self.assertEqual(detail_res.data['total_size_mb'], 30.0)
        self.assertEqual(detail_res.data['total_size_formatted'], "30.0 MB")

        # Test GET /api/events/{id}/media/
        media_res = self.client.get(f"/api/events/{event.id}/media/")
        self.assertEqual(media_res.status_code, status.HTTP_200_OK)
        m_list = media_res.data if isinstance(media_res.data, list) else media_res.data.get('results', [])
        self.assertEqual(len(m_list), 2)
        first_m = m_list[0]
        self.assertIn('file_size', first_m)
        self.assertIn('size_mb', first_m)

        # Test GET /api/events/public/{slug}/ and /api/public/events/{slug}/
        pub1 = self.client.get(f"/api/events/public/{event.slug}/")
        self.assertEqual(pub1.status_code, status.HTTP_200_OK)
        self.assertEqual(pub1.data['photos_count'], 1)
        self.assertEqual(pub1.data['videos_count'], 1)
        self.assertEqual(pub1.data['total_media_count'], 2)
        self.assertEqual(pub1.data['total_size_bytes'], 31457280)
        self.assertEqual(pub1.data['total_size_mb'], 30.0)
        self.assertEqual(pub1.data['total_size_formatted'], "30.0 MB")

        pub2 = self.client.get(f"/api/public/events/{event.slug}/")
        self.assertEqual(pub2.status_code, status.HTTP_200_OK)
        self.assertEqual(pub2.data['total_size_bytes'], 31457280)

    def test_tether_upload_populates_metrics(self):
        event = LiveEvent.objects.create(
            photographer=self.user,
            title="Tether Testing Event"
        )
        img = create_dummy_image("shot_001.jpg")
        res = self.client.post(
            f"/api/events/{event.id}/tether/",
            {"photo": img, "section_title": "CEREMONY"},
            format="multipart"
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("file_size", res.data)
        self.assertGreater(res.data["file_size"], 0)
        self.assertEqual(res.data["media_type"], "photo")

        # Check refreshed event metrics
        event.refresh_from_db()
        self.assertEqual(event.photos_count, 1)
        self.assertEqual(event.videos_count, 0)
        self.assertEqual(event.total_media_count, 1)
        self.assertGreater(event.total_size_bytes, 0)

    def test_section_title_default_to_highlights(self):
        event = LiveEvent.objects.create(
            photographer=self.user,
            title="Corporate Gala Conference"
        )
        # Upload photo with NO section_title provided
        img = create_dummy_image("speaker.jpg")
        res = self.client.post(
            f"/api/events/{event.slug}/tether/",
            {"photo": img},
            format="multipart"
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["section_title"], "HIGHLIGHTS")
        self.assertEqual(res.data["sectionTitle"], "HIGHLIGHTS")

        # Bulk upload with empty section_title
        img2 = create_dummy_image("crowd.jpg")
        bulk_res = self.client.post(
            f"/api/events/{event.slug}/upload/",
            {"photos": [img2], "section_title": "  "},
            format="multipart"
        )
        self.assertEqual(bulk_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(bulk_res.data["media"][0]["section_title"], "HIGHLIGHTS")

    def test_event_media_bulk_delete_and_alias(self):
        event = LiveEvent.objects.create(
            photographer=self.user,
            title="Sangeet Party Event"
        )
        m1 = EventMedia.objects.create(
            event=event,
            original_filename="clip1.mp4",
            media_type="video",
            file_size=10485760,  # 10 MB
            size_mb=10.0
        )
        m2 = EventMedia.objects.create(
            event=event,
            original_filename="clip2.mp4",
            media_type="video",
            file_size=20971520,  # 20 MB
            size_mb=20.0
        )
        m3 = EventMedia.objects.create(
            event=event,
            original_filename="photo1.jpg",
            media_type="photo",
            file_size=5242880,  # 5 MB
            size_mb=5.0
        )

        # 1. Test validation on empty or bad payload
        bad_res = self.client.post(f"/api/events/{event.id}/media/bulk-delete/", {"media_ids": []})
        self.assertEqual(bad_res.status_code, status.HTTP_400_BAD_REQUEST)

        # 2. Test bulk delete via primary route using slug
        del_res = self.client.post(
            f"/api/events/{event.slug}/media/bulk-delete/",
            {"media_ids": [str(m1.id), str(m2.id)]},
            format="json"
        )
        self.assertEqual(del_res.status_code, status.HTTP_200_OK)
        self.assertEqual(del_res.data["status"], "success")
        self.assertEqual(del_res.data["deleted_count"], 2)
        self.assertEqual(del_res.data["freed_bytes"], 31457280)
        self.assertIn(str(m1.id), del_res.data["deleted_media_ids"])
        self.assertIn(str(m2.id), del_res.data["deleted_media_ids"])

        # Verify records are deleted
        self.assertFalse(EventMedia.objects.filter(id=m1.id).exists())
        self.assertFalse(EventMedia.objects.filter(id=m2.id).exists())
        self.assertTrue(EventMedia.objects.filter(id=m3.id).exists())

        # Verify event storage metrics updated
        event.refresh_from_db()
        self.assertEqual(event.total_media_count, 1)
        self.assertEqual(event.photos_count, 1)
        self.assertEqual(event.videos_count, 0)
        self.assertEqual(event.total_size_bytes, 5242880)

        # 3. Test convenience alias POST /api/events/{id}/bulk-delete/
        alias_res = self.client.post(
            f"/api/events/{event.id}/bulk-delete/",
            {"media_ids": [str(m3.id)]},
            format="json"
        )
        self.assertEqual(alias_res.status_code, status.HTTP_200_OK)
        self.assertEqual(alias_res.data["status"], "success")
        self.assertEqual(alias_res.data["deleted_count"], 1)
        self.assertFalse(EventMedia.objects.filter(id=m3.id).exists())

        # 4. Test deleting already deleted or nonexistent IDs returns 200 with deleted_count=0
        repeat_res = self.client.post(
            f"/api/events/{event.id}/media/bulk-delete/",
            {"media_ids": [str(m3.id)]},
            format="json"
        )
        self.assertEqual(repeat_res.status_code, status.HTTP_200_OK)
        self.assertEqual(repeat_res.data["deleted_count"], 0)
        self.assertEqual(repeat_res.data["freed_bytes"], 0)

    def test_update_qr_settings_with_iso_strings(self):
        event = LiveEvent.objects.create(
            photographer=self.user,
            title="QR Settings ISO String Test"
        )
        # Post ISO string formatted timestamps
        res = self.client.post(
            f"/api/events/{event.id}/qr-settings/",
            {
                "valid_from": "2026-09-28T10:00:00Z",
                "expires_at": "2026-10-05T23:59:59Z",
                "duration_hours": 48,
                "pin_code": "8899",
                "allow_guest_uploads": True
            },
            format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "success")
        self.assertTrue(res.data["is_active"])
        self.assertEqual(res.data["pin_code"], "8899")
        self.assertTrue(res.data["allow_guest_uploads"])

        # Also test via slug with expired date
        res2 = self.client.post(
            f"/api/events/{event.slug}/qr-settings/",
            {
                "expires_at": "2020-01-01T00:00:00Z",
            },
            format="json"
        )
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertFalse(res2.data["is_active"])

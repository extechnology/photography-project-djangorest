from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
import io
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import SubscriptionPlans
from App.Storage.storage_models import Gallery, Media


class GalleryStatusFilteringAndQuotaTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

        # Create a plan with max_galleries = 2
        self.plan = SubscriptionPlans.objects.create(
            name="Limited Test Plan",
            price=29.00,
            storage_limit_bytes=10 * 1024 * 1024 * 1024,
            max_galleries=2,
            face_search_enabled=True,
            allowed_templates=["editorial", "masonry"]
        )

        # Photographer User
        self.user = User.objects.create_user(
            username="photographer_test",
            email="photographer@test.com",
            password="securepassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            plan=self.plan,
            name="Elena Studio",
            studio_name="Elena Visuals"
        )
        self.client.force_authenticate(user=self.user)

    def test_gallery_serializer_includes_status_default(self):
        """1. GallerySerializer includes status field defaulting to 'active'."""
        response = self.client.post('/api/galleries/', {
            "title": "Summer Wedding",
            "client_name": "Alice & Bob",
            "event_date": str(timezone.now().date()),
            "template_id": "editorial"
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("status", response.data)
        self.assertEqual(response.data["status"], "active")
        self.assertEqual(response.data["client_name"], "Alice & Bob")

    def test_patch_gallery_status_switching(self):
        """2. Allow updating status via PATCH /api/galleries/{id}/."""
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Autumn Gala",
            client_name="Corporate Client",
            status="active",
            event_date=timezone.now().date()
        )

        # Update status to delivered
        patch_response = self.client.patch(f"/api/galleries/{gallery.id}/", {
            "status": "delivered"
        })
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data["status"], "delivered")

        gallery.refresh_from_db()
        self.assertEqual(gallery.status, "delivered")

        # Switch back to active
        patch_response_2 = self.client.patch(f"/api/galleries/{gallery.id}/", {
            "status": "active"
        })
        self.assertEqual(patch_response_2.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response_2.data["status"], "active")

        gallery.refresh_from_db()
        self.assertEqual(gallery.status, "active")

    def test_server_side_filtering_status_and_search(self):
        """3. Support query filtering: search and status."""
        today = timezone.now().date()
        g1 = Gallery.objects.create(
            photographer=self.profile,
            title="Roy Wedding Celebration",
            client_name="Rahul & Priya Roy",
            status="active",
            event_date=today
        )
        g2 = Gallery.objects.create(
            photographer=self.profile,
            title="Sharma Reception",
            client_name="Ananya Sharma",
            status="delivered",
            event_date=today
        )

        # Search by title
        res = self.client.get('/api/galleries/?search=Wedding')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["id"], str(g1.id))

        # Search by client name
        res = self.client.get('/api/galleries/?search=Sharma')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["id"], str(g2.id))

        # Filter by status: active
        res_active = self.client.get('/api/galleries/?status=active')
        self.assertEqual(res_active.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_active.data), 1)
        self.assertEqual(res_active.data[0]["status"], "active")

        # Filter by status: delivered
        res_deliv = self.client.get('/api/galleries/?status=delivered')
        self.assertEqual(res_deliv.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_deliv.data), 1)
        self.assertEqual(res_deliv.data[0]["status"], "delivered")

    def test_date_presets_and_custom_filtering(self):
        """3b. Support date presets (this-year, last-30-days, etc.) and custom range."""
        today = timezone.now().date()
        this_year_date = today.replace(month=1, day=15)
        last_year_date = today.replace(year=today.year - 1, month=5, day=10)
        recent_date = today - timedelta(days=10)
        old_date = today - timedelta(days=50)

        g_recent = Gallery.objects.create(
            photographer=self.profile,
            title="Recent Event",
            event_date=recent_date
        )
        g_old = Gallery.objects.create(
            photographer=self.profile,
            title="Old Event This Year",
            event_date=old_date
        )
        g_last_year = Gallery.objects.create(
            photographer=self.profile,
            title="Last Year Event",
            event_date=last_year_date
        )

        # last-30-days
        res = self.client.get('/api/galleries/?date_filter=last-30-days')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        titles = [item["title"] for item in res.data]
        self.assertIn("Recent Event", titles)
        self.assertNotIn("Old Event This Year", titles)
        self.assertNotIn("Last Year Event", titles)

        # last-year
        res = self.client.get('/api/galleries/?date_filter=last-year')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        titles = [item["title"] for item in res.data]
        self.assertIn("Last Year Event", titles)
        self.assertNotIn("Recent Event", titles)

        # custom range
        res = self.client.get(f'/api/galleries/?date_filter=custom&date_from={old_date}&date_to={recent_date}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        titles = [item["title"] for item in res.data]
        self.assertIn("Recent Event", titles)
        self.assertIn("Old Event This Year", titles)
        self.assertNotIn("Last Year Event", titles)

    def test_sorting_and_ordering(self):
        """3c. Support sorting: name, date-asc, date-desc, photos."""
        today = timezone.now().date()
        g_alpha = Gallery.objects.create(
            photographer=self.profile,
            title="Alpha Gallery",
            event_date=today - timedelta(days=20)
        )
        g_beta = Gallery.objects.create(
            photographer=self.profile,
            title="Beta Gallery",
            event_date=today - timedelta(days=5)
        )

        # Create media items for g_alpha so photos count is higher
        Media.objects.create(
            gallery=g_alpha,
            photographer=self.profile,
            original_filename="a1.jpg",
            storage_key="a1.jpg",
            file_size=1000
        )
        Media.objects.create(
            gallery=g_alpha,
            photographer=self.profile,
            original_filename="a2.jpg",
            storage_key="a2.jpg",
            file_size=1000
        )

        # Sort by name
        res = self.client.get('/api/galleries/?sort=name')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data[0]["title"], "Alpha Gallery")
        self.assertEqual(res.data[1]["title"], "Beta Gallery")

        # Sort by date-desc (newest event first)
        res = self.client.get('/api/galleries/?sort=date-desc')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data[0]["title"], "Beta Gallery")
        self.assertEqual(res.data[1]["title"], "Alpha Gallery")

        # Sort by photos count (most photos first)
        res = self.client.get('/api/galleries/?sort=photos')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data[0]["title"], "Alpha Gallery")
        self.assertEqual(res.data[0]["photos_count"], 2)
        self.assertEqual(res.data[1]["title"], "Beta Gallery")
        self.assertEqual(res.data[1]["photos_count"], 0)

    def test_plan_quota_enforcement_on_gallery_creation(self):
        """4. Enforce plan limits on gallery creation (POST /api/galleries/)."""
        # Our plan has max_galleries = 2
        # Create gallery 1
        res1 = self.client.post('/api/galleries/', {
            "title": "Gallery 1",
            "template_id": "editorial"
        })
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Create gallery 2
        res2 = self.client.post('/api/galleries/', {
            "title": "Gallery 2",
            "template_id": "editorial"
        })
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)

        # Attempt to create gallery 3 -> Should fail with 403 GALLERY_LIMIT_EXCEEDED
        res3 = self.client.post('/api/galleries/', {
            "title": "Gallery 3 Exceeded",
            "template_id": "editorial"
        })
        self.assertEqual(res3.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res3.data.get("code"), "GALLERY_LIMIT_EXCEEDED")
        self.assertTrue(res3.data.get("upgrade_required"))
        self.assertIn("Gallery quota reached", res3.data.get("message"))

    def _create_test_image(self, filename="photo.jpg", width=200, height=100):
        file_io = io.BytesIO()
        image = Image.new('RGB', (width, height), color=(73, 109, 137))
        image.save(file_io, format='JPEG')
        file_io.seek(0)
        return SimpleUploadedFile(filename, file_io.read(), content_type='image/jpeg')

    def _create_test_video(self, filename="clip.mp4", size=1024):
        return SimpleUploadedFile(filename, b"X" * size, content_type='video/mp4')

    def test_batch_upload_photos_and_videos_with_section_and_storage_usage(self):
        """Batch upload photos & videos, auto-detect media_type, persist section, return storage_usage."""
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Roy Wedding Celebration",
            client_name="Rahul & Priya Roy",
            event_date=timezone.now().date(),
        )

        img1 = self._create_test_image("ceremony_01.jpg", width=3840, height=2160)
        img2 = self._create_test_image("ceremony_02.jpg", width=1920, height=1080)
        vid1 = self._create_test_video("ceremony_video.mp4", size=2048)

        response = self.client.post(
            f"/api/galleries/{gallery.id}/upload/",
            {
                "photos": [img1, img2],
                "videos": [vid1],
                "section_title": "Ceremony",
            },
            format='multipart'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["total_uploaded"], 3)
        self.assertIn("storage_usage", response.data)
        usage = response.data["storage_usage"]
        self.assertIn("used_bytes", usage)
        self.assertIn("limit_bytes", usage)
        self.assertIn("used_gb", usage)
        self.assertIn("limit_gb", usage)
        self.assertIn("used_percentage", usage)

        # Check section persistence on gallery
        gallery.refresh_from_db()
        self.assertIn("CEREMONY", gallery.sections)

        # Check media items
        media_list = response.data["media"]
        self.assertEqual(len(media_list), 3)
        photo_items = [m for m in media_list if m["media_type"] == "photo"]
        video_items = [m for m in media_list if m["media_type"] == "video"]
        self.assertEqual(len(photo_items), 2)
        self.assertEqual(len(video_items), 1)

        # Verify photo details
        first_photo = photo_items[0]
        self.assertEqual(first_photo["section_title"], "CEREMONY")
        self.assertIn("download_url", first_photo)
        self.assertTrue(first_photo["download_url"].endswith(f"/api/galleries/media/{first_photo['id']}/download/"))
        self.assertTrue(first_photo["download_url"].startswith("http://testserver"))
        self.assertIsNotNone(first_photo["width"])
        self.assertIsNotNone(first_photo["height"])
        self.assertIsNotNone(first_photo["aspect_ratio"])

        # Verify video details
        first_video = video_items[0]
        self.assertEqual(first_video["section_title"], "CEREMONY")
        self.assertEqual(first_video["media_type"], "video")

    def test_batch_upload_no_files_returns_400(self):
        """Batch upload with no files returns 400 Bad Request."""
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Empty Upload Gallery",
            event_date=timezone.now().date(),
        )

        response = self.client.post(f"/api/galleries/{gallery.id}/upload/", {}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertIn("No files provided", response.data["error"])

    def test_batch_upload_storage_quota_exceeded_returns_403(self):
        """Storage limit exceeded returns 403 Forbidden with STORAGE_LIMIT_EXCEEDED."""
        self.plan.storage_limit_bytes = 1000
        self.plan.save()
        self.profile.storage_used_bytes = 900
        self.profile.save()

        gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Quota Gallery",
            event_date=timezone.now().date(),
        )

        # Upload 500 bytes (will exceed remaining 100 bytes)
        vid = self._create_test_video("huge.mp4", size=500)
        response = self.client.post(
            f"/api/galleries/{gallery.id}/upload/",
            {"videos": [vid]},
            format='multipart'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data.get("code"), "STORAGE_LIMIT_EXCEEDED")
        self.assertTrue(response.data.get("upgrade_required"))
        self.assertIn("available_bytes", response.data)
        self.assertIn("requested_bytes", response.data)
        self.assertIn("Storage limit reached", response.data.get("message"))

    def test_gallery_detail_returns_sections_counts_and_media(self):
        """GET /api/galleries/{id_or_slug}/ returns sections, photos_count, videos_count, and media list."""
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Detailed Wedding",
            client_name="John & Jane Doe",
            sections=["Highlights", "RECEPTION"],
            event_date=timezone.now().date(),
        )

        # Add 1 photo and 1 video
        Media.objects.create(
            gallery=gallery,
            photographer=self.profile,
            original_filename="pic.jpg",
            storage_key="pic.jpg",
            media_type="photo",
            section_title="Highlights",
            file_size=500,
        )
        Media.objects.create(
            gallery=gallery,
            photographer=self.profile,
            original_filename="clip.mp4",
            storage_key="clip.mp4",
            media_type="video",
            section_title="RECEPTION",
            file_size=2000,
        )

        # Test GET by UUID
        res_uuid = self.client.get(f"/api/galleries/{gallery.id}/")
        self.assertEqual(res_uuid.status_code, status.HTTP_200_OK)
        self.assertEqual(res_uuid.data["photos_count"], 1)
        self.assertEqual(res_uuid.data["videos_count"], 1)
        self.assertIn("Highlights", res_uuid.data["sections"])
        self.assertIn("RECEPTION", res_uuid.data["sections"])
        self.assertEqual(len(res_uuid.data["media"]), 2)

        # Test GET by Slug
        res_slug = self.client.get(f"/api/galleries/{gallery.slug}/")
        self.assertEqual(res_slug.status_code, status.HTTP_200_OK)
        self.assertEqual(res_slug.data["id"], str(gallery.id))

    def test_gallery_move_media_section(self):
        """POST /api/galleries/{id}/media/move-section/ moves media to new section and updates gallery.sections."""
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Moving Test Gallery",
            sections=["Highlights"],
            event_date=timezone.now().date(),
        )

        m1 = Media.objects.create(
            gallery=gallery,
            photographer=self.profile,
            original_filename="m1.jpg",
            storage_key="m1.jpg",
            section_title="Highlights",
            file_size=500,
        )

        res = self.client.post(f"/api/galleries/{gallery.id}/media/move-section/", {
            "media_ids": [str(m1.id)],
            "target_section": "Party",
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "success")
        self.assertEqual(res.data["updated_count"], 1)
        self.assertEqual(res.data["section"], "PARTY")
        self.assertIn("PARTY", res.data["sections"])

        m1.refresh_from_db()
        self.assertEqual(m1.section_title, "PARTY")
        gallery.refresh_from_db()
        self.assertIn("PARTY", gallery.sections)

    def test_delete_photo_in_gallery_and_quota_deduction(self):
        """DELETE /api/galleries/{gallery_id}/media/{media_id}/ and /photos/{photo_id}/."""
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Deletion Test Gallery",
            event_date=timezone.now().date(),
        )

        initial_storage = 1000000
        self.profile.storage_used_bytes = initial_storage
        self.profile.save(update_fields=['storage_used_bytes'])

        m1 = Media.objects.create(
            gallery=gallery,
            photographer=self.profile,
            original_filename="photo_to_delete.jpg",
            storage_key="photo_to_delete.jpg",
            media_type="photo",
            file_size=250000,
        )
        gallery.cover_media = m1
        gallery.save(update_fields=['cover_media'])

        # 1. DELETE /api/galleries/{gallery_id}/media/{media_id}/
        del_res = self.client.delete(f"/api/galleries/{gallery.id}/media/{m1.id}/")
        self.assertEqual(del_res.status_code, status.HTTP_200_OK)
        self.assertEqual(del_res.data["status"], "success")

        m1.refresh_from_db()
        self.assertIsNotNone(m1.deleted_at)

        # Quota should be deducted
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.storage_used_bytes, initial_storage - 250000)

        # Cover should be reset
        gallery.refresh_from_db()
        self.assertIsNone(gallery.cover_media)

        # 2. Test DELETE via /photos/{photo_id}/
        m2 = Media.objects.create(
            gallery=gallery,
            photographer=self.profile,
            original_filename="photo_to_delete_2.jpg",
            storage_key="photo_to_delete_2.jpg",
            media_type="photo",
            file_size=150000,
        )
        del_res_2 = self.client.delete(f"/api/galleries/{gallery.id}/photos/{m2.id}/")
        self.assertEqual(del_res_2.status_code, status.HTTP_200_OK)
        m2.refresh_from_db()
        self.assertIsNotNone(m2.deleted_at)

        # 3. Test POST /delete/ action endpoint
        m3 = Media.objects.create(
            gallery=gallery,
            photographer=self.profile,
            original_filename="photo_to_delete_3.jpg",
            storage_key="photo_to_delete_3.jpg",
            media_type="photo",
            file_size=100000,
        )
        del_res_3 = self.client.post(f"/api/galleries/{gallery.id}/media/{m3.id}/delete/")
        self.assertEqual(del_res_3.status_code, status.HTTP_200_OK)
        m3.refresh_from_db()
        self.assertIsNotNone(m3.deleted_at)

    def test_media_urls_are_absolute_with_request_context(self):
        """Ensure media paths and cover image URLs build absolute URIs with request context."""
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Absolute URL Test Gallery",
            event_date=timezone.now().date(),
        )

        m = Media.objects.create(
            gallery=gallery,
            photographer=self.profile,
            original_filename="img1.jpg",
            storage_key="galleries/test/img1.jpg",
            preview_storage_key="galleries/test/preview_img1.jpg",
            thumbnail_storage_key="galleries/test/thumb_img1.jpg",
            media_type="photo",
            file_size=50000,
        )
        gallery.cover_media = m
        gallery.save(update_fields=['cover_media'])

        # GET gallery detail includes absolute URLs
        res = self.client.get(f"/api/galleries/{gallery.id}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["cover_image"].startswith("http://testserver"))
        self.assertTrue(res.data["media"][0]["thumbnail_url"].startswith("http://testserver"))
        self.assertTrue(res.data["media"][0]["preview_url"].startswith("http://testserver"))
        self.assertTrue(res.data["media"][0]["download_url"].startswith("http://testserver"))

        # GET single photo detail
        res_single = self.client.get(f"/api/galleries/{gallery.id}/media/{m.id}/")
        self.assertEqual(res_single.status_code, status.HTTP_200_OK)
        self.assertTrue(res_single.data["thumbnail_url"].startswith("http://testserver"))
        self.assertTrue(res_single.data["download_url"].startswith("http://testserver"))


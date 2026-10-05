import uuid
from django.test import TestCase
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import SubscriptionPlans
from App.Storage.storage_models import Gallery, Media


class GalleryBulkDeleteAndCountsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

        self.plan = SubscriptionPlans.objects.create(
            name="Studio Pro Plan",
            price=49.00,
            storage_limit_bytes=50 * 1024 * 1024 * 1024,
            max_galleries=20,
            face_search_enabled=True,
            allowed_templates=["editorial", "masonry", "cinematic", "slideshow", "minimal"]
        )

        self.user = User.objects.create_user(
            username="gallery_tester",
            email="gallery_tester@studio.com",
            password="securepassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            plan=self.plan,
            name="Gallery Tester",
            studio_name="Ex Share Studios",
            storage_used_bytes=8000000
        )
        self.client.force_authenticate(user=self.user)

        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Sample Gallery",
            slug="sample-gallery",
            client_name="John David",
            template_id="editorial",
            status="active",
            sections=["HIGHLIGHTS", "CEREMONY", "RECEPTION"]
        )

        # 3 in HIGHLIGHTS (2 photos, 1 favorite)
        self.m1 = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="IMG_001",
            original_filename="img_001.jpg",
            media_type="photo",
            section_title="HIGHLIGHTS",
            is_favorite=True,
            file_size=4500000,
            storage_key=f"galleries/{self.gallery.id}/img_001.jpg"
        )
        self.m2 = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="IMG_002",
            original_filename="img_002.jpg",
            media_type="photo",
            section_title="HIGHLIGHTS",
            is_favorite=False,
            file_size=1500000,
            storage_key=f"galleries/{self.gallery.id}/img_002.jpg"
        )

        # 2 in CEREMONY (2 photos)
        self.m3 = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="IMG_003",
            original_filename="img_003.jpg",
            media_type="photo",
            section_title="CEREMONY",
            is_favorite=False,
            file_size=500000,
            storage_key=f"galleries/{self.gallery.id}/img_003.jpg"
        )
        self.m4 = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="IMG_004",
            original_filename="img_004.jpg",
            media_type="photo",
            section_title="CEREMONY",
            is_favorite=False,
            file_size=500000,
            storage_key=f"galleries/{self.gallery.id}/img_004.jpg"
        )

        # 1 in RECEPTION (1 video)
        self.m5 = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="VID_001",
            original_filename="vid_001.mp4",
            media_type="video",
            section_title="RECEPTION",
            is_favorite=False,
            file_size=1000000,
            storage_key=f"galleries/{self.gallery.id}/vid_001.mp4"
        )

    def test_get_gallery_detail_counts_and_section_breakdown(self):
        url = f"/api/galleries/{self.gallery.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data
        self.assertEqual(data["id"], str(self.gallery.id))
        self.assertEqual(data["title"], "Sample Gallery")
        self.assertEqual(data["slug"], "sample-gallery")
        self.assertEqual(data["client_name"], "John David")
        self.assertEqual(data["total_media_count"], 5)
        self.assertEqual(data["photos_count"], 4)
        self.assertEqual(data["videos_count"], 1)
        self.assertEqual(data["favorites_count"], 1)

        section_counts = data.get("section_counts", {})
        self.assertEqual(section_counts.get("HIGHLIGHTS"), 2)
        self.assertEqual(section_counts.get("CEREMONY"), 2)
        self.assertEqual(section_counts.get("RECEPTION"), 1)

        # Check media items formatting
        self.assertEqual(len(data["media"]), 5)
        first_item = data["media"][0]
        self.assertIn("id", first_item)
        self.assertIn("type", first_item)
        self.assertIn("size_bytes", first_item)

    def test_get_gallery_with_all_media_and_filters(self):
        # 1. ?all_media=true
        url = f"/api/galleries/{self.gallery.slug}/?all_media=true"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["media"]), 5)
        self.assertIsNone(response.data.get("next_cursor"))
        self.assertFalse(response.data.get("has_more"))

        # 2. Section filter
        url_sec = f"/api/galleries/{self.gallery.slug}/?all_media=true&section=CEREMONY"
        res_sec = self.client.get(url_sec)
        self.assertEqual(res_sec.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_sec.data["media"]), 2)
        self.assertEqual(res_sec.data["total_media_count"], 5)  # Overall total intact

        # 3. Favorites filter
        url_fav = f"/api/galleries/{self.gallery.id}/?all_media=true&is_favorite=true"
        res_fav = self.client.get(url_fav)
        self.assertEqual(res_fav.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_fav.data["media"]), 1)
        self.assertTrue(res_fav.data["media"][0]["is_favorite"])

    def test_bulk_delete_specific_media_ids(self):
        url = "/api/galleries/media/bulk-delete/"
        payload = {
            "gallery_id": str(self.gallery.id),
            "media_ids": [str(self.m3.id), str(self.m4.id)],
            "delete_all": False
        }
        initial_storage = self.profile.storage_used_bytes
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data["deleted_count"], 2)
        self.assertEqual(response.data["freed_bytes"], 1000000)

        # Verified soft deleted in database
        self.assertEqual(Media.objects.filter(gallery=self.gallery, deleted_at__isnull=True).count(), 3)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.storage_used_bytes, initial_storage - 1000000)

    def test_bulk_delete_all_by_section(self):
        url = "/api/galleries/media/bulk-delete/"
        payload = {
            "gallery_id": str(self.gallery.id),
            "delete_all": True,
            "section": "HIGHLIGHTS"
        }
        initial_storage = self.profile.storage_used_bytes
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data["deleted_count"], 2)
        self.assertEqual(response.data["freed_bytes"], 6000000)  # 4500000 + 1500000

        # HIGHLIGHTS media soft-deleted
        self.assertEqual(
            Media.objects.filter(gallery=self.gallery, section_title="HIGHLIGHTS", deleted_at__isnull=True).count(),
            0
        )
        self.assertEqual(Media.objects.filter(gallery=self.gallery, deleted_at__isnull=True).count(), 3)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.storage_used_bytes, initial_storage - 6000000)

    def test_bulk_delete_all_in_gallery(self):
        url = f"/api/galleries/{self.gallery.id}/bulk-delete/"
        payload = {
            "delete_all": True
        }
        initial_storage = self.profile.storage_used_bytes
        total_gallery_bytes = 4500000 + 1500000 + 500000 + 500000 + 1000000

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data["deleted_count"], 5)
        self.assertEqual(response.data["freed_bytes"], total_gallery_bytes)
        self.assertEqual(Media.objects.filter(gallery=self.gallery, deleted_at__isnull=True).count(), 0)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.storage_used_bytes, initial_storage - total_gallery_bytes)

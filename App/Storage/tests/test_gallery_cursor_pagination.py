import uuid
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from django.core.cache import cache

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import SubscriptionPlans
from App.Storage.storage_models import Gallery, Media
from App.Storage.storage_views import GalleryMediaCursorPagination


class GalleryCursorPaginationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

        self.plan = SubscriptionPlans.objects.create(
            name="Studio Pagination Pro",
            price=99.00,
            storage_limit_bytes=100 * 1024 * 1024 * 1024,
            max_galleries=50,
            allowed_templates=["editorial", "masonry", "cinematic", "slideshow", "minimal"]
        )

        self.user = User.objects.create_user(
            username="atelier_curator",
            email="curator@atelier.studio",
            password="pass-word-secure-123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            plan=self.plan,
            name="Master Curator",
            studio_name="Atelier Pagination Studio"
        )
        self.client.force_authenticate(user=self.user)

        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title="High Fashion Paris 2026",
            client_name="Maison Dior",
            sections=["EDITORIAL", "BACKSTAGE", "RUNWAY"]
        )

        # Create 10 media items with varying sections, favorites, types, and sort orders
        self.media_items = []
        now = timezone.now()
        for i in range(10):
            sec = "EDITORIAL" if i < 4 else ("BACKSTAGE" if i < 7 else "RUNWAY")
            is_fav = (i % 2 == 0)
            m_type = "video" if i == 9 else "photo"
            m = Media.objects.create(
                photographer=self.profile,
                gallery=self.gallery,
                original_filename=f"photo_{i:02d}.jpg",
                storage_key=f"galleries/test/photo_{i:02d}.jpg",
                section_title=sec,
                media_type=m_type,
                file_size=2 * 1024 * 1024,
                display_order=i,
                is_favorite=is_fav,
            )
            # Stagger created_at for deterministic ordering
            Media.objects.filter(id=m.id).update(created_at=now - timedelta(minutes=10 - i))
            m.refresh_from_db()
            self.media_items.append(m)

    def test_cursor_encoding_and_decoding(self):
        """Test base64 token encoding and decoding."""
        test_id = str(uuid.uuid4())
        token = GalleryMediaCursorPagination.encode_cursor(
            sort_order=5,
            created_at_iso="2026-09-26T12:00:00Z",
            media_id=test_id
        )
        self.assertIsInstance(token, str)
        decoded = GalleryMediaCursorPagination.decode_cursor(token)
        self.assertEqual(decoded['s'], 5)
        self.assertEqual(decoded['c'], "2026-09-26T12:00:00Z")
        self.assertEqual(decoded['id'], test_id)

        # Invalid token returns None
        self.assertIsNone(GalleryMediaCursorPagination.decode_cursor("invalid-token!!"))
        self.assertIsNone(GalleryMediaCursorPagination.decode_cursor(None))

    def test_default_pagination_and_metadata(self):
        """GET /api/galleries/<id>/ returns page 1 with metadata fields."""
        res = self.client.get(f"/api/galleries/{self.gallery.id}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data

        self.assertEqual(data["title"], "High Fashion Paris 2026")
        self.assertEqual(data["total_media_count"], 10)
        self.assertEqual(data["filtered_media_count"], 10)
        self.assertIn("media", data)
        self.assertEqual(len(data["media"]), 10)  # default limit 48 >= 10 items
        self.assertFalse(data["has_more"])
        self.assertIsNone(data["next_cursor"])

        # Check gallery_id on media item
        self.assertEqual(data["media"][0]["gallery_id"], str(self.gallery.id))

    def test_keyset_cursor_pagination_paging_flow(self):
        """Paginate through media items in batches of 3 using cursor."""
        # Page 1: limit=3
        res1 = self.client.get(f"/api/galleries/{self.gallery.id}/?limit=3")
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res1.data["media"]), 3)
        self.assertTrue(res1.data["has_more"])
        self.assertIsNotNone(res1.data["next_cursor"])
        p1_ids = [m["id"] for m in res1.data["media"]]

        # Page 2: limit=3 with cursor from page 1
        cursor1 = res1.data["next_cursor"]
        res2 = self.client.get(f"/api/galleries/{self.gallery.id}/?limit=3&cursor={cursor1}")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res2.data["media"]), 3)
        self.assertTrue(res2.data["has_more"])
        self.assertIsNotNone(res2.data["next_cursor"])
        p2_ids = [m["id"] for m in res2.data["media"]]

        # Verify page 1 and page 2 have no overlapping IDs
        self.assertTrue(set(p1_ids).isdisjoint(set(p2_ids)))

        # Page 3: limit=3 with cursor from page 2
        cursor2 = res2.data["next_cursor"]
        res3 = self.client.get(f"/api/galleries/{self.gallery.id}/?limit=3&cursor={cursor2}")
        self.assertEqual(res3.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res3.data["media"]), 3)
        self.assertTrue(res3.data["has_more"])
        p3_ids = [m["id"] for m in res3.data["media"]]
        self.assertTrue(set(p2_ids).isdisjoint(set(p3_ids)))

        # Page 4: final 1 item
        cursor3 = res3.data["next_cursor"]
        res4 = self.client.get(f"/api/galleries/{self.gallery.id}/?limit=3&cursor={cursor3}")
        self.assertEqual(res4.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res4.data["media"]), 1)
        self.assertFalse(res4.data["has_more"])
        self.assertIsNone(res4.data["next_cursor"])

    def test_section_filtering(self):
        """Test ?section=EDITORIAL returns only items from that section."""
        res = self.client.get(f"/api/galleries/{self.gallery.id}/?section=EDITORIAL")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["total_media_count"], 10)
        self.assertEqual(res.data["filtered_media_count"], 4)
        self.assertEqual(len(res.data["media"]), 4)
        for item in res.data["media"]:
            self.assertEqual(item["section_title"].upper(), "EDITORIAL")

    def test_favorite_filtering(self):
        """Test ?is_favorite=true filters only liked photos."""
        res = self.client.get(f"/api/galleries/{self.gallery.id}/?is_favorite=true")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["total_media_count"], 10)
        self.assertEqual(res.data["filtered_media_count"], 5)
        for item in res.data["media"]:
            self.assertTrue(item["is_favorite"])

    def test_media_type_filtering(self):
        """Test ?type=video filters only video items."""
        res = self.client.get(f"/api/galleries/{self.gallery.id}/?type=video")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["total_media_count"], 10)
        self.assertEqual(res.data["filtered_media_count"], 1)
        self.assertEqual(len(res.data["media"]), 1)
        self.assertEqual(res.data["media"][0]["type"], "video")

    def test_legacy_all_media_override(self):
        """Test ?all_media=true bypasses pagination and returns all media in one payload."""
        res = self.client.get(f"/api/galleries/{self.gallery.id}/?all_media=true")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data["media"]), 10)
        self.assertFalse(res.data["has_more"])
        self.assertIsNone(res.data["next_cursor"])

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


class GalleryExpirationAndAccessWindowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

        self.plan = SubscriptionPlans.objects.create(
            name="Studio Expiration Pro",
            price=120.00,
            storage_limit_bytes=500 * 1024 * 1024 * 1024,
            max_galleries=100,
            allowed_templates=["editorial", "masonry", "cinematic", "slideshow", "minimal"]
        )

        self.user = User.objects.create_user(
            username="studio_owner_exp",
            email="owner@studio.com",
            password="secure-pass-12345",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            plan=self.plan,
            name="John Studio Master",
            studio_name="Ex Share Master Studio"
        )
        self.client.force_authenticate(user=self.user)

        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title="John David Weds Saniya Varma",
            client_name="John David",
            client_email="david@wedding.com",
            slug="john-david-weds-saniya-varma",
            is_password_protected=True,
            password="securepin2026",
            download_pin="securepin2026",
            allow_downloads=True,
            expires_at=None,
        )

        self.media = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            original_filename="wedding_main.jpg",
            storage_key="galleries/test/wedding_main.jpg",
            section_title="CEREMONY",
            file_size=3 * 1024 * 1024,
            display_order=0,
            upload_status="completed",
        )

    def test_manager_active_and_expired_filters(self):
        """Test Gallery.objects.active() and Gallery.objects.expired() querysets."""
        now = timezone.now()
        # Gallery initially has expires_at=None (permanent -> active)
        self.assertIn(self.gallery, Gallery.objects.active())
        self.assertNotIn(self.gallery, Gallery.objects.expired())

        # Set future expiration
        self.gallery.expires_at = now + timedelta(days=10)
        self.gallery.save()
        self.assertIn(self.gallery, Gallery.objects.active())
        self.assertNotIn(self.gallery, Gallery.objects.expired())
        self.assertFalse(self.gallery.is_expired)

        # Set past expiration
        self.gallery.expires_at = now - timedelta(days=2)
        self.gallery.save()
        self.assertNotIn(self.gallery, Gallery.objects.active())
        self.assertIn(self.gallery, Gallery.objects.expired())
        self.assertTrue(self.gallery.is_expired)

    def test_set_gallery_future_expiry_via_studio_patch(self):
        """Test 1: Studio owner sets future expiry date via PATCH /api/galleries/<id>/."""
        future_iso = "2027-01-01T00:00:00Z"
        res = self.client.patch(f"/api/galleries/{self.gallery.id}/", {
            "expires_at": future_iso
        }, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.gallery.refresh_from_db()
        self.assertFalse(res.data["is_expired"])
        self.assertFalse(self.gallery.is_expired)

        # Public client views the gallery
        client = APIClient()
        pub_res = client.get(f"/api/public/galleries/{self.gallery.slug}/")
        self.assertEqual(pub_res.status_code, status.HTTP_200_OK)
        self.assertEqual(pub_res.data["title"], "John David Weds Saniya Varma")
        self.assertFalse(pub_res.data["is_expired"])

        # Public PIN verification succeeds with valid PIN
        pin_res = client.post(f"/api/public/galleries/{self.gallery.slug}/verify-pin/", {
            "pin": "securepin2026"
        }, format="json")
        self.assertEqual(pin_res.status_code, status.HTTP_200_OK)
        self.assertTrue(pin_res.data["is_valid"])

    def test_expired_gallery_rejects_public_access_with_410_gone(self):
        """Test 2: When gallery has expired, client viewing, downloading, and PIN return HTTP 410 Gone."""
        past_iso = "2020-01-01T00:00:00Z"
        # Studio owner sets past expiry
        res = self.client.patch(f"/api/galleries/{self.gallery.id}/", {
            "expires_at": past_iso
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["is_expired"])

        # Studio owner STILL has access for management
        studio_get = self.client.get(f"/api/galleries/{self.gallery.id}/")
        self.assertEqual(studio_get.status_code, status.HTTP_200_OK)
        self.assertTrue(studio_get.data["is_expired"])

        # Public client attempts to view gallery -> 410 GONE
        client = APIClient()
        pub_res = client.get(f"/api/public/galleries/{self.gallery.slug}/")
        self.assertEqual(pub_res.status_code, status.HTTP_410_GONE)
        self.assertEqual(pub_res.data["code"], "gallery_expired")
        self.assertTrue(pub_res.data["is_expired"])
        self.assertEqual(pub_res.data["title"], "John David Weds Saniya Varma")
        self.assertEqual(pub_res.data["client_name"], "John David")
        self.assertEqual(pub_res.data["error"], "The access period for this private collection has expired.")

        # Public client attempts to download ZIP -> 410 GONE
        dl_res = client.get(f"/api/public/galleries/{self.gallery.slug}/download-zip/")
        self.assertEqual(dl_res.status_code, status.HTTP_410_GONE)
        self.assertEqual(dl_res.data["code"], "gallery_expired")
        self.assertTrue(dl_res.data["is_expired"])

        # Public client attempts PIN verification -> 410 GONE
        pin_res = client.post(f"/api/public/galleries/{self.gallery.slug}/verify-pin/", {
            "pin": "securepin2026"
        }, format="json")
        self.assertEqual(pin_res.status_code, status.HTTP_410_GONE)
        self.assertEqual(pin_res.data["code"], "gallery_expired")
        self.assertTrue(pin_res.data["is_expired"])

    def test_clear_expiry_restores_permanent_access(self):
        """Test 3: Clearing expires_at (null) sets permanent access and re-enables public viewing."""
        # 1. First expire the gallery
        self.gallery.expires_at = timezone.now() - timedelta(days=5)
        self.gallery.save()
        self.assertTrue(self.gallery.is_expired)

        # 2. Studio owner sets expires_at to null
        res = self.client.patch(f"/api/galleries/{self.gallery.id}/", {
            "expires_at": None
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsNone(res.data["expires_at"])
        self.assertFalse(res.data["is_expired"])

        # 3. Public client can view gallery again (200 OK)
        client = APIClient()
        pub_res = client.get(f"/api/public/galleries/{self.gallery.slug}/")
        self.assertEqual(pub_res.status_code, status.HTTP_200_OK)
        self.assertEqual(pub_res.data["title"], "John David Weds Saniya Varma")
        self.assertFalse(pub_res.data["is_expired"])

    def test_public_gallery_by_uuid_or_slug(self):
        """Public gallery endpoints resolve either by UUID or URL slug."""
        client = APIClient()
        res_by_slug = client.get(f"/api/public/galleries/{self.gallery.slug}/")
        self.assertEqual(res_by_slug.status_code, status.HTTP_200_OK)

        res_by_id = client.get(f"/api/public/galleries/{self.gallery.id}/")
        self.assertEqual(res_by_id.status_code, status.HTTP_200_OK)
        self.assertEqual(res_by_slug.data["id"], res_by_id.data["id"])

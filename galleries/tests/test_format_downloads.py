import io
import os
import zipfile
import uuid
from PIL import Image
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status
from django.core.cache import cache

from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import SubscriptionPlans
from galleries.models import Gallery, Media as GalleryMedia
from App.Storage.services.storage_service import get_storage_provider

User = get_user_model()


def create_dummy_jpeg(name='photo.jpg', size=(100, 100), color='blue'):
    buf = io.BytesIO()
    img = Image.new('RGB', size, color=color)
    img.save(buf, format='JPEG', quality=90)
    buf.seek(0)
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


class FormatDownloadAndSelectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

        self.plan = SubscriptionPlans.objects.create(
            name="Atelier Master Plan",
            price=199.00,
            storage_limit_bytes=1000 * 1024 * 1024 * 1024,
            max_galleries=200,
            allowed_templates=["editorial", "masonry", "cinematic"]
        )

        self.user = User.objects.create_user(
            username="atelier_photographer",
            email="atelier@photography.com",
            password="atelier-password-2026",
            role=User.Role.PHOTOGRAPHER if hasattr(User, 'Role') else None
        )

        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            plan=self.plan,
            name="Jean-Luc Atelier",
            studio_name="Atelier Lumiere",
            watermark_type="text",
            watermark_text="© ATELIER LUMIERE",
            watermark_opacity=0.5,
            watermark_position="bottom-right"
        )

        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Vogue Fashion Autumn 2026",
            client_name="Vogue Editorial",
            slug="vogue-fashion-autumn-2026",
            allow_downloads=True,
            downloads_enabled=True,
            watermark_enabled=False,
            watermark_text="ATELIER LUMIERE",
        )

        # Create dummy JPEG bytes and dummy RAW bytes
        self.jpeg_content = create_dummy_jpeg('fashion_01.jpg').read()
        self.raw_content = b"\x49\x49\x2A\x00" + b"CANON_RAW_CR3_SIMULATED_BINARY_DATA" * 50

        # Upload files to storage provider
        storage = get_storage_provider()
        self.key_jpeg = f"galleries/{self.gallery.id}/originals/fashion_01.jpg"
        self.key_raw = f"galleries/{self.gallery.id}/raw/fashion_01.cr3"
        storage.upload(self.key_jpeg, self.jpeg_content, content_type="image/jpeg")
        storage.upload(self.key_raw, self.raw_content, content_type="image/x-canon-cr3")

        # Create Media with both web JPEG master and raw_file companion
        self.media_with_raw = GalleryMedia.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="Editorial Runway Master",
            original_filename="fashion_01.cr3",
            storage_key=self.key_jpeg,
            file=SimpleUploadedFile('fashion_01.jpg', self.jpeg_content, content_type='image/jpeg'),
            raw_file=SimpleUploadedFile('fashion_01.cr3', self.raw_content, content_type='image/x-canon-cr3'),
            file_size=len(self.jpeg_content),
            file_extension=".cr3",
            mime_type="image/x-canon-cr3",
            upload_status="completed"
        )

        # Create Media with only JPEG master (no raw file)
        self.media_jpeg_only = GalleryMedia.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="Editorial Backstage",
            original_filename="backstage_02.jpg",
            file=SimpleUploadedFile('backstage_02.jpg', self.jpeg_content, content_type='image/jpeg'),
            file_size=len(self.jpeg_content),
            file_extension=".jpg",
            mime_type="image/jpeg",
            upload_status="completed"
        )

    def tearDown(self):
        storage = get_storage_provider()
        try:
            storage.delete(self.key_jpeg)
            storage.delete(self.key_raw)
        except Exception:
            pass

    # =========================================================================
    # 1. Single Media Download Tests
    # =========================================================================
    def test_single_download_default_serves_attachment(self):
        """Single download endpoint must serve Content-Disposition: attachment to prevent opening in tab."""
        url = f"/api/galleries/media/{self.media_jpeg_only.id}/download/"
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn("backstage_02.jpg", res["Content-Disposition"])
        self.assertEqual(res["Content-Type"], "image/jpeg")
        self.assertEqual(res["Access-Control-Allow-Origin"], "*")
        self.assertIn("Content-Disposition", res["Access-Control-Expose-Headers"])

        # Check telemetry increment
        self.media_jpeg_only.refresh_from_db()
        self.assertEqual(self.media_jpeg_only.downloads_count, 1)

    def test_single_download_format_raw_serves_raw_file(self):
        """?format=raw serves the camera sensor uncompressed companion file."""
        url = f"/api/galleries/media/{self.media_with_raw.id}/download/?format=raw"
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn(".cr3", res["Content-Disposition"])
        self.assertEqual(res.content, self.raw_content)


    def test_single_download_format_raw_fallback_when_no_raw_file(self):
        """?format=raw falls back to high-res master file if no RAW companion exists."""
        url = f"/api/galleries/media/{self.media_jpeg_only.id}/download/?format=raw"
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn("backstage_02.jpg", res["Content-Disposition"])
        self.assertEqual(res.content, self.jpeg_content)

    def test_single_download_format_jpeg_with_watermark(self):
        """?format=jpeg&watermark=true bakes watermark into image and serves attachment."""
        url = f"/api/galleries/media/{self.media_jpeg_only.id}/download/?format=jpeg&watermark=true"
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertEqual(res["Content-Type"], "image/jpeg")
        # Ensure result is valid image bytes
        img = Image.open(io.BytesIO(res.content))
        self.assertEqual(img.format, "JPEG")

    def test_single_download_raw_never_watermarked(self):
        """RAW files must never be watermarked even if watermark=true is requested."""
        url = f"/api/galleries/media/{self.media_with_raw.id}/download/?format=raw&watermark=true"
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.content, self.raw_content)

    def test_single_download_disabled_returns_403(self):
        """When gallery has downloads disabled, returns 403."""
        self.gallery.allow_downloads = False
        self.gallery.downloads_enabled = False
        self.gallery.save()

        url = f"/api/galleries/media/{self.media_jpeg_only.id}/download/"
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # =========================================================================
    # 2. Multi-Image ZIP Download Tests
    # =========================================================================
    def test_gallery_zip_download_format_raw(self):
        """GET /api/public/galleries/<slug>/download-zip/?format=raw packages RAW companion files."""
        url = f"/api/public/galleries/{self.gallery.slug}/download-zip/?format=raw"
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res["Content-Type"], "application/zip")
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertIn(f"{self.gallery.slug}-raw-collection.zip", res["Content-Disposition"])

        with zipfile.ZipFile(io.BytesIO(res.content), 'r') as z:
            names = z.namelist()
            self.assertEqual(len(names), 2)
            # Find the raw file in archive
            raw_entry = next((n for n in names if n.endswith('.cr3')), None)
            self.assertIsNotNone(raw_entry)
            self.assertEqual(z.read(raw_entry), self.raw_content)

    def test_gallery_zip_download_format_jpeg(self):
        """GET /api/public/galleries/<slug>/download-zip/?format=jpeg packages web JPEG files."""
        url = f"/api/public/galleries/{self.gallery.slug}/download-zip/?format=jpeg"
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res["Content-Type"], "application/zip")
        self.assertIn(f"{self.gallery.slug}-jpeg-collection.zip", res["Content-Disposition"])

        with zipfile.ZipFile(io.BytesIO(res.content), 'r') as z:
            names = z.namelist()
            self.assertEqual(len(names), 2)
            for n in names:
                self.assertTrue(n.endswith('.jpg'))

    def test_gallery_zip_download_by_uuid(self):
        """GET /api/galleries/<uuid:gallery_id>/download-zip/?format=jpeg works via dashboard route."""
        url = f"/api/galleries/{self.gallery.id}/download-zip/?format=jpeg"
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn(f"{self.gallery.slug}-jpeg-collection.zip", res["Content-Disposition"])

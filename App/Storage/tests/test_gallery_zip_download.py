import io
import os
import zipfile
import uuid
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status
from django.core.cache import cache

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import SubscriptionPlans
from App.Storage.storage_models import Gallery, Media
from App.Storage.services.storage_service import get_storage_provider


class GalleryZipDownloadTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

        self.plan = SubscriptionPlans.objects.create(
            name="Studio Pro",
            price=99.00,
            storage_limit_bytes=500 * 1024 * 1024 * 1024,
            max_galleries=100,
            allowed_templates=["editorial", "masonry"]
        )

        self.user = User.objects.create_user(
            username="zip_photographer",
            email="zip@studio.com",
            password="secure-pass-12345",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            plan=self.plan,
            name="Zip Test Studio",
            studio_name="Zip Studio Master"
        )

        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Emma & Liam Wedding",
            client_name="Emma Liam",
            slug="emma-liam-wedding-2026",
            allow_downloads=True,
            downloads_enabled=True,
            expires_at=None,
        )

        # Write test media files into storage_objects
        storage = get_storage_provider()
        self.img_bytes1 = b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + b"A" * 100
        self.img_bytes2 = b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + b"B" * 200

        self.key1 = f"galleries/{self.gallery.id}/originals/photo_one.jpg"
        self.key2 = f"galleries/{self.gallery.id}/originals/photo_two.jpg"
        storage.upload(self.key1, self.img_bytes1, content_type="image/jpeg")
        storage.upload(self.key2, self.img_bytes2, content_type="image/jpeg")

        self.media1 = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="Ceremony Highlight",
            original_filename="photo_one.jpg",
            storage_key=self.key1,
            section_title="CEREMONY",
            file_size=len(self.img_bytes1),
            upload_status="completed",
        )

        self.media2 = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="Reception Dance",
            original_filename="photo_two.jpg",
            storage_key=self.key2,
            section_title="RECEPTION",
            file_size=len(self.img_bytes2),
            upload_status="completed",
        )

    def tearDown(self):
        storage = get_storage_provider()
        try:
            storage.delete(self.key1)
            storage.delete(self.key2)
        except Exception:
            pass

    def test_download_zip_by_slug_returns_valid_populated_archive(self):
        """Calling GET /api/public/galleries/{slug}/download-zip/ returns non-empty ZIP with all files."""
        res = self.client.get(f"/api/public/galleries/{self.gallery.slug}/download-zip/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res["Content-Type"], "application/zip")
        self.assertIn("attachment; filename=", res["Content-Disposition"])
        self.assertIn("emma-liam-wedding-2026_photos.zip", res["Content-Disposition"])

        # Unpack in-memory ZIP and verify files
        zip_file = zipfile.ZipFile(io.BytesIO(res.content))
        file_list = zip_file.namelist()
        self.assertEqual(len(file_list), 2)
        ceremony_file = next(f for f in file_list if "Ceremony Highlight" in f)
        reception_file = next(f for f in file_list if "Reception Dance" in f)

        # Check content integrity
        data1 = zip_file.read(ceremony_file)
        self.assertEqual(data1, self.img_bytes1)
        data2 = zip_file.read(reception_file)
        self.assertEqual(data2, self.img_bytes2)

    def test_download_zip_by_uuid(self):
        """Calling GET /api/public/galleries/{uuid}/download-zip/ returns non-empty ZIP."""
        res = self.client.get(f"/api/public/galleries/{self.gallery.id}/download-zip/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res["Content-Type"], "application/zip")

        zip_file = zipfile.ZipFile(io.BytesIO(res.content))
        self.assertEqual(len(zip_file.namelist()), 2)

    def test_download_zip_filtered_by_section(self):
        """Filtering by ?section=CEREMONY only packages photos belonging to that section."""
        res = self.client.get(f"/api/public/galleries/{self.gallery.slug}/download-zip/?section=CEREMONY")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        zip_file = zipfile.ZipFile(io.BytesIO(res.content))
        file_list = zip_file.namelist()
        self.assertEqual(len(file_list), 1)
        self.assertEqual(file_list[0], "001_Ceremony Highlight.jpg")

    def test_download_zip_filtered_by_media_ids(self):
        """Filtering by ?media_ids=<uuid> only packages specified photos."""
        res = self.client.get(f"/api/public/galleries/{self.gallery.slug}/download-zip/?media_ids={self.media2.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        zip_file = zipfile.ZipFile(io.BytesIO(res.content))
        file_list = zip_file.namelist()
        self.assertEqual(len(file_list), 1)
        self.assertEqual(file_list[0], "001_Reception Dance.jpg")

    def test_download_zip_handles_remote_url_fallback(self):
        """If storage_key is absent or fails, it falls back to fetching via URL."""
        remote_media = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="Remote Shot",
            original_filename="remote.jpg",
            storage_key="remote_nonexistent_key",
            section_title="PORTRAITS",
            upload_status="completed",
        )
        # file_url or url property on the instance
        remote_media.file_url = "https://cdn.exshare.ai/galleries/remote.jpg"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"REMOTE_IMAGE_CONTENT"

        with patch("requests.get", return_value=mock_resp):
            res = self.client.get(f"/api/public/galleries/{self.gallery.slug}/download-zip/?media_ids={remote_media.id}")
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            zip_file = zipfile.ZipFile(io.BytesIO(res.content))
            self.assertEqual(len(zip_file.namelist()), 1)
            self.assertEqual(zip_file.read("001_Remote Shot.jpg"), b"REMOTE_IMAGE_CONTENT")

    def test_download_zip_downloads_disabled_returns_403(self):
        """When gallery has allow_downloads=False and downloads_enabled=False, returns 403."""
        self.gallery.allow_downloads = False
        self.gallery.downloads_enabled = False
        self.gallery.save()

        res = self.client.get(f"/api/public/galleries/{self.gallery.slug}/download-zip/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data["code"], "downloads_disabled")

    def test_download_zip_non_existent_gallery_returns_404(self):
        """When gallery does not exist, returns 404."""
        res = self.client.get("/api/public/galleries/non-existent-gallery-slug/download-zip/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

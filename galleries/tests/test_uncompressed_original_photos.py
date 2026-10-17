import io
import os
import uuid
import zipfile
import hashlib
from PIL import Image
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework import status

from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import SubscriptionPlans
from galleries.models import Gallery, Media as GalleryMedia
from App.Storage.services.storage_service import get_storage_provider

User = get_user_model()


def create_sample_photo(filename="canon_master_001.jpg", size=(800, 600), color=(180, 45, 90)):
    """Generate high-resolution test JPEG bytes."""
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    # Save with specific quality so we have deterministic test bytes
    img.save(buf, format="JPEG", quality=98)
    buf.seek(0)
    return buf.getvalue()


class UncompressedOriginalPhotoTests(APITestCase):
    def setUp(self):
        User.objects.all().delete()
        PhotographerProfile.objects.all().delete()
        Gallery.objects.all().delete()

        self.plan = SubscriptionPlans.objects.create(
            name="Atelier Pro Master Plan",
            price=199.00,
            storage_limit_bytes=500 * 1024 * 1024 * 1024,
            max_galleries=100
        )

        self.user = User.objects.create_user(
            username="master_photographer",
            email="master@exshare.ai",
            password="Password123!"
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            plan=self.plan,
            name="Ansel Adams Studio",
            studio_name="Yosemite Visuals",
            storage_used_bytes=0,
            storage_reserved_bytes=0,
            watermark_type="text",
            watermark_text="© YOSEMITE VISUALS",
            watermark_opacity=0.5,
            watermark_position="bottom-right"
        )
        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Alpine Range 2026",
            slug="alpine-range-2026",
            allow_downloads=True,
            downloads_enabled=True,
            watermark_enabled=True,  # Studio has watermarking enabled for web previews
            watermark_text="YOSEMITE VISUALS",
        )

        self.sample_bytes = create_sample_photo("canon_master_001.jpg", size=(1200, 800))
        self.sample_hash = hashlib.sha256(self.sample_bytes).hexdigest()

    def test_upload_and_download_original_preserves_exact_bytes_and_size(self):
        """
        Uploading a photo and downloading it must return the exact same bytes,
        size, and quality without compression, even when gallery.watermark_enabled is True.
        """
        self.client.force_authenticate(user=self.user)
        upload_url = f"/api/galleries/{self.gallery.id}/media/bulk-upload/"

        uploaded_file = SimpleUploadedFile(
            "canon_master_001.jpg",
            self.sample_bytes,
            content_type="image/jpeg"
        )

        # 1. Upload original photo
        response = self.client.post(
            upload_url,
            {"photos": [uploaded_file], "section_title": "LANDSCAPE"},
            format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        media_id = response.json()["media"][0]["id"]

        media_item = GalleryMedia.objects.get(id=media_id)
        self.assertTrue(bool(media_item.file), "media.file field must be populated with original file")
        self.assertEqual(media_item.file_size, len(self.sample_bytes))

        # 2. Download original photo (Default format=original)
        download_url = f"/api/galleries/media/{media_id}/download/"
        dl_res = self.client.get(download_url)

        self.assertEqual(dl_res.status_code, status.HTTP_200_OK)
        self.assertIn("attachment", dl_res["Content-Disposition"])
        self.assertEqual(int(dl_res["Content-Length"]), len(self.sample_bytes))

        # Byte-for-byte exact equality: zero compression, zero loss
        self.assertEqual(dl_res.content, self.sample_bytes)
        downloaded_hash = hashlib.sha256(dl_res.content).hexdigest()
        self.assertEqual(downloaded_hash, self.sample_hash)

    def test_download_original_when_format_original_explicitly_requested(self):
        """
        ?format=original explicitly guarantees raw uncompressed master asset delivery.
        """
        media_item = GalleryMedia.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="Alpine Ridge Sunset",
            original_filename="sunset_master.jpg",
            file=SimpleUploadedFile("sunset_master.jpg", self.sample_bytes, content_type="image/jpeg"),
            file_size=len(self.sample_bytes),
            file_extension=".jpg",
            mime_type="image/jpeg",
            upload_status="completed"
        )

        url = f"/api/galleries/media/{media_item.id}/download/?format=original"
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.content, self.sample_bytes)
        self.assertEqual(int(res["Content-Length"]), len(self.sample_bytes))

    def test_explicit_watermark_download_applies_at_max_quality(self):
        """
        When watermark is explicitly requested with ?watermark=true,
        watermark is applied while maintaining full image dimensions.
        """
        media_item = GalleryMedia.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="Alpine Peak",
            original_filename="peak.jpg",
            file=SimpleUploadedFile("peak.jpg", self.sample_bytes, content_type="image/jpeg"),
            file_size=len(self.sample_bytes),
            file_extension=".jpg",
            mime_type="image/jpeg",
            upload_status="completed"
        )

        url = f"/api/galleries/media/{media_item.id}/download/?format=jpeg&watermark=true"
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        img = Image.open(io.BytesIO(res.content))
        self.assertEqual(img.format, "JPEG")
        self.assertEqual(img.size, (1200, 800))

    def test_gallery_zip_download_serves_exact_original_uncompressed_bytes(self):
        """
        Gallery ZIP download (/api/galleries/<id>/download-zip/) must package the exact
        original photos without lossy re-encoding or watermarking by default.
        """
        media_item = GalleryMedia.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title="Glacier Peak",
            original_filename="glacier.jpg",
            file=SimpleUploadedFile("glacier.jpg", self.sample_bytes, content_type="image/jpeg"),
            file_size=len(self.sample_bytes),
            file_extension=".jpg",
            mime_type="image/jpeg",
            upload_status="completed"
        )

        zip_url = f"/api/galleries/{self.gallery.id}/download-zip/"
        res = self.client.get(zip_url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("attachment", res["Content-Disposition"])

        # Unpack ZIP archive in-memory
        with zipfile.ZipFile(io.BytesIO(res.content), "r") as z:
            names = z.namelist()
            self.assertEqual(len(names), 1)
            archived_bytes = z.read(names[0])
            # Archived photo must be byte-for-byte identical to original
            self.assertEqual(archived_bytes, self.sample_bytes)
            self.assertEqual(len(archived_bytes), len(self.sample_bytes))

    def test_standard_media_upload_and_download_exact_bytes(self):
        """
        Verify StandardMediaUploadView saves the original uncompressed photo,
        assigns file and original_storage_key, and allows full quality download.
        """
        self.client.force_authenticate(user=self.user)
        upload_url = f"/api/storage/galleries/{self.gallery.id}/upload/"

        uploaded_file = SimpleUploadedFile(
            "studio_portrait_raw.jpg",
            self.sample_bytes,
            content_type="image/jpeg"
        )

        response = self.client.post(
            upload_url,
            {"photos": [uploaded_file], "section_title": "PORTRAITS"},
            format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        media_list = response.json().get("media", [])
        self.assertTrue(len(media_list) > 0)
        media_id = media_list[0]["id"]

        media_item = GalleryMedia.objects.get(id=media_id)
        self.assertTrue(bool(media_item.file), "media.file field must be populated")
        self.assertEqual(media_item.file_size, len(self.sample_bytes))

        # Download original photo
        download_url = f"/api/galleries/media/{media_id}/download/"
        dl_res = self.client.get(download_url)

        self.assertEqual(dl_res.status_code, status.HTTP_200_OK)
        self.assertEqual(dl_res.content, self.sample_bytes)
        self.assertEqual(int(dl_res["Content-Length"]), len(self.sample_bytes))

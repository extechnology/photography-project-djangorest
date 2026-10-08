import io
import os
import shutil
import uuid
from PIL import Image
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
from App.Storage.services.resumable_upload_service import ResumableUploadService


def create_dummy_jpeg(size=(200, 200), color="blue"):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format="JPEG")
    return buf.getvalue()


class ResumableAndFastTransferTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

        self.plan = SubscriptionPlans.objects.create(
            name="Pro Test Plan",
            price=99.00,
            storage_limit_bytes=500 * 1024 * 1024, # 500 MB
            max_galleries=50,
            face_search_enabled=True,
        )

        self.user = User.objects.create_user(
            username="resumable_pro",
            email="resumable@test.com",
            password="securepassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            plan=self.plan,
            name="Resumable Studio",
            email="resumable@test.com",
        )
        self.client.force_authenticate(user=self.user)

        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Fast Transfer Wedding",
            client_name="Sarah & John",
            slug="fast-transfer-wedding",
            allow_downloads=True,
            downloads_enabled=True,
        )

        self.test_jpeg_bytes = create_dummy_jpeg()
        self.total_size = len(self.test_jpeg_bytes)

    def tearDown(self):
        # Cleanup temporary upload sessions
        upload_temp = os.path.join(settings.MEDIA_ROOT, "upload_temp")
        if os.path.exists(upload_temp):
            try:
                shutil.rmtree(upload_temp)
            except Exception:
                pass

    def test_resumable_upload_lifecycle_success(self):
        """Full end-to-end test of Init -> Chunk 0 -> Chunk 1 -> Complete."""
        chunk_size = 500
        total_chunks = (self.total_size + chunk_size - 1) // chunk_size

        # 1. Init
        init_payload = {
            "filename": "wedding_highres.jpg",
            "file_size": self.total_size,
            "chunk_size": chunk_size,
            "mime_type": "image/jpeg",
            "total_chunks": total_chunks,
            "gallery_id": str(self.gallery.id),
            "section_title": "CEREMONY",
        }
        res_init = self.client.post("/api/storage/uploads/init/", init_payload, format="json")
        self.assertEqual(res_init.status_code, status.HTTP_201_CREATED)
        self.assertIn("upload_id", res_init.data)
        upload_id = res_init.data["upload_id"]
        self.assertEqual(res_init.data["committed_offset"], 0)

        # 2. Upload Chunks
        committed = 0
        for i in range(total_chunks):
            start = i * chunk_size
            end = min(self.total_size, start + chunk_size)
            chunk_data = self.test_jpeg_bytes[start:end]
            chunk_file = SimpleUploadedFile("chunk.bin", chunk_data, content_type="application/octet-stream")

            chunk_payload = {
                "upload_id": upload_id,
                "chunk_index": i,
                "offset": start,
                "chunk": chunk_file,
            }
            res_chunk = self.client.post("/api/storage/uploads/chunk/", chunk_payload, format="multipart")
            self.assertEqual(res_chunk.status_code, status.HTTP_200_OK)
            self.assertEqual(res_chunk.data["committed_offset"], end)
            committed = end

        # 3. Check Status
        res_status = self.client.get(f"/api/storage/uploads/status/?upload_id={upload_id}")
        self.assertEqual(res_status.status_code, status.HTTP_200_OK)
        self.assertEqual(res_status.data["committed_offset"], self.total_size)
        self.assertEqual(res_status.data["status"], "in_progress")

        # 4. Complete
        complete_payload = {
            "upload_id": upload_id,
            "final_filename": "wedding_highres.jpg",
            "section_title": "CEREMONY",
        }
        res_complete = self.client.post("/api/storage/uploads/complete/", complete_payload, format="json")
        self.assertEqual(res_complete.status_code, status.HTTP_201_CREATED)
        self.assertIn("media_id", res_complete.data)
        media_id = res_complete.data["media_id"]

        # Verify Media record created in database
        media = Media.objects.get(id=media_id)
        self.assertEqual(media.gallery_id, self.gallery.id)
        self.assertEqual(media.original_filename, "wedding_highres.jpg")
        self.assertEqual(media.file_size, self.total_size)
        self.assertEqual(media.section_title, "CEREMONY")
        self.assertEqual(media.upload_status, "completed")

        # Verify physical file existence and byte integrity on disk
        storage = get_storage_provider()
        abs_path = storage.get_absolute_path(media.storage_key)
        self.assertTrue(abs_path.exists())
        self.assertEqual(abs_path.stat().st_size, self.total_size)
        with open(abs_path, "rb") as f:
            self.assertEqual(f.read(), self.test_jpeg_bytes)

    def test_resumable_upload_rejects_mismatched_offset(self):
        """Chunk upload must reject corrupted or duplicate out-of-order offsets."""
        init_payload = {
            "filename": "offset_test.jpg",
            "file_size": self.total_size,
            "mime_type": "image/jpeg",
            "total_chunks": 2,
            "gallery_id": str(self.gallery.id),
        }
        res_init = self.client.post("/api/storage/uploads/init/", init_payload, format="json")
        upload_id = res_init.data["upload_id"]

        # Send invalid offset (e.g. 500 when committed is 0)
        chunk_file = SimpleUploadedFile("chunk.bin", b"A" * 100, content_type="application/octet-stream")
        chunk_payload = {
            "upload_id": upload_id,
            "chunk_index": 1,
            "offset": 500,
            "chunk": chunk_file,
        }
        res_chunk = self.client.post("/api/storage/uploads/chunk/", chunk_payload, format="multipart")
        self.assertEqual(res_chunk.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", res_chunk.data)

    def test_resumable_upload_cancel_cleans_up_storage(self):
        """Cancelling an upload session purges temporary chunk directory."""
        init_payload = {
            "filename": "cancel_test.jpg",
            "file_size": 2000,
            "mime_type": "image/jpeg",
            "total_chunks": 2,
            "gallery_id": str(self.gallery.id),
        }
        res_init = self.client.post("/api/storage/uploads/init/", init_payload, format="json")
        upload_id = res_init.data["upload_id"]

        # Upload first chunk
        chunk_file = SimpleUploadedFile("chunk.bin", b"B" * 1000, content_type="application/octet-stream")
        self.client.post("/api/storage/uploads/chunk/", {
            "upload_id": upload_id,
            "chunk_index": 0,
            "offset": 0,
            "chunk": chunk_file,
        }, format="multipart")

        session_dir = ResumableUploadService.get_upload_dir(upload_id)
        self.assertTrue(os.path.exists(session_dir))

        # Cancel
        res_cancel = self.client.post("/api/storage/uploads/cancel/", {"upload_id": upload_id}, format="json")
        self.assertEqual(res_cancel.status_code, status.HTTP_200_OK)
        self.assertFalse(os.path.exists(session_dir))

    def test_direct_upload_execute_view(self):
        """Test streaming direct-upload endpoint."""
        file_obj = SimpleUploadedFile("direct_photo.jpg", self.test_jpeg_bytes, content_type="image/jpeg")
        res = self.client.post(
            f"/api/storage/direct-upload/?key=galleries/{self.gallery.id}/originals/direct_photo.jpg",
            {"file": file_obj},
            format="multipart"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "success")

        # Test direct media file serve
        res_serve = self.client.get(f"/api/storage/media-file/?key=galleries/{self.gallery.id}/originals/direct_photo.jpg")
        self.assertEqual(res_serve.status_code, status.HTTP_200_OK)

    def test_quota_exceeded_on_init(self):
        """Init must reject uploads exceeding photographer quota."""
        # Set quota limit to 10 bytes
        self.profile.storage_used_bytes = 500 * 1024 * 1024 - 10
        self.profile.save()

        init_payload = {
            "filename": "oversized.jpg",
            "file_size": 100 * 1024 * 1024, # 100MB
            "total_chunks": 1,
            "gallery_id": str(self.gallery.id),
        }
        res_init = self.client.post("/api/storage/uploads/init/", init_payload, format="json")
        self.assertEqual(res_init.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    def test_atomic_culling_transfer_fast_path(self):
        """Verify media_transfer moves staging photos into gallery without RAM overhead."""
        from App.Storage.services.media_transfer import transfer_media_to_gallery
        from App.Storage.storage_models import GallerySection

        staging_dir = os.path.join(settings.MEDIA_ROOT, "culling_staging", "test_cull_session")
        os.makedirs(staging_dir, exist_ok=True)
        staging_file = os.path.join(staging_dir, "staged_shot.jpg")
        with open(staging_file, "wb") as f:
            f.write(self.test_jpeg_bytes)

        section = GallerySection.objects.create(gallery=self.gallery, title="CULLING_SELECTIONS")

        # Perform atomic transfer
        media = transfer_media_to_gallery(
            gallery=self.gallery,
            photographer=self.profile,
            section=section,
            original_filename="staged_shot.jpg",
            file_source=staging_file,
            media_type="photo",
        )

        self.assertIsNotNone(media)
        self.assertEqual(media.gallery_id, self.gallery.id)
        # Source staging file should have been moved away atomically
        self.assertFalse(os.path.exists(staging_file))
        # Destination file should exist in gallery originals
        storage = get_storage_provider()
        abs_dest = storage.get_absolute_path(media.storage_key)
        self.assertTrue(abs_dest.exists())
        self.assertEqual(abs_dest.stat().st_size, self.total_size)

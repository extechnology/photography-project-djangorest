import io
from datetime import timedelta
from PIL import Image
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from django.core.cache import cache
from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import SubscriptionPlans
from App.Storage.storage_models import (
    Gallery,
    Media,
    FaceEmbedding,
    BulkDownloadJob,
    UploadReservation,
)
from App.Storage.services.quota_service import StorageQuotaService, StorageQuotaExceededException
from App.Storage.services.face_service import FaceService
from App.Storage.services.storage_service import get_storage_provider


def create_test_image(filename="photo.jpg", size=(200, 200), color="blue"):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format="JPEG")
    buf.seek(0)
    return SimpleUploadedFile(filename, buf.read(), content_type="image/jpeg")


class EnterpriseStorageAndGalleryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()


        # Subscription plan with 100 MB limit for testing
        self.plan = SubscriptionPlans.objects.create(
            name="Pro Test Plan",
            price=99.00,
            storage_limit_bytes=100 * 1024 * 1024,  # 100 MB
            max_galleries=20,
            face_search_enabled=True,
        )

        # Photographer 1
        self.user1 = User.objects.create_user(
            username="photo_pro_1",
            email="pro1@test.com",
            password="testpassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile1 = PhotographerProfile.objects.create(
            user=self.user1,
            plan=self.plan,
            name="Studio One",
            email="pro1@test.com",
        )

        # Photographer 2
        self.user2 = User.objects.create_user(
            username="photo_pro_2",
            email="pro2@test.com",
            password="testpassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile2 = PhotographerProfile.objects.create(
            user=self.user2,
            plan=self.plan,
            name="Studio Two",
            email="pro2@test.com",
        )

    # -------------------------------------------------------------------------
    # 1. Authentication & Ownership Isolation
    # -------------------------------------------------------------------------
    def test_photographer_ownership_isolation(self):
        """Photographer cannot access or edit another photographer's gallery."""
        self.client.force_authenticate(user=self.user1)

        # Photographer 1 creates a gallery
        resp = self.client.post("/api/galleries/", {
            "title": "Private Wedding 2026",
            "visibility": "private",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        gallery_id = resp.data["id"]

        # Photographer 2 attempts to retrieve it
        self.client.force_authenticate(user=self.user2)
        get_resp = self.client.get(f"/api/galleries/{gallery_id}/")
        self.assertEqual(get_resp.status_code, status.HTTP_403_FORBIDDEN)

        # Photographer 2 attempts to patch it
        patch_resp = self.client.patch(f"/api/galleries/{gallery_id}/", {"title": "Hacked Title"}, format="json")
        self.assertEqual(patch_resp.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------------------
    # 2. Storage Quota Enforcement & Direct Uploads
    # -------------------------------------------------------------------------
    def test_storage_quota_enforcement_and_reconciliation(self):
        """System strictly enforces subscription storage quota and blocks exceeding uploads."""
        self.client.force_authenticate(user=self.user1)

        gallery = Gallery.objects.create(
            photographer=self.profile1,
            title="Quota Test Gallery",
        )

        # 1. Upload init within quota (50 MB out of 100 MB)
        init_resp = self.client.post(f"/api/galleries/{gallery.id}/upload-init/", {
            "original_filename": "big_shot.jpg",
            "file_size": 50 * 1024 * 1024,
            "mime_type": "image/jpeg",
        }, format="json")
        self.assertEqual(init_resp.status_code, status.HTTP_200_OK)
        self.assertIn("upload_url", init_resp.data)
        self.assertIn("reservation_id", init_resp.data)

        # Verify reserved bytes
        self.profile1.refresh_from_db()
        self.assertEqual(self.profile1.storage_reserved_bytes, 50 * 1024 * 1024)

        # 2. Upload init exceeding remaining quota (60 MB + 50 MB reserved = 110 MB > 100 MB limit)
        exceed_resp = self.client.post(f"/api/galleries/{gallery.id}/upload-init/", {
            "original_filename": "too_big.jpg",
            "file_size": 60 * 1024 * 1024,
            "mime_type": "image/jpeg",
        }, format="json")
        self.assertEqual(exceed_resp.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        self.assertEqual(exceed_resp.data["code"], "STORAGE_LIMIT_EXCEEDED")

        # 3. Simulate file upload and confirm
        storage = get_storage_provider()
        storage_key = init_resp.data["storage_key"]
        dummy_data = b"dummy jpeg bytes"
        storage.upload(storage_key, dummy_data, content_type="image/jpeg")

        confirm_resp = self.client.post(f"/api/galleries/{gallery.id}/upload-confirm/", {
            "reservation_id": init_resp.data["reservation_id"],
            "storage_key": storage_key,
            "original_filename": "big_shot.jpg",
            "file_size": len(dummy_data),
            "mime_type": "image/jpeg",
        }, format="json")
        self.assertEqual(confirm_resp.status_code, status.HTTP_201_CREATED)

        # Quota should now be committed (reserved bytes cleared, used bytes updated)
        self.profile1.refresh_from_db()
        self.assertEqual(self.profile1.storage_reserved_bytes, 0)
        self.assertEqual(self.profile1.storage_used_bytes, len(dummy_data))

        # 4. Storage Usage API check
        usage_resp = self.client.get("/api/account/storage/")
        self.assertEqual(usage_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(usage_resp.data["storage_used_bytes"], len(dummy_data))
        self.assertEqual(usage_resp.data["storage_limit_bytes"], 100 * 1024 * 1024)

        # 5. Run management command reconcile_storage_usage
        out = io.StringIO()
        call_command("reconcile_storage_usage", stdout=out)
        self.assertIn("Storage reconciliation complete", out.getvalue())

    # -------------------------------------------------------------------------
    # 3. Secure Share Links & Expiration
    # -------------------------------------------------------------------------
    def test_secure_share_link_and_revocation(self):
        """Photographer can generate and revoke share links; expired links are rejected."""
        self.client.force_authenticate(user=self.user1)

        gallery = Gallery.objects.create(
            photographer=self.profile1,
            title="Wedding Showcase",
            visibility="public",
        )
        initial_token = gallery.share_token

        # Unauthenticated client accesses gallery via token
        guest_client = APIClient()
        resp = guest_client.get(f"/api/shared-galleries/{initial_token}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["title"], "Wedding Showcase")

        # Photographer revokes share link (generates new token)
        revoke_resp = self.client.delete(f"/api/galleries/{gallery.id}/share/")
        self.assertEqual(revoke_resp.status_code, status.HTTP_200_OK)

        # Old token is now invalid
        old_token_resp = guest_client.get(f"/api/shared-galleries/{initial_token}/")
        self.assertEqual(old_token_resp.status_code, status.HTTP_404_NOT_FOUND)

        # Test expiration
        gallery.refresh_from_db()
        gallery.expires_at = timezone.now() - timedelta(minutes=10)
        gallery.save(update_fields=["expires_at"])

        expired_resp = guest_client.get(f"/api/shared-galleries/{gallery.share_token}/")
        self.assertEqual(expired_resp.status_code, status.HTTP_410_GONE)
        self.assertEqual(expired_resp.data["code"], "GALLERY_EXPIRED")

    # -------------------------------------------------------------------------
    # 4. Secure Single & Bulk Downloads
    # -------------------------------------------------------------------------
    def test_secure_download_permissions(self):
        """Enforces downloads_enabled on single and bulk download requests."""
        gallery = Gallery.objects.create(
            photographer=self.profile1,
            title="Download Test Gallery",
            downloads_enabled=False,  # Downloads explicitly disabled!
        )

        storage = get_storage_provider()
        key = f"galleries/{gallery.id}/originals/p1.jpg"
        storage.upload(key, b"test image payload", content_type="image/jpeg")

        media = Media.objects.create(
            photographer=self.profile1,
            gallery=gallery,
            original_filename="p1.jpg",
            storage_key=key,
            file_size=18,
        )

        guest_client = APIClient()

        # 1. Single download should be rejected
        single_resp = guest_client.get(f"/api/galleries/media/{media.id}/download/")
        self.assertEqual(single_resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(single_resp.data["code"], "DOWNLOAD_DISABLED")

        # 2. Bulk download should be rejected
        bulk_resp = guest_client.post(f"/api/galleries/{gallery.id}/bulk-download/", format="json")
        self.assertEqual(bulk_resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(bulk_resp.data["code"], "DOWNLOAD_DISABLED")

        # 3. Enable downloads
        gallery.downloads_enabled = True
        gallery.save(update_fields=["downloads_enabled"])

        # Bulk download accepted
        bulk_ok_resp = guest_client.post(f"/api/galleries/{gallery.id}/bulk-download/", format="json")
        self.assertEqual(bulk_ok_resp.status_code, status.HTTP_202_ACCEPTED)
        job_id = bulk_ok_resp.data["job"]["id"]

        # Check job status
        job_resp = guest_client.get(f"/api/galleries/bulk-download-jobs/{job_id}/")
        self.assertEqual(job_resp.status_code, status.HTTP_200_OK)
        self.assertIn(job_resp.data["status"], ["ready", "processing", "pending"])

    # -------------------------------------------------------------------------
    # 5. Face Detection & Isolated Gallery Search
    # -------------------------------------------------------------------------
    def test_face_search_gallery_isolation(self):
        """Face search returns matching photos and strictly isolates results to the target gallery."""
        # Gallery A and Gallery B
        gallery_a = Gallery.objects.create(
            photographer=self.profile1,
            title="Gallery A (Weddings)",
            face_search_enabled=True,
        )
        gallery_b = Gallery.objects.create(
            photographer=self.profile2,
            title="Gallery B (Corporate)",
            face_search_enabled=True,
        )

        storage = get_storage_provider()

        # Create photo in Gallery A
        img_a = create_test_image("bride.jpg", color="pink")
        key_a = f"galleries/{gallery_a.id}/originals/bride.jpg"
        data_a = img_a.read()
        storage.upload(key_a, data_a, content_type="image/jpeg")

        media_a = Media.objects.create(
            photographer=self.profile1,
            gallery=gallery_a,
            original_filename="bride.jpg",
            storage_key=key_a,
            file_size=len(data_a),
        )

        # Index faces for Media A
        FaceService.process_and_index_media_faces(media_a, data_a)
        self.assertTrue(FaceEmbedding.objects.filter(gallery=gallery_a).exists())

        # Also create a photo in Gallery B
        img_b = create_test_image("ceo.jpg", color="pink")
        key_b = f"galleries/{gallery_b.id}/originals/ceo.jpg"
        data_b = img_b.read()
        storage.upload(key_b, data_b, content_type="image/jpeg")

        media_b = Media.objects.create(
            photographer=self.profile2,
            gallery=gallery_b,
            original_filename="ceo.jpg",
            storage_key=key_b,
            file_size=len(data_b),
        )
        FaceService.process_and_index_media_faces(media_b, data_b)

        guest_client = APIClient()

        # Search in Gallery A using the same selfie face
        selfie_file = create_test_image("selfie.jpg", color="pink")
        search_resp = guest_client.post(
            f"/api/galleries/{gallery_a.id}/face-search/",
            {"selfie": selfie_file},
            format="multipart"
        )
        self.assertEqual(search_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(search_resp.data["count"], 1)

        # Verify results strictly contain media from Gallery A, never Gallery B
        result_media_ids = [r["media_id"] for r in search_resp.data["results"]]
        self.assertIn(str(media_a.id), result_media_ids)
        self.assertNotIn(str(media_b.id), result_media_ids)

        # Verify face search disabled returns proper error
        gallery_a.face_search_enabled = False
        gallery_a.save(update_fields=["face_search_enabled"])

        selfie_file.seek(0)
        disabled_resp = guest_client.post(
            f"/api/galleries/{gallery_a.id}/face-search/",
            {"selfie": selfie_file},
            format="multipart"
        )
        self.assertEqual(disabled_resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(disabled_resp.data["code"], "FACE_SEARCH_DISABLED")

    # -------------------------------------------------------------------------
    # 6. Rate Limiting Throttles
    # -------------------------------------------------------------------------
    def test_rate_limiting_throttles(self):
        """Verifies that exceeding configured rate limits returns HTTP 429 Too Many Requests."""
        gallery = Gallery.objects.create(
            photographer=self.profile1,
            title="Rate Limit Gallery",
            downloads_enabled=True,
        )

        guest_client = APIClient()

        # Bulk download throttle has scope 'bulk_download' (e.g. 5/minute).
        # Trigger requests until throttled or verify throttle class logic
        throttled = False
        for _ in range(10):
            resp = guest_client.post(f"/api/galleries/{gallery.id}/bulk-download/", format="json")
            if resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                throttled = True
                break

        self.assertTrue(throttled, "Bulk download requests should be throttled with HTTP 429 when rate limit is exceeded.")


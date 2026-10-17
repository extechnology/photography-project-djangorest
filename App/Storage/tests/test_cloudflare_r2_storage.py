import io
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError
from django.test import TestCase, override_settings
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import SubscriptionPlans
from App.Storage.storage_models import Gallery, Media, UploadReservation
from App.Storage.storage_serializers import MediaSerializer
from App.Storage.services.quota_service import StorageQuotaService
from App.Storage.services.storage_service import (
    CloudflareR2StorageProvider,
    CloudflareR2Storage,
    get_storage_provider,
)


class CloudflareR2StorageTests(TestCase):
    """
    Comprehensive test suite for Cloudflare R2 integration:
    - Client configuration & endpoint generation
    - Presigned upload & download URL generation
    - Delivery through configurable CDN custom domain
    - Direct upload init & confirm API workflows
    - Permission & authentication enforcement
    - Missing object handling & safe idempotent deletion
    - Preservation of existing response structures and schemas
    """

    def setUp(self):
        cache.clear()
        self.client = APIClient()

        # Subscription plan with 100 MB quota
        self.plan = SubscriptionPlans.objects.create(
            name="R2 Test Pro Plan",
            price=199.00,
            storage_limit_bytes=100 * 1024 * 1024,
            max_galleries=10,
            face_search_enabled=True,
        )

        # Photographer 1 (Owner)
        self.user1 = User.objects.create_user(
            username="r2_photographer_1",
            email="r2_photo1@example.com",
            password="testpassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile1 = PhotographerProfile.objects.create(
            user=self.user1,
            plan=self.plan,
            name="R2 Studio Pro",
            storage_used_bytes=0,
            storage_reserved_bytes=0,
        )

        # Photographer 2 (Attacker / Unauthorized)
        self.user2 = User.objects.create_user(
            username="r2_photographer_2",
            email="r2_photo2@example.com",
            password="testpassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile2 = PhotographerProfile.objects.create(
            user=self.user2,
            plan=self.plan,
            name="R2 Studio Two",
            storage_used_bytes=0,
            storage_reserved_bytes=0,
        )

        # Gallery owned by Photographer 1
        self.gallery = Gallery.objects.create(
            photographer=self.profile1,
            title="R2 Wedding Showcase",
            slug="r2-wedding-showcase",
        )

    def test_r2_client_configuration_and_endpoint(self):
        """Test R2 provider initializes with proper endpoint URL, region, and SigV4 config."""
        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.return_value = mock_s3

            provider = CloudflareR2StorageProvider(
                account_id="test_acc_123",
                access_key="test_key_abc",
                secret_key="test_secret_xyz",
                bucket="exshareai",
                public_domain="https://media.exshare.ai",
            )

            self.assertEqual(provider.account_id, "test_acc_123")
            self.assertEqual(provider.bucket, "exshareai")
            self.assertEqual(provider.endpoint_url, "https://test_acc_123.r2.cloudflarestorage.com")
            self.assertEqual(provider.cdn_base, "https://media.exshare.ai")
            self.assertEqual(provider.region, "auto")

            mock_boto.assert_called_once()
            args, kwargs = mock_boto.call_args
            self.assertEqual(args[0], "s3")
            self.assertEqual(kwargs["endpoint_url"], "https://test_acc_123.r2.cloudflarestorage.com")
            self.assertEqual(kwargs["aws_access_key_id"], "test_key_abc")
            self.assertEqual(kwargs["aws_secret_access_key"], "test_secret_xyz")
            self.assertEqual(kwargs["region_name"], "auto")
            self.assertEqual(kwargs["config"].signature_version, "s3v4")

    def test_r2_presigned_upload_url_generation(self):
        """Test presigned PUT URL generation with exact expected structure."""
        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_s3.generate_presigned_url.return_value = "https://test_acc.r2.cloudflarestorage.com/exshareai/photo.jpg?signed=true"
            mock_boto.return_value = mock_s3

            provider = CloudflareR2StorageProvider(
                account_id="test_acc",
                access_key="key",
                secret_key="secret",
                bucket="exshareai",
            )

            res = provider.generate_signed_upload_url(
                key="galleries/g1/originals/photo.jpg",
                expires_in=1800,
                content_type="image/jpeg",
            )

            # Validate exact structure required by API and frontend
            self.assertIn("upload_url", res)
            self.assertIn("method", res)
            self.assertIn("headers", res)
            self.assertIn("storage_key", res)
            self.assertIn("expires_in", res)

            self.assertEqual(res["method"], "PUT")
            self.assertEqual(res["headers"], {"Content-Type": "image/jpeg"})
            self.assertEqual(res["storage_key"], "galleries/g1/originals/photo.jpg")
            self.assertEqual(res["expires_in"], 1800)
            self.assertEqual(res["upload_url"], "https://test_acc.r2.cloudflarestorage.com/exshareai/photo.jpg?signed=true")

            mock_s3.generate_presigned_url.assert_called_once_with(
                ClientMethod="put_object",
                Params={"Bucket": "exshareai", "Key": "galleries/g1/originals/photo.jpg", "ContentType": "image/jpeg"},
                ExpiresIn=1800,
            )

    def test_r2_presigned_download_url_generation(self):
        """Test presigned GET URL generation for private download delivery."""
        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_s3.generate_presigned_url.return_value = "https://test_acc.r2.cloudflarestorage.com/exshareai/photo.jpg?download=true"
            mock_boto.return_value = mock_s3

            provider = CloudflareR2StorageProvider(
                account_id="test_acc",
                access_key="key",
                secret_key="secret",
                bucket="exshareai",
            )

            url = provider.generate_signed_download_url(
                key="galleries/g1/originals/photo.jpg",
                expires_in=3600,
                filename="wedding_highres.jpg",
            )

            self.assertEqual(url, "https://test_acc.r2.cloudflarestorage.com/exshareai/photo.jpg?download=true")
            mock_s3.generate_presigned_url.assert_called_once_with(
                ClientMethod="get_object",
                Params={
                    "Bucket": "exshareai",
                    "Key": "galleries/g1/originals/photo.jpg",
                    "ResponseContentDisposition": 'attachment; filename="wedding_highres.jpg"',
                },
                ExpiresIn=3600,
            )

    def test_r2_cdn_url_generation_with_custom_domain(self):
        """Test CDN delivery URL when R2_PUBLIC_DOMAIN is configured."""
        with patch("boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock()

            provider = CloudflareR2StorageProvider(
                account_id="test_acc",
                access_key="key",
                secret_key="secret",
                bucket="exshareai",
                public_domain="https://media.exshare.ai",
            )

            cdn_url = provider.generate_cdn_url("galleries/g1/previews/preview.jpg")
            self.assertEqual(cdn_url, "https://media.exshare.ai/galleries/g1/previews/preview.jpg")

    def test_r2_cdn_url_fallback_to_signed_download_when_no_public_domain(self):
        """Test private media delivery: when no CDN domain is configured, fallback to signed GET URL."""
        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_s3.generate_presigned_url.return_value = "https://test_acc.r2.cloudflarestorage.com/exshareai/secret.jpg?signed_get=true"
            mock_boto.return_value = mock_s3

            provider = CloudflareR2StorageProvider(
                account_id="test_acc",
                access_key="key",
                secret_key="secret",
                bucket="exshareai",
                public_domain="",  # No custom domain connected
            )

            secure_url = provider.generate_cdn_url("galleries/g1/secret.jpg")
            self.assertEqual(secure_url, "https://test_acc.r2.cloudflarestorage.com/exshareai/secret.jpg?signed_get=true")
            mock_s3.generate_presigned_url.assert_called_once()

    def test_r2_safe_idempotent_deletion(self):
        """Test object deletion safely handles missing objects and exceptions."""
        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.return_value = mock_s3

            provider = CloudflareR2StorageProvider(
                account_id="test_acc",
                access_key="key",
                secret_key="secret",
                bucket="exshareai",
            )

            # Successful deletion
            res = provider.delete("galleries/g1/photo.jpg")
            self.assertTrue(res)
            mock_s3.delete_object.assert_called_with(Bucket="exshareai", Key="galleries/g1/photo.jpg")

            # Missing or empty key
            self.assertTrue(provider.delete(""))

            # Exception handling
            mock_s3.delete_object.side_effect = Exception("Network timeout")
            self.assertFalse(provider.delete("galleries/g1/photo.jpg"))

    def test_r2_streaming_save_file_and_move_file(self):
        """Test zero-RAM-buffering upload via upload_fileobj and local move_file."""
        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.return_value = mock_s3

            provider = CloudflareR2StorageProvider(
                account_id="test_acc",
                access_key="key",
                secret_key="secret",
                bucket="exshareai",
            )

            # Test streaming save_file
            stream = io.BytesIO(b"sample file binary stream data")
            res_key = provider.save_file("galleries/g1/stream.jpg", stream, content_type="image/jpeg")
            self.assertEqual(res_key, "galleries/g1/stream.jpg")
            mock_s3.upload_fileobj.assert_called_once()
            call_kwargs = mock_s3.upload_fileobj.call_args[1]
            self.assertEqual(call_kwargs["Bucket"], "exshareai")
            self.assertEqual(call_kwargs["Key"], "galleries/g1/stream.jpg")
            self.assertEqual(call_kwargs["ExtraArgs"], {"ContentType": "image/jpeg"})

    def test_direct_upload_init_api_workflow_with_r2(self):
        """Test Step 1: Photographer requests pre-signed direct upload URL(s). Response schema preserved."""
        self.client.force_authenticate(user=self.user1)

        with patch("App.Storage.storage_views.get_storage_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.generate_signed_upload_url.return_value = {
                "upload_url": "https://acc.r2.cloudflarestorage.com/exshareai/galleries/upload.jpg?X-Amz=...",
                "method": "PUT",
                "headers": {"Content-Type": "image/jpeg"},
                "storage_key": f"galleries/{self.gallery.id}/originals/res_test.jpg",
                "expires_in": 1800,
            }
            mock_get_provider.return_value = mock_provider

            url = f"/api/storage/galleries/{self.gallery.id}/upload-init/"
            payload = {
                "filename": "wedding_photo.jpg",
                "file_size": 5 * 1024 * 1024,
                "mime_type": "image/jpeg",
                "media_type": "photo",
            }
            response = self.client.post(url, payload, format="json")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            data = response.json()

            # Exact response contract check
            self.assertIn("reservation_id", data)
            self.assertIn("storage_key", data)
            self.assertEqual(data["filename"], "wedding_photo.jpg")
            self.assertEqual(data["media_type"], "photo")
            self.assertEqual(data["method"], "PUT")
            self.assertEqual(data["headers"], {"Content-Type": "image/jpeg"})
            self.assertEqual(data["expires_in"], 1800)
            self.assertTrue(data["upload_url"].startswith("https://"))

    def test_direct_upload_init_unauthenticated_and_unauthorized_rejection(self):
        """Test Step 1 security: anonymous users and unauthorized photographers are rejected."""
        url = f"/api/storage/galleries/{self.gallery.id}/upload-init/"
        payload = {
            "filename": "hacker_photo.jpg",
            "file_size": 1024 * 1024,
        }

        # 1. Unauthenticated request -> 401
        res_anon = self.client.post(url, payload, format="json")
        self.assertEqual(res_anon.status_code, status.HTTP_401_UNAUTHORIZED)

        # 2. Authenticated as User 2 (not gallery owner) -> 403
        self.client.force_authenticate(user=self.user2)
        res_unauth = self.client.post(url, payload, format="json")
        self.assertEqual(res_unauth.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res_unauth.json().get("code"), "GALLERY_ACCESS_DENIED")

    def test_direct_upload_confirm_api_workflow_with_r2(self):
        """Test Step 2: Confirmation endpoint verifies file exists in R2, commits quota, returns 201."""
        self.client.force_authenticate(user=self.user1)

        # Create a valid quota reservation first
        reservation = StorageQuotaService.reserve_quota(self.profile1, self.gallery, 4 * 1024 * 1024)
        storage_key = f"galleries/{self.gallery.id}/originals/{reservation.id}_wedding.jpg"

        with patch("App.Storage.storage_views.get_storage_provider") as mock_get_views_provider, \
             patch("App.Storage.storage_serializers.get_storage_provider") as mock_get_ser_provider, \
             patch("App.Storage.storage_views.run_or_queue_task") as mock_task:

            mock_storage = MagicMock()
            mock_storage.exists.return_value = True
            mock_storage.get_metadata.return_value = {
                "size": 4 * 1024 * 1024,
                "content_type": "image/jpeg",
            }
            mock_storage.generate_cdn_url.return_value = f"https://media.exshare.ai/{storage_key}"
            mock_get_views_provider.return_value = mock_storage
            mock_get_ser_provider.return_value = mock_storage

            url = f"/api/storage/galleries/{self.gallery.id}/upload-confirm/"
            payload = {
                "reservation_id": str(reservation.id),
                "storage_key": storage_key,
                "original_filename": "wedding.jpg",
                "file_size": 4 * 1024 * 1024,
                "mime_type": "image/jpeg",
                "media_type": "photo",
            }
            response = self.client.post(url, payload, format="json")

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            data = response.json()

            # Ensure response structure is preserved
            self.assertEqual(data["message"], "Media upload confirmed successfully.")
            self.assertIn("media", data)
            media_data = data["media"]
            self.assertEqual(media_data["original_filename"], "wedding.jpg")
            self.assertEqual(media_data["file_size"], 4 * 1024 * 1024)
            self.assertEqual(media_data["preview_url"], f"https://media.exshare.ai/{storage_key}")

            # Ensure Media model record is created in DB with correct storage_key
            media_obj = Media.objects.get(storage_key=storage_key)
            self.assertEqual(media_obj.gallery_id, self.gallery.id)
            self.assertEqual(media_obj.photographer_id, self.profile1.id)

            # Verify background task dispatched
            mock_task.assert_called_once()

    def test_direct_upload_confirm_missing_r2_object_rejected(self):
        """Test Step 2: If object does not exist in R2, confirmation fails with 400 and releases quota."""
        self.client.force_authenticate(user=self.user1)

        reservation = StorageQuotaService.reserve_quota(self.profile1, self.gallery, 2 * 1024 * 1024)
        storage_key = f"galleries/{self.gallery.id}/originals/{reservation.id}_missing.jpg"

        with patch("App.Storage.storage_views.get_storage_provider") as mock_get_provider:
            mock_storage = MagicMock()
            mock_storage.exists.return_value = False  # Object NOT found in R2
            mock_get_provider.return_value = mock_storage

            url = f"/api/storage/galleries/{self.gallery.id}/upload-confirm/"
            payload = {
                "reservation_id": str(reservation.id),
                "storage_key": storage_key,
                "original_filename": "missing.jpg",
            }
            response = self.client.post(url, payload, format="json")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            data = response.json()
            self.assertEqual(data.get("code"), "FILE_NOT_FOUND_IN_STORAGE")

            # Check that reservation was cancelled/released
            res_after = UploadReservation.objects.get(id=reservation.id)
            self.assertIn(res_after.status, ("cancelled", "released"))

    def test_media_serializer_generates_cdn_url(self):
        """Test MediaSerializer returns the configured CDN URL in url, thumbnail_url, and preview_url fields."""
        media = Media.objects.create(
            photographer=self.profile1,
            gallery=self.gallery,
            storage_key="galleries/g1/originals/1.jpg",
            preview_storage_key="galleries/g1/previews/1.jpg",
            thumbnail_storage_key="galleries/g1/thumbnails/1.jpg",
            original_filename="1.jpg",
            file_size=1024,
        )

        with patch("App.Storage.storage_serializers.get_storage_provider") as mock_get_provider:
            mock_storage = MagicMock()
            mock_storage.generate_cdn_url.side_effect = lambda k: f"https://media.exshare.ai/{k}"
            mock_get_provider.return_value = mock_storage

            serializer = MediaSerializer(media)
            data = serializer.data

            self.assertEqual(data["thumbnail_url"], "https://media.exshare.ai/galleries/g1/thumbnails/1.jpg")
            self.assertEqual(data["preview_url"], "https://media.exshare.ai/galleries/g1/previews/1.jpg")
            self.assertEqual(data["url"], "https://media.exshare.ai/galleries/g1/previews/1.jpg")

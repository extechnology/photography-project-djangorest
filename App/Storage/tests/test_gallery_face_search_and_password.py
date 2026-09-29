import io
from PIL import Image
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import SubscriptionPlans
from App.Storage.storage_models import Gallery, Media


def create_test_image(filename="photo.jpg", size=(200, 200), color="blue"):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format="JPEG")
    buf.seek(0)
    return SimpleUploadedFile(filename, buf.read(), content_type="image/jpeg")


class GalleryFaceSearchAndPasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

        # Plan with face search enabled
        self.plan_with_face = SubscriptionPlans.objects.create(
            name="Pro Plan Face Search",
            price=99.00,
            storage_limit_bytes=100 * 1024 * 1024,
            max_galleries=20,
            face_search_enabled=True,
        )

        # Plan with face search locked
        self.plan_without_face = SubscriptionPlans.objects.create(
            name="Starter Plan No Face Search",
            price=29.00,
            storage_limit_bytes=50 * 1024 * 1024,
            max_galleries=5,
            face_search_enabled=False,
        )

        # Photographer 1 (Plan with face search)
        self.user1 = User.objects.create_user(
            username="photographer_pro",
            email="pro@studio.com",
            password="testpassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile1 = PhotographerProfile.objects.create(
            user=self.user1,
            plan=self.plan_with_face,
            name="Studio Pro",
            email="pro@studio.com",
        )

        # Photographer 2 (Plan without face search)
        self.user2 = User.objects.create_user(
            username="photographer_basic",
            email="basic@studio.com",
            password="testpassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile2 = PhotographerProfile.objects.create(
            user=self.user2,
            plan=self.plan_without_face,
            name="Studio Basic",
            email="basic@studio.com",
        )

    def test_gallery_default_face_search_disabled(self):
        """Newly created gallery should have face_search_enabled=False by default."""
        self.client.force_authenticate(user=self.user1)
        resp = self.client.post("/api/galleries/", {
            "title": "Summer Beach Shoot",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertFalse(resp.data.get("face_search_enabled"))

        gallery = Gallery.objects.get(id=resp.data["id"])
        self.assertFalse(gallery.face_search_enabled)

    def test_patch_password_protection_toggle_and_wipe(self):
        """Disabling password protection sets is_password_protected=False and wipes password."""
        self.client.force_authenticate(user=self.user1)
        # Create gallery with password
        gallery = Gallery.objects.create(
            photographer=self.profile1,
            title="Secured Event",
            is_password_protected=True,
            password="InitialSecret123",
            visibility="password_protected",
        )

        # Disable password protection
        patch_resp = self.client.patch(f"/api/galleries/{gallery.id}/", {
            "is_password_protected": False,
        }, format="json")
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        gallery.refresh_from_db()
        self.assertFalse(gallery.is_password_protected)
        self.assertEqual(gallery.password, "")
        self.assertEqual(gallery.visibility, "public")

        # Public guest accesses gallery without password
        self.client.logout()
        get_resp = self.client.get(f"/api/galleries/{gallery.id}/")
        self.assertEqual(get_resp.status_code, status.HTTP_200_OK)

    def test_patch_password_protection_enable(self):
        """Enabling password protection sets password and protects gallery for visitors."""
        self.client.force_authenticate(user=self.user1)
        gallery = Gallery.objects.create(
            photographer=self.profile1,
            title="Open Event",
            is_password_protected=False,
            password="",
            visibility="public",
        )

        patch_resp = self.client.patch(f"/api/galleries/{gallery.id}/", {
            "is_password_protected": True,
            "password": "NewSecretPassword",
        }, format="json")
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        gallery.refresh_from_db()
        self.assertTrue(gallery.is_password_protected)
        self.assertTrue(gallery.check_access_password("NewSecretPassword"))

        # Public visitor access without password returns 403 PASSWORD_REQUIRED
        self.client.logout()
        get_resp = self.client.get(f"/api/galleries/{gallery.id}/")
        self.assertEqual(get_resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(get_resp.data.get("code"), "PASSWORD_REQUIRED")

        # Public visitor access with password returns 200 OK
        auth_get_resp = self.client.get(f"/api/galleries/{gallery.id}/", HTTP_X_GALLERY_PASSWORD="NewSecretPassword")
        self.assertEqual(auth_get_resp.status_code, status.HTTP_200_OK)

    def test_face_search_plan_enforcement_rejected_when_not_allowed(self):
        """Photographer with basic plan cannot enable face search."""
        self.client.force_authenticate(user=self.user2)
        gallery = Gallery.objects.create(
            photographer=self.profile2,
            title="Basic Gallery",
            face_search_enabled=False,
        )

        resp = self.client.patch(f"/api/galleries/{gallery.id}/", {
            "face_search_enabled": True,
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data.get("error_code"), "FACE_SEARCH_LOCKED")

    def test_face_search_plan_enforcement_allowed_when_plan_permits(self):
        """Photographer with pro plan can enable face search."""
        self.client.force_authenticate(user=self.user1)
        gallery = Gallery.objects.create(
            photographer=self.profile1,
            title="Pro Gallery",
            face_search_enabled=False,
        )

        resp = self.client.patch(f"/api/galleries/{gallery.id}/", {
            "face_search_enabled": True,
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        gallery.refresh_from_db()
        self.assertTrue(gallery.face_search_enabled)

    def test_face_search_endpoint_permissions_and_slug_resolution(self):
        """Face search endpoint allows public guest, resolves slug, and returns expected schema."""
        # 1. Gallery with face search disabled
        gallery = Gallery.objects.create(
            photographer=self.profile1,
            title="Face Search Gallery",
            slug="face-search-test-slug",
            face_search_enabled=False,
        )

        selfie = create_test_image("selfie.jpg")
        self.client.logout()

        # Should return 403 FACE_SEARCH_DISABLED by slug
        resp_disabled = self.client.post(
            f"/api/galleries/{gallery.slug}/face-search/",
            {"selfie": selfie},
            format="multipart",
        )
        self.assertEqual(resp_disabled.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_disabled.data.get("error_code"), "FACE_SEARCH_DISABLED")

        # 2. Enable face search on gallery
        gallery.face_search_enabled = True
        gallery.save()

        # Add a media item to gallery
        photo_file = create_test_image("test_photo.jpg")
        media = Media.objects.create(
            gallery=gallery,
            photographer=self.profile1,
            file=photo_file,
            original_filename="test_photo.jpg",
            file_size=1024,
            media_type="photo",
        )

        # 3. Perform face search with selfie by UUID
        selfie.seek(0)
        resp_search = self.client.post(
            f"/api/galleries/{gallery.id}/face-search/",
            {"selfie": selfie},
            format="multipart",
        )
        self.assertEqual(resp_search.status_code, status.HTTP_200_OK)
        self.assertIn("matched_media_ids", resp_search.data)
        self.assertIn("matched_media", resp_search.data)
        self.assertIn("total_matches", resp_search.data)
        self.assertIn("confidence", resp_search.data)

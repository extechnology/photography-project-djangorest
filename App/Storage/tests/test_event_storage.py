import io
import zipfile
from PIL import Image
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Storage.storage_models import SharedEvent, EventPhoto


def create_dummy_image(name="test.jpg", color="blue", size=(100, 100)):
    file_obj = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(file_obj, format="JPEG")
    file_obj.seek(0)
    return SimpleUploadedFile(name, file_obj.read(), content_type="image/jpeg")


def create_dummy_zip(files_dict):
    """files_dict: { 'photo1.jpg': image_bytes, 'photo2.png': image_bytes }"""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as z:
        for fname, data in files_dict.items():
            z.writestr(fname, data)
    zip_buffer.seek(0)
    return SimpleUploadedFile("wedding_photos.zip", zip_buffer.read(), content_type="application/zip")


class PhotoSharingAndBulkDownloadTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create photographer user
        self.user = User.objects.create_user(
            username="wedding_candid_pro",
            email="photographer@test.com",
            password="securepassword123",
            role=User.Role.PHOTOGRAPHER
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Candid Studios",
            phone="9876543210",
            email="photographer@test.com"
        )
        self.client.force_authenticate(user=self.user)

    def test_create_shared_event(self):
        """Photographer can create a marriage function photo album."""
        payload = {
            "title": "Rahul & Priya Wedding",
            "event_type": "wedding",
            "venue": "Grand Palace Auditorium",
            "description": "Ceremony & Reception photos",
            "pin_code": "1234",
            "allow_downloads": True,
        }
        response = self.client.post("/api/storage/events/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("access_code", response.data["data"])
        self.assertEqual(response.data["data"]["title"], "Rahul & Priya Wedding")
        self.assertTrue(response.data["data"]["is_pin_protected"])

    def test_bulk_photo_upload_multifile(self):
        """Photographer can upload multiple photos in bulk at once."""
        event = SharedEvent.objects.create(
            photographer=self.profile,
            title="Rahul & Priya Wedding",
            event_type="wedding"
        )

        img1 = create_dummy_image("ceremony_01.jpg", color="red")
        img2 = create_dummy_image("ceremony_02.jpg", color="green")
        img3 = create_dummy_image("reception_01.jpg", color="yellow")

        response = self.client.post(
            f"/api/storage/events/{event.id}/upload/",
            {
                "photos": [img1, img2, img3],
                "category_tag": "Ceremony",
                "caption": "Wedding ceremony highlights"
            },
            format="multipart"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["total_uploaded"], 3)
        self.assertEqual(EventPhoto.objects.filter(event=event).count(), 3)
        self.assertEqual(EventPhoto.objects.filter(event=event, category_tag="Ceremony").count(), 3)

    def test_bulk_photo_upload_zip(self):
        """Photographer can upload a complete exported ZIP archive."""
        event = SharedEvent.objects.create(
            photographer=self.profile,
            title="Rohit & Ananya Reception",
            event_type="reception"
        )

        img1_data = create_dummy_image("stage_01.jpg").read()
        img2_data = create_dummy_image("couple_02.jpg").read()
        zip_file = create_dummy_zip({
            "wedding/stage_01.jpg": img1_data,
            "wedding/couple_02.jpg": img2_data,
            "wedding/notes.txt": b"This is a text file that should be skipped"
        })

        response = self.client.post(
            f"/api/storage/events/{event.id}/upload-zip/",
            {
                "zip_file": zip_file,
                "category_tag": "Stage",
            },
            format="multipart"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["total_extracted"], 2)
        self.assertEqual(response.data["total_skipped"], 1)
        self.assertEqual(EventPhoto.objects.filter(event=event).count(), 2)

    def test_public_guest_access_without_login(self):
        """Guests can view photos instantly via access code without logging in."""
        event = SharedEvent.objects.create(
            photographer=self.profile,
            title="Arjun & Maya Marriage",
            event_type="wedding"
        )
        img = create_dummy_image("photo1.jpg")
        EventPhoto.objects.create(event=event, image=img, original_filename="photo1.jpg")

        # Unauthenticated client (wedding guest)
        guest_client = APIClient()
        response = guest_client.get(f"/api/storage/share/{event.access_code}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["pin_required"])
        self.assertEqual(len(response.data["photos"]), 1)
        self.assertEqual(response.data["event"]["title"], "Arjun & Maya Marriage")

        # Verify views count incremented
        event.refresh_from_db()
        self.assertEqual(event.views_count, 1)

    def test_pin_protected_event_access(self):
        """PIN protected events require guest to provide correct PIN."""
        event = SharedEvent.objects.create(
            photographer=self.profile,
            title="Private Marriage",
            pin_code="7788"
        )
        img = create_dummy_image("photo_private.jpg")
        EventPhoto.objects.create(event=event, image=img, original_filename="photo_private.jpg")

        guest_client = APIClient()

        # Without PIN
        resp1 = guest_client.get(f"/api/storage/share/{event.access_code}/")
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertTrue(resp1.data["pin_required"])

        # With wrong PIN
        resp2 = guest_client.get(f"/api/storage/share/{event.access_code}/?pin=0000")
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertTrue(resp2.data["pin_required"])

        # With correct PIN
        resp3 = guest_client.get(f"/api/storage/share/{event.access_code}/?pin=7788")
        self.assertEqual(resp3.status_code, status.HTTP_200_OK)
        self.assertFalse(resp3.data["pin_required"])
        self.assertEqual(len(resp3.data["photos"]), 1)

        # PIN verify endpoint
        verify_resp = guest_client.post(f"/api/storage/share/{event.access_code}/verify-pin/", {"pin": "7788"})
        self.assertEqual(verify_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(verify_resp.data["valid"])

    def test_instant_single_photo_download(self):
        """Guests can instantly download a single photo with attachment disposition."""
        event = SharedEvent.objects.create(
            photographer=self.profile,
            title="Wedding Function",
            allow_downloads=True
        )
        img = create_dummy_image("candid_moment.jpg")
        photo = EventPhoto.objects.create(event=event, image=img, original_filename="candid_moment.jpg")

        guest_client = APIClient()
        response = guest_client.get(f"/api/storage/photos/{photo.id}/download/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('attachment; filename="candid_moment.jpg"', response.headers.get("Content-Disposition", ""))

        # Check download metrics incremented
        photo.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(photo.downloads_count, 1)
        self.assertEqual(event.downloads_count, 1)

    def test_instant_bulk_download_all_zip(self):
        """Guests can instantly download all wedding photos as a ZIP archive."""
        event = SharedEvent.objects.create(
            photographer=self.profile,
            title="Sunil & Deepa Wedding",
            allow_downloads=True
        )
        p1 = EventPhoto.objects.create(event=event, image=create_dummy_image("p1.jpg"), original_filename="p1.jpg")
        p2 = EventPhoto.objects.create(event=event, image=create_dummy_image("p2.jpg"), original_filename="p2.jpg")

        guest_client = APIClient()
        response = guest_client.get(f"/api/storage/share/{event.access_code}/download-all/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.headers.get("Content-Type"), "application/zip")
        self.assertIn("sunil-deepa-wedding_photos.zip", response.headers.get("Content-Disposition", ""))

        # Verify the returned content is a valid ZIP archive containing the 2 photos
        zip_in_memory = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_in_memory, 'r') as z:
            names = z.namelist()
            self.assertIn("p1.jpg", names)
            self.assertIn("p2.jpg", names)

    def test_instant_bulk_download_selected_zip(self):
        """Guests can select specific photos to download in a ZIP file."""
        event = SharedEvent.objects.create(
            photographer=self.profile,
            title="Anniversary Celebration",
            allow_downloads=True
        )
        p1 = EventPhoto.objects.create(event=event, image=create_dummy_image("sel1.jpg"), original_filename="sel1.jpg")
        p2 = EventPhoto.objects.create(event=event, image=create_dummy_image("sel2.jpg"), original_filename="sel2.jpg")
        p3 = EventPhoto.objects.create(event=event, image=create_dummy_image("sel3.jpg"), original_filename="sel3.jpg")

        guest_client = APIClient()
        response = guest_client.post(
            f"/api/storage/share/{event.access_code}/download-all/",
            {"photo_ids": [p1.id, p3.id]},
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        zip_in_memory = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_in_memory, 'r') as z:
            names = z.namelist()
            self.assertEqual(len(names), 2)
            self.assertIn("sel1.jpg", names)
            self.assertIn("sel3.jpg", names)
            self.assertNotIn("sel2.jpg", names)

    def test_qr_code_endpoint(self):
        """Generates QR code sharing information."""
        event = SharedEvent.objects.create(
            photographer=self.profile,
            title="Grand Wedding Reception"
        )
        guest_client = APIClient()
        response = guest_client.get(f"/api/storage/share/{event.access_code}/qr/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("qr_image_url", response.data)
        self.assertIn("share_url", response.data)
        self.assertIn(event.access_code, response.data["share_url"])

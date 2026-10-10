import io
import uuid
from PIL import Image
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework import status

from App.Photographers.photo_models import PhotographerProfile
from galleries.models import Gallery, GalleryMedia, GallerySection
from App.LiveEvents.event_models import LiveEvent, EventMedia
from galleries.views_upload import BulkMediaUploadService

User = get_user_model()


def create_test_image(name='test.jpg', size=(200, 200), color='red'):
    file_io = io.BytesIO()
    img = Image.new('RGB', size, color=color)
    img.save(file_io, format='JPEG')
    file_io.seek(0)
    return SimpleUploadedFile(name, file_io.getvalue(), content_type='image/jpeg')


class BulkMediaUploadTests(APITestCase):
    def setUp(self):
        User.objects.all().delete()
        PhotographerProfile.objects.all().delete()
        Gallery.objects.all().delete()
        LiveEvent.objects.all().delete()

        # Photographer user & profile
        self.user = User.objects.create_user(
            username='studio_pro_upload',
            email='upload@exshare.ai',
            password='Password123!'
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name='Sarah Connor',
            studio_name='Skynet Studio',
            storage_used_bytes=0,
            storage_reserved_bytes=0
        )

        # Other photographer for tenancy tests
        self.other_user = User.objects.create_user(
            username='other_studio_upload',
            email='other@exshare.ai',
            password='Password123!'
        )
        self.other_profile = PhotographerProfile.objects.create(
            user=self.other_user,
            name='Kyle Reese',
            studio_name='Resistance Studio'
        )

        # Gallery
        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Wedding Highlights 2026'
        )

        # Live Event
        self.event = LiveEvent.objects.create(
            photographer=self.user,
            title='Cyberdyne Gala'
        )

    def test_calculate_file_hash(self):
        """Verifies deterministic SHA-256 calculation on uploaded file."""
        img1 = create_test_image('sample1.jpg', (50, 50), 'blue')
        img2 = create_test_image('sample2.jpg', (50, 50), 'blue')

        hash1 = BulkMediaUploadService.calculate_file_hash(img1)
        hash2 = BulkMediaUploadService.calculate_file_hash(img2)

        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)

    def test_gallery_bulk_upload_success(self):
        """
        Tests successful multi-file batch upload to gallery:
        POST /api/galleries/<gallery_id>/media/bulk-upload/
        """
        self.client.force_authenticate(user=self.user)
        url = f'/api/galleries/{self.gallery.id}/media/bulk-upload/'

        img1 = create_test_image('photo_01.jpg', (120, 120), 'green')
        img2 = create_test_image('photo_02.jpg', (150, 150), 'yellow')

        payload = {
            'photos': [img1, img2],
            'section_title': 'CEREMONY',
            'type': 'photo',
        }

        response = self.client.post(url, data=payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        self.assertEqual(data['total_uploaded'], 2)
        self.assertEqual(data['section_title'], 'CEREMONY')
        self.assertEqual(len(data['media']), 2)

        # Verify contract properties on each media item
        item = data['media'][0]
        self.assertIn('id', item)
        self.assertEqual(item['gallery'], str(self.gallery.id))
        self.assertIn('url', item)
        self.assertIn('thumbnail_url', item)
        self.assertIn('preview_url', item)
        self.assertEqual(item['section_title'], 'CEREMONY')
        self.assertEqual(item['type'], 'photo')
        self.assertGreater(item['file_size'], 0)

        # Verify database insertion
        self.assertEqual(self.gallery.media_items.filter(deleted_at__isnull=True).count(), 2)
        self.profile.refresh_from_db()
        self.assertGreater(self.profile.storage_used_bytes, 0)

    def test_deduplication_and_idempotency_on_repeated_upload(self):
        """
        Uploading the same file twice within a section reuses the existing record
        without duplicating disk storage or creating duplicate DB rows.
        """
        self.client.force_authenticate(user=self.user)
        url = f'/api/galleries/{self.gallery.id}/media/bulk-upload/'

        img1 = create_test_image('portrait.jpg', (100, 100), 'purple')
        payload1 = {'photos': [img1], 'section_title': 'HIGHLIGHTS'}

        res1 = self.client.post(url, data=payload1, format='multipart')
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        data1 = res1.json()
        self.assertEqual(data1['total_uploaded'], 1)
        first_id = data1['media'][0]['id']

        # Repeat identical upload
        img2 = create_test_image('portrait.jpg', (100, 100), 'purple')
        payload2 = {'photos': [img2], 'section_title': 'HIGHLIGHTS'}

        res2 = self.client.post(url, data=payload2, format='multipart')
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)
        data2 = res2.json()

        self.assertEqual(data2['message'], 'Successfully uploaded 0 new file(s)')
        self.assertEqual(data2['total_uploaded'], 1)
        self.assertEqual(data2['media'][0]['id'], first_id)
        # Database count remains strictly 1
        self.assertEqual(self.gallery.media_items.filter(deleted_at__isnull=True).count(), 1)

    def test_pre_upload_storage_quota_guard_413(self):
        """
        When the incoming upload exceeds the photographer's storage quota,
        immediately returns HTTP 413 with error_code STORAGE_LIMIT_EXCEEDED.
        """
        # Artificially set storage limit to 500 bytes and used to 450 bytes
        self.profile.storage_used_bytes = 450
        # Mock can_allocate_storage to reject
        def mock_can_allocate(bytes_needed):
            return False
        self.profile.can_allocate_storage = mock_can_allocate
        self.profile.get_remaining_storage_bytes = lambda: 50
        self.profile.save()

        self.client.force_authenticate(user=self.user)
        url = f'/api/galleries/{self.gallery.id}/media/bulk-upload/'

        large_img = create_test_image('large.jpg', (500, 500), 'black')
        payload = {'photos': [large_img]}

        response = self.client.post(url, data=payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        data = response.json()

        self.assertEqual(data['error_code'], 'STORAGE_LIMIT_EXCEEDED')
        self.assertTrue(data['upgrade_required'])
        self.assertIn('Studio cloud storage limit exceeded', data['detail'])

    def test_gallery_upload_resume_status(self):
        """
        GET /api/galleries/<gallery_id>/upload-status/?section_title=CEREMONY
        Returns existing files with hashes so client can skip already uploaded files.
        """
        self.client.force_authenticate(user=self.user)
        upload_url = f'/api/galleries/{self.gallery.id}/media/bulk-upload/'

        img = create_test_image('reception_01.jpg', (80, 80), 'orange')
        self.client.post(upload_url, data={'photos': [img], 'section_title': 'CEREMONY'}, format='multipart')

        status_url = f'/api/galleries/{self.gallery.id}/upload-status/?section_title=CEREMONY'
        response = self.client.get(status_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['gallery_id'], str(self.gallery.id))
        self.assertEqual(data['section_title'], 'CEREMONY')
        self.assertEqual(data['existing_count'], 1)
        self.assertEqual(len(data['files']), 1)
        self.assertIn('file_hash', data['files'][0])
        self.assertIsNotNone(data['files'][0]['file_hash'])

    def test_event_bulk_upload_and_status(self):
        """
        Tests bulk upload and resume status for Live Events:
        POST /api/events/<event_id>/media/bulk-upload/
        GET /api/events/<event_id>/upload-status/
        """
        self.client.force_authenticate(user=self.user)
        url = f'/api/events/{self.event.id}/media/bulk-upload/'

        img = create_test_image('event_photo.jpg', (90, 90), 'teal')
        payload = {
            'photos': [img],
            'section_title': 'STAGE',
            'type': 'photo',
        }

        response = self.client.post(url, data=payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        self.assertEqual(data['total_uploaded'], 1)
        self.assertEqual(data['section_title'], 'STAGE')
        self.assertEqual(data['media'][0]['event'], str(self.event.id))

        # Check resume status endpoint for event
        status_url = f'/api/events/{self.event.id}/upload-status/?section_title=STAGE'
        res_status = self.client.get(status_url)
        self.assertEqual(res_status.status_code, status.HTTP_200_OK)
        self.assertEqual(res_status.json()['existing_count'], 1)

    def test_unauthorized_user_cannot_upload_to_other_gallery(self):
        """Other users receive 404 when attempting to upload to an unauthorized gallery."""
        self.client.force_authenticate(user=self.other_user)
        url = f'/api/galleries/{self.gallery.id}/media/bulk-upload/'

        img = create_test_image('rogue.jpg', (50, 50), 'red')
        response = self.client.post(url, data={'photos': [img]}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

import uuid
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from App.Photographers.photo_models import PhotographerProfile
from galleries.models import Gallery, Media
from galleries.views.bulk_favorite import (
    BulkFavoriteService,
    BulkMediaFavoriteAPIView,
    get_gallery_model,
    get_media_model,
)

User = get_user_model()


class BulkMediaFavoriteTests(APITestCase):
    def setUp(self):
        User.objects.all().delete()
        PhotographerProfile.objects.all().delete()
        Gallery.objects.all().delete()
        Media.objects.all().delete()

        # Photographer 1
        self.user1 = User.objects.create_user(
            username='studio_pro',
            email='studio@exshare.ai',
            password='Password123!'
        )
        self.profile1 = PhotographerProfile.objects.create(
            user=self.user1,
            name='Elena Rostova',
            studio_name='Elena Rostova Studio'
        )

        # Photographer 2 (for tenancy isolation tests)
        self.user2 = User.objects.create_user(
            username='other_pro',
            email='other@exshare.ai',
            password='Password123!'
        )
        self.profile2 = PhotographerProfile.objects.create(
            user=self.user2,
            name='Marcus Vance',
            studio_name='Vance Studio'
        )

        # Gallery 1 owned by profile 1
        self.gallery1 = Gallery.objects.create(
            photographer=self.profile1,
            title='Vogue Runway Paris'
        )

        # Gallery 2 owned by profile 2
        self.gallery2 = Gallery.objects.create(
            photographer=self.profile2,
            title='Private Shoot'
        )

        # Create media items for Gallery 1
        self.media1 = Media.objects.create(
            gallery=self.gallery1,
            photographer=self.profile1,
            original_filename='look_01.jpg',
            storage_key='galleries/test/look_01.jpg',
            is_favorite=False
        )
        self.media2 = Media.objects.create(
            gallery=self.gallery1,
            photographer=self.profile1,
            original_filename='look_02.jpg',
            storage_key='galleries/test/look_02.jpg',
            is_favorite=False
        )
        self.media3 = Media.objects.create(
            gallery=self.gallery1,
            photographer=self.profile1,
            original_filename='look_03.jpg',
            storage_key='galleries/test/look_03.jpg',
            is_favorite=False
        )

    def test_dynamic_model_resolvers(self):
        """Tests that get_gallery_model and get_media_model correctly resolve models."""
        GalleryModel = get_gallery_model()
        MediaModel = get_media_model()
        self.assertIsNotNone(GalleryModel)
        self.assertIsNotNone(MediaModel)
        self.assertEqual(GalleryModel, Gallery)
        self.assertEqual(MediaModel, Media)

    def test_bulk_favorite_nested_endpoint_success(self):
        """Tests bulk liking via nested route: POST /api/galleries/<gallery_id>/media/bulk-favorite/"""
        self.client.force_authenticate(user=self.user1)
        url = f'/api/galleries/{self.gallery1.id}/media/bulk-favorite/'

        payload = {
            'media_ids': [str(self.media1.id), str(self.media2.id)],
            'is_favorite': True
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['updated_count'], 2)
        self.assertTrue(data['is_favorite'])
        self.assertEqual(data['favorites_count'], 2)

        # Verify DB updates
        self.media1.refresh_from_db()
        self.media2.refresh_from_db()
        self.media3.refresh_from_db()
        self.self_gallery1 = Gallery.objects.get(id=self.gallery1.id)

        self.assertTrue(self.media1.is_favorite)
        self.assertTrue(self.media2.is_favorite)
        self.assertFalse(self.media3.is_favorite)
        self.assertEqual(self.self_gallery1.favorites_count, 2)

    def test_bulk_unfavorite_nested_endpoint_success(self):
        """Tests bulk unliking via nested route: POST /api/galleries/<gallery_id>/media/bulk-favorite/"""
        # Set all as favorite initially
        Media.objects.filter(gallery=self.gallery1).update(is_favorite=True)
        self.gallery1.favorites_count = 3
        self.gallery1.save()

        self.client.force_authenticate(user=self.user1)
        url = f'/api/galleries/{self.gallery1.id}/media/bulk-favorite/'

        payload = {
            'media_ids': [str(self.media1.id), str(self.media2.id)],
            'is_favorite': False
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['updated_count'], 2)
        self.assertFalse(data['is_favorite'])
        self.assertEqual(data['favorites_count'], 1)  # Only media3 remains favorite

        # Verify DB updates
        self.media1.refresh_from_db()
        self.media2.refresh_from_db()
        self.media3.refresh_from_db()
        self.self_gallery1 = Gallery.objects.get(id=self.gallery1.id)

        self.assertFalse(self.media1.is_favorite)
        self.assertFalse(self.media2.is_favorite)
        self.assertTrue(self.media3.is_favorite)
        self.assertEqual(self.self_gallery1.favorites_count, 1)

    def test_bulk_favorite_flat_endpoint_success(self):
        """Tests bulk favorite via flat endpoint: POST /api/galleries/media/bulk-favorite/"""
        self.client.force_authenticate(user=self.user1)
        url = '/api/galleries/media/bulk-favorite/'

        payload = {
            'gallery_id': str(self.gallery1.id),
            'media_ids': [str(self.media1.id), str(self.media3.id)],
            'is_favorite': True
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['updated_count'], 2)
        self.assertTrue(data['is_favorite'])
        self.assertEqual(data['favorites_count'], 2)

        self.media1.refresh_from_db()
        self.media2.refresh_from_db()
        self.media3.refresh_from_db()
        self.assertTrue(self.media1.is_favorite)
        self.assertFalse(self.media2.is_favorite)
        self.assertTrue(self.media3.is_favorite)

    def test_deduplication_of_media_ids(self):
        """Tests that duplicate UUIDs in media_ids are properly deduplicated."""
        self.client.force_authenticate(user=self.user1)
        url = f'/api/galleries/{self.gallery1.id}/media/bulk-favorite/'

        payload = {
            'media_ids': [str(self.media1.id), str(self.media1.id), str(self.media2.id)],
            'is_favorite': True
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(len(data['media_ids']), 2)
        self.assertEqual(data['updated_count'], 2)

    def test_empty_media_ids_validation_error(self):
        """Tests that an empty media_ids list returns 400 Bad Request."""
        self.client.force_authenticate(user=self.user1)
        url = f'/api/galleries/{self.gallery1.id}/media/bulk-favorite/'

        payload = {
            'media_ids': [],
            'is_favorite': True
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_flat_route_missing_gallery_id_error(self):
        """Tests that flat route without gallery_id in body returns 400 Bad Request."""
        self.client.force_authenticate(user=self.user1)
        url = '/api/galleries/media/bulk-favorite/'

        payload = {
            'media_ids': [str(self.media1.id)],
            'is_favorite': True
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Gallery ID must be specified', response.json()['detail'])

    def test_unauthenticated_request_rejected(self):
        """Tests that unauthenticated requests receive 401 Unauthorized."""
        url = f'/api/galleries/{self.gallery1.id}/media/bulk-favorite/'
        payload = {
            'media_ids': [str(self.media1.id)],
            'is_favorite': True
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_tenancy_isolation_gallery_access_denied(self):
        """Tests that a photographer cannot bulk-favorite another photographer's gallery."""
        # Authenticate as user2 and attempt to modify gallery1 owned by user1
        self.client.force_authenticate(user=self.user2)
        url = f'/api/galleries/{self.gallery1.id}/media/bulk-favorite/'

        payload = {
            'media_ids': [str(self.media1.id)],
            'is_favorite': True
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_nonexistent_gallery_returns_404(self):
        """Tests that a nonexistent gallery UUID returns 404 Not Found."""
        self.client.force_authenticate(user=self.user1)
        random_id = uuid.uuid4()
        url = f'/api/galleries/{random_id}/media/bulk-favorite/'

        payload = {
            'media_ids': [str(self.media1.id)],
            'is_favorite': True
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_service_execute_direct(self):
        """Tests calling BulkFavoriteService.execute directly."""
        updated_count, total_favs = BulkFavoriteService.execute(
            gallery=self.gallery1,
            media_ids=[self.media1.id, self.media2.id],
            is_favorite=True
        )
        self.assertEqual(updated_count, 2)
        self.assertEqual(total_favs, 2)

        self.gallery1.refresh_from_db()
        self.assertEqual(self.gallery1.favorites_count, 2)

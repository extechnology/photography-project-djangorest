import uuid
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from App.Photographers.photo_models import PhotographerProfile
from galleries.models import Gallery, Media
from gallery_favorites_api import (
    get_annotated_gallery_queryset,
    GalleryDetailFavoritesMixin,
    BulkToggleMediaFavoriteSerializer,
    SingleToggleMediaFavoriteSerializer,
)

User = get_user_model()


class GalleryFavoritesSystemTests(APITestCase):
    def setUp(self):
        User.objects.all().delete()
        PhotographerProfile.objects.all().delete()
        Gallery.objects.all().delete()
        Media.objects.all().delete()

        # Photographer user & profile
        self.user = User.objects.create_user(
            username='art_photographer',
            email='art@exshare.ai',
            password='Password123!'
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name='Arthur Morgan',
            studio_name='Saint Denis Studio'
        )

        # Another photographer for permission isolation
        self.other_user = User.objects.create_user(
            username='john_photographer',
            email='john@exshare.ai',
            password='Password123!'
        )
        self.other_profile = PhotographerProfile.objects.create(
            user=self.other_user,
            name='John Marston',
            studio_name='Beecher Studio'
        )

        # Gallery
        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Autumn Collection 2026'
        )

        # Other gallery
        self.other_gallery = Gallery.objects.create(
            photographer=self.other_profile,
            title='Wild West Landscapes'
        )

        # Populate Gallery with 10 media items
        self.media_items = []
        for i in range(10):
            item = Media.objects.create(
                gallery=self.gallery,
                photographer=self.profile,
                original_filename=f'photo_{i+1:02d}.jpg',
                storage_key=f'galleries/autumn/photo_{i+1:02d}.jpg',
                media_type='photo' if i < 8 else 'video',
                order=i,
                display_order=i,
                is_favorite=True  # All 10 initially liked
            )
            self.media_items.append(item)

        # Sync gallery cached favorites_count
        self.gallery.favorites_count = 10
        self.gallery.save(update_fields=['favorites_count'])

    def test_composite_index_exists_on_media(self):
        """Verifies composite index idx_media_gallery_favorite is present on Media model."""
        index_names = [idx.name for idx in Media._meta.indexes]
        self.assertIn('idx_media_gallery_favorite', index_names)

    def test_get_annotated_gallery_queryset(self):
        """Verifies O(1) database-level aggregate counts annotated onto Gallery queryset."""
        qs = get_annotated_gallery_queryset(self.user)
        gallery_obj = qs.get(id=self.gallery.id)

        self.assertEqual(gallery_obj.annotated_total_media_count, 10)
        self.assertEqual(gallery_obj.annotated_favorites_count, 10)
        self.assertEqual(gallery_obj.annotated_photos_count, 8)
        self.assertEqual(gallery_obj.annotated_videos_count, 2)

    def test_gallery_detail_pagination_does_not_slice_favorites_count(self):
        """
        Critical Root-Cause Test:
        When client fetches first page with limit=2, response['media'] has 2 items,
        but response['favorites_count'] MUST return the unpaginated total 10.
        """
        self.client.force_authenticate(user=self.user)
        url = f'/api/galleries/{self.gallery.id}/?limit=2'

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Paginated media slice length is 2
        self.assertEqual(len(data['media']), 2)
        # Unpaginated favorites count across the entire database is 10
        self.assertEqual(data['favorites_count'], 10)
        self.assertEqual(data['total_media_count'], 10)

    def test_bulk_favorite_select_all_true_unfavorite(self):
        """
        Tests bulk unliking all photos via select_all=True in a single SQL operation.
        """
        self.client.force_authenticate(user=self.user)
        url = f'/api/galleries/{self.gallery.id}/media/bulk-favorite/'

        payload = {
            'select_all': True,
            'is_favorite': False
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['updated_count'], 10)
        self.assertFalse(data['is_favorite'])
        self.assertEqual(data['favorites_count'], 0)
        self.assertEqual(data['total_media_count'], 10)

        # Verify in DB
        self.assertEqual(self.gallery.media.filter(is_favorite=True).count(), 0)
        self.gallery.refresh_from_db()
        self.assertEqual(self.gallery.favorites_count, 0)

    def test_bulk_favorite_select_all_true_favorite(self):
        """
        Tests bulk liking all photos via select_all=True.
        """
        # First mark all as not favorite
        self.gallery.media.all().update(is_favorite=False)
        self.gallery.favorites_count = 0
        self.gallery.save(update_fields=['favorites_count'])

        self.client.force_authenticate(user=self.user)
        url = f'/api/galleries/{self.gallery.id}/media/bulk-favorite/'

        payload = {
            'select_all': True,
            'is_favorite': True
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['updated_count'], 10)
        self.assertTrue(data['is_favorite'])
        self.assertEqual(data['favorites_count'], 10)

        # Verify in DB
        self.assertEqual(self.gallery.media.filter(is_favorite=True).count(), 10)
        self.gallery.refresh_from_db()
        self.assertEqual(self.gallery.favorites_count, 10)

    def test_bulk_favorite_media_ids_subset(self):
        """
        Tests updating a specific list of media_ids.
        """
        # Mark all as false first
        self.gallery.media.all().update(is_favorite=False)
        self.gallery.favorites_count = 0
        self.gallery.save(update_fields=['favorites_count'])

        target_ids = [str(self.media_items[0].id), str(self.media_items[1].id), str(self.media_items[2].id)]

        self.client.force_authenticate(user=self.user)
        url = f'/api/galleries/{self.gallery.id}/media/bulk-favorite/'

        payload = {
            'media_ids': target_ids,
            'is_favorite': True,
            'select_all': False
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data['updated_count'], 3)
        self.assertEqual(data['favorites_count'], 3)

        self.media_items[0].refresh_from_db()
        self.media_items[1].refresh_from_db()
        self.media_items[2].refresh_from_db()
        self.media_items[3].refresh_from_db()

        self.assertTrue(self.media_items[0].is_favorite)
        self.assertTrue(self.media_items[1].is_favorite)
        self.assertTrue(self.media_items[2].is_favorite)
        self.assertFalse(self.media_items[3].is_favorite)

    def test_bulk_favorite_missing_both_select_all_and_media_ids(self):
        """
        Fails with 400 Bad Request when select_all is False and media_ids is empty.
        """
        self.client.force_authenticate(user=self.user)
        url = f'/api/galleries/{self.gallery.id}/media/bulk-favorite/'

        payload = {
            'select_all': False,
            'media_ids': []
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_single_photo_favorite_toggle_and_explicit(self):
        """
        Tests single photo favorite endpoint:
        POST /api/galleries/<gallery_id>/media/<media_id>/favorite/
        - Toggle when no body
        - Explicit state when is_favorite provided
        """
        self.client.force_authenticate(user=self.user)
        media_item = self.media_items[0]
        self.assertTrue(media_item.is_favorite)

        url = f'/api/galleries/{self.gallery.id}/media/{media_item.id}/favorite/'

        # 1. Toggle (currently True -> becomes False)
        res1 = self.client.post(url, data={}, format='json')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        data1 = res1.json()
        self.assertFalse(data1['is_favorite'])
        self.assertEqual(data1['favorites_count'], 9)

        media_item.refresh_from_db()
        self.assertFalse(media_item.is_favorite)

        # 2. Explicitly set to True
        res2 = self.client.post(url, data={'is_favorite': True}, format='json')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        data2 = res2.json()
        self.assertTrue(data2['is_favorite'])
        self.assertEqual(data2['favorites_count'], 10)

        media_item.refresh_from_db()
        self.assertTrue(media_item.is_favorite)

        # 3. Explicitly set to False
        res3 = self.client.post(url, data={'is_favorite': False}, format='json')
        self.assertEqual(res3.status_code, status.HTTP_200_OK)
        data3 = res3.json()
        self.assertFalse(data3['is_favorite'])
        self.assertEqual(data3['favorites_count'], 9)

        media_item.refresh_from_db()
        self.assertFalse(media_item.is_favorite)

    def test_tenancy_isolation_blocks_unauthorized_user(self):
        """
        Verifies photographer B cannot toggle favorites on photographer A's gallery.
        """
        self.client.force_authenticate(user=self.other_user)
        url = f'/api/galleries/{self.gallery.id}/media/bulk-favorite/'

        payload = {'select_all': True, 'is_favorite': False}
        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

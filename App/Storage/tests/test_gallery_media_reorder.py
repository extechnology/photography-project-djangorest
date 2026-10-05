from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from App.Storage.storage_models import Gallery, Media as GalleryMedia
from App.Photographers.photo_models import PhotographerProfile

User = get_user_model()


class StorageGalleryMediaReorderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='photographer_storage_reorder',
            email='photographer_storage@example.com',
            password='password123'
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Photographer Storage",
            studio_name="Storage Studios",
        )
        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Storage Wedding Gallery'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_reorder_via_storage_route(self):
        m1 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='1.jpg', order=0)
        m2 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='2.jpg', order=1)
        m3 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='3.jpg', order=2)

        # POST /api/storage/galleries/<gallery_id>/media/reorder/
        res = self.client.post(
            f'/api/storage/galleries/{self.gallery.id}/media/reorder/',
            {'media_ids': [str(m3.id), str(m1.id), str(m2.id)]},
            format='json'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'success')
        self.assertEqual(res.data['gallery_id'], str(self.gallery.id))

        m1.refresh_from_db()
        m2.refresh_from_db()
        m3.refresh_from_db()
        self.assertEqual(m3.order, 0)
        self.assertEqual(m1.order, 1)
        self.assertEqual(m2.order, 2)

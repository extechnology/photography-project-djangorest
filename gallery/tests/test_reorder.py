from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from gallery.models import Gallery, GalleryMedia
from App.Photographers.photo_models import PhotographerProfile

User = get_user_model()


class GalleryMediaReorderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='photographer_reorder',
            email='photographer@example.com',
            password='password123'
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Photographer Reorder",
            studio_name="Reorder Studios",
        )
        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Wedding Gallery'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_reorder_full_array(self):
        m1 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='1.jpg', order=0)
        m2 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='2.jpg', order=1)
        m3 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='3.jpg', order=2)

        # Invert order: [m3, m2, m1]
        res = self.client.post(
            f'/api/galleries/{self.gallery.id}/media/reorder/',
            {'media_ids': [str(m3.id), str(m2.id), str(m1.id)]},
            format='json'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'success')

        m1.refresh_from_db()
        m2.refresh_from_db()
        m3.refresh_from_db()
        self.assertEqual(m3.order, 0)
        self.assertEqual(m2.order, 1)
        self.assertEqual(m1.order, 2)

    def test_jump_to_top(self):
        m1 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='1.jpg', order=0)
        m2 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='2.jpg', order=1)
        m3 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='3.jpg', order=2)

        # Move bottom photo m3 to top
        res = self.client.post(
            f'/api/galleries/{self.gallery.id}/media/reorder/',
            {'media_id': str(m3.id), 'action': 'top'},
            format='json'
        )
        self.assertEqual(res.status_code, 200)

        m1.refresh_from_db()
        m2.refresh_from_db()
        m3.refresh_from_db()
        self.assertEqual(m3.order, 0)
        self.assertEqual(m1.order, 1)
        self.assertEqual(m2.order, 2)

    def test_jump_to_bottom(self):
        m1 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='1.jpg', order=0)
        m2 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='2.jpg', order=1)
        m3 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='3.jpg', order=2)

        # Move top photo m1 to bottom
        res = self.client.post(
            f'/api/galleries/{self.gallery.id}/media/reorder/',
            {'media_id': str(m1.id), 'action': 'bottom'},
            format='json'
        )
        self.assertEqual(res.status_code, 200)

        m1.refresh_from_db()
        m2.refresh_from_db()
        m3.refresh_from_db()
        self.assertEqual(m2.order, 0)
        self.assertEqual(m3.order, 1)
        self.assertEqual(m1.order, 2)

    def test_arbitrary_position_jump(self):
        m1 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='1.jpg', order=0)
        m2 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='2.jpg', order=1)
        m3 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='3.jpg', order=2)
        m4 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='4.jpg', order=3)

        # Move photo m4 to 1-based position 2 (second item in list)
        res = self.client.post(
            f'/api/galleries/{self.gallery.id}/media/reorder/',
            {'media_id': str(m4.id), 'action': 'position', 'target_position': 2},
            format='json'
        )
        self.assertEqual(res.status_code, 200)

        m1.refresh_from_db()
        m2.refresh_from_db()
        m3.refresh_from_db()
        m4.refresh_from_db()
        # Order should now be: m1 (0), m4 (1), m2 (2), m3 (3)
        self.assertEqual(m1.order, 0)
        self.assertEqual(m4.order, 1)
        self.assertEqual(m2.order, 2)
        self.assertEqual(m3.order, 3)

    def test_batch_jump_to_top_and_bottom(self):
        m1 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='1.jpg', order=0)
        m2 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='2.jpg', order=1)
        m3 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='3.jpg', order=2)
        m4 = GalleryMedia.objects.create(gallery=self.gallery, original_filename='4.jpg', order=3)

        # Send [m3, m4] to top
        res = self.client.post(
            f'/api/galleries/{self.gallery.id}/media/reorder/',
            {'media_ids': [str(m3.id), str(m4.id)], 'action': 'top'},
            format='json'
        )
        self.assertEqual(res.status_code, 200)

        m1.refresh_from_db()
        m2.refresh_from_db()
        m3.refresh_from_db()
        m4.refresh_from_db()
        # Order should be m3 (0), m4 (1), m1 (2), m2 (3)
        self.assertEqual(m3.order, 0)
        self.assertEqual(m4.order, 1)
        self.assertEqual(m1.order, 2)
        self.assertEqual(m2.order, 3)


try:
    import pytest

    @pytest.mark.django_db
    def test_reorder_full_array():
        user = User.objects.create_user(username='pytest_user', email='photographer@example.com', password='password123')
        profile = PhotographerProfile.objects.create(user=user, name="Photographer", studio_name="Studio")
        gallery = Gallery.objects.create(photographer=profile, title='Wedding Gallery')
        m1 = GalleryMedia.objects.create(gallery=gallery, original_filename='1.jpg', order=0)
        m2 = GalleryMedia.objects.create(gallery=gallery, original_filename='2.jpg', order=1)
        m3 = GalleryMedia.objects.create(gallery=gallery, original_filename='3.jpg', order=2)

        client = APIClient()
        client.force_authenticate(user=user)

        res = client.post(
            f'/api/galleries/{gallery.id}/media/reorder/',
            {'media_ids': [str(m3.id), str(m2.id), str(m1.id)]},
            format='json'
        )
        assert res.status_code == 200

        m1.refresh_from_db()
        m2.refresh_from_db()
        m3.refresh_from_db()
        assert m3.order == 0
        assert m2.order == 1
        assert m1.order == 2

    @pytest.mark.django_db
    def test_jump_to_top():
        user = User.objects.create_user(username='pytest_user_top', email='photographer_top@example.com', password='password123')
        profile = PhotographerProfile.objects.create(user=user, name="Photographer", studio_name="Studio")
        gallery = Gallery.objects.create(photographer=profile, title='Wedding Gallery')
        m1 = GalleryMedia.objects.create(gallery=gallery, original_filename='1.jpg', order=0)
        m2 = GalleryMedia.objects.create(gallery=gallery, original_filename='2.jpg', order=1)
        m3 = GalleryMedia.objects.create(gallery=gallery, original_filename='3.jpg', order=2)

        client = APIClient()
        client.force_authenticate(user=user)

        res = client.post(
            f'/api/galleries/{gallery.id}/media/reorder/',
            {'media_id': str(m3.id), 'action': 'top'},
            format='json'
        )
        assert res.status_code == 200

        m1.refresh_from_db()
        m2.refresh_from_db()
        m3.refresh_from_db()
        assert m3.order == 0
        assert m1.order == 1
        assert m2.order == 2
except ImportError:
    pass


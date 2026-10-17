import uuid
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework import status
from rest_framework.test import APITestCase

from App.Photographers.photo_models import PhotographerProfile
from galleries.models import (
    Gallery,
    Media,
    GalleryViewer,
    ViewerLikedMedia,
    ViewerOtpVerification,
)

User = get_user_model()


class ViewerLikesAndOtpTests(APITestCase):
    def setUp(self):
        User.objects.all().delete()
        PhotographerProfile.objects.all().delete()
        Gallery.objects.all().delete()
        Media.objects.all().delete()
        GalleryViewer.objects.all().delete()
        ViewerLikedMedia.objects.all().delete()
        ViewerOtpVerification.objects.all().delete()

        # Photographer user & profile
        self.user = User.objects.create_user(
            username='photographer_alice',
            email='alice@exshare.ai',
            password='TestPassword123!'
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name='Alice Wonderland',
            studio_name='Wonderland Atelier'
        )

        # Other photographer for isolation tests
        self.other_user = User.objects.create_user(
            username='photographer_bob',
            email='bob@exshare.ai',
            password='TestPassword123!'
        )
        self.other_profile = PhotographerProfile.objects.create(
            user=self.other_user,
            name='Bob Builder',
            studio_name='Builder Studio'
        )

        # Galleries
        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Royal Wedding 2026',
            slug='royal-wedding-2026'
        )
        self.other_gallery = Gallery.objects.create(
            photographer=self.other_profile,
            title='Mountain Expedition 2026',
            slug='mountain-expedition-2026'
        )

        # Media items
        self.media1 = Media.objects.create(
            gallery=self.gallery,
            photographer=self.profile,
            title='Bride Entrance',
            original_filename='entrance_001.jpg',
            storage_key='storage_objects/galleries/entrance_001.jpg'
        )
        self.media2 = Media.objects.create(
            gallery=self.gallery,
            photographer=self.profile,
            title='First Dance',
            original_filename='dance_002.jpg',
            storage_key='storage_objects/galleries/dance_002.jpg'
        )
        self.media3 = Media.objects.create(
            gallery=self.gallery,
            photographer=self.profile,
            title='Cake Cutting',
            original_filename='cake_003.jpg',
            storage_key='storage_objects/galleries/cake_003.jpg'
        )

        self.viewer_email = 'guest.sarah@example.com'

    def test_send_otp_success_and_email_dispatched(self):
        url = f'/api/public/galleries/{self.gallery.slug}/auth/send-otp/'
        response = self.client.post(url, {'email': self.viewer_email}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'success')
        self.assertEqual(response.data['expires_in_seconds'], 600)

        # Verify OTP record in database
        otp_record = ViewerOtpVerification.objects.filter(
            gallery=self.gallery,
            email=self.viewer_email
        ).first()
        self.assertIsNotNone(otp_record)
        self.assertEqual(len(otp_record.otp_code), 6)
        self.assertTrue(otp_record.is_valid())

        # Verify email was dispatched
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn(otp_record.otp_code, sent_email.body)
        self.assertIn(self.gallery.title, sent_email.subject)
        self.assertEqual(sent_email.to, [self.viewer_email])

    def test_send_otp_rate_limiting_max_5_requests(self):
        url = f'/api/public/galleries/{self.gallery.id}/auth/send-otp/'
        for _ in range(5):
            res = self.client.post(url, {'email': self.viewer_email}, format='json')
            self.assertEqual(res.status_code, status.HTTP_200_OK)

        # 6th request should be rate-limited
        blocked_res = self.client.post(url, {'email': self.viewer_email}, format='json')
        self.assertEqual(blocked_res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Too many verification requests", blocked_res.data['message'])

    def test_verify_otp_invalid_code_increments_attempts(self):
        otp_record = ViewerOtpVerification.objects.create(
            gallery=self.gallery,
            email=self.viewer_email,
            otp_code='123456',
            expires_at=timezone.now() + timedelta(minutes=10)
        )

        url = f'/api/public/galleries/{self.gallery.slug}/auth/verify-otp/'
        bad_res = self.client.post(url, {
            'email': self.viewer_email,
            'otp': '999999'
        }, format='json')

        self.assertEqual(bad_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Incorrect verification code", bad_res.data['message'])

        otp_record.refresh_from_db()
        self.assertEqual(otp_record.attempts, 1)

    def test_verify_otp_success_creates_viewer_session(self):
        otp_record = ViewerOtpVerification.objects.create(
            gallery=self.gallery,
            email=self.viewer_email,
            otp_code='654321',
            expires_at=timezone.now() + timedelta(minutes=10)
        )

        url = f'/api/public/galleries/{self.gallery.slug}/auth/verify-otp/'
        res = self.client.post(url, {
            'email': self.viewer_email,
            'otp': '654321'
        }, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'success')
        self.assertIn('viewer', res.data)
        self.assertEqual(res.data['viewer']['email'], self.viewer_email)
        self.assertTrue(bool(res.data['viewer']['session_token']))

        otp_record.refresh_from_db()
        self.assertTrue(otp_record.is_verified)

        # Ensure viewer exists in DB
        viewer = GalleryViewer.objects.get(gallery=self.gallery, email=self.viewer_email)
        self.assertEqual(viewer.session_token, res.data['viewer']['session_token'])

    def test_single_toggle_favorite_and_likes_list(self):
        # 1. Like media1
        fav_url = f'/api/public/galleries/{self.gallery.id}/favorite/'
        res = self.client.post(fav_url, {
            'media_id': str(self.media1.id),
            'is_favorite': True,
            'email': self.viewer_email
        }, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['is_favorite'], True)
        self.assertEqual(res.data['favorites_count'], 1)

        self.media1.refresh_from_db()
        self.assertTrue(self.media1.is_favorite)

        # 2. Query viewer likes list
        likes_url = f'/api/public/galleries/{self.gallery.slug}/likes/?email={self.viewer_email}'
        list_res = self.client.get(likes_url)
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertEqual(list_res.data['total_likes'], 1)
        self.assertEqual(list_res.data['liked_media_ids'], [str(self.media1.id)])

        # 3. Unlike media1
        unfav_res = self.client.post(fav_url, {
            'media_id': str(self.media1.id),
            'is_favorite': False,
            'email': self.viewer_email
        }, format='json')
        self.assertEqual(unfav_res.status_code, status.HTTP_200_OK)
        self.assertEqual(unfav_res.data['is_favorite'], False)
        self.assertEqual(unfav_res.data['favorites_count'], 0)

        self.media1.refresh_from_db()
        self.assertFalse(self.media1.is_favorite)

    def test_bulk_toggle_favorite(self):
        bulk_url = f'/api/public/galleries/{self.gallery.slug}/bulk-like/'

        # Bulk like media1 and media2
        res = self.client.post(bulk_url, {
            'media_ids': [str(self.media1.id), str(self.media2.id)],
            'is_favorite': True,
            'email': self.viewer_email
        }, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['updated_count'], 2)
        self.assertEqual(res.data['favorites_count'], 2)

        # Verify in DB
        viewer = GalleryViewer.objects.get(gallery=self.gallery, email=self.viewer_email)
        liked_mids = set(
            ViewerLikedMedia.objects.filter(viewer=viewer).values_list('media_id', flat=True)
        )
        self.assertEqual(liked_mids, {self.media1.id, self.media2.id})

        # Bulk like all with select_all
        res_all = self.client.post(bulk_url, {
            'select_all': True,
            'is_favorite': True,
            'email': self.viewer_email
        }, format='json')
        self.assertEqual(res_all.status_code, status.HTTP_200_OK)
        self.assertEqual(res_all.data['updated_count'], 3)
        self.assertEqual(res_all.data['favorites_count'], 3)

        # Bulk unlike media3
        res_unlike = self.client.post(bulk_url, {
            'media_ids': [str(self.media3.id)],
            'is_favorite': False,
            'email': self.viewer_email
        }, format='json')
        self.assertEqual(res_unlike.status_code, status.HTTP_200_OK)
        self.assertEqual(res_unlike.data['favorites_count'], 2)

    def test_studio_dashboard_client_favorites_endpoint(self):
        # Create viewer and likes
        viewer = GalleryViewer.objects.create(
            gallery=self.gallery,
            email=self.viewer_email,
            name='Sarah Connor',
            session_token='test-session-token-123'
        )
        ViewerLikedMedia.objects.create(viewer=viewer, gallery=self.gallery, media=self.media1)
        ViewerLikedMedia.objects.create(viewer=viewer, gallery=self.gallery, media=self.media2)

        client_favs_url = f'/api/galleries/{self.gallery.id}/client-favorites/'

        # 1. Unauthenticated request -> 401
        unauth_res = self.client.get(client_favs_url)
        self.assertEqual(unauth_res.status_code, status.HTTP_401_UNAUTHORIZED)

        # 2. Non-owner request -> 403
        self.client.force_authenticate(user=self.other_user)
        forbidden_res = self.client.get(client_favs_url)
        self.assertEqual(forbidden_res.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Owner request -> 200 OK
        self.client.force_authenticate(user=self.user)
        owner_res = self.client.get(client_favs_url)
        self.assertEqual(owner_res.status_code, status.HTTP_200_OK)
        self.assertIn('viewers', owner_res.data)
        self.assertEqual(len(owner_res.data['viewers']), 1)

        v_data = owner_res.data['viewers'][0]
        self.assertEqual(v_data['email'], self.viewer_email)
        self.assertEqual(v_data['liked_count'], 2)
        self.assertEqual(len(v_data['liked_media']), 2)
        media_titles = [m['title'] for m in v_data['liked_media']]
        self.assertIn('Bride Entrance', media_titles)
        self.assertIn('First Dance', media_titles)
        self.assertTrue('thumbnailUrl' in v_data['liked_media'][0])

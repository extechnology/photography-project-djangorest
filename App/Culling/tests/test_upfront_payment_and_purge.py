import io
import uuid
from PIL import Image, ImageDraw
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from App.Culling.culling_models import (
    CullingSession,
    CullingClusterGroup,
    CullingItem,
    TIER_LIMITS,
    CullingPricingTier,
)
from App.Storage.storage_models import Gallery, Media as GalleryMedia, GallerySection
from App.Photographers.photo_models import PhotographerProfile

User = get_user_model()


def make_test_photo(color=(200, 100, 100), label="test") -> bytes:
    img = Image.new('RGB', (150, 150), color=color)
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), label, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()


class UpfrontPaymentAndPurgeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='photographer_amy',
            email='amy@example.com',
            password='Password123!',
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Amy Pond",
            studio_name="Pond Studio",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_upfront_payment_order_creation_root_and_detail(self):
        session = CullingSession.objects.create(user=self.user, title='Wedding Batch')

        # 1. Detail endpoint
        res = self.client.post(
            f'/api/culling/sessions/{session.id}/payments/create-order/',
            {'tier_id': 'cull_wedding_1200'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['price_inr'], 249)
        self.assertEqual(res.data['max_photos'], 1200)
        self.assertEqual(res.data['tier'], 'cull_wedding_1200')

        session.refresh_from_db()
        self.assertEqual(session.max_photos_allowed, 1200)
        self.assertEqual(session.paid_amount, 249.00)

        # 2. Root endpoint with auto-creation of session
        session_key = f"cull-session-{uuid.uuid4().hex[:8]}"
        res_root = self.client.post(
            '/api/culling/payments/create-order/',
            {'session_id': session_key, 'tier_id': 'cull_single_300'},
            format='json'
        )
        self.assertEqual(res_root.status_code, status.HTTP_200_OK)
        self.assertEqual(res_root.data['price_inr'], 149)
        self.assertEqual(res_root.data['max_photos'], 300)

        created_session = CullingSession.objects.get(session_key=session_key)
        self.assertEqual(created_session.max_photos_allowed, 300)
        self.assertEqual(created_session.paid_amount, 149.00)

    def test_upfront_payment_verification_unlocks_session(self):
        session = CullingSession.objects.create(
            user=self.user,
            title='Pro Shoot',
            paid_tier='cull_pro_unlimited',
            max_photos_allowed=999999,
            paid_amount=499.00,
        )
        self.assertFalse(session.is_paid)

        res_verify = self.client.post(
            f'/api/culling/sessions/{session.id}/payments/verify/',
            {
                'razorpay_order_id': 'order_cull_test999',
                'razorpay_payment_id': 'pay_test888',
                'razorpay_signature': 'sig_mock_verified',
            },
            format='json'
        )
        self.assertEqual(res_verify.status_code, status.HTTP_200_OK)
        self.assertTrue(res_verify.data['is_paid'])

        session.refresh_from_db()
        self.assertTrue(session.is_paid)
        self.assertEqual(session.status, 'paid')
        self.assertIsNotNone(session.paid_at)

    def test_upload_photos_rejected_with_402_if_unpaid(self):
        session = CullingSession.objects.create(user=self.user, title='Unpaid Session', is_paid=False)

        photo = SimpleUploadedFile('sample.jpg', make_test_photo(), content_type='image/jpeg')
        res = self.client.post(
            f'/api/culling/sessions/{session.id}/upload-photos/',
            {'files': [photo]},
            format='multipart'
        )
        self.assertEqual(res.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(res.data['error'], 'PAYMENT_REQUIRED')
        self.assertIn('required_tiers', res.data)

    def test_upload_photos_enforces_tier_photo_limit(self):
        # Session paid for single shoot (max 300 photos), set limit to 2 for test
        session = CullingSession.objects.create(
            user=self.user,
            title='Limited Session',
            is_paid=True,
            paid_tier='cull_single_300',
            max_photos_allowed=2
        )

        p1 = SimpleUploadedFile('p1.jpg', make_test_photo(label="1"), content_type='image/jpeg')
        p2 = SimpleUploadedFile('p2.jpg', make_test_photo(label="2"), content_type='image/jpeg')
        p3 = SimpleUploadedFile('p3.jpg', make_test_photo(label="3"), content_type='image/jpeg')

        # Upload 3 photos when max is 2 -> Expect 400 TIER_LIMIT_EXCEEDED
        res = self.client.post(
            f'/api/culling/sessions/{session.id}/upload-photos/',
            {'files': [p1, p2, p3]},
            format='multipart'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['error'], 'TIER_LIMIT_EXCEEDED')

    def test_upload_photos_and_cull_analysis_end_to_end(self):
        session = CullingSession.objects.create(
            user=self.user,
            title='Paid Active Session',
            is_paid=True,
            paid_tier='cull_single_300',
            max_photos_allowed=300
        )

        # Upload two similar photos (burst shot) and one different photo
        b1 = SimpleUploadedFile('burst1.jpg', make_test_photo(color=(100, 100, 100), label="burst"), content_type='image/jpeg')
        b2 = SimpleUploadedFile('burst2.jpg', make_test_photo(color=(100, 100, 100), label="burst"), content_type='image/jpeg')
        diff = SimpleUploadedFile('diff.jpg', make_test_photo(color=(255, 50, 50), label="unique"), content_type='image/jpeg')

        res = self.client.post(
            f'/api/culling/sessions/{session.id}/upload-photos/',
            {'files': [b1, b2, diff], 'similarity_threshold': 80.0},
            format='multipart'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['total_photos'], 3)
        self.assertIn('clusters', res.data)

        session.refresh_from_db()
        self.assertEqual(session.status, 'ready')
        self.assertEqual(session.progress_percentage, 100)
        self.assertEqual(session.total_photos, 3)
        self.assertEqual(session.keeper_count + session.duplicate_count, 3)

    def test_move_to_gallery_category_bridge_and_auto_purge(self):
        session = CullingSession.objects.create(
            user=self.user,
            title='Culled Ready Session',
            is_paid=True,
            status='ready',
        )

        img_bytes_1 = make_test_photo(color=(10, 20, 30), label="1")
        img_bytes_2 = make_test_photo(color=(40, 50, 60), label="2")

        item1 = CullingItem.objects.create(
            session=session,
            image=SimpleUploadedFile('photo1.jpg', img_bytes_1, content_type='image/jpeg'),
            original_filename='photo1.jpg',
            size_bytes=len(img_bytes_1),
            status='keep',
            is_best_pick=True,
        )
        item2 = CullingItem.objects.create(
            session=session,
            image=SimpleUploadedFile('photo2.jpg', img_bytes_2, content_type='image/jpeg'),
            original_filename='photo2.jpg',
            size_bytes=len(img_bytes_2),
            status='discard',
            is_best_pick=False,
        )

        payload = {
            'target_mode': 'new',
            'new_gallery_title': 'Grand Wedding 2026',
            'category_assignments': {
                str(item1.id): 'PORTRAITS',
                str(item2.id): 'CANDID MOMENTS',
            },
            'include_duplicates': True,
        }

        # Call move-to-gallery
        res = self.client.post(
            f'/api/culling/sessions/{session.id}/move-to-gallery/',
            payload,
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['purged'])
        self.assertEqual(res.data['moved_count'], 2)

        # 1. Target Gallery and Sections were created
        gallery_id = res.data['gallery_id']
        gallery = Gallery.objects.get(id=gallery_id)
        self.assertEqual(gallery.title, 'Grand Wedding 2026')
        self.assertTrue(GallerySection.objects.filter(gallery=gallery, title='PORTRAITS').exists())
        self.assertTrue(GallerySection.objects.filter(gallery=gallery, title='CANDID MOMENTS').exists())

        # 2. Photos moved to GalleryMedia
        self.assertEqual(GalleryMedia.objects.filter(gallery=gallery).count(), 2)

        # 3. CRITICAL STORAGE PURGE: staging items & files permanently deleted
        session.refresh_from_db()
        self.assertEqual(session.status, 'completed')
        self.assertEqual(session.items.count(), 0)
        self.assertEqual(session.clusters.count(), 0)

    def test_direct_root_move_to_gallery_alias_with_session_key(self):
        session_key = f"key-{uuid.uuid4().hex[:6]}"
        session = CullingSession.objects.create(
            user=self.user,
            session_key=session_key,
            title='Direct Session',
            is_paid=True,
            status='ready',
        )

        img_bytes = make_test_photo(label="solo")
        item = CullingItem.objects.create(
            session=session,
            image=SimpleUploadedFile('solo.jpg', img_bytes, content_type='image/jpeg'),
            original_filename='solo.jpg',
            size_bytes=len(img_bytes),
            status='keep',
            is_best_pick=True,
        )

        res = self.client.post(
            '/api/culling/move-to-gallery/',
            {
                'session_id': session_key,
                'target_mode': 'new',
                'new_gallery_title': 'Solo Portrait Gallery',
                'category_assignments': {str(item.id): 'SOLO'},
            },
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['moved_count'], 1)
        self.assertTrue(res.data['purged'])

        session.refresh_from_db()
        self.assertEqual(session.status, 'completed')
        self.assertEqual(session.items.count(), 0)

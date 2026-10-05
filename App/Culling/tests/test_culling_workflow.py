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
    CullingPaymentOrder,
)
from App.Culling.services.culling_engine import (
    compute_dhash_64,
    compute_laplacian_sharpness,
    calculate_hamming_similarity,
    cluster_culling_items,
)
from App.Culling.services.payment_service import (
    create_razorpay_culling_order,
    verify_razorpay_culling_signature,
)
from App.Culling.services.move_service import execute_move_to_gallery
from App.Culling.tasks import analyze_culling_session_task
from App.Storage.storage_models import Gallery, Media as GalleryMedia, GallerySection
from App.Photographers.photo_models import PhotographerProfile

User = get_user_model()


def create_test_image(sharp: bool = True, pattern: int = 1) -> bytes:
    """Creates an in-memory JPEG image with either sharp edges or blurred/flat content."""
    img = Image.new('RGB', (200, 200), color=( pattern * 30 % 255, pattern * 50 % 255, 100))
    draw = ImageDraw.Draw(img)
    if sharp:
        # Draw high-contrast sharp crosshatching
        for i in range(0, 200, 10):
            draw.line([(0, i), (200, i)], fill=(255, 255, 255), width=2)
            draw.line([(i, 0), (i, 200)], fill=(0, 0, 0), width=2)
    else:
        # Solid flat color / smooth box
        draw.rectangle([(50, 50), (150, 150)], fill=(120, 120, 120))
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()


class CullingEngineTests(TestCase):
    def test_dhash_and_hamming_similarity(self):
        img_bytes_1 = create_test_image(sharp=True, pattern=1)
        img_bytes_2 = create_test_image(sharp=True, pattern=1)  # Identical

        h1 = compute_dhash_64(io.BytesIO(img_bytes_1))
        h2 = compute_dhash_64(io.BytesIO(img_bytes_2))

        self.assertEqual(len(h1), 64)
        self.assertEqual(len(h2), 64)
        sim = calculate_hamming_similarity(h1, h2)
        self.assertEqual(sim, 100.0)

    def test_laplacian_sharpness_differentiates(self):
        sharp_bytes = create_test_image(sharp=True, pattern=1)
        blur_bytes = create_test_image(sharp=False, pattern=1)

        sharp_var, sharp_score = compute_laplacian_sharpness(io.BytesIO(sharp_bytes))
        blur_var, blur_score = compute_laplacian_sharpness(io.BytesIO(blur_bytes))

        self.assertGreater(sharp_var, blur_var)
        self.assertGreaterEqual(sharp_score, blur_score)

    def test_clustering_elects_sharpest_pick(self):
        user = User.objects.create_user(username='testculler', email='testculler@example.com', password='password123')
        session = CullingSession.objects.create(user=user, title='Burst Session')

        # Two similar photos (burst shot) but one sharp, one blur
        h = '1' * 60 + '0000'
        h_dup = '1' * 61 + '000'  # 63/64 similar ~ 98.4%
        h_diff = '0' * 60 + '1111'  # Dissimilar photo

        item_sharp = CullingItem.objects.create(
            session=session,
            file=SimpleUploadedFile('sharp.jpg', create_test_image(sharp=True)),
            original_filename='sharp.jpg',
            file_size_bytes=1000,
            dhash_string=h,
            sharpness_score=95,
        )
        item_blur = CullingItem.objects.create(
            session=session,
            file=SimpleUploadedFile('blur.jpg', create_test_image(sharp=False)),
            original_filename='blur.jpg',
            file_size_bytes=1000,
            dhash_string=h_dup,
            sharpness_score=40,
        )
        item_diff = CullingItem.objects.create(
            session=session,
            file=SimpleUploadedFile('diff.jpg', create_test_image(sharp=True)),
            original_filename='diff.jpg',
            file_size_bytes=1000,
            dhash_string=h_diff,
            sharpness_score=85,
        )

        clusters = cluster_culling_items([item_sharp, item_blur, item_diff], similarity_threshold=88.0)
        self.assertEqual(len(clusters), 1)
        cluster = clusters[0]
        self.assertEqual(len(cluster), 2)
        winner = cluster[0]
        loser = cluster[1]

        self.assertEqual(winner.id, item_sharp.id)
        self.assertTrue(winner.is_best_pick)
        self.assertEqual(winner.status, 'keep')

        self.assertEqual(loser.id, item_blur.id)
        self.assertFalse(loser.is_best_pick)
        self.assertEqual(loser.status, 'discard')


class CullingWorkflowIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='photographer_john',
            email='john@example.com',
            password='Password123!',
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="John Doe",
            studio_name="John's Photography",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_culling_task_analysis_end_to_end(self):
        session = CullingSession.objects.create(user=self.user, title='Wedding Burst')

        # Add 3 items: 2 identical/burst and 1 distinct
        img1 = SimpleUploadedFile('burst_1.jpg', create_test_image(sharp=True, pattern=2), content_type='image/jpeg')
        img2 = SimpleUploadedFile('burst_2.jpg', create_test_image(sharp=False, pattern=2), content_type='image/jpeg')
        img3 = SimpleUploadedFile('distinct.jpg', create_test_image(sharp=True, pattern=9), content_type='image/jpeg')

        item1 = CullingItem.objects.create(session=session, file=img1, original_filename='burst_1.jpg', file_size_bytes=len(img1))
        item2 = CullingItem.objects.create(session=session, file=img2, original_filename='burst_2.jpg', file_size_bytes=len(img2))
        item3 = CullingItem.objects.create(session=session, file=img3, original_filename='distinct.jpg', file_size_bytes=len(img3))

        res = analyze_culling_session_task(str(session.id), similarity_threshold=85.0)
        self.assertEqual(res['status'], 'success')

        session.refresh_from_db()
        self.assertEqual(session.status, 'completed')
        self.assertEqual(session.progress_percentage, 100)
        self.assertEqual(session.total_photos, 3)

        # Items should have dhash and sharpness computed
        for itm in [item1, item2, item3]:
            itm.refresh_from_db()
            self.assertEqual(len(itm.dhash_string), 64)
            self.assertGreater(itm.sharpness_score, 0)

    def test_payment_order_and_signature_unlock(self):
        session = CullingSession.objects.create(user=self.user, title='Paid Cull Session')

        # Create Order
        order_res = create_razorpay_culling_order(session, amount_inr=149.0, tier_name='Single Shoot Batch')
        self.assertIn('order_id', order_res)
        self.assertEqual(order_res['amount'], 14900)

        order_id = order_res['order_id']
        order_obj = CullingPaymentOrder.objects.get(razorpay_order_id=order_id)
        self.assertEqual(order_obj.status, 'created')
        self.assertFalse(session.is_paid)

        # Verify signature unlocks session
        verified = verify_razorpay_culling_signature(
            session=session,
            order_id=order_id,
            payment_id='pay_test123456',
            signature='valid_test_signature',
        )
        self.assertTrue(verified)

        session.refresh_from_db()
        self.assertTrue(session.is_paid)
        self.assertEqual(session.paid_amount, 149.00)
        self.assertIn(session.paid_tier, ['cull_single_300', 'Single Shoot Batch'])

    def test_move_to_gallery_purges_staging_and_creates_sections(self):
        session = CullingSession.objects.create(user=self.user, title='Transfer Session', is_paid=True)

        img1 = SimpleUploadedFile('ceremony_1.jpg', create_test_image(sharp=True, pattern=1), content_type='image/jpeg')
        img2 = SimpleUploadedFile('reception_1.jpg', create_test_image(sharp=True, pattern=2), content_type='image/jpeg')

        item1 = CullingItem.objects.create(session=session, file=img1, original_filename='ceremony_1.jpg', file_size_bytes=len(img1), status='keep')
        item2 = CullingItem.objects.create(session=session, file=img2, original_filename='reception_1.jpg', file_size_bytes=len(img2), status='keep')

        payload = {
            'target_mode': 'new',
            'new_gallery_title': 'Smith Wedding AI Curated',
            'category_assignments': {
                str(item1.id): 'CEREMONY',
                str(item2.id): 'RECEPTION',
            },
            'target_section_title': 'AI CURATED',
        }

        res = execute_move_to_gallery(session, payload)
        self.assertTrue(res['success'])
        self.assertEqual(res['transferred_count'], 2)
        gallery_id = res['gallery_id']

        # Gallery and Sections created
        gallery = Gallery.objects.get(id=gallery_id)
        self.assertEqual(gallery.title, 'Smith Wedding AI Curated')
        self.assertTrue(GallerySection.objects.filter(gallery=gallery, title='CEREMONY').exists())
        self.assertTrue(GallerySection.objects.filter(gallery=gallery, title='RECEPTION').exists())

        # Media transferred
        self.assertEqual(GalleryMedia.objects.filter(gallery=gallery).count(), 2)

        # Culling session purged & completed
        session.refresh_from_db()
        self.assertEqual(session.items.count(), 0)
        self.assertEqual(session.clusters.count(), 0)
        self.assertEqual(session.status, 'completed')

    def test_api_endpoints_full_lifecycle(self):
        # 1. Create Session
        res = self.client.post('/api/culling/sessions/', {'title': 'Studio Session Alpha'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        session_id = res.data['id']

        # 2. Attempt Upload before payment -> Must be rejected with 402 PAYMENT_REQUIRED
        img1 = SimpleUploadedFile('shot_a.jpg', create_test_image(sharp=True), content_type='image/jpeg')
        img2 = SimpleUploadedFile('shot_b.jpg', create_test_image(sharp=False), content_type='image/jpeg')
        res_upload_unpaid = self.client.post(
            f'/api/culling/sessions/{session_id}/upload-photos/',
            {'photos': [img1, img2]},
            format='multipart',
        )
        self.assertEqual(res_upload_unpaid.status_code, status.HTTP_402_PAYMENT_REQUIRED)

        # 3. Create Upfront Payment Order
        res_order = self.client.post(
            f'/api/culling/sessions/{session_id}/payments/create-order/',
            {'tier_id': 'cull_single_300'},
            format='json',
        )
        self.assertEqual(res_order.status_code, status.HTTP_200_OK)
        order_id = res_order.data['order_id']

        # 4. Verify Payment to unlock
        res_verify = self.client.post(
            f'/api/culling/sessions/{session_id}/payments/verify/',
            {
                'razorpay_order_id': order_id,
                'razorpay_payment_id': 'pay_mock_123',
                'razorpay_signature': 'valid_test_signature',
            },
            format='json',
        )
        self.assertEqual(res_verify.status_code, status.HTTP_200_OK)
        self.assertTrue(res_verify.data['is_paid'])

        # 5. Upload photos now succeeds with 201 CREATED
        img1 = SimpleUploadedFile('shot_a.jpg', create_test_image(sharp=True), content_type='image/jpeg')
        img2 = SimpleUploadedFile('shot_b.jpg', create_test_image(sharp=False), content_type='image/jpeg')
        res_upload_paid = self.client.post(
            f'/api/culling/sessions/{session_id}/upload-photos/',
            {'photos': [img1, img2]},
            format='multipart',
        )
        self.assertEqual(res_upload_paid.status_code, status.HTTP_201_CREATED)

        # 6. Retrieve Session
        res_get = self.client.get(f'/api/culling/sessions/{session_id}/')
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)
        self.assertEqual(res_get.data['total_photos'], 2)

        # 7. Move to Gallery succeeds and auto-purges staging
        res_move_paid = self.client.post(
            f'/api/culling/sessions/{session_id}/move-to-gallery/',
            {'target_mode': 'new', 'new_gallery_title': 'Unlocked AI Gallery'},
            format='json',
        )
        self.assertEqual(res_move_paid.status_code, status.HTTP_200_OK)
        self.assertTrue(res_move_paid.data['success'])
        self.assertEqual(res_move_paid.data['moved_count'], 2)

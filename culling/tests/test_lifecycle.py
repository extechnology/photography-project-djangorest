import io
import os
import zipfile
import uuid
from datetime import timedelta
from PIL import Image, ImageDraw
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from culling.models import (
    CullingPricingTier,
    CullingSession,
    CullingPhoto,
    CullingCluster
)
from culling.tasks import cleanup_abandoned_culling_sessions
from App.Photographers.photo_models import PhotographerProfile
from gallery.models import Gallery, GalleryMedia

User = get_user_model()


def make_dummy_jpeg(name='test.jpg', color=(100, 150, 200)) -> SimpleUploadedFile:
    img = Image.new('RGB', (100, 100), color=color)
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), name, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


class CullingSessionLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='cull_photographer',
            email='cull@example.com',
            password='Password123!'
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Cull Studio",
            studio_name="Cull Studio Pro"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Seed tier
        self.tier_single = CullingPricingTier.objects.create(
            id='cull_single_300',
            name='Single Shoot Batch',
            price_inr=149,
            photos_limit=300,
            badge='Single Shoot',
            display_order=1
        )
        self.tier_wedding = CullingPricingTier.objects.create(
            id='cull_wedding_1200',
            name='Wedding Event',
            price_inr=399,
            photos_limit=1200,
            badge='Popular',
            display_order=2
        )

    def test_pricing_tiers_public_endpoint(self):
        anon_client = APIClient()
        res = anon_client.get('/api/culling/pricing-tiers/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data) >= 2)

        # Alias /plans/
        res_alias = anon_client.get('/api/culling/plans/')
        self.assertEqual(res_alias.status_code, status.HTTP_200_OK)

    def test_active_session_hydration_empty(self):
        res = self.client.get('/api/culling/sessions/active/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data['active'])
        self.assertIsNone(res.data['session'])

    def test_checkout_order_creation_and_capacity_loophole_enforcement(self):
        session_id = f"cull_test_{uuid.uuid4().hex[:8]}"

        # 1. Capacity exceeded check
        res_overflow = self.client.post('/api/culling/checkout/order/', {
            'session_id': session_id,
            'tier_id': 'cull_single_300',
            'photo_count': 301
        }, format='json')
        self.assertEqual(res_overflow.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('limit exceeded', res_overflow.data['error'].lower())

        # 2. Valid order creation
        res = self.client.post('/api/culling/checkout/order/', {
            'session_id': session_id,
            'tier_id': 'cull_single_300',
            'photo_count': 150
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['amount'], 14900)
        self.assertEqual(res.data['tier_id'], 'cull_single_300')

        session = CullingSession.objects.get(id=session_id)
        self.assertIn(session.status, [CullingSession.Status.DRAFT, CullingSession.Status.PENDING_PAYMENT, 'draft', 'pending_payment'])
        self.assertFalse(session.is_paid)

    def test_verify_payment_activates_session_and_blocks_concurrent_active_batches(self):
        session_id = f"cull_active_{uuid.uuid4().hex[:8]}"
        self.client.post('/api/culling/checkout/order/', {
            'session_id': session_id,
            'tier_id': 'cull_single_300',
            'photo_count': 50
        }, format='json')

        # Verify payment
        res_verify = self.client.post('/api/culling/checkout/verify/', {
            'session_id': session_id,
            'razorpay_payment_id': 'pay_test_12345'
        }, format='json')
        self.assertEqual(res_verify.status_code, status.HTTP_200_OK)

        session = CullingSession.objects.get(id=session_id)
        self.assertTrue(session.is_paid)
        self.assertIn(session.status, [CullingSession.Status.PAID, CullingSession.Status.ACTIVE, 'paid', 'active'])

        # GET /api/culling/sessions/active/ now returns active=True
        res_active = self.client.get('/api/culling/sessions/active/')
        self.assertEqual(res_active.status_code, status.HTTP_200_OK)
        self.assertTrue(res_active.data['active'])
        self.assertEqual(res_active.data['session']['id'], session_id)

        # LOOPHOLE CHECK: Attempting to start a second batch while one is active returns 409 Conflict
        res_second = self.client.post('/api/culling/checkout/order/', {
            'session_id': 'new_session_attempt',
            'tier_id': 'cull_wedding_1200',
            'photo_count': 500
        }, format='json')
        self.assertEqual(res_second.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('active batch', res_second.data['error'].lower())

    def test_upload_photos_and_strict_single_upload_rule(self):
        session_id = f"cull_upload_{uuid.uuid4().hex[:8]}"
        session = CullingSession.objects.create(
            id=session_id,
            user=self.user,
            tier=self.tier_single,
            status=CullingSession.Status.ACTIVE,
            is_paid=True
        )

        f1 = make_dummy_jpeg('photo_1.jpg')
        f2 = make_dummy_jpeg('photo_2.jpg')

        res_upload = self.client.post('/api/culling/upload/', {
            'session_id': session_id,
            'photos': [f1, f2]
        }, format='multipart')
        self.assertEqual(res_upload.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_upload.data['uploaded_count'], 2)

        session.refresh_from_db()
        self.assertEqual(session.total_photos, 2)
        self.assertEqual(session.photos.count(), 2)

        # STRICT LOOPHOLE ENFORCEMENT: A plan covers only ONE batch upload.
        # Attempting incremental uploads to the same session is rejected with 400 Bad Request
        f3 = make_dummy_jpeg('photo_3.jpg')
        res_incremental = self.client.post('/api/culling/upload/', {
            'session_id': session_id,
            'photos': [f3]
        }, format='multipart')
        self.assertEqual(res_incremental.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Single upload rule violated', res_incremental.data['error'])

    def test_sync_session_state_and_persistence_across_navigation(self):
        session_id = f"cull_sync_{uuid.uuid4().hex[:8]}"
        session = CullingSession.objects.create(
            id=session_id,
            user=self.user,
            tier=self.tier_single,
            status=CullingSession.Status.ACTIVE,
            is_paid=True
        )

        p1 = CullingPhoto.objects.create(
            id='p1',
            session=session,
            file=make_dummy_jpeg('p1.jpg'),
            name='p1.jpg',
            size_bytes=1000,
            status=CullingPhoto.PhotoStatus.KEEP
        )
        p2 = CullingPhoto.objects.create(
            id='p2',
            session=session,
            file=make_dummy_jpeg('p2.jpg'),
            name='p2.jpg',
            size_bytes=1200,
            status=CullingPhoto.PhotoStatus.KEEP
        )

        # Client sends analysis & user keep/discard override
        sync_payload = {
            'session_id': session_id,
            'tier_id': 'cull_single_300',
            'is_paid': True,
            'photos': [
                {
                    'id': 'p1',
                    'status': 'keep',
                    'isBestPick': True,
                    'clusterId': 'cluster_burst_1',
                    'similarityWithBest': 1.0,
                    'sharpnessScore': 94.5,
                    'rawSharpnessVariance': 450.2,
                    'hash': 'a1b2c3d4'
                },
                {
                    'id': 'p2',
                    'status': 'discard',
                    'isBestPick': False,
                    'clusterId': 'cluster_burst_1',
                    'similarityWithBest': 0.96,
                    'sharpnessScore': 62.1,
                    'rawSharpnessVariance': 180.5,
                    'hash': 'a1b2c3d5'
                }
            ],
            'clusters': [
                {
                    'id': 'cluster_burst_1',
                    'bestPickId': 'p1',
                    'photoIds': ['p1', 'p2'],
                    'averageSimilarity': 0.96
                }
            ]
        }

        res_sync = self.client.post(
            f'/api/culling/sessions/{session_id}/sync/',
            sync_payload,
            format='json'
        )
        self.assertEqual(res_sync.status_code, status.HTTP_200_OK)

        # Verify active session returns fully hydrated state with camelCase fields
        res_active = self.client.get('/api/culling/sessions/active/')
        self.assertEqual(res_active.status_code, status.HTTP_200_OK)
        session_data = res_active.data['session']
        self.assertEqual(session_data['id'], session_id)
        self.assertEqual(len(session_data['photos']), 2)
        self.assertEqual(len(session_data['clusters']), 1)

        # Check p1 attributes
        p1_data = next(p for p in session_data['photos'] if p['id'] == 'p1')
        self.assertEqual(p1_data['status'], 'keep')
        self.assertTrue(p1_data['isBestPick'])
        self.assertEqual(p1_data['sharpnessScore'], 94.5)

        # Check p2 attributes
        p2_data = next(p for p in session_data['photos'] if p['id'] == 'p2')
        self.assertEqual(p2_data['status'], 'discard')
        self.assertFalse(p2_data['isBestPick'])

    def test_export_zip_of_keepers(self):
        session_id = f"cull_zip_{uuid.uuid4().hex[:8]}"
        session = CullingSession.objects.create(
            id=session_id,
            user=self.user,
            status=CullingSession.Status.ACTIVE,
            is_paid=True
        )
        f1 = make_dummy_jpeg('winner.jpg')
        CullingPhoto.objects.create(
            id='photo_winner',
            session=session,
            file=f1,
            name='winner.jpg',
            status=CullingPhoto.PhotoStatus.KEEP
        )
        f2 = make_dummy_jpeg('duplicate.jpg')
        CullingPhoto.objects.create(
            id='photo_dupe',
            session=session,
            file=f2,
            name='duplicate.jpg',
            status=CullingPhoto.PhotoStatus.DISCARD
        )

        res_zip = self.client.get(f'/api/culling/sessions/{session_id}/export-zip/?status=keep')
        self.assertEqual(res_zip.status_code, status.HTTP_200_OK)
        self.assertEqual(res_zip['Content-Type'], 'application/zip')

        # Read zip content
        zip_buf = io.BytesIO(res_zip.content)
        with zipfile.ZipFile(zip_buf, 'r') as zf:
            namelist = zf.namelist()
            self.assertIn('winner.jpg', namelist)
            self.assertNotIn('duplicate.jpg', namelist)

    def test_move_culling_to_gallery_and_purge_staging(self):
        gallery = Gallery.objects.create(photographer=self.profile, title='Wedding Highlights')
        session_id = f"cull_move_{uuid.uuid4().hex[:8]}"
        session = CullingSession.objects.create(
            id=session_id,
            user=self.user,
            status=CullingSession.Status.ACTIVE,
            is_paid=True
        )

        f1 = make_dummy_jpeg('good1.jpg')
        CullingPhoto.objects.create(
            id='k1',
            session=session,
            file=f1,
            name='good1.jpg',
            size_bytes=5000,
            status=CullingPhoto.PhotoStatus.KEEP
        )
        f2 = make_dummy_jpeg('bad2.jpg')
        CullingPhoto.objects.create(
            id='d1',
            session=session,
            file=f2,
            name='bad2.jpg',
            size_bytes=5000,
            status=CullingPhoto.PhotoStatus.DISCARD
        )

        res_move = self.client.post(
            f'/api/culling/sessions/{session_id}/move-to-gallery/',
            {'gallery_id': str(gallery.id)},
            format='json'
        )
        self.assertEqual(res_move.status_code, status.HTTP_200_OK)

        session.refresh_from_db()
        self.assertIn(session.status, [CullingSession.Status.MOVED_TO_GALLERY, CullingSession.Status.COMPLETED, 'moved_to_gallery', 'completed'])
        # Keeper photo was transferred to gallery
        self.assertEqual(gallery.media_items.count(), 1)
        media_item = gallery.media_items.first()
        self.assertEqual(media_item.original_filename, 'good1.jpg')

        # Active session endpoint is now freed
        res_active = self.client.get('/api/culling/sessions/active/')
        self.assertFalse(res_active.data.get('active', False) and res_active.data.get('session') is not None)

    def test_discard_session_frees_active_state(self):
        session_id = f"cull_discard_{uuid.uuid4().hex[:8]}"
        session = CullingSession.objects.create(
            id=session_id,
            user=self.user,
            status=CullingSession.Status.ACTIVE,
            is_paid=True
        )
        CullingPhoto.objects.create(
            id='p_discard',
            session=session,
            file=make_dummy_jpeg('p_discard.jpg'),
            name='p_discard.jpg',
            status=CullingPhoto.PhotoStatus.KEEP
        )

        res_del = self.client.delete(f'/api/culling/sessions/{session_id}/')
        self.assertEqual(res_del.status_code, status.HTTP_200_OK)

        session.refresh_from_db()
        self.assertEqual(session.status, CullingSession.Status.DISCARDED)
        self.assertEqual(session.photos.count(), 0)

        res_active = self.client.get('/api/culling/sessions/active/')
        self.assertFalse(res_active.data['active'])

    def test_cleanup_abandoned_culling_sessions_task(self):
        # 1. Expired session
        expired_id = f"cull_expired_{uuid.uuid4().hex[:8]}"
        expired_session = CullingSession.objects.create(
            id=expired_id,
            user=self.user,
            status=CullingSession.Status.ACTIVE,
            expires_at=timezone.now() - timedelta(days=1)
        )
        CullingPhoto.objects.create(
            id='p_exp',
            session=expired_session,
            file=make_dummy_jpeg('exp.jpg'),
            name='exp.jpg'
        )

        # 2. Fresh active session
        fresh_id = f"cull_fresh_{uuid.uuid4().hex[:8]}"
        fresh_session = CullingSession.objects.create(
            id=fresh_id,
            user=self.user,
            status=CullingSession.Status.ACTIVE,
            expires_at=timezone.now() + timedelta(days=6)
        )

        # Run task
        msg = cleanup_abandoned_culling_sessions()
        self.assertIn("Purged staging storage for 1 expired", msg)

        expired_session.refresh_from_db()
        self.assertEqual(expired_session.status, CullingSession.Status.EXPIRED)
        self.assertEqual(expired_session.photos.count(), 0)

        fresh_session.refresh_from_db()
        self.assertEqual(fresh_session.status, CullingSession.Status.ACTIVE)

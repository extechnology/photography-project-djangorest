import io
import os
import shutil
import uuid
from datetime import timedelta
from PIL import Image, ImageDraw
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.conf import settings
from rest_framework.test import APIClient
from rest_framework import status

from culling.models import (
    CullingSession,
    CullingStagingPhoto,
    CullingPhoto,
    CullingCluster,
    CullingPricingTier,
)
from App.Subscriptions.sub_models import Plan, PhotographerSubscription
from App.Photographers.photo_models import PhotographerProfile
from App.Storage.storage_models import Gallery, Media as GalleryMedia

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

        # Main subscription plan with AI Culling enabled
        self.plan = Plan.objects.create(
            id='plan_test_pro',
            name='Pro Studio',
            ai_culling_enabled=True,
            is_active=True,
        )
        self.subscription = PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan,
            status='active',
            started_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )

    def test_permission_blocked_if_plan_ai_culling_disabled(self):
        # Disable AI culling on user's plan
        self.plan.ai_culling_enabled = False
        self.plan.save()

        res_upload = self.client.post('/api/culling/upload/', {
            'photos': [make_dummy_jpeg('p1.jpg')]
        }, format='multipart')
        self.assertEqual(res_upload.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("not included in your current subscription plan", res_upload.data['detail'])

        res_active = self.client.get('/api/culling/sessions/active/')
        self.assertEqual(res_active.status_code, status.HTTP_403_FORBIDDEN)

        # Re-enable
        self.plan.ai_culling_enabled = True
        self.plan.save()

    def test_active_session_hydration_empty(self):
        res = self.client.get('/api/culling/sessions/active/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data['active'])
        self.assertIsNone(res.data['session'])

    def test_unlimited_upload_to_staging(self):
        session_id = f"cull_test_{uuid.uuid4().hex[:8]}"
        f1 = make_dummy_jpeg('shot1.jpg', color=(200, 50, 50))
        f2 = make_dummy_jpeg('shot2.jpg', color=(200, 50, 50))
        f3 = make_dummy_jpeg('shot3.jpg', color=(50, 200, 50))

        res_upload = self.client.post('/api/culling/upload/', {
            'session_id': session_id,
            'photos': [f1, f2, f3]
        }, format='multipart')
        self.assertEqual(res_upload.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res_upload.data['uploaded_count'], 3)
        self.assertEqual(len(res_upload.data['photos']), 3)

        session = CullingSession.objects.get(id=session_id)
        self.assertEqual(session.total_photos, 3)
        self.assertEqual(session.status, "staging")

    def test_server_side_ai_analysis_pipeline(self):
        session_id = f"cull_ai_{uuid.uuid4().hex[:8]}"
        session = CullingSession.objects.create(
            id=session_id,
            user=self.user,
            title="Burst Shoot Session",
            status="staging",
        )
        # Duplicate shots (same color/content)
        f1 = make_dummy_jpeg('burst1.jpg', color=(120, 120, 120))
        f2 = make_dummy_jpeg('burst2.jpg', color=(120, 120, 120))
        # Unique shot
        f3 = make_dummy_jpeg('unique.jpg', color=(20, 80, 220))

        self.client.post('/api/culling/upload/', {
            'session_id': session_id,
            'photos': [f1, f2, f3]
        }, format='multipart')

        # Run AI analysis
        res_analyze = self.client.post(f'/api/culling/sessions/{session_id}/analyze/', {
            'similarity_threshold': 85.0
        }, format='json')
        self.assertEqual(res_analyze.status_code, status.HTTP_200_OK)
        self.assertTrue(res_analyze.data['success'])

        session.refresh_from_db()
        self.assertEqual(session.status, "analyzed")
        self.assertEqual(session.total_photos, 3)

        # Check sharpness and perceptual hash were calculated
        photos = list(session.photos.all())
        for p in photos:
            self.assertGreater(p.sharpness_score, 0)
            self.assertTrue(len(p.perceptual_hash) > 0)

    def test_sync_curation_decisions(self):
        session_id = f"cull_sync_{uuid.uuid4().hex[:8]}"
        session = CullingSession.objects.create(
            id=session_id,
            user=self.user,
            status="staging"
        )
        f1 = make_dummy_jpeg('photo_a.jpg')
        p1 = CullingStagingPhoto.objects.create(
            session=session,
            file=f1,
            original_filename='photo_a.jpg',
            size_bytes=4000,
            status="keep"
        )

        res_sync = self.client.post(f'/api/culling/sessions/{session_id}/sync/', {
            'photos': [
                {
                    'id': p1.id,
                    'status': 'discard',
                    'sharpnessScore': 92.5,
                    'isBestPick': False,
                    'clusterId': 'cluster_1'
                }
            ],
            'clusters': [
                {
                    'id': 'cluster_1',
                    'title': 'Burst Cluster 1',
                    'averageSimilarity': 95.0,
                    'bestPickId': p1.id,
                    'photoIds': [p1.id],
                    'totalPhotos': 1,
                    'duplicatesCount': 0,
                    'wastedBytes': 4000
                }
            ]
        }, format='json')
        self.assertEqual(res_sync.status_code, status.HTTP_200_OK)

        p1.refresh_from_db()
        self.assertEqual(p1.status, 'discard')
        self.assertEqual(p1.sharpness_score, 92.5)

        session.refresh_from_db()
        self.assertEqual(session.status, 'analyzed')
        self.assertEqual(session.clusters.count(), 1)

    def test_move_culling_to_gallery_and_purge_staging(self):
        session_id = f"cull_migrate_{uuid.uuid4().hex[:8]}"
        session = CullingSession.objects.create(
            id=session_id,
            user=self.user,
            status="analyzed",
        )

        # Ensure staging folder exists
        staging_dir = os.path.join(settings.MEDIA_ROOT, 'culling_staging', session_id)
        os.makedirs(staging_dir, exist_ok=True)

        f1 = make_dummy_jpeg('good1.jpg')
        p1 = CullingStagingPhoto.objects.create(
            session=session,
            file=f1,
            original_filename='good1.jpg',
            size_bytes=5000,
            status="keep"
        )
        f2 = make_dummy_jpeg('bad2.jpg')
        p2 = CullingStagingPhoto.objects.create(
            session=session,
            file=f2,
            original_filename='bad2.jpg',
            size_bytes=5000,
            status="discard"
        )

        # Test transfer to new gallery
        res_move = self.client.post(
            f'/api/culling/sessions/{session_id}/move-to-gallery/',
            {
                'target_mode': 'new',
                'new_gallery_title': 'Wedding Ceremony Highlights',
                'target_section_title': 'Ceremony'
            },
            format='json'
        )
        self.assertEqual(res_move.status_code, status.HTTP_200_OK)
        self.assertTrue(res_move.data['success'])
        self.assertEqual(res_move.data['transferred_count'], 1)

        # Gallery was created and keeper was migrated
        gallery = Gallery.objects.get(id=res_move.data['gallery_id'])
        self.assertEqual(gallery.title, 'Wedding Ceremony Highlights')
        self.assertEqual(gallery.media_items.count(), 1)
        media_item = gallery.media_items.first()
        self.assertEqual(media_item.original_filename, 'good1.jpg')

        session.refresh_from_db()
        self.assertEqual(session.status, 'moved_to_gallery')

        # Staging disk was purged
        self.assertFalse(os.path.exists(staging_dir))

    def test_discard_session_frees_active_state(self):
        session_id = f"cull_discard_{uuid.uuid4().hex[:8]}"
        session = CullingSession.objects.create(
            id=session_id,
            user=self.user,
            status="staging",
        )
        staging_dir = os.path.join(settings.MEDIA_ROOT, 'culling_staging', session_id)
        os.makedirs(staging_dir, exist_ok=True)

        res_discard = self.client.delete(f'/api/culling/sessions/{session_id}/')
        self.assertEqual(res_discard.status_code, status.HTTP_200_OK)

        self.assertFalse(CullingSession.objects.filter(id=session_id).exists())
        self.assertFalse(os.path.exists(staging_dir))

    def test_storage_quota_exceeded_returns_413(self):
        # Set profile used storage to be at the plan limit
        self.profile.storage_used_bytes = self.subscription.effective_storage_limit_bytes
        self.profile.save()

        res = self.client.post('/api/culling/upload/', {
            'photos': [make_dummy_jpeg('excess.jpg')]
        }, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        self.assertIn(res.data.get('code'), ['storage_quota_exceeded', 'STORAGE_LIMIT_EXCEEDED'])
        self.assertTrue(bool(res.data.get('error') or res.data.get('detail')))

        # Reset profile storage
        self.profile.storage_used_bytes = 0
        self.profile.save()

    def test_discard_session_via_post_reclaims_staging_storage(self):
        session_id = f"cull_post_discard_{uuid.uuid4().hex[:8]}"
        session = CullingSession.objects.create(
            id=session_id,
            user=self.user,
            status="staging",
        )
        staging_dir = os.path.join(settings.MEDIA_ROOT, 'culling_staging', session_id)
        os.makedirs(staging_dir, exist_ok=True)

        res = self.client.post(f'/api/culling/sessions/{session_id}/discard/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data.get("success"))
        self.assertFalse(CullingSession.objects.filter(id=session_id).exists())
        self.assertFalse(os.path.exists(staging_dir))

    def test_plan_and_subscription_serializers_expose_ai_culling_enabled(self):
        from App.Subscriptions.sub_serializers import PlanSerializer, CurrentSubscriptionSerializer, UserSubscriptionSerializer

        plan_data = PlanSerializer(self.plan).data
        self.assertIn('ai_culling_enabled', plan_data)
        self.assertTrue(plan_data['ai_culling_enabled'])

        sub_data = CurrentSubscriptionSerializer(self.subscription).data
        self.assertIn('ai_culling_enabled', sub_data)
        self.assertTrue(sub_data['ai_culling_enabled'])

        user_sub_data = UserSubscriptionSerializer(self.subscription).data
        self.assertIn('ai_culling_enabled', user_sub_data)
        self.assertTrue(user_sub_data['ai_culling_enabled'])

    def test_multiple_sessions_cluster_uniqueness_preventing_integrity_error(self):
        # Session 1 with duplicates
        sid_1 = f"cull_batch1_{uuid.uuid4().hex[:8]}"
        self.client.post('/api/culling/upload/', {
            'session_id': sid_1,
            'photos': [
                make_dummy_jpeg('batch1_a.jpg', color=(100, 100, 100)),
                make_dummy_jpeg('batch1_b.jpg', color=(100, 100, 100)),
            ]
        }, format='multipart')
        res1 = self.client.post(f'/api/culling/sessions/{sid_1}/analyze/', {'similarity_threshold': 80.0}, format='json')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)

        # Session 2 with duplicates - must not trigger UNIQUE constraint failed: culling_cluster.id
        sid_2 = f"cull_batch2_{uuid.uuid4().hex[:8]}"
        self.client.post('/api/culling/upload/', {
            'session_id': sid_2,
            'photos': [
                make_dummy_jpeg('batch2_a.jpg', color=(150, 150, 150)),
                make_dummy_jpeg('batch2_b.jpg', color=(150, 150, 150)),
            ]
        }, format='multipart')
        res2 = self.client.post(f'/api/culling/sessions/{sid_2}/analyze/', {'similarity_threshold': 80.0}, format='json')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)

        s1_clusters = list(CullingCluster.objects.filter(session_id=sid_1).values_list('id', flat=True))
        s2_clusters = list(CullingCluster.objects.filter(session_id=sid_2).values_list('id', flat=True))
        self.assertGreater(len(s1_clusters), 0)
        self.assertGreater(len(s2_clusters), 0)
        # Ensure disjoint cluster IDs
        self.assertTrue(set(s1_clusters).isdisjoint(set(s2_clusters)))

    def test_get_session_latest_and_detail_endpoint(self):
        session_id = f"cull_latest_{uuid.uuid4().hex[:8]}"
        self.client.post('/api/culling/upload/', {
            'session_id': session_id,
            'photos': [make_dummy_jpeg('test_photo.jpg')]
        }, format='multipart')

        # Test GET /api/culling/sessions/latest/ does not return 405 Method Not Allowed
        res_latest = self.client.get('/api/culling/sessions/latest/')
        self.assertEqual(res_latest.status_code, status.HTTP_200_OK)
        self.assertEqual(res_latest.data['id'], session_id)
        self.assertEqual(res_latest.data['photo_count'], 1)

        # Test GET /api/culling/sessions/{session_id}/ returns session detail
        res_detail = self.client.get(f'/api/culling/sessions/{session_id}/')
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(res_detail.data['id'], session_id)


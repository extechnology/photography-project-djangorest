import uuid
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from App.Subscriptions.sub_models import Plan as StudioPlan, PhotographerSubscription
from App.Photographers.photo_models import PhotographerProfile
from App.Storage.storage_models import Gallery
from App.LiveEvents.event_models import LiveEvent
from App.Subscriptions.views_razorpay import CurrentSubscriptionSerializer
from backend.atelier_plans.subscription_enforcement import is_studio_active

User = get_user_model()


class SubscriptionExpiryLockTests(APITestCase):
    def setUp(self):
        self.client = APIClient()

        # 1. Create or Update Plans
        self.basic_plan, _ = StudioPlan.objects.update_or_create(
            id='plan-basic-test',
            defaults={
                'name': 'Basic Studio',
                'monthly_price': 999,
                'billing_cycle': 'monthly',
                'duration_months': 1,
                'sort_order': 1,
                'storage_limit_bytes': 10 * 1024 * 1024 * 1024,
                'max_galleries': 10,
                'max_events': 5,
                'is_active': True,
            }
        )
        self.elite_plan, _ = StudioPlan.objects.update_or_create(
            id='plan-premium-elite',
            defaults={
                'name': 'Studio Premium Elite',
                'monthly_price': 2999,
                'billing_cycle': 'annual',
                'duration_months': 12,
                'sort_order': 3,
                'storage_limit_bytes': 100 * 1024 * 1024 * 1024,
                'max_galleries': 0,
                'max_events': 0,
                'is_active': True,
            }
        )

        # 2. Create Photographers
        self.active_user = User.objects.create_user(
            username='active_photog',
            email='active@studio.com',
            password='password123',
            role='photographer'
        )
        self.active_profile = PhotographerProfile.objects.create(
            user=self.active_user,
            studio_name='Active Studio',
            name='Active User',
            email='active@studio.com'
        )
        now = timezone.now()
        self.active_sub = PhotographerSubscription.objects.create(
            user=self.active_user,
            photographer=self.active_profile,
            plan=self.elite_plan,
            status='active',
            start_date=now - timedelta(days=10),
            expiry_date=now + timedelta(days=50),
            started_at=now - timedelta(days=10),
            expires_at=now + timedelta(days=50),
            auto_renew=True,
            storage_limit_bytes=self.elite_plan.storage_limit_bytes,
        )

        self.expired_user = User.objects.create_user(
            username='expired_photog',
            email='expired@studio.com',
            password='password123',
            role='photographer'
        )
        self.expired_profile = PhotographerProfile.objects.create(
            user=self.expired_user,
            studio_name='Expired Studio',
            name='Expired User',
            email='expired@studio.com'
        )
        self.expired_sub = PhotographerSubscription.objects.create(
            user=self.expired_user,
            photographer=self.expired_profile,
            plan=self.elite_plan,
            status='expired',
            start_date=now - timedelta(days=400),
            expiry_date=now - timedelta(days=35),
            started_at=now - timedelta(days=400),
            expires_at=now - timedelta(days=35),
            auto_renew=False,
            storage_limit_bytes=self.elite_plan.storage_limit_bytes,
        )

        # 3. Create Galleries
        self.active_gallery = Gallery.objects.create(
            photographer=self.active_profile,
            title='Active Wedding Collection',
            slug='active-wedding-col',
            client_name='Alice & Bob',
            status='active',
        )
        self.expired_gallery = Gallery.objects.create(
            photographer=self.expired_profile,
            title='Expired Wedding Collection',
            slug='expired-wedding-col',
            client_name='Carol & Dave',
            download_pin='1234',
            status='active',
        )

        # 4. Create LiveEvents
        self.active_event = LiveEvent.objects.create(
            photographer=self.active_user,
            title='Active Live Gala',
            slug='active-live-gala',
            venue='Royal Palace',
            status='live',
        )
        self.expired_event = LiveEvent.objects.create(
            photographer=self.expired_user,
            title='Expired Live Gala',
            slug='expired-live-gala',
            venue='Grand Hall',
            status='live',
        )

    def test_is_studio_active_helper(self):
        self.assertTrue(is_studio_active(self.active_user))
        self.assertFalse(is_studio_active(self.expired_user))

    def test_current_subscription_serializer_sanitizes_expired_plan(self):
        serializer = CurrentSubscriptionSerializer(self.expired_sub)
        data = serializer.data
        self.assertEqual(data['status'], 'expired')
        self.assertEqual(data['days_remaining'], 0)
        self.assertEqual(data['auto_renew'], False)

    def test_current_subscription_serializer_reports_active_plan(self):
        serializer = CurrentSubscriptionSerializer(self.active_sub)
        data = serializer.data
        self.assertEqual(data['status'], 'active')
        self.assertGreater(data['days_remaining'], 0)
        self.assertEqual(data['auto_renew'], True)

    def test_public_gallery_access_locked_when_studio_expired(self):
        # 1. Accessing gallery of expired studio returns 403
        resp = self.client.get(f'/api/galleries/{self.expired_gallery.slug}/public/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data.get('code'), 'studio_plan_expired')
        self.assertTrue(resp.data.get('is_studio_plan_expired'))
        self.assertEqual(resp.data.get('studio_name'), 'Expired Studio')

        # Also via legacy route /api/public/galleries/<slug>/
        resp_alt = self.client.get(f'/api/public/galleries/{self.expired_gallery.slug}/')
        self.assertEqual(resp_alt.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_alt.data.get('code'), 'studio_plan_expired')

        # 2. Accessing gallery of active studio returns 200
        resp_active = self.client.get(f'/api/galleries/{self.active_gallery.slug}/public/')
        self.assertEqual(resp_active.status_code, status.HTTP_200_OK)

    def test_public_gallery_pin_verify_locked_when_studio_expired(self):
        resp = self.client.post(
            f'/api/galleries/{self.expired_gallery.slug}/verify-pin/',
            {'pin': '1234'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data.get('code'), 'studio_plan_expired')

    def test_public_gallery_download_zip_locked_when_studio_expired(self):
        resp = self.client.get(f'/api/galleries/{self.expired_gallery.slug}/download-zip/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data.get('code'), 'studio_plan_expired')

    def test_public_event_access_locked_when_studio_expired(self):
        # 1. Accessing live event of expired studio returns 403
        resp = self.client.get(f'/api/events/{self.expired_event.slug}/public/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data.get('code'), 'studio_plan_expired')
        self.assertTrue(resp.data.get('is_studio_plan_expired'))
        self.assertEqual(resp.data.get('studio_name'), 'Expired Studio')

        # 2. Accessing live event of active studio returns 200
        resp_active = self.client.get(f'/api/events/{self.active_event.slug}/public/')
        self.assertEqual(resp_active.status_code, status.HTTP_200_OK)

    def test_public_event_face_search_locked_when_studio_expired(self):
        resp = self.client.post(
            f'/api/events/{self.expired_event.id}/face-search/',
            {'selfie': 'dummy_data'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data.get('code'), 'studio_plan_expired')

    def test_gallery_and_event_creation_blocked_when_expired(self):
        self.client.force_authenticate(user=self.expired_user)

        # 1. Create gallery blocked
        resp_gal = self.client.post('/api/storage/galleries/', {'title': 'New Gallery', 'client_name': 'Test Client'})
        self.assertEqual(resp_gal.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_gal.data.get('code'), 'studio_plan_expired')

        # 2. Create event blocked
        resp_ev = self.client.post('/api/events/', {'title': 'New Live Event', 'event_type': 'wedding'})
        self.assertEqual(resp_ev.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_ev.data.get('code'), 'studio_plan_expired')

    def test_plan_checkout_permits_renewing_same_tier_when_expired(self):
        self.client.force_authenticate(user=self.expired_user)

        with patch('App.Subscriptions.views_razorpay.razorpay_client') as mock_rzp:
            # Mock subscription create fallback to order
            mock_rzp.plan.create.side_effect = Exception("Autopay not configured")
            mock_rzp.order.create.return_value = {
                'id': 'order_test_renewal_123',
                'amount': 3598800,
                'currency': 'INR',
                'status': 'created'
            }

            resp = self.client.post(
                '/api/plans/checkout/',
                {'plan_id': self.elite_plan.id, 'gateway': 'razorpay'},
                format='json'
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            self.assertEqual(resp.data.get('order_id'), 'order_test_renewal_123')
            self.assertEqual(resp.data.get('plan_id'), self.elite_plan.id)

    def test_plan_checkout_blocks_same_tier_when_active(self):
        self.client.force_authenticate(user=self.active_user)

        resp = self.client.post(
            '/api/plans/checkout/',
            {'plan_id': self.elite_plan.id, 'gateway': 'razorpay'},
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already have an active subscription', resp.data.get('detail', ''))

    def test_plan_verify_reactivates_subscription_and_supersedes_old(self):
        self.client.force_authenticate(user=self.expired_user)

        with patch('App.Subscriptions.views_razorpay.razorpay_client') as mock_rzp:
            mock_rzp.utility.verify_payment_signature.return_value = True

            resp = self.client.post(
                '/api/plans/verify/',
                {
                    'plan_id': self.elite_plan.id,
                    'razorpay_payment_id': 'pay_test_renewal_999',
                    'razorpay_order_id': 'order_test_renewal_123',
                    'razorpay_signature': 'valid_mock_signature',
                },
                format='json'
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            self.assertEqual(resp.data.get('status'), 'success')

            # Verify active state
            self.expired_user.refresh_from_db()
            self.assertTrue(is_studio_active(self.expired_user))

            # Old subscription is superseded
            self.expired_sub.refresh_from_db()
            self.assertEqual(self.expired_sub.status, 'superseded')

    def test_billing_endpoints_direct_access(self):
        # 1. Billing gallery public locked when expired
        resp_gal = self.client.get(f'/api/billing/galleries/{self.expired_gallery.slug}/public/')
        self.assertEqual(resp_gal.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_gal.data.get('code'), 'studio_plan_expired')

        # 2. Billing gallery public active returns 200
        resp_gal_active = self.client.get(f'/api/billing/galleries/{self.active_gallery.slug}/public/')
        self.assertEqual(resp_gal_active.status_code, status.HTTP_200_OK)

        # 3. Billing event public locked when expired
        resp_ev = self.client.get(f'/api/billing/events/{self.expired_event.slug}/public/')
        self.assertEqual(resp_ev.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_ev.data.get('code'), 'studio_plan_expired')

        # 4. Billing event public active returns 200
        resp_ev_active = self.client.get(f'/api/billing/events/{self.active_event.slug}/public/')
        self.assertEqual(resp_ev_active.status_code, status.HTTP_200_OK)

        # 5. Billing pin verify locked when expired
        resp_pin = self.client.post(f'/api/billing/galleries/{self.expired_gallery.slug}/verify-pin/', {'pin': '1234'}, format='json')
        self.assertEqual(resp_pin.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_pin.data.get('code'), 'studio_plan_expired')

        # 6. Billing download zip locked when expired
        resp_zip = self.client.get(f'/api/billing/galleries/{self.expired_gallery.slug}/download-zip/')
        self.assertEqual(resp_zip.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_zip.data.get('code'), 'studio_plan_expired')


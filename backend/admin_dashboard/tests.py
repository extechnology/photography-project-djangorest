import datetime
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import Plan, PhotographerSubscription, SubscriptionPayment
from App.Storage.storage_models import Gallery, Media

User = get_user_model()


class AdminDashboardApiTests(APITestCase):
    def setUp(self):
        User.objects.all().delete()
        PhotographerProfile.objects.all().delete()
        Plan.objects.all().delete()
        PhotographerSubscription.objects.all().delete()
        SubscriptionPayment.objects.all().delete()
        Gallery.objects.all().delete()
        Media.objects.all().delete()

        # 1. Super Admin User
        self.admin_user = User.objects.create_user(
            username='super_admin',
            email='admin@exshare.ai',
            password='AdminPassword123!',
            is_staff=True,
            is_superuser=True,
            role=User.Role.ADMIN
        )

        # 2. Regular Photographer User
        self.photographer_user = User.objects.create_user(
            username='photographer_john',
            email='john@studio.com',
            password='UserPassword123!',
            is_staff=False,
            is_superuser=False,
            role=User.Role.PHOTOGRAPHER
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.photographer_user,
            name='John Doe',
            studio_name='Doe Fine Art Studio',
            storage_used_bytes=1073741824  # 1 GB
        )

        # 3. Plan & Subscription
        self.plan = Plan.objects.create(
            id='plan-standard-3m',
            name='Standard Quarterly',
            tier='standard',
            billing_cycle='quarterly',
            duration_months=3,
            monthly_price=Decimal('1500.00'),
            total_price=Decimal('4500.00'),
            image_storage_gb=200,
            video_storage_gb=10,
        )

        self.subscription = PhotographerSubscription.objects.create(
            user=self.photographer_user,
            photographer=self.profile,
            plan=self.plan,
            status='active',
            started_at=timezone.now() - datetime.timedelta(days=10),
            expires_at=timezone.now() + datetime.timedelta(days=80),
        )

        # 4. Successful Payment
        self.payment = SubscriptionPayment.objects.create(
            subscription=self.subscription,
            plan=self.plan,
            amount=Decimal('4500.00'),
            currency='INR',
            gateway='razorpay',
            gateway_order_id='order_test_123',
            gateway_payment_id='pay_test_456',
            status='success',
            paid_at=timezone.now() - datetime.timedelta(days=10)
        )

        # 5. Gallery & Media
        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Sample Wedding 2026',
            status='published'
        )
        self.media = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            title='Entrance Photo',
            media_type='photo',
            file_size=5242880  # 5 MB
        )

    def test_permission_denied_for_unauthenticated_or_regular_users(self):
        url = '/api/admin/dashboard/overview/'

        # Unauthenticated -> 401
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

        # Regular photographer -> 403
        self.client.force_authenticate(user=self.photographer_user)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_dashboard_overview_metrics(self):
        self.client.force_authenticate(user=self.admin_user)
        url = '/api/admin/dashboard/overview/'

        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data

        self.assertEqual(data['status'], 'success')
        self.assertIn('kpis', data)
        self.assertIn('user_growth', data)
        self.assertIn('revenue_analytics', data)
        self.assertIn('subscriptions', data)
        self.assertIn('storage', data)
        self.assertIn('recent_payments', data)
        self.assertIn('recent_users', data)
        self.assertIn('system_health', data)

        kpis = data['kpis']
        self.assertEqual(kpis['total_users'], 2)
        self.assertEqual(kpis['total_photographers'], 1)
        self.assertEqual(kpis['active_subscribers'], 1)
        self.assertEqual(kpis['total_revenue'], 4500.0)
        self.assertEqual(kpis['mrr'], 1500.0)  # 4500 / 3 months = 1500/mo
        self.assertEqual(kpis['arr'], 18000.0)  # 1500 * 12 = 18000
        self.assertEqual(kpis['total_galleries'], 1)
        self.assertEqual(kpis['total_media_items'], 1)

    def test_admin_users_list_view(self):
        self.client.force_authenticate(user=self.admin_user)
        url = '/api/admin/dashboard/users/'

        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 2)

        # Search by studio name
        search_res = self.client.get(f'{url}?search=Fine Art')
        self.assertEqual(search_res.status_code, status.HTTP_200_OK)
        self.assertEqual(search_res.data['count'], 1)
        self.assertEqual(search_res.data['results'][0]['email'], 'john@studio.com')
        self.assertEqual(search_res.data['results'][0]['studio_name'], 'Doe Fine Art Studio')
        self.assertEqual(search_res.data['results'][0]['plan_name'], 'Standard Quarterly')

    def test_admin_payments_list_view(self):
        self.client.force_authenticate(user=self.admin_user)
        url = '/api/admin/dashboard/payments/'

        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['summary']['filtered_total_successful_revenue'], 4500.0)

        payment_item = res.data['results'][0]
        self.assertEqual(payment_item['gateway_order_id'], 'order_test_123')
        self.assertEqual(payment_item['user_email'], 'john@studio.com')
        self.assertEqual(float(payment_item['amount']), 4500.0)
        self.assertEqual(payment_item['status'], 'success')

    def test_admin_growth_analytics_view(self):
        self.client.force_authenticate(user=self.admin_user)
        url = '/api/admin/dashboard/growth/?range=7d'

        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'success')
        self.assertEqual(res.data['range'], '7d')
        self.assertIn('time_series', res.data)
        self.assertIn('timeline', res.data)
        self.assertIn('summary', res.data)
        self.assertTrue(len(res.data['time_series']) >= 7)
        self.assertIn('total_users_acquired', res.data['summary'])
        self.assertIn('total_revenue_generated', res.data['summary'])

    def test_admin_jwt_authentication_token_and_login(self):
        # 1. Test POST /api/token/ with username
        url = '/api/token/'
        res = self.client.post(url, {
            'username': 'super_admin',
            'password': 'AdminPassword123!'
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('access', res.data)
        self.assertIn('refresh', res.data)
        self.assertIn('token', res.data)
        self.assertIn('user', res.data)
        self.assertEqual(res.data['user']['username'], 'super_admin')
        self.assertEqual(res.data['user']['role'], 'admin')

        # 2. Test POST /api/token/ with email
        res_email = self.client.post(url, {
            'username': 'admin@exshare.ai',
            'password': 'AdminPassword123!'
        })
        self.assertEqual(res_email.status_code, status.HTTP_200_OK)
        self.assertIn('access', res_email.data)

        # 3. Test POST /api/accounts/login/
        login_url = '/api/accounts/login/'
        res_login = self.client.post(login_url, {
            'username': 'super_admin',
            'password': 'AdminPassword123!'
        })
        self.assertEqual(res_login.status_code, status.HTTP_200_OK)
        self.assertIn('access', res_login.data)
        self.assertIn('token', res_login.data)


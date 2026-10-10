import uuid
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

from portfolios.models import (
    PortfolioConfig,
    PortfolioWork,
    PortfolioWorkPhoto,
    PortfolioInquiry,
    PortfolioView,
    validate_subdomain,
    RESERVED_SUBDOMAINS,
)
from portfolios.tenant_resolver import (
    resolve_tenant_subdomain,
    get_tenant_profile,
)

User = get_user_model()


class TenantResolverTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        User.objects.all().delete()
        PortfolioConfig.objects.all().delete()

        self.user = User.objects.create_user(
            username='mridhul',
            email='mridhul@exshare.ai',
            password='Password123!'
        )
        self.profile = PortfolioConfig.objects.create(
            user=self.user,
            studio_name='Mridhul Photography Studio',
            subdomain='mridhul',
            is_published=True
        )

    def test_resolve_from_tenant_subdomain_header(self):
        req = self.factory.get('/', HTTP_X_TENANT_SUBDOMAIN='mridhul')
        sub = resolve_tenant_subdomain(req)
        self.assertEqual(sub, 'mridhul')

        tenant = get_tenant_profile(req)
        self.assertIsNotNone(tenant)
        self.assertEqual(tenant.id, self.profile.id)

    def test_resolve_from_host_wildcard(self):
        req = self.factory.get('/', HTTP_HOST='mridhul.exshare.ai')
        sub = resolve_tenant_subdomain(req)
        self.assertEqual(sub, 'mridhul')

    def test_resolve_from_x_forwarded_host(self):
        req = self.factory.get('/', HTTP_X_FORWARDED_HOST='mridhul.exshare.ai')
        sub = resolve_tenant_subdomain(req)
        self.assertEqual(sub, 'mridhul')

    def test_resolve_from_query_param_fallback(self):
        req = self.factory.get('/?subdomain=mridhul')
        sub = resolve_tenant_subdomain(req)
        self.assertEqual(sub, 'mridhul')

    def test_reserved_subdomain_ignored(self):
        req = self.factory.get('/', HTTP_HOST='app.exshare.ai')
        sub = resolve_tenant_subdomain(req)
        self.assertIsNone(sub)

        req_api = self.factory.get('/', HTTP_HOST='api.exshare.ai')
        self.assertIsNone(resolve_tenant_subdomain(req_api))

        req_admin = self.factory.get('/', HTTP_HOST='admin.exshare.ai')
        self.assertIsNone(resolve_tenant_subdomain(req_admin))


class TenantPublicEndpointsContractTests(APITestCase):
    def setUp(self):
        User.objects.all().delete()
        PortfolioConfig.objects.all().delete()
        PortfolioWork.objects.all().delete()
        PortfolioInquiry.objects.all().delete()

        self.user = User.objects.create_user(
            username='mridhul',
            email='mridhul@exshare.ai',
            password='Password123!'
        )
        self.profile = PortfolioConfig.objects.create(
            user=self.user,
            studio_name='Mridhul Photography Studio',
            artist_name='Mridhul Nair',
            tagline='Luxury Weddings & Editorial',
            bio='Visual storyteller based in Mumbai.',
            about_story='Crafting timeless heirlooms.',
            location='Mumbai & Worldwide',
            subdomain='mridhul',
            template_id='editorial-vogue',
            accent_color='#d4af37',
            pricing_starting_at='$3,500',
            philosophy_quote='Beauty is in the fleeting moments.',
            philosophy_author='Mridhul Nair',
            is_published=True,
            is_booking_open=True
        )

        self.work = PortfolioWork.objects.create(
            portfolio=self.profile,
            title='Royal Udaipur Palace Wedding',
            category='weddings',
            cover_url='https://cdn.exshare.ai/cover.jpg',
            year='2026',
            location='Udaipur, Rajasthan',
            description='A grand celebration.',
            is_published=True
        )
        PortfolioWorkPhoto.objects.create(
            work=self.work,
            photo_url='https://cdn.exshare.ai/photo1.jpg',
            order=1
        )

    def test_public_tenant_portfolio_view_contract(self):
        res = self.client.get('/api/public/portfolio-site/', HTTP_HOST='mridhul.exshare.ai')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        # Check all camelCase contract fields
        self.assertEqual(data['templateId'], 'editorial-vogue')
        self.assertEqual(data['studioName'], 'Mridhul Photography Studio')
        self.assertEqual(data['artistName'], 'Mridhul Nair')
        self.assertEqual(data['tagline'], 'Luxury Weddings & Editorial')
        self.assertEqual(data['subdomain'], 'mridhul')
        self.assertEqual(data['accentColor'], '#d4af37')
        self.assertEqual(data['pricingStartingAt'], '$3,500')
        self.assertEqual(data['philosophyQuote'], 'Beauty is in the fleeting moments.')

        # Check featuredWorks array
        self.assertIn('featuredWorks', data)
        self.assertEqual(len(data['featuredWorks']), 1)
        work_data = data['featuredWorks'][0]
        self.assertEqual(work_data['title'], 'Royal Udaipur Palace Wedding')
        self.assertEqual(work_data['coverUrl'], 'https://cdn.exshare.ai/cover.jpg')
        self.assertEqual(work_data['mediaCount'], 1)
        self.assertIn('https://cdn.exshare.ai/photo1.jpg', work_data['highlightMedia'])

    def test_public_tenant_inquiry_contract(self):
        payload = {
            'client_name': 'Aarav Sharma',
            'client_email': 'aarav@wedding.in',
            'client_phone': '+91 98765 43210',
            'event_type': 'wedding',
            'event_date': '2026-12-15',
            'location': 'Goa Beach Resort',
            'budget': '$5,000+',
            'message': 'Looking for three days of wedding coverage.'
        }
        res = self.client.post(
            '/api/public/portfolio-site/inquiries/',
            data=payload,
            format='json',
            HTTP_HOST='mridhul.exshare.ai'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertIn('inquiry_id', data)

        inquiry = PortfolioInquiry.objects.get(id=data['inquiry_id'])
        self.assertEqual(inquiry.photographer_id, self.user.id)
        self.assertEqual(inquiry.client_name, 'Aarav Sharma')

    def test_public_tenant_track_view_contract(self):
        payload = {
            'device': 'desktop',
            'page_section': 'hero'
        }
        res = self.client.post(
            '/api/public/portfolio-site/track-view/',
            data=payload,
            format='json',
            HTTP_HOST='mridhul.exshare.ai'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['tracked'])

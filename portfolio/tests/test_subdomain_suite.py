import uuid
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework.test import APITestCase
from rest_framework import status

from portfolio.models import PortfolioConfig, ReservedSubdomain, PortfolioInquiry, PortfolioView
from portfolio.subdomain_service import (
    validate_subdomain_label,
    check_subdomain_availability,
    resolve_portfolio_from_request,
    normalize_subdomain,
)

User = get_user_model()


class SubdomainValidationAndServiceTests(TestCase):
    def setUp(self):
        User.objects.all().delete()
        PortfolioConfig.objects.all().delete()
        ReservedSubdomain.objects.all().delete()

        self.user1 = User.objects.create_user(
            username='photographer1',
            email='p1@exshare.ai',
            password='Password123!'
        )
        self.config1 = PortfolioConfig.objects.create(
            user=self.user1,
            studio_name='Atelier Mridhul',
            subdomain='mridhul',
            is_published=True
        )

    def test_valid_subdomain_labels(self):
        valid_samples = ['mridhul', 'elena-studio', 'studio123', 'a-b-c', 'a1b']
        for sample in valid_samples:
            is_valid, reason = validate_subdomain_label(sample)
            self.assertTrue(is_valid, f"Expected '{sample}' to be valid, got: {reason}")
            self.assertIsNone(reason)

    def test_invalid_subdomain_labels(self):
        invalid_samples = [
            ('ab', 'at least 3 characters'),
            ('a' * 64, 'cannot exceed 63 characters'),
            ('-mridhul', 'cannot begin or end with a hyphen'),
            ('mridhul-', 'cannot begin or end with a hyphen'),
            ('mridhul.photo', 'lowercase letters, numbers, and internal hyphens'),
            ('mridhul_photo', 'lowercase letters, numbers, and internal hyphens'),
            ('mridhul photo', 'lowercase letters, numbers, and internal hyphens'),
            ('mridhul@photo', 'lowercase letters, numbers, and internal hyphens'),
            ('www', 'reserved for platform infrastructure'),
            ('api', 'reserved for platform infrastructure'),
            ('admin', 'reserved for platform infrastructure'),
            ('auth', 'reserved for platform infrastructure'),
            ('staging', 'reserved for platform infrastructure'),
            ('static', 'reserved for platform infrastructure'),
            ('media', 'reserved for platform infrastructure'),
            ('cdn', 'reserved for platform infrastructure'),
        ]
        for sample, expected_err_part in invalid_samples:
            is_valid, reason = validate_subdomain_label(sample)
            self.assertFalse(is_valid, f"Expected '{sample}' to be invalid")
            self.assertIn(expected_err_part, reason)

    def test_availability_check_states(self):
        # 1. Available new name
        res = check_subdomain_availability('vance-studio')
        self.assertTrue(res['available'])
        self.assertIsNone(res['reason'])
        self.assertFalse(res['is_current_owner'])

        # 2. Already taken by user1
        res = check_subdomain_availability('mridhul')
        self.assertFalse(res['available'])
        self.assertEqual(res['reason'], 'already_taken')

        # 3. Checked by current owner (user1)
        res = check_subdomain_availability('mridhul', current_user=self.user1)
        self.assertTrue(res['available'])
        self.assertEqual(res['reason'], 'already_owned')
        self.assertTrue(res['is_current_owner'])

        # 4. Reserved name
        res = check_subdomain_availability('admin')
        self.assertFalse(res['available'])
        self.assertIn('reserved', res['reason'])

        # 5. Invalid format
        res = check_subdomain_availability('hi')
        self.assertFalse(res['available'])
        self.assertIn('at least 3 characters', res['reason'])

    def test_subdomain_retention_on_portfolio_deletion(self):
        """Deleting a portfolio preserves the subdomain in ReservedSubdomain table."""
        self.config1.delete()
        self.assertTrue(
            ReservedSubdomain.objects.filter(name='mridhul').exists()
        )
        # Verify subsequent availability check reports it as reserved/unavailable
        res = check_subdomain_availability('mridhul')
        self.assertFalse(res['available'])
        self.assertIn('reserved', res['reason'])


class SubdomainAPITests(APITestCase):
    def setUp(self):
        User.objects.all().delete()
        PortfolioConfig.objects.all().delete()
        ReservedSubdomain.objects.all().delete()
        PortfolioInquiry.objects.all().delete()

        self.user1 = User.objects.create_user(
            username='mridhul',
            email='mridhul@exshare.ai',
            password='Password123!'
        )
        self.config1 = PortfolioConfig.objects.create(
            user=self.user1,
            studio_name='Mridhul Photography',
            subdomain=None,
            is_published=True
        )

        self.user2 = User.objects.create_user(
            username='elena',
            email='elena@exshare.ai',
            password='Password123!'
        )
        self.config2 = PortfolioConfig.objects.create(
            user=self.user2,
            studio_name='Elena Rostova Studio',
            subdomain='elena',
            is_published=True
        )

    def test_availability_endpoint_success(self):
        self.client.force_authenticate(user=self.user1)
        res = self.client.get('/api/portfolio/subdomain/availability/?name=mridhul')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data['name'], 'mridhul')
        self.assertTrue(data['available'])
        self.assertIsNone(data['reason'])

    def test_availability_endpoint_missing_param(self):
        self.client.force_authenticate(user=self.user1)
        res = self.client.get('/api/portfolio/subdomain/availability/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('MISSING_NAME_PARAMETER', res.json()['code'])

    def test_availability_endpoint_unauthenticated(self):
        res = self.client.get('/api/portfolio/subdomain/availability/?name=mridhul')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_claim_subdomain_success(self):
        self.client.force_authenticate(user=self.user1)
        res = self.client.put('/api/portfolio/subdomain/', data={'subdomain': 'mridhul'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['subdomain'], 'mridhul')
        self.assertEqual(data['domain'], 'mridhul.exshare.ai')
        self.assertEqual(data['url'], 'https://mridhul.exshare.ai')

        self.config1.refresh_from_db()
        self.assertEqual(self.config1.subdomain, 'mridhul')

    def test_claim_subdomain_idempotent_repeat(self):
        # Claim once
        self.client.force_authenticate(user=self.user1)
        self.client.put('/api/portfolio/subdomain/', data={'subdomain': 'mridhul'}, format='json')

        # Claim same again
        res = self.client.put('/api/portfolio/subdomain/', data={'subdomain': 'mridhul'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data['subdomain'], 'mridhul')
        self.assertIn('already assigned', data['message'])

    def test_claim_subdomain_already_taken_conflict(self):
        self.client.force_authenticate(user=self.user1)
        # Attempt to claim 'elena' which is already owned by user2
        res = self.client.put('/api/portfolio/subdomain/', data={'subdomain': 'elena'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.json()['code'], 'SUBDOMAIN_ALREADY_TAKEN')

    def test_claim_subdomain_prohibit_rename_v1(self):
        # user2 already has 'elena'
        self.client.force_authenticate(user=self.user2)
        res = self.client.put('/api/portfolio/subdomain/', data={'subdomain': 'elena-new'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()['code'], 'RENAME_PROHIBITED')

    def test_claim_subdomain_invalid_format(self):
        self.client.force_authenticate(user=self.user1)
        res = self.client.put('/api/portfolio/subdomain/', data={'subdomain': 'bad_name!'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()['code'], 'INVALID_SUBDOMAIN')

    def test_claim_subdomain_reserved_name(self):
        self.client.force_authenticate(user=self.user1)
        res = self.client.put('/api/portfolio/subdomain/', data={'subdomain': 'admin'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()['code'], 'INVALID_SUBDOMAIN')

    def test_claim_subdomain_concurrency_integrity_error(self):
        self.client.force_authenticate(user=self.user1)
        with patch.object(PortfolioConfig, 'save', side_effect=IntegrityError("Duplicate key")):
            res = self.client.put('/api/portfolio/subdomain/', data={'subdomain': 'race-winner'}, format='json')
            self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(res.json()['code'], 'SUBDOMAIN_ALREADY_TAKEN')


class PublicTenantHostRoutingTests(APITestCase):
    def setUp(self):
        User.objects.all().delete()
        PortfolioConfig.objects.all().delete()
        PortfolioInquiry.objects.all().delete()
        PortfolioView.objects.all().delete()

        self.user = User.objects.create_user(
            username='elena',
            email='elena@exshare.ai',
            password='Password123!'
        )
        self.portfolio = PortfolioConfig.objects.create(
            user=self.user,
            studio_name='Elena Rostova Studio',
            artist_name='Elena Rostova',
            subdomain='elena',
            is_published=True
        )

        self.unpublished_user = User.objects.create_user(
            username='draftuser',
            email='draft@exshare.ai',
            password='Password123!'
        )
        self.unpublished_portfolio = PortfolioConfig.objects.create(
            user=self.unpublished_user,
            studio_name='Draft Studio',
            subdomain='draft',
            is_published=False
        )

    def test_public_tenant_site_resolved_from_host(self):
        # Host header simulates visitor opening https://elena.exshare.ai
        res = self.client.get('/api/public/portfolio-site/', HTTP_HOST='elena.exshare.ai')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data['studio_name'], 'Elena Rostova Studio')
        self.assertEqual(data['subdomain'], 'elena')
        self.assertEqual(data['portfolio_url'], 'https://elena.exshare.ai')

    def test_public_tenant_site_unknown_subdomain_404(self):
        res = self.client.get('/api/public/portfolio-site/', HTTP_HOST='unknown.exshare.ai')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_tenant_site_unpublished_portfolio_404(self):
        res = self.client.get('/api/public/portfolio-site/', HTTP_HOST='draft.exshare.ai')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_tenant_site_reserved_host_404(self):
        res = self.client.get('/api/public/portfolio-site/', HTTP_HOST='api.exshare.ai')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_tenant_site_multi_level_subdomain_rejected(self):
        res = self.client.get('/api/public/portfolio-site/', HTTP_HOST='a.b.exshare.ai')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_tenant_inquiry_submission_scoped_to_host(self):
        inquiry_payload = {
            'client_name': 'Sophie Martin',
            'client_email': 'sophie@fashion.paris',
            'client_phone': '+33 6 12 34 56 78',
            'event_type': 'editorial',
            'message': 'We would love to book your studio for Paris Fashion Week runway coverage.'
        }
        res = self.client.post(
            '/api/public/portfolio-site/inquiries/',
            data=inquiry_payload,
            format='json',
            HTTP_HOST='elena.exshare.ai'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.json()['success'])

        # Verify inquiry in DB is strictly scoped to elena's user account
        inquiry = PortfolioInquiry.objects.get(id=res.json()['inquiry_id'])
        self.assertEqual(inquiry.photographer_id, self.user.id)
        self.assertEqual(inquiry.client_name, 'Sophie Martin')

    def test_public_tenant_track_view_scoped_to_host(self):
        track_payload = {
            'page_section': 'hero',
            'device': 'desktop'
        }
        res = self.client.post(
            '/api/public/portfolio-site/track-view/',
            data=track_payload,
            format='json',
            HTTP_HOST='elena.exshare.ai'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.json()['tracked'])

        # Verify telemetry in DB is scoped to elena
        view_event = PortfolioView.objects.get(id=res.json()['view_id'])
        self.assertEqual(view_event.photographer_id, self.user.id)

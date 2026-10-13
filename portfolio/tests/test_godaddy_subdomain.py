"""
Comprehensive Unit & Integration Test Suite for Photographer Portfolio Subdomains
& GoDaddy Automated DNS Integration.
Tests:
- Validation (syntax, length, symbols, dots, spaces, underscores, URLs)
- Reserved platform names (www, api, admin, app, mail, smtp, ftp, ns1, ns2, etc.)
- Authentication & ownership enforcement
- Concurrent claim conflict handling (HTTP 409)
- GoDaddy DNS service (PATCH records, pre-checks, CNAME/A conflict detection, idempotency)
- Async Celery task provisioning & retries
- Status reporting & throttled retry endpoint
- Hostname tenant routing, nested subdomain rejection, and private-content isolation
"""
import uuid
from unittest.mock import patch, MagicMock
from datetime import timedelta
from django.utils import timezone
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APITestCase
from rest_framework import status

from portfolio.models import (
    PortfolioConfig,
    PortfolioWork,
    PortfolioWorkPhoto,
    ReservedSubdomain,
    validate_subdomain,
)
from portfolio.godaddy_service import (
    GoDaddyDNSClient,
    GoDaddyAuthError,
    GoDaddyConflictError,
    GoDaddyRateLimitError,
    GoDaddyServerError,
)
from portfolio.bigrock_service import (
    BigRockDNSClient,
    BigRockAuthError,
    BigRockValidationError,
    BigRockConflictError,
    BigRockRateLimitError,
    BigRockServerError,
)
from portfolio.subdomain_service import (
    validate_subdomain_label,
    normalize_subdomain,
    resolve_portfolio_from_request,
)
from portfolio.tenant_resolver import (
    resolve_tenant_subdomain,
    get_tenant_profile,
)
from portfolio.tasks import provision_subdomain_dns_task

User = get_user_model()


class SubdomainValidationTests(TestCase):
    """Tests syntax, character set, length, and reserved name validation."""

    def test_valid_subdomain_labels(self):
        valid_cases = ['mridhul', 'studio-99', 'atelier-vogue', 'photo123', 'a-b-c']
        for name in valid_cases:
            is_valid, err = validate_subdomain_label(name)
            self.assertTrue(is_valid, f"Expected '{name}' to be valid, got error: {err}")
            # Ensure model validator does not raise
            validate_subdomain(name)

    def test_invalid_length(self):
        # Too short (< 3)
        for short in ['', 'a', 'ab']:
            is_valid, err = validate_subdomain_label(short)
            self.assertFalse(is_valid)
            with self.assertRaises(ValidationError):
                validate_subdomain(short)

        # Too long (> 63)
        long_name = 'a' * 64
        is_valid, err = validate_subdomain_label(long_name)
        self.assertFalse(is_valid)
        with self.assertRaises(ValidationError):
            validate_subdomain(long_name)

    def test_invalid_characters_and_hyphens(self):
        invalid_cases = [
            '-leading',
            'trailing-',
            'has.dots',
            'has_underscores',
            'has spaces',
            'https://mridhul.com',
            'studio@atelier',
            'vogue!',
        ]
        for name in invalid_cases:
            is_valid, err = validate_subdomain_label(name)
            self.assertFalse(is_valid, f"Expected '{name}' to be rejected")
            with self.assertRaises(ValidationError):
                validate_subdomain(name)

    def test_reserved_infrastructure_names(self):
        reserved_list = [
            'www', 'api', 'admin', 'app', 'mail', 'smtp', 'pop', 'imap',
            'ftp', 'ns', 'ns1', 'ns2', 'culling', 'gallery', 'server', 'exshare'
        ]
        for name in reserved_list:
            is_valid, err = validate_subdomain_label(name)
            self.assertFalse(is_valid, f"Expected reserved name '{name}' to be rejected")
            with self.assertRaises(ValidationError):
                validate_subdomain(name)

    def test_dynamic_reserved_table(self):
        ReservedSubdomain.objects.create(name='vip-celebrity', reason='reserved_for_partner')
        is_valid, err = validate_subdomain_label('vip-celebrity')
        self.assertFalse(is_valid)
        with self.assertRaises(ValidationError):
            validate_subdomain('vip-celebrity')


class GoDaddyServiceTests(TestCase):
    """Unit tests for GoDaddy DNS Client and conflict handling."""

    def setUp(self):
        self.client = GoDaddyDNSClient(
            api_key="test_key",
            api_secret="test_secret",
            domain="exshare.ai",
            server_ip="31.97.232.245"
        )

    @patch('requests.Session.request')
    def test_check_subdomain_conflict_when_no_records_exist(self, mock_request):
        # 404 on CNAME and A queries -> no conflict
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_request.return_value = mock_resp

        is_conflict, reason, exact = self.client.check_subdomain_conflict('mridhul')
        self.assertFalse(is_conflict)
        self.assertIsNone(reason)
        self.assertIsNone(exact)

    @patch('requests.Session.request')
    def test_check_subdomain_conflict_with_cname(self, mock_request):
        # Existing CNAME returns 200 with record
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"data": "other.domain.com", "name": "mridhul", "type": "CNAME"}]
        mock_request.return_value = mock_resp

        is_conflict, reason, exact = self.client.check_subdomain_conflict('mridhul')
        self.assertTrue(is_conflict)
        self.assertIn("CNAME", reason)

    @patch('requests.Session.request')
    def test_check_subdomain_conflict_with_external_a_record(self, mock_request):
        def mock_dispatch(method, url, **kwargs):
            resp = MagicMock()
            if '/CNAME/' in url:
                resp.status_code = 404
                return resp
            if '/A/' in url:
                resp.status_code = 200
                resp.json.return_value = [{"data": "1.2.3.4", "name": "mridhul", "type": "A"}]
                return resp
            resp.status_code = 404
            return resp

        mock_request.side_effect = mock_dispatch

        is_conflict, reason, exact = self.client.check_subdomain_conflict('mridhul')
        self.assertTrue(is_conflict)
        self.assertIn("external", reason)

    @patch('requests.Session.request')
    def test_check_subdomain_exact_match_reuses_record(self, mock_request):
        def mock_dispatch(method, url, **kwargs):
            resp = MagicMock()
            if '/CNAME/' in url:
                resp.status_code = 404
                return resp
            if '/A/' in url:
                resp.status_code = 200
                resp.json.return_value = [{"data": "31.97.232.245", "name": "mridhul", "type": "A", "ttl": 600}]
                return resp
            resp.status_code = 404
            return resp

        mock_request.side_effect = mock_dispatch

        is_conflict, reason, exact = self.client.check_subdomain_conflict('mridhul')
        self.assertFalse(is_conflict)
        self.assertEqual(reason, "exact_match")
        self.assertIsNotNone(exact)

    @patch('requests.Session.request')
    def test_provision_a_record_patches_godaddy(self, mock_request):
        def mock_dispatch(method, url, **kwargs):
            resp = MagicMock()
            if method == 'GET':
                resp.status_code = 404
                return resp
            if method == 'PATCH':
                resp.status_code = 200
                return resp
            resp.status_code = 404
            return resp

        mock_request.side_effect = mock_dispatch

        result = self.client.provision_portfolio_a_record('mridhul')
        self.assertEqual(result['action'], 'created')
        self.assertEqual(result['name'], 'mridhul')
        self.assertEqual(result['data'], '31.97.232.245')


class SubdomainAuthenticatedAPITests(APITestCase):
    """Integration tests for availability, claim, status, and retry endpoints."""

    def setUp(self):
        User.objects.all().delete()
        PortfolioConfig.objects.all().delete()

        self.user1 = User.objects.create_user(
            username='photographer1',
            email='p1@exshare.ai',
            password='Password123!'
        )
        self.portfolio1 = PortfolioConfig.objects.create(
            user=self.user1,
            studio_name='Studio One',
            is_published=True
        )

        self.user2 = User.objects.create_user(
            username='photographer2',
            email='p2@exshare.ai',
            password='Password123!'
        )
        self.portfolio2 = PortfolioConfig.objects.create(
            user=self.user2,
            studio_name='Studio Two',
            is_published=True
        )

    def test_availability_requires_authentication(self):
        res = self.client.get('/api/portfolio/subdomain/availability/?name=mridhul')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_availability_checking(self):
        self.client.force_authenticate(user=self.user1)

        # 1. Available name
        res = self.client.get('/api/portfolio/subdomain/availability/?name=mridhul')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['available'])
        self.assertIsNone(res.data['reason'])

        # 2. Reserved name
        res = self.client.get('/api/portfolio/subdomain/availability/?name=api')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data['available'])
        self.assertIn('reserved', res.data['reason'].lower())

        # 3. Already claimed name
        # 3. Already claimed name
        self.portfolio2.subdomain = 'luxury-frames'
        self.portfolio2.subdomain_status = PortfolioConfig.SubdomainStatus.ACTIVE
        self.portfolio2.save()

        res = self.client.get('/api/portfolio/subdomain/availability/?name=luxury-frames')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data['available'])
        self.assertEqual(res.data['reason'], 'already_taken')

    @patch('portfolio.views_subdomain.provision_subdomain_dns_task.delay')
    def test_claim_subdomain_atomically_returns_202(self, mock_delay):
        self.client.force_authenticate(user=self.user1)

        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.put('/api/portfolio/subdomain/', {'subdomain': 'mridhul'})
        
        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(res.data['status'], 'pending')
        self.assertEqual(res.data['subdomain'], 'mridhul')

        # Check DB state
        self.portfolio1.refresh_from_db()
        self.assertEqual(self.portfolio1.subdomain, 'mridhul')
        self.assertEqual(self.portfolio1.subdomain_status, PortfolioConfig.SubdomainStatus.PENDING)

        # Enqueued task
        mock_delay.assert_called_once_with(self.portfolio1.id, 'mridhul')

    def test_concurrent_claim_conflict_returns_409(self):
        # user2 already claimed 'vogue-art'
        self.portfolio2.subdomain = 'vogue-art'
        self.portfolio2.subdomain_status = PortfolioConfig.SubdomainStatus.ACTIVE
        self.portfolio2.save()

        # user1 tries to claim 'vogue-art'
        self.client.force_authenticate(user=self.user1)
        res = self.client.put('/api/portfolio/subdomain/', {'subdomain': 'vogue-art'})
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['code'], 'SUBDOMAIN_ALREADY_TAKEN')

    def test_get_provisioning_status(self):
        self.client.force_authenticate(user=self.user1)

        # Initial: no subdomain
        res = self.client.get('/api/portfolio/subdomain/status/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIsNone(res.data['subdomain'])

        # After claim
        self.portfolio1.subdomain = 'mridhul'
        self.portfolio1.subdomain_status = PortfolioConfig.SubdomainStatus.ACTIVE
        self.portfolio1.subdomain_provisioned_at = timezone.now()
        self.portfolio1.save()

        res = self.client.get('/api/portfolio/subdomain/status/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['subdomain'], 'mridhul')
        self.assertEqual(res.data['status'], 'active')
        self.assertFalse(res.data['retry_allowed'])

    @patch('portfolio.views_subdomain.provision_subdomain_dns_task.delay')
    def test_retry_failed_provisioning_with_throttling(self, mock_delay):
        self.client.force_authenticate(user=self.user1)

        self.portfolio1.subdomain = 'mridhul'
        self.portfolio1.subdomain_status = PortfolioConfig.SubdomainStatus.FAILED
        self.portfolio1.subdomain_error = 'GoDaddy rate limit'
        self.portfolio1.save()

        # 1. First retry succeeds (202)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post('/api/portfolio/subdomain/retry/')
        
        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once()

        self.portfolio1.refresh_from_db()
        self.assertEqual(self.portfolio1.subdomain_status, PortfolioConfig.SubdomainStatus.PENDING)
        self.assertEqual(self.portfolio1.subdomain_retry_count, 1)

        # Set status back to failed for test
        self.portfolio1.subdomain_status = PortfolioConfig.SubdomainStatus.FAILED
        self.portfolio1.save(update_fields=['subdomain_status'])

        # 2. Immediate second retry within 30s -> throttled (429)
        res2 = self.client.post('/api/portfolio/subdomain/retry/')
        self.assertEqual(res2.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(res2.data['code'], 'RETRY_THROTTLED')


class CeleryTaskProvisioningTests(TestCase):
    """Tests for asynchronous Celery task execution."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='celeryuser',
            email='celery@exshare.ai',
            password='Password123!'
        )
        self.portfolio = PortfolioConfig.objects.create(
            user=self.user,
            studio_name='Celery Studio',
            subdomain='celerytest',
            subdomain_status=PortfolioConfig.SubdomainStatus.PENDING,
            is_published=True
        )

    @patch('portfolio.tasks.get_bigrock_client')
    def test_task_provisions_record_and_marks_active(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.server_ip = "31.97.232.245"
        mock_client.check_subdomain_conflict.return_value = (False, None)
        mock_client.provision_portfolio_a_record.return_value = {
            "action": "created",
            "name": "celerytest",
            "data": "31.97.232.245"
        }
        mock_get_client.return_value = mock_client

        res = provision_subdomain_dns_task(self.portfolio.id, 'celerytest')
        self.assertEqual(res['status'], 'active')

        self.portfolio.refresh_from_db()
        self.assertEqual(self.portfolio.subdomain_status, PortfolioConfig.SubdomainStatus.ACTIVE)
        self.assertIsNotNone(self.portfolio.subdomain_provisioned_at)
        self.assertEqual(self.portfolio.subdomain_dns_record_data, '31.97.232.245')
        self.assertEqual(self.portfolio.subdomain_error, '')

    @patch('portfolio.tasks.get_bigrock_client')
    def test_task_handles_auth_error_as_permanent_failure(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.server_ip = "31.97.232.245"
        mock_client.check_subdomain_conflict.side_effect = BigRockAuthError("Invalid API key")
        mock_get_client.return_value = mock_client

        res = provision_subdomain_dns_task(self.portfolio.id, 'celerytest')
        self.assertEqual(res['status'], 'failed')
        self.assertFalse(res['retriable'])

        self.portfolio.refresh_from_db()
        self.assertEqual(self.portfolio.subdomain_status, PortfolioConfig.SubdomainStatus.FAILED)
        self.assertIn("Invalid API key", self.portfolio.subdomain_error)


class BigRockServiceTests(TestCase):
    """Unit tests for BigRock DNS HTTP API Client."""

    def setUp(self):
        self.client = BigRockDNSClient(
            auth_userid="123456",
            api_key="test_api_key",
            domain="exshare.ai",
            server_ip="31.97.232.245"
        )

    @patch('requests.request')
    def test_bigrock_check_conflict_when_no_records_exist(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"recsonpage": 0, "recsindb": 0}
        mock_req.return_value = mock_resp

        is_conflict, reason = self.client.check_subdomain_conflict('mridhul')
        self.assertFalse(is_conflict)
        self.assertIsNone(reason)

    @patch('requests.request')
    def test_bigrock_check_conflict_with_cname(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "1": {"host": "mridhul", "type": "CNAME", "value": "other.domain.com"}
        }
        mock_req.return_value = mock_resp

        is_conflict, reason = self.client.check_subdomain_conflict('mridhul')
        self.assertTrue(is_conflict)
        self.assertIn("CNAME", reason)

    @patch('requests.request')
    def test_bigrock_check_conflict_with_external_a_record(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "1": {"host": "mridhul", "type": "A", "value": "1.2.3.4"}
        }
        mock_req.return_value = mock_resp

        is_conflict, reason = self.client.check_subdomain_conflict('mridhul')
        self.assertTrue(is_conflict)
        self.assertIn("external", reason)

    @patch('requests.request')
    def test_bigrock_exact_match_reuses_record(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "1": {"host": "mridhul", "type": "A", "value": "31.97.232.245"}
        }
        mock_req.return_value = mock_resp

        is_conflict, reason = self.client.check_subdomain_conflict('mridhul')
        self.assertFalse(is_conflict)
        self.assertEqual(reason, "already_configured")

    @patch('requests.request')
    @patch('requests.post')
    def test_bigrock_provision_a_record_success(self, mock_post, mock_req):
        mock_search_resp = MagicMock()
        mock_search_resp.status_code = 200
        mock_search_resp.json.return_value = {"recsonpage": 0}
        mock_req.return_value = mock_search_resp

        mock_add_resp = MagicMock()
        mock_add_resp.status_code = 200
        mock_add_resp.json.return_value = "Success"
        mock_post.return_value = mock_add_resp

        res = self.client.provision_portfolio_a_record('mridhul')
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['action'], 'created')
        self.assertEqual(res['name'], 'mridhul')
        self.assertEqual(res['data'], '31.97.232.245')

    @patch('requests.request')
    def test_bigrock_auth_failure_raises_auth_error(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"status": "ERROR", "message": "Authentication failed"}
        mock_req.return_value = mock_resp

        with self.assertRaises(BigRockAuthError):
            self.client.search_records(host='mridhul')


class HostnameRoutingAndIsolationTests(TestCase):
    """Tests for Host resolution, nested subdomain rejection, and private-content isolation."""

    def setUp(self):
        self.factory = RequestFactory()
        User.objects.all().delete()
        PortfolioConfig.objects.all().delete()

        self.user = User.objects.create_user(
            username='hostuser',
            email='host@exshare.ai',
            password='Password123!'
        )
        self.portfolio = PortfolioConfig.objects.create(
            user=self.user,
            studio_name='Host Studio',
            subdomain='hoststudio',
            subdomain_status=PortfolioConfig.SubdomainStatus.ACTIVE,
            is_published=True
        )

        # Published project
        self.pub_work = PortfolioWork.objects.create(
            portfolio=self.portfolio,
            title='Published Wedding',
            is_published=True
        )
        PortfolioWorkPhoto.objects.create(
            work=self.pub_work,
            photo_url='https://example.com/photo1.jpg',
            caption='Photo 1'
        )

        # Unpublished / draft project
        self.draft_work = PortfolioWork.objects.create(
            portfolio=self.portfolio,
            title='Draft Private Project',
            is_published=False
        )
        PortfolioWorkPhoto.objects.create(
            work=self.draft_work,
            photo_url='https://example.com/private.jpg',
            caption='Private Photo'
        )

    def test_resolve_tenant_from_host(self):
        req = self.factory.get('/', HTTP_HOST='hoststudio.exshare.ai')
        sub = resolve_tenant_subdomain(req)
        self.assertEqual(sub, 'hoststudio')

        tenant = get_tenant_profile(req)
        self.assertIsNotNone(tenant)
        self.assertEqual(tenant.id, self.portfolio.id)

    def test_reject_nested_subdomain(self):
        # Multi-level subdomain e.g. foo.hoststudio.exshare.ai
        req = self.factory.get('/', HTTP_HOST='foo.hoststudio.exshare.ai')
        sub = resolve_tenant_subdomain(req)
        self.assertIsNone(sub)

        tenant = get_tenant_profile(req)
        self.assertIsNone(tenant)

    def test_reject_unpublished_portfolio(self):
        self.portfolio.is_published = False
        self.portfolio.save()

        req = self.factory.get('/', HTTP_HOST='hoststudio.exshare.ai')
        tenant = get_tenant_profile(req)
        self.assertIsNone(tenant)

    def test_reject_non_active_subdomain(self):
        self.portfolio.subdomain_status = PortfolioConfig.SubdomainStatus.PENDING
        self.portfolio.save()

        req = self.factory.get('/', HTTP_HOST='hoststudio.exshare.ai')
        tenant = get_tenant_profile(req)
        self.assertIsNone(tenant)

    def test_private_content_isolation(self):
        from portfolio.views_public_tenant import PublicTenantPortfolioView
        view = PublicTenantPortfolioView.as_view()

        req = self.factory.get('/api/public/portfolio-site/', HTTP_HOST='hoststudio.exshare.ai')
        res = view(req)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        works = res.data['featuredWorks']
        titles = [w['title'] for w in works]
        self.assertIn('Published Wedding', titles)
        # Verify draft / private work is completely excluded!
        self.assertNotIn('Draft Private Project', titles)

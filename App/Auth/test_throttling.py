from django.test import TestCase
from django.core.cache import cache
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.settings import api_settings

User = get_user_model()


class ThrottlingTestSuite(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.orig_rates = dict(api_settings.DEFAULT_THROTTLE_RATES)
        # Apply strict test-level rates
        api_settings.DEFAULT_THROTTLE_RATES['login'] = '3/minute'
        api_settings.DEFAULT_THROTTLE_RATES['availability_check'] = '5/minute'
        api_settings.DEFAULT_THROTTLE_RATES['otp_send'] = '3/minute'
        api_settings.DEFAULT_THROTTLE_RATES['password_verify'] = '3/minute'
        api_settings.DEFAULT_THROTTLE_RATES['inquiry_submit'] = '3/minute'
        api_settings.DEFAULT_THROTTLE_RATES['view_track'] = '4/minute'

    def tearDown(self):
        cache.clear()
        api_settings.DEFAULT_THROTTLE_RATES = self.orig_rates

    def test_login_endpoint_throttled_after_limit_exceeded(self):
        """
        Verify that hitting the login endpoint repeatedly with the same identifier and IP
        is throttled to HTTP 429 once the configured rate limit (3/min) is reached.
        """
        url = '/api/auth/login/'
        payload = {'identifier': 'bruteforce_target', 'password': 'wrongpassword'}

        for i in range(3):
            response = self.client.post(url, payload, format='json')
            self.assertNotEqual(
                response.status_code,
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Attempt {i+1} should not be throttled yet"
            )

        # 4th attempt should be blocked with HTTP 429
        response = self.client.post(url, payload, format='json')
        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "4th login attempt must be throttled with HTTP 429"
        )
        self.assertIn('detail', response.data)
        self.assertIn('throttled', response.data['detail'].lower())

    def test_availability_check_throttled_after_limit(self):
        """
        Verify that hitting check-username repeatedly is throttled (5/min).
        """
        url = '/api/auth/check-username/'

        for i in range(5):
            response = self.client.get(url, {'username': 'testuser'})
            self.assertNotEqual(
                response.status_code,
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Attempt {i+1} should pass"
            )

        response = self.client.get(url, {'username': 'testuser'})
        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "6th availability check must return 429 Too Many Requests"
        )

    def test_different_ip_has_independent_throttle_bucket(self):
        """
        Verify that an attacker from IP 1.2.3.4 getting throttled does not lock out
        a legitimate user connecting from IP 5.6.7.8.
        """
        url = '/api/auth/check-username/'

        # Consume quota on attacker IP (5 requests)
        for _ in range(5):
            self.client.get(url, {'username': 'victim'}, REMOTE_ADDR='198.51.100.1')

        # Attacker should now be blocked
        blocked_resp = self.client.get(url, {'username': 'victim'}, REMOTE_ADDR='198.51.100.1')
        self.assertEqual(blocked_resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # Different IP should succeed
        clean_resp = self.client.get(url, {'username': 'victim'}, REMOTE_ADDR='203.0.113.99')
        self.assertEqual(clean_resp.status_code, status.HTTP_200_OK)

    def test_otp_resend_endpoint_throttled(self):
        """
        Verify that attempting to spam OTP generation is throttled to prevent SMS/email bombing.
        """
        url = '/api/auth/resend-otp/'
        payload = {'email': 'victim@example.com'}

        for i in range(3):
            response = self.client.post(url, payload, format='json')
            self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # 4th request must be throttled
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_password_verify_endpoint_throttled(self):
        """
        Verify that attempting to brute-force a shared gallery password is throttled.
        """
        url = '/api/shared-galleries/dummy-share-token/verify-password/'
        payload = {'password': 'guess123'}

        for i in range(3):
            response = self.client.post(url, payload, format='json')
            self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_inquiry_submit_throttled(self):
        """
        Verify that spamming client inquiries from public portfolio is throttled (3/min).
        """
        url = '/api/public/inquiries/'
        payload = {
            'client_name': 'Bot Spammer',
            'client_email': 'spammer@example.com',
            'message': 'Spam message'
        }

        for i in range(3):
            response = self.client.post(url, payload, format='json')
            self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

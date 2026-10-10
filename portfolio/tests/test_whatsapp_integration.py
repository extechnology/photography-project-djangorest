from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse

from portfolio.models import PortfolioConfig

User = get_user_model()


class PortfolioWhatsAppIntegrationTests(APITestCase):
    def setUp(self):
        User.objects.all().delete()
        PortfolioConfig.objects.all().delete()

        self.user = User.objects.create_user(
            username='mridhul',
            email='mridhul@exshare.ai',
            password='Password123!'
        )
        self.config = PortfolioConfig.objects.create(
            user=self.user,
            studio_name='Mridhul Photography Studio',
            artist_name='Mridhul Nair',
            subdomain='mridhul',
            contact_phone='+919876543210',
            is_published=True
        )

    def test_update_portfolio_whatsapp_settings(self):
        self.client.force_authenticate(user=self.user)
        url = reverse('portfolio-config')
        payload = {
            'whatsapp_enabled': True,
            'whatsapp_number': '+919876543210',
            'whatsapp_prefill_message': 'Hello studio, I need wedding coverage for Dec 2026.',
            'whatsapp_button_label': 'Inquire on WhatsApp',
        }

        response = self.client.patch(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['whatsapp_enabled'])
        self.assertEqual(response.data['whatsapp_number'], '+919876543210')
        self.assertEqual(response.data['whatsapp_button_label'], 'Inquire on WhatsApp')
        self.assertEqual(response.data['clean_whatsapp_number'], '919876543210')
        self.assertEqual(response.data['cleanWhatsappNumber'], '919876543210')

        self.config.refresh_from_db()
        self.assertTrue(self.config.whatsapp_enabled)
        self.assertEqual(self.config.whatsapp_number, '+919876543210')
        self.assertEqual(self.config.get_clean_whatsapp_number(), '919876543210')

    def test_update_portfolio_whatsapp_camel_case(self):
        self.client.force_authenticate(user=self.user)
        url = reverse('portfolio-config')
        payload = {
            'whatsappEnabled': False,
            'whatsappNumber': '+1 (555) 123-4567',
            'whatsappPrefillMessage': 'Hi! I would like to inquire about a portrait session.',
            'whatsappButtonLabel': 'Chat with us',
        }

        response = self.client.patch(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['whatsappEnabled'])
        self.assertEqual(response.data['whatsappNumber'], '+15551234567')
        self.assertEqual(response.data['whatsappButtonLabel'], 'Chat with us')
        self.assertEqual(response.data['cleanWhatsappNumber'], '15551234567')

        self.config.refresh_from_db()
        self.assertFalse(self.config.whatsapp_enabled)
        self.assertEqual(self.config.whatsapp_number, '+15551234567')

    def test_public_portfolio_returns_whatsapp_config(self):
        self.config.whatsapp_enabled = True
        self.config.whatsapp_number = '+919876543210'
        self.config.whatsapp_prefill_message = 'Custom prefill message'
        self.config.whatsapp_button_label = 'Message Studio'
        self.config.save()

        url = reverse('public-portfolio', kwargs={'slug': self.user.username})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertIn('whatsapp_enabled', response.data)
        self.assertIn('whatsappEnabled', response.data)
        self.assertTrue(response.data['whatsapp_enabled'])
        self.assertEqual(response.data['whatsapp_number'], '+919876543210')
        self.assertEqual(response.data['whatsapp_button_label'], 'Message Studio')
        self.assertEqual(response.data['clean_whatsapp_number'], '919876543210')

    def test_public_tenant_returns_whatsapp_config(self):
        self.config.whatsapp_enabled = True
        self.config.whatsapp_number = '+919876543210'
        self.config.save()

        response = self.client.get('/api/public/portfolio-site/', HTTP_HOST='mridhul.exshare.ai')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['whatsappEnabled'])
        self.assertEqual(response.data['whatsappNumber'], '+919876543210')
        self.assertEqual(response.data['cleanWhatsappNumber'], '919876543210')

    def test_whatsapp_number_validation_invalid_length(self):
        self.client.force_authenticate(user=self.user)
        url = reverse('portfolio-config')

        # Too short (< 7 digits)
        res_short = self.client.patch(url, {'whatsapp_number': '+1234'}, format='json')
        self.assertEqual(res_short.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('whatsapp_number', res_short.data)

        # Too long (> 15 digits)
        res_long = self.client.patch(url, {'whatsapp_number': '+123456789012345678'}, format='json')
        self.assertEqual(res_long.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('whatsapp_number', res_long.data)

    def test_fallback_to_contact_phone_when_whatsapp_number_empty(self):
        # whatsapp_number is empty, but contact_phone is set
        self.config.whatsapp_number = ''
        self.config.contact_phone = '+919876543210'
        self.config.save()

        self.client.force_authenticate(user=self.user)
        url = reverse('portfolio-config')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['whatsapp_number'], '+919876543210')
        self.assertEqual(response.data['whatsappNumber'], '+919876543210')

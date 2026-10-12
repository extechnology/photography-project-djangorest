import uuid
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from App.Photographers.photo_models import PhotographerProfile
from App.Storage.storage_models import Gallery
from inquiries.models import Inquiry

User = get_user_model()


class ClientGalleryInquiryTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create photographer user and profile
        self.photographer_user = User.objects.create_user(
            username='lensmaster',
            email='photographer@exshare.ai',
            password='Password123!',
            role='photographer'
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.photographer_user,
            studio_name='Lensmaster Atelier',
            name='Lens Master'
        )

        # Create public gallery owned by photographer
        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Royal Tuscan Wedding',
            slug='royal-tuscan-wedding',
            template_id='cinematic',
            status='active',
            visibility='public'
        )

    def test_submit_inquiry_with_gallery_id(self):
        """
        Submitting inquiry with gallery_id automatically attributes to gallery photographer,
        populates gallery_title, source, and defaults status to 'new'.
        """
        payload = {
            'gallery_id': str(self.gallery.id),
            'client_name': 'Eleanor Vance',
            'client_email': 'eleanor@example.com',
            'client_phone': '+1 555-0199',
            'event_type': 'wedding',
            'event_date': '2026-11-20',
            'location': 'Florence, Italy',
            'budget': '$8,000',
            'message': 'We fell in love with your cinematic gallery coverage!'
        }

        response = self.client.post('/api/public/inquiries/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data.get('success'))
        self.assertIn('inquiry_id', response.data)

        inquiry = Inquiry.objects.get(id=response.data['inquiry_id'])
        self.assertEqual(inquiry.photographer, self.photographer_user)
        self.assertEqual(inquiry.gallery, self.gallery)
        self.assertEqual(inquiry.gallery_title, 'Royal Tuscan Wedding')
        self.assertEqual(inquiry.source, 'gallery:cinematic')
        self.assertEqual(inquiry.client_name, 'Eleanor Vance')
        self.assertEqual(inquiry.status, 'new')

    def test_submit_inquiry_with_gallery_slug(self):
        """
        Submitting inquiry with gallery_slug automatically attributes to gallery owner.
        """
        payload = {
            'gallery_slug': 'royal-tuscan-wedding',
            'client_name': 'Julian Thorne',
            'client_email': 'julian@example.com',
            'client_phone': '+44 7700 900077',
            'event_type': 'editorial',
            'location': 'London, UK',
            'budget': '£5,000',
            'message': 'Interested in commercial fashion editorial coverage.',
            'source': 'gallery:editorial'
        }

        response = self.client.post('/api/public/inquiries/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        inquiry_id = response.data['inquiry_id']

        inquiry = Inquiry.objects.get(id=inquiry_id)
        self.assertEqual(inquiry.photographer, self.photographer_user)
        self.assertEqual(inquiry.gallery, self.gallery)
        self.assertEqual(inquiry.source, 'gallery:editorial')

    def test_submit_inquiry_with_photographer_id(self):
        """
        Submitting inquiry with explicit photographer_id attributes directly to photographer.
        """
        payload = {
            'photographer_id': self.photographer_user.id,
            'client_name': 'Sophia Laurent',
            'client_email': 'sophia@example.com',
            'event_type': 'portrait',
            'message': 'Bespoke portrait session inquiry.',
            'source': 'portfolio'
        }

        response = self.client.post('/api/public/inquiries/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        inquiry = Inquiry.objects.get(id=response.data['inquiry_id'])
        self.assertEqual(inquiry.photographer, self.photographer_user)
        self.assertIsNone(inquiry.gallery)
        self.assertEqual(inquiry.source, 'portfolio')

    def test_validation_error_when_no_photographer_or_gallery(self):
        """
        Fails validation when neither photographer_id nor gallery_id nor gallery_slug is supplied.
        """
        payload = {
            'client_name': 'Ghost User',
            'client_email': 'ghost@example.com',
            'message': 'Who gets this?'
        }

        response = self.client.post('/api/public/inquiries/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_authenticated_photographer_dashboard_list(self):
        """
        GET /api/inquiries/ returns inquiries belonging to authenticated photographer,
        formatted with total_inquiries, accessible_inquiries, and camelCase serializer attributes.
        """
        # Create 2 inquiries for this photographer
        Inquiry.objects.create(
            photographer=self.photographer_user,
            gallery=self.gallery,
            gallery_title=self.gallery.title,
            source='gallery:cinematic',
            client_name='Alice Smith',
            client_email='alice@test.com',
            event_type='wedding',
            message='First test lead',
            status='new'
        )
        Inquiry.objects.create(
            photographer=self.photographer_user,
            source='portfolio',
            client_name='Bob Jones',
            client_email='bob@test.com',
            event_type='portrait',
            message='Second test lead',
            status='contacted'
        )

        # Another photographer's lead
        other_user = User.objects.create_user(username='other', email='other@test.com', password='pw')
        Inquiry.objects.create(
            photographer=other_user,
            client_name='Stranger',
            client_email='stranger@test.com',
            message='Should not appear'
        )

        # Authenticate as photographer
        self.client.force_authenticate(user=self.photographer_user)

        response = self.client.get('/api/inquiries/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_inquiries'], 2)
        self.assertEqual(response.data['accessible_inquiries'], 2)
        self.assertTrue(response.data['has_full_inquiry_access'])

        inquiries = response.data['inquiries']
        self.assertEqual(len(inquiries), 2)

        # Verify camelCase & snake_case fields are present
        first = inquiries[0]
        self.assertIn('clientName', first)
        self.assertIn('clientEmail', first)
        self.assertIn('eventType', first)
        self.assertIn('createdAt', first)
        self.assertIn('galleryTitle', first)

    def test_inquiry_status_update_and_notes(self):
        """
        PATCH /api/inquiries/<id>/ updates workflow status and notes.
        """
        inquiry = Inquiry.objects.create(
            photographer=self.photographer_user,
            client_name='Claire Redfield',
            client_email='claire@test.com',
            message='Inquiry to update',
            status='new'
        )

        self.client.force_authenticate(user=self.photographer_user)
        patch_payload = {
            'status': 'contacted',
            'notes': 'Sent pricing guide via email.'
        }
        response = self.client.patch(f'/api/inquiries/{inquiry.id}/', patch_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        inquiry.refresh_from_db()
        self.assertEqual(inquiry.status, 'contacted')
        self.assertEqual(inquiry.notes, 'Sent pricing guide via email.')

    def test_inquiry_analytics(self):
        """
        GET /api/inquiries/analytics/ returns correct aggregated pipeline metrics.
        """
        Inquiry.objects.create(
            photographer=self.photographer_user,
            client_name='Lead 1',
            client_email='l1@test.com',
            event_type='wedding',
            status='new',
            message='msg'
        )
        Inquiry.objects.create(
            photographer=self.photographer_user,
            client_name='Lead 2',
            client_email='l2@test.com',
            event_type='wedding',
            status='booked',
            message='msg'
        )

        self.client.force_authenticate(user=self.photographer_user)
        response = self.client.get('/api/inquiries/analytics/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_inquiries'], 2)
        self.assertEqual(response.data['new'], 1)
        self.assertEqual(response.data['booked'], 1)
        self.assertEqual(response.data['conversion_rate'], 50.0)

import io
import os
from PIL import Image
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from subscriptions.models import SubscriptionPlan, CurrentSubscription
from galleries.models import Gallery
from App.Photographers.photo_models import PhotographerProfile
from utils.watermark import stamp_watermark_on_image

User = get_user_model()


class GalleryWatermarkTests(APITestCase):
    def setUp(self):
        # Clear users for test isolation
        User.objects.all().delete()
        PhotographerProfile.objects.all().delete()
        SubscriptionPlan.objects.all().delete()

        self.user = User.objects.create_user(username='photographer1', email='test@exshare.ai', password='password123')
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name='Elena Rostova',
            studio_name='Elena Rostova Studio',
            watermark_text='© ELENA ROSTOVA STUDIO',
            watermark_opacity=0.5,
            watermark_position='bottom-right'
        )

        # Plan without watermark
        self.free_plan = SubscriptionPlan.objects.create(
            id='plan-free',
            name='Free Tier',
            tier='standard',
            billing_cycle='monthly',
            watermark_enabled=False
        )

        # Plan with watermark
        self.pro_plan = SubscriptionPlan.objects.create(
            id='plan-standard-1y',
            name='Standard Annual',
            tier='standard',
            billing_cycle='annual',
            watermark_enabled=True
        )

    def test_cannot_enable_watermark_without_entitlement(self):
        # Assign free plan
        CurrentSubscription.objects.create(user=self.user, photographer=self.profile, plan=self.free_plan, status='active')
        self.client.force_authenticate(user=self.user)

        res = self.client.post('/api/galleries/', {
            'title': 'Restricted Shoot',
            'watermark_enabled': True
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data.get('error_code'), 'WATERMARK_LOCKED')
        self.assertTrue(res.data.get('upgrade_required'))

    def test_can_enable_watermark_with_entitled_plan(self):
        # Assign pro plan
        CurrentSubscription.objects.create(user=self.user, photographer=self.profile, plan=self.pro_plan, status='active')
        self.client.force_authenticate(user=self.user)

        res = self.client.post('/api/galleries/', {
            'title': 'Entitled Shoot',
            'watermark_enabled': True
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data.get('watermark_enabled'))

    def test_cannot_patch_gallery_watermark_without_entitlement(self):
        # Start with free plan and watermark disabled
        CurrentSubscription.objects.create(user=self.user, photographer=self.profile, plan=self.free_plan, status='active')
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Existing Shoot',
            watermark_enabled=False
        )
        self.client.force_authenticate(user=self.user)

        res = self.client.patch(f'/api/galleries/{gallery.id}/', {
            'watermark_enabled': True
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data.get('error_code'), 'WATERMARK_LOCKED')

    def test_can_patch_gallery_watermark_with_entitled_plan(self):
        CurrentSubscription.objects.create(user=self.user, photographer=self.profile, plan=self.pro_plan, status='active')
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Existing Shoot',
            watermark_enabled=False
        )
        self.client.force_authenticate(user=self.user)

        res = self.client.patch(f'/api/galleries/{gallery.id}/', {
            'watermark_enabled': True,
            'watermark_text': '© CUSTOM OVERRIDE'
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data.get('watermark_enabled'))
        self.assertEqual(res.data.get('watermark_text'), '© CUSTOM OVERRIDE')

    def test_public_gallery_watermark_resolution(self):
        CurrentSubscription.objects.create(user=self.user, photographer=self.profile, plan=self.pro_plan, status='active')
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Public Showcase',
            slug='public-showcase-test',
            watermark_enabled=True,
            watermark_text='© ELENA ROSTOVA STUDIO'
        )

        res = self.client.get(f'/api/public/galleries/{gallery.slug}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data.get('watermark_enabled'))
        self.assertEqual(res.data.get('watermark_text'), '© ELENA ROSTOVA STUDIO')
        self.assertEqual(res.data.get('watermark_position'), 'bottom-right')
        self.assertEqual(res.data.get('watermark_opacity'), 0.5)

    def test_photographer_watermark_settings_endpoint(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            'enable_watermark': True,
            'watermark_text': '© STUDIO BRAND',
            'watermark_opacity': 0.65,
            'watermark_position': 'bottom-right'
        }
        res = self.client.patch('/api/photographers/profiles/me/watermark/', payload)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('data', res.data)
        data = res.data['data']
        self.assertEqual(data.get('watermark_text'), '© STUDIO BRAND')
        self.assertEqual(data.get('watermark_opacity'), 0.65)

    def test_pillow_watermark_stamping(self):
        # Generate dummy 400x300 image
        base_img = Image.new('RGB', (400, 300), color=(180, 200, 220))
        img_buffer = io.BytesIO()
        base_img.save(img_buffer, format='JPEG')
        img_buffer.seek(0)

        out_stream = stamp_watermark_on_image(
            img_buffer,
            watermark_text='TEST STUDIO',
            opacity=0.5,
            position='bottom-right'
        )
        self.assertIsInstance(out_stream, io.BytesIO)
        out_stream.seek(0)
        stamped_img = Image.open(out_stream)
        self.assertEqual(stamped_img.size, (400, 300))
        self.assertEqual(stamped_img.format, 'JPEG')

    def test_plans_catalog_includes_watermark_enabled(self):
        res = self.client.get('/api/plans/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        plans = res.data
        self.assertTrue(len(plans) > 0)
        for p in plans:
            self.assertIn('watermark_enabled', p)

    def test_watermark_strictly_defaults_to_photographer_name(self):
        user = User.objects.create_user(username='sarah_j', email='sarah@example.com', password='password123')
        user.fullname = 'Sarah Jenkins'
        user.save()

        profile = PhotographerProfile.objects.create(
            user=user,
            name='Sarah Jenkins',
            studio_name='Jenkins Visuals',
            watermark_text='',
        )
        # Verify save populated photographer name
        self.assertEqual(profile.watermark_text, '© Sarah Jenkins')
        self.assertEqual(profile.get_effective_watermark_text(), '© Sarah Jenkins')

        # When legacy placeholder is saved, get_effective_watermark_text still cleans it
        profile.watermark_text = '© Ex Studio'
        self.assertEqual(profile.get_effective_watermark_text(), '© Sarah Jenkins')

    def test_public_gallery_watermark_uses_photographer_name(self):
        user = User.objects.create_user(username='michael_c', email='mc@example.com', password='password123')
        user.fullname = 'Michael Chang'
        user.save()

        profile = PhotographerProfile.objects.create(
            user=user,
            name='Michael Chang',
            studio_name='Chang Studio',
            watermark_text='',
        )
        CurrentSubscription.objects.create(user=user, photographer=profile, plan=self.pro_plan, status='active')

        gallery = Gallery.objects.create(
            photographer=profile,
            title='Michael Showcase',
            slug='michael-showcase',
            watermark_enabled=True,
            watermark_text='',
        )

        res = self.client.get(f'/api/public/galleries/{gallery.slug}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data.get('watermark_enabled'))
        self.assertEqual(res.data.get('watermark_text'), '© Michael Chang')
        self.assertEqual(res.data.get('photographer_name'), 'Michael Chang')
        self.assertNotIn('Ex Studio', res.data.get('watermark_text', ''))
        self.assertNotIn('ATELIER', res.data.get('watermark_text', ''))

    def test_media_cors_headers_on_options_and_get(self):
        import tempfile
        from django.conf import settings
        # Create a temporary file in media root
        media_test_path = os.path.join(settings.MEDIA_ROOT, 'cors_test.jpg')
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        with open(media_test_path, 'wb') as f:
            f.write(b'dummy-image-bytes')

        try:
            # Test OPTIONS request
            res_opt = self.client.options('/media/cors_test.jpg')
            self.assertEqual(res_opt.status_code, status.HTTP_200_OK)
            self.assertEqual(res_opt['Access-Control-Allow-Origin'], '*')
            self.assertIn('GET', res_opt['Access-Control-Allow-Methods'])

            # Test GET request
            res_get = self.client.get('/media/cors_test.jpg')
            self.assertEqual(res_get.status_code, status.HTTP_200_OK)
            self.assertEqual(res_get['Access-Control-Allow-Origin'], '*')
            if hasattr(res_get, 'close'):
                res_get.close()
        finally:
            try:
                if os.path.exists(media_test_path):
                    os.remove(media_test_path)
            except Exception:
                pass

    def test_zip_download_stamps_watermark(self):
        from galleries.models import Media as GalleryMedia
        from django.core.files.uploadedfile import SimpleUploadedFile
        import zipfile

        CurrentSubscription.objects.create(user=self.user, photographer=self.profile, plan=self.pro_plan, status='active')
        gallery = Gallery.objects.create(
            photographer=self.profile,
            title='Stamped Zip Gallery',
            slug='stamped-zip-gallery',
            watermark_enabled=True,
            watermark_text='© Elena Rostova',
        )

        # Create dummy photo in gallery
        base_img = Image.new('RGB', (200, 200), color=(100, 150, 200))
        buf = io.BytesIO()
        base_img.save(buf, format='JPEG')
        raw_bytes = buf.getvalue()

        media = GalleryMedia.objects.create(
            photographer=self.profile,
            gallery=gallery,
            file=SimpleUploadedFile('test_photo.jpg', raw_bytes, content_type='image/jpeg'),
            original_filename='test_photo.jpg',
            media_type='photo',
        )

        res = self.client.get(f'/api/public/galleries/{gallery.slug}/download-zip/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'application/zip')

        # Read zip contents and inspect image
        zip_buf = io.BytesIO(res.content)
        with zipfile.ZipFile(zip_buf, 'r') as z:
            names = z.namelist()
            matching_files = [n for n in names if 'test_photo.jpg' in n]
            self.assertTrue(len(matching_files) > 0)
            photo_data = z.read(matching_files[0])
            stamped_im = Image.open(io.BytesIO(photo_data))
            self.assertEqual(stamped_im.size, (200, 200))


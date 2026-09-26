import uuid
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from django.core.cache import cache

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import SubscriptionPlans
from App.Storage.storage_models import Gallery, GallerySection, Media, GalleryAnalyticsEvent


class GalleryAtelierBalancedApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

        self.plan = SubscriptionPlans.objects.create(
            name="Studio Pro Plan",
            price=49.00,
            storage_limit_bytes=50 * 1024 * 1024 * 1024,
            max_galleries=20,
            face_search_enabled=True,
            allowed_templates=["editorial", "masonry", "cinematic", "slideshow", "minimal"]
        )

        self.user = User.objects.create_user(
            username="atelier_photographer",
            email="atelier@studio.com",
            password="securepassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            plan=self.plan,
            name="Atelier Master",
            studio_name="Ex Share Atelier"
        )
        self.client.force_authenticate(user=self.user)

        # Create a test gallery
        self.gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Venice Editorial Session",
            client_name="Lady Victoria",
            client_email="victoria@palace.com",
            client_phone="+14155552671",
            template_id="editorial",
            status="active",
            download_pin="8492",
            sections=["HIGHLIGHTS", "CEREMONY"]
        )

        # Create test media
        self.media1 = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            original_filename="venice_grand_canal.jpg",
            storage_key="galleries/test/media1.jpg",
            section_title="HIGHLIGHTS",
            file_size=5 * 1024 * 1024,
            display_order=0
        )
        self.media2 = Media.objects.create(
            photographer=self.profile,
            gallery=self.gallery,
            original_filename="venice_gondola.jpg",
            storage_key="galleries/test/media2.jpg",
            section_title="HIGHLIGHTS",
            file_size=6 * 1024 * 1024,
            display_order=1
        )

    def test_gallery_settings_and_detail(self):
        """Test GET and PATCH on /api/galleries/<id>/ with new fields."""
        response = self.client.get(f'/api/galleries/{self.gallery.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], "Venice Editorial Session")
        self.assertEqual(response.data['download_pin'], "8492")
        self.assertEqual(response.data['client_phone'], "+14155552671")
        self.assertIn("sections", response.data)

        # Patch settings
        patch_res = self.client.patch(f'/api/galleries/{self.gallery.id}/', {
            "client_phone": "+19998887777",
            "download_pin": "1234",
            "status": "delivered",
            "template_id": "masonry"
        })
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_res.data['client_phone'], "+19998887777")
        self.assertEqual(patch_res.data['download_pin'], "1234")
        self.assertEqual(patch_res.data['status'], "delivered")
        self.assertEqual(patch_res.data['template_id'], "masonry")

    def test_section_management_create_list_rename_reorder_delete(self):
        """Test Section endpoints: create, list, rename, reorder, delete."""
        # 1. Create section
        create_res = self.client.post(f'/api/galleries/{self.gallery.id}/sections/', {
            "title": "RECEPTION"
        })
        self.assertEqual(create_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_res.data['title'], "RECEPTION")

        # 2. List sections
        list_res = self.client.get(f'/api/galleries/{self.gallery.id}/sections/')
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        titles = [s['title'] for s in list_res.data]
        self.assertIn("RECEPTION", titles)

        # 3. Rename section with cascade to media
        rename_res = self.client.post(f'/api/galleries/{self.gallery.id}/sections/rename/', {
            "old_title": "HIGHLIGHTS",
            "new_title": "BEST_OF_VENICE"
        })
        self.assertEqual(rename_res.status_code, status.HTTP_200_OK)
        self.assertEqual(rename_res.data['new_title'], "BEST_OF_VENICE")
        self.media1.refresh_from_db()
        self.assertEqual(self.media1.section_title, "BEST_OF_VENICE")

        # 4. Reorder sections
        reorder_res = self.client.post(f'/api/galleries/{self.gallery.id}/sections/reorder/', {
            "sections": ["RECEPTION", "BEST_OF_VENICE"]
        })
        self.assertEqual(reorder_res.status_code, status.HTTP_200_OK)
        self.assertEqual(reorder_res.data['sections'], ["RECEPTION", "BEST_OF_VENICE"])

        # 5. Delete section with safe reassign to UNASSIGNED
        del_res = self.client.delete(f'/api/galleries/{self.gallery.id}/sections/BEST_OF_VENICE/')
        self.assertEqual(del_res.status_code, status.HTTP_200_OK)
        self.assertTrue(del_res.data['success'])
        self.media1.refresh_from_db()
        self.assertEqual(self.media1.section_title, "UNASSIGNED")

    def test_move_media_between_sections(self):
        """Test POST /api/galleries/<id>/media/move-section/."""
        move_res = self.client.post(f'/api/galleries/{self.gallery.id}/media/move-section/', {
            "media_ids": [str(self.media1.id), str(self.media2.id)],
            "target_section": "PORTRAITS"
        })
        self.assertEqual(move_res.status_code, status.HTTP_200_OK)
        self.assertEqual(move_res.data['section'], "PORTRAITS")
        self.assertEqual(move_res.data['updated_count'], 2)

        self.media1.refresh_from_db()
        self.media2.refresh_from_db()
        self.assertEqual(self.media1.section_title, "PORTRAITS")
        self.assertEqual(self.media2.section_title, "PORTRAITS")

    def test_design_and_layout_customization(self):
        """Test template, hero banners, 4-slot masonry, and cover photo endpoints."""
        # 1. Template switcher
        tpl_res = self.client.post(f'/api/galleries/{self.gallery.id}/template/', {
            "template_id": "cinematic"
        })
        self.assertEqual(tpl_res.status_code, status.HTTP_200_OK)
        self.gallery.refresh_from_db()
        self.assertEqual(self.gallery.template_id, "cinematic")

        # 2. Hero banners
        banner_res = self.client.post(f'/api/galleries/{self.gallery.id}/banners/', {
            "template_id": "cinematic",
            "media_url": "https://cdn.atelier.studio/hero/cinematic_banner.jpg"
        })
        self.assertEqual(banner_res.status_code, status.HTTP_200_OK)
        self.gallery.refresh_from_db()
        self.assertEqual(self.gallery.template_banners.get("cinematic"), "https://cdn.atelier.studio/hero/cinematic_banner.jpg")

        # 3. 4-slot Masonry mosaic
        slot_res = self.client.post(f'/api/galleries/{self.gallery.id}/masonry-slots/', {
            "slot_index": 0,
            "media_url": "https://cdn.atelier.studio/mosaic/slot0.jpg"
        })
        self.assertEqual(slot_res.status_code, status.HTTP_200_OK)
        self.gallery.refresh_from_db()
        self.assertEqual(self.gallery.masonry_banner_images[0], "https://cdn.atelier.studio/mosaic/slot0.jpg")

        # 4. Cover photo
        cover_res = self.client.post(f'/api/galleries/{self.gallery.id}/cover/', {
            "media_id": str(self.media1.id),
            "media_url": "https://cdn.atelier.studio/photos/cover.jpg"
        })
        self.assertEqual(cover_res.status_code, status.HTTP_200_OK)
        self.gallery.refresh_from_db()
        self.assertEqual(self.gallery.cover_image, "https://cdn.atelier.studio/photos/cover.jpg")
        self.media1.refresh_from_db()
        self.assertTrue(self.media1.is_cover)

    def test_media_reordering_and_favorites(self):
        """Test bulk reordering and heart favorite toggling."""
        # Reorder sequence
        reorder_res = self.client.post(f'/api/galleries/{self.gallery.id}/media/reorder/', {
            "media_ids": [str(self.media2.id), str(self.media1.id)]
        })
        self.assertEqual(reorder_res.status_code, status.HTTP_200_OK)
        self.media1.refresh_from_db()
        self.media2.refresh_from_db()
        self.assertEqual(self.media2.display_order, 0)
        self.assertEqual(self.media1.display_order, 1)

        # Favorite toggle (client or photographer)
        fav_res = self.client.post(f'/api/galleries/{self.gallery.id}/media/{self.media1.id}/favorite/')
        self.assertEqual(fav_res.status_code, status.HTTP_200_OK)
        self.assertTrue(fav_res.data['is_favorite'])
        self.assertEqual(fav_res.data['favorites_count'], 1)

        self.gallery.refresh_from_db()
        self.assertEqual(self.gallery.favorites_count, 1)

    def test_analytics_tracking_and_intelligence(self):
        """Test telemetry logging, analytics intelligence dashboard, and CSV export."""
        # Log view event
        event_res = self.client.post(f'/api/galleries/{self.gallery.id}/analytics/event/', {
            "event_type": "view",
            "device": "mobile",
            "details": "Client opened gallery on iPhone 15"
        })
        self.assertEqual(event_res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(event_res.data['success'])

        # Log download event
        dl_res = self.client.post(f'/api/galleries/{self.gallery.id}/analytics/event/', {
            "event_type": "download",
            "media_id": str(self.media1.id),
            "device": "desktop",
            "details": "Client downloaded high-res photo"
        })
        self.assertEqual(dl_res.status_code, status.HTTP_201_CREATED)

        # GET analytics intelligence
        analytics_res = self.client.get(f'/api/galleries/{self.gallery.id}/analytics/?time_range=30d')
        self.assertEqual(analytics_res.status_code, status.HTTP_200_OK)
        self.assertIn("total_views", analytics_res.data)
        self.assertIn("timeline", analytics_res.data)
        self.assertIn("devices", analytics_res.data)
        self.assertIn("traffic_sources", analytics_res.data)
        self.assertIn("recent_activity", analytics_res.data)

        # GET analytics CSV export
        csv_res = self.client.get(f'/api/galleries/{self.gallery.id}/analytics/export-csv/')
        self.assertEqual(csv_res.status_code, status.HTTP_200_OK)
        self.assertEqual(csv_res['Content-Type'], 'text/csv')
        self.assertIn(b"EX SHARE ATELIER", csv_res.content)

    def test_share_details_endpoint(self):
        """Test GET /api/galleries/<id>/share-details/."""
        share_res = self.client.get(f'/api/galleries/{self.gallery.id}/share-details/')
        self.assertEqual(share_res.status_code, status.HTTP_200_OK)
        self.assertIn("share_url", share_res.data)
        self.assertEqual(share_res.data['pin_code'], "8492")
        self.assertTrue(share_res.data['allow_downloads'])
        self.assertTrue(share_res.data['allow_favorites'])

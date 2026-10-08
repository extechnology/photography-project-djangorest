import io
from PIL import Image
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from utils.watermark import apply_watermark, hex_to_rgba, stamp_watermark_on_image


def create_test_image(filename="logo.png", size=(100, 100), color=(255, 0, 0, 255), fmt="PNG"):
    buf = io.BytesIO()
    img = Image.new("RGBA", size, color=color)
    img.save(buf, format=fmt)
    buf.seek(0)
    return SimpleUploadedFile(filename, buf.read(), content_type=f"image/{fmt.lower()}")


class StudioWatermarkingSuiteTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="sarah_photographer",
            email="sarah@jenkins.com",
            password="securepassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Sarah Jenkins",
            studio_name="Jenkins Fine Art",
            watermark_text="© Sarah Jenkins",
            watermark_type="text",
            watermark_opacity=0.45,
            watermark_position="bottom-right",
            watermark_font_size="md",
            watermark_font_color="#FFFFFF",
            watermark_font_style="serif",
            enable_watermark=True,
        )
        self.client.force_authenticate(user=self.user)

    def test_get_photographer_profile_me_includes_watermark_suite(self):
        """GET /api/photographers/profiles/me/ returns full watermark fields."""
        res = self.client.get("/api/photographers/profiles/me/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertEqual(data["name"], "Sarah Jenkins")
        self.assertEqual(data["studio_name"], "Jenkins Fine Art")
        self.assertTrue(data["enable_watermark"])
        self.assertEqual(data["watermark_type"], "text")
        self.assertEqual(data["watermark_text"], "© Sarah Jenkins")
        self.assertEqual(data["watermark_opacity"], 0.45)
        self.assertEqual(data["watermark_position"], "bottom-right")
        self.assertEqual(data["watermark_font_size"], "md")
        self.assertEqual(data["watermark_font_color"], "#FFFFFF")
        self.assertEqual(data["watermark_font_style"], "serif")

    def test_get_watermark_settings_endpoint(self):
        """GET /api/photographers/profiles/me/watermark/ returns watermark config."""
        res = self.client.get("/api/photographers/profiles/me/watermark/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["enable_watermark"])
        self.assertEqual(res.data["watermark_type"], "text")
        self.assertEqual(res.data["watermark_text"], "© Sarah Jenkins")
        self.assertEqual(res.data["watermark_font_style"], "serif")

    def test_patch_text_watermark_configuration(self):
        """PATCH /api/photographers/profiles/me/watermark/ updates typography and branding."""
        payload = {
            "enable_watermark": True,
            "watermark_type": "text",
            "watermark_text": "© Sarangsaru44",
            "watermark_opacity": 0.6,
            "watermark_position": "bottom-right",
            "watermark_font_size": "lg",
            "watermark_font_color": "#D4AF37",
            "watermark_font_style": "serif",
        }
        res = self.client.patch("/api/photographers/profiles/me/watermark/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "success")
        self.assertEqual(res.data["message"], "Watermark configuration updated successfully.")

        data = res.data["data"]
        self.assertEqual(data["watermark_text"], "© Sarangsaru44")
        self.assertEqual(data["watermark_opacity"], 0.6)
        self.assertEqual(data["watermark_font_size"], "lg")
        self.assertEqual(data["watermark_font_color"], "#D4AF37")
        self.assertEqual(data["watermark_font_style"], "serif")

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.watermark_text, "© Sarangsaru44")
        self.assertEqual(self.profile.watermark_font_color, "#D4AF37")

    def test_patch_image_logo_upload(self):
        """PATCH /api/photographers/profiles/me/watermark/ uploads custom logo."""
        logo_file = create_test_image("studio_logo.png", size=(120, 80))
        payload = {
            "watermark_type": "image",
            "watermark_opacity": 0.5,
            "watermark_position": "bottom-right",
            "watermark_image": logo_file,
        }
        res = self.client.patch("/api/photographers/profiles/me/watermark/", payload, format="multipart")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "success")

        data = res.data["data"]
        self.assertEqual(data["watermark_type"], "image")
        self.assertEqual(data["watermark_opacity"], 0.5)
        self.assertIsNotNone(data["watermark_image"])
        self.assertIn("studio_logo", data["watermark_image"])

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.watermark_type, "image")
        self.assertTrue(bool(self.profile.watermark_image))

    def test_patch_remove_watermark_image(self):
        """PATCH with remove_watermark_image=True deletes logo from storage."""
        logo_file = create_test_image("temp_logo.png")
        self.profile.watermark_image = logo_file
        self.profile.watermark_type = "image"
        self.profile.save()

        payload = {
            "remove_watermark_image": True,
            "watermark_type": "text",
        }
        res = self.client.patch("/api/photographers/profiles/me/watermark/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertFalse(bool(self.profile.watermark_image))
        self.assertEqual(self.profile.watermark_type, "text")

    def test_opacity_validation_bounds(self):
        """Opacity must be constrained between 0.05 and 1.0."""
        res_low = self.client.patch("/api/photographers/profiles/me/watermark/", {"watermark_opacity": 0.01}, format="json")
        self.assertEqual(res_low.status_code, status.HTTP_400_BAD_REQUEST)

        res_high = self.client.patch("/api/photographers/profiles/me/watermark/", {"watermark_opacity": 1.5}, format="json")
        self.assertEqual(res_high.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logo_file_size_validation(self):
        """Logo files larger than 5MB are rejected."""
        large_bytes = b"0" * (6 * 1024 * 1024)
        large_file = SimpleUploadedFile("big_logo.png", large_bytes, content_type="image/png")
        res = self.client.patch("/api/photographers/profiles/me/watermark/", {"watermark_image": large_file}, format="multipart")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fallback_compatibility_patch_profiles_me(self):
        """PATCH /api/photographers/profiles/me/ also updates watermark suite fields."""
        payload = {
            "watermark_type": "text",
            "watermark_font_style": "script",
            "watermark_font_size": "xl",
            "watermark_font_color": "#18181B",
        }
        res = self.client.patch("/api/photographers/profiles/me/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.watermark_font_style, "script")
        self.assertEqual(self.profile.watermark_font_size, "xl")
        self.assertEqual(self.profile.watermark_font_color, "#18181B")

    def test_hex_to_rgba_helper(self):
        """Validates hex color conversions to RGBA with alpha scaling."""
        white = hex_to_rgba("#FFFFFF", 1.0)
        self.assertEqual(white, (255, 255, 255, 255))

        gold = hex_to_rgba("#D4AF37", 0.5)
        self.assertEqual(gold[0], 212)
        self.assertEqual(gold[1], 175)
        self.assertEqual(gold[2], 55)
        self.assertEqual(gold[3], 127)

    def test_pillow_apply_watermark_text_and_styles(self):
        """Pillow engine stamps text with custom font styles, sizes, and colors."""
        base_img = Image.new("RGB", (600, 400), color=(100, 100, 100))

        # Test each font style preset
        for style in ["serif", "sans", "script", "mono"]:
            self.profile.watermark_font_style = style
            self.profile.watermark_font_size = "lg"
            self.profile.watermark_font_color = "#D4AF37"
            self.profile.watermark_type = "text"
            stamped = apply_watermark(base_img, self.profile)
            self.assertEqual(stamped.size, (600, 400))

        # Test tiled position
        self.profile.watermark_position = "tiled"
        stamped_tiled = apply_watermark(base_img, self.profile)
        self.assertEqual(stamped_tiled.size, (600, 400))

    def test_pillow_apply_watermark_image_logo(self):
        """Pillow engine scales and stamps logo image."""
        base_img = Image.new("RGB", (600, 400), color=(100, 100, 100))
        logo = Image.new("RGBA", (150, 100), color=(255, 255, 255, 200))
        logo_buf = io.BytesIO()
        logo.save(logo_buf, format="PNG")
        logo_buf.seek(0)

        self.profile.watermark_type = "image"
        self.profile.watermark_image = SimpleUploadedFile("brand_logo.png", logo_buf.read(), content_type="image/png")
        self.profile.watermark_position = "center"
        stamped = apply_watermark(base_img, self.profile)
        self.assertEqual(stamped.size, (600, 400))

    def test_watermark_disabled_returns_unmodified_image(self):
        """When enable_watermark=False, image is returned untouched."""
        base_img = Image.new("RGB", (300, 200), color=(50, 50, 50))
        self.profile.enable_watermark = False
        res_img = apply_watermark(base_img, self.profile)
        self.assertEqual(list(base_img.getdata()), list(res_img.getdata()))

    def test_strict_one_at_a_time_text_mode_returns_null_image_even_with_stored_logo(self):
        """When watermark_type is 'text', watermark_image MUST be null even if logo is in DB."""
        logo_file = create_test_image("existing_logo.png")
        self.profile.watermark_image = logo_file
        self.profile.watermark_type = "text"
        self.profile.watermark_font_color = "#D4AF37"
        self.profile.save()

        # 1. Profile watermark endpoint
        res = self.client.get("/api/photographers/profiles/me/watermark/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["watermark_type"], "text")
        self.assertEqual(res.data["watermark_font_color"], "#D4AF37")
        self.assertIsNone(res.data["watermark_image"])
        self.assertIsNone(res.data["watermark_image_url"])

        # 2. Main profile endpoint
        res_me = self.client.get("/api/photographers/profiles/me/")
        self.assertEqual(res_me.status_code, status.HTTP_200_OK)
        self.assertEqual(res_me.data["watermark_type"], "text")
        self.assertEqual(res_me.data["watermark_font_color"], "#D4AF37")
        self.assertIsNone(res_me.data["watermark_image"])

    def test_gallery_endpoints_inherit_watermark_settings_strict_mode(self):
        """Gallery endpoints inherit watermark settings and return null watermark_image in text mode."""
        from App.Storage.storage_models import Gallery
        from subscriptions.models import SubscriptionPlan, CurrentSubscription

        # Grant plan with watermarking
        plan = SubscriptionPlan.objects.create(
            id="plan-pro-test",
            name="Pro Plan",
            tier="standard",
            billing_cycle="annual",
            watermark_enabled=True,
        )
        CurrentSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=plan,
            status="active"
        )

        gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Lucas & Sophia Wedding",
            slug="lucas-sophia",
            watermark_enabled=True,
        )

        # 1. Store a logo in profile
        logo_file = create_test_image("stored_logo.png")
        self.profile.watermark_image = logo_file
        self.profile.watermark_type = "text"
        self.profile.watermark_font_color = "#D4AF37"
        self.profile.watermark_font_style = "serif"
        self.profile.watermark_font_size = "lg"
        self.profile.save()

        # 2. GET /api/galleries/{id}/ in text mode
        res_gal = self.client.get(f"/api/galleries/{gallery.id}/")
        self.assertEqual(res_gal.status_code, status.HTTP_200_OK)
        self.assertEqual(res_gal.data["watermark_type"], "text")
        self.assertEqual(res_gal.data["watermark_font_color"], "#D4AF37")
        self.assertEqual(res_gal.data["watermark_font_size"], "lg")
        self.assertEqual(res_gal.data["watermark_font_style"], "serif")
        self.assertIsNone(res_gal.data["watermark_image"])

        # 3. GET /api/public/galleries/{slug}/ in text mode
        res_pub = self.client.get(f"/api/public/galleries/{gallery.slug}/")
        self.assertEqual(res_pub.status_code, status.HTTP_200_OK)
        self.assertEqual(res_pub.data["watermark_type"], "text")
        self.assertEqual(res_pub.data["watermark_font_color"], "#D4AF37")
        self.assertIsNone(res_pub.data["watermark_image"])

        # 4. Switch to image mode
        patch_res = self.client.patch("/api/photographers/profiles/me/watermark/", {"watermark_type": "image"}, format="json")
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(patch_res.data["data"]["watermark_image"])

        res_gal_img = self.client.get(f"/api/galleries/{gallery.id}/")
        self.assertEqual(res_gal_img.data["watermark_type"], "image")
        self.assertIsNotNone(res_gal_img.data["watermark_image"])

        # 5. Switch back to text mode
        patch_back = self.client.patch("/api/photographers/profiles/me/watermark/", {"watermark_type": "text"}, format="json")
        self.assertEqual(patch_back.status_code, status.HTTP_200_OK)
        self.assertIsNone(patch_back.data["data"]["watermark_image"])

        res_gal_text = self.client.get(f"/api/galleries/{gallery.id}/")
        self.assertEqual(res_gal_text.data["watermark_type"], "text")
        self.assertIsNone(res_gal_text.data["watermark_image"])

    def test_apply_watermark_with_dict_config_and_strict_text_mode(self):
        """apply_watermark accepts a config dict, applies strict text mode, and handles dark font contrast."""
        base_img = Image.new("RGB", (500, 300), color=(120, 120, 120))
        logo_img = Image.new("RGBA", (80, 80), color=(255, 0, 0, 255))

        # Config dict with text mode and an image logo present (logo MUST be ignored)
        cfg_dict = {
            "enable_watermark": True,
            "watermark_type": "text",
            "watermark_text": "© Sarangsaru44",
            "watermark_image": logo_img,
            "watermark_opacity": 0.6,
            "watermark_position": "bottom-right",
            "watermark_font_size": "lg",
            "watermark_font_color": "#D4AF37",
            "watermark_font_style": "serif",
        }
        stamped = apply_watermark(base_img, cfg_dict)
        self.assertEqual(stamped.size, (500, 300))

        # Test script font style
        cfg_script = dict(cfg_dict, watermark_font_style="script", watermark_font_color="#000000")
        stamped_script = apply_watermark(base_img, cfg_script)
        self.assertEqual(stamped_script.size, (500, 300))

import io
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from portfolio.models import (
    PortfolioConfig,
    PortfolioWork,
    PortfolioWorkPhoto,
    PortfolioInquiry
)
from App.Photographers.photo_models import PhotographerProfile

User = get_user_model()


def create_test_image(name="test.jpg", color="blue"):
    file_obj = io.BytesIO()
    img = Image.new("RGB", (200, 200), color=color)
    img.save(file_obj, format="JPEG")
    file_obj.seek(0)
    return SimpleUploadedFile(name, file_obj.read(), content_type="image/jpeg")


class PortfolioLifecycleTests(APITestCase):

    def setUp(self):
        # Create test photographer user
        self.user = User.objects.create_user(
            username="sarang_artist",
            email="sarang@atelier.studio",
            password="testpassword123",
            role="photographer"
        )
        self.user.fullname = "Sarang Varma"
        self.user.phone = "+91 98765 00000"
        self.user.save()

        # Create linked profile
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Sarang Varma",
            studio_name="Sarang Varma Atelier",
            phone="+91 98765 00000",
            location="Udaipur & Worldwide"
        )

        from App.management.commands.seed_plans import Command as SeedPlansCommand
        from App.Subscriptions.sub_models import Plan, PhotographerSubscription
        SeedPlansCommand().handle()
        self.plan_standard_3m = Plan.objects.get(id="plan-standard-3m")
        self.plan_standard_1y = Plan.objects.get(id="plan-standard-1y")
        self.plan_premium_elite = Plan.objects.get(id="plan-premium-elite")
        self.subscription = PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_standard_3m,
            status='active'
        )

    def test_01_get_portfolio_config_auto_seeds_starter_data(self):
        """GET /api/portfolio/config/ auto-creates starter portfolio with genuine details."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/portfolio/config/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["studioName"], "Sarang Varma Atelier")
        self.assertEqual(data["artistName"], "Sarang Varma")
        self.assertEqual(data["templateId"], "darkroom-atelier")
        self.assertEqual(data["contactEmail"], "sarang@atelier.studio")
        self.assertEqual(data["location"], "Udaipur & Worldwide")
        self.assertTrue(data["isBookingOpen"])

        # Check starter featured works
        self.assertIn("featuredWorks", data)
        self.assertEqual(len(data["featuredWorks"]), 3)
        w1 = data["featuredWorks"][0]
        self.assertEqual(w1["title"], "Royal Palace Udaipur Celebration")
        self.assertEqual(w1["category"], "weddings")
        self.assertGreaterEqual(len(w1["highlightMedia"]), 3)

    def test_02_update_portfolio_config_live(self):
        """PATCH /api/portfolio/config/ updates template and branding in-place."""
        self.client.force_authenticate(user=self.user)
        # First ensure seeded
        self.client.get("/api/portfolio/config/")

        patch_data = {
            "templateId": "editorial-vogue",
            "tagline": "Pure Light & Minimal Haute Couture",
            "instagramHandle": "@sarang.atelier",
            "isBookingOpen": False
        }
        patch_res = self.client.patch("/api/portfolio/config/", patch_data, format="json")
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_res.data["templateId"], "editorial-vogue")
        self.assertEqual(patch_res.data["tagline"], "Pure Light & Minimal Haute Couture")
        self.assertEqual(patch_res.data["instagramHandle"], "@sarang.atelier")
        self.assertFalse(patch_res.data["isBookingOpen"])

    def test_03_public_portfolio_detail_access(self):
        """GET /api/public/portfolio/{photographer_slug}/ allows visitor view without auth."""
        res = self.client.get("/api/public/portfolio/sarang_artist/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["studioName"], "Sarang Varma Atelier")
        self.assertIn("featuredWorks", res.data)

        # Non-existent slug returns 404
        res_404 = self.client.get("/api/public/portfolio/unknown_photographer_xyz/")
        self.assertEqual(res_404.status_code, status.HTTP_404_NOT_FOUND)

    def test_04_create_and_delete_project(self):
        """POST /api/portfolio/projects/ creates new project; DELETE removes it."""
        self.client.force_authenticate(user=self.user)
        post_data = {
            "title": "Milan Fashion Week Autumn",
            "category": "editorial",
            "cover_url": "https://images.unsplash.com/photo-1509631179647-0177331693ae?w=1200",
            "location": "Milan, Italy",
            "year": "2026",
            "description": "Runway and backstage captures of avant-garde collections."
        }
        res = self.client.post("/api/portfolio/projects/", post_data, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        work_id = res.data["id"]
        self.assertEqual(res.data["title"], "Milan Fashion Week Autumn")

        # Delete project
        del_res = self.client.delete(f"/api/portfolio/projects/{work_id}/")
        self.assertEqual(del_res.status_code, status.HTTP_200_OK)
        self.assertTrue(del_res.data.get("success"))

    def test_05_add_event_photos_to_project(self):
        """POST /api/portfolio/projects/{work_id}/photos/ uploads event highlight photos."""
        self.client.force_authenticate(user=self.user)
        # Create work first
        post_res = self.client.post("/api/portfolio/projects/", {
            "title": "Jaipur Royal Wedding",
            "category": "weddings"
        }, format="json")
        work_id = post_res.data["id"]

        # 1. Add via JSON URL list
        urls_payload = {
            "photos": [
                "https://images.unsplash.com/photo-1583939003579-730e3918a45a?w=1000",
                "https://images.unsplash.com/photo-1519741497674-611481863552?w=1000"
            ]
        }
        photo_res = self.client.post(f"/api/portfolio/projects/{work_id}/photos/", urls_payload, format="json")
        self.assertEqual(photo_res.status_code, status.HTTP_200_OK)
        self.assertEqual(photo_res.data["media_count"], 2)

        # 2. Add via multipart file upload
        test_file = create_test_image("event_shot.jpg")
        upload_res = self.client.post(
            f"/api/portfolio/projects/{work_id}/photos/",
            {"photos": [test_file]},
            format="multipart"
        )
        self.assertEqual(upload_res.status_code, status.HTTP_200_OK)
        self.assertEqual(upload_res.data["media_count"], 3)

        # 3. Delete a photo
        photo_to_del_id = upload_res.data["photos"][0]["id"]
        del_photo_res = self.client.delete(f"/api/portfolio/projects/{work_id}/photos/{photo_to_del_id}/")
        self.assertEqual(del_photo_res.status_code, status.HTTP_200_OK)
        self.assertTrue(del_photo_res.data.get("success"))

    def test_06_public_inquiry_submission_and_pipeline_crm(self):
        """Test public inquiry submission (workshop), listing with filters, and patching status."""
        # 1. Submit public inquiry (AllowAny)
        inquiry_payload = {
            "photographer_id": "sarang_artist",
            "client_name": "Rhea & Kabir",
            "client_email": "rhea@luxurywedding.com",
            "client_phone": "+91 98765 43210",
            "event_type": "workshop",
            "event_date": "2026-11-20",
            "location": "Mumbai",
            "budget": "Custom Masterclass",
            "message": "Interested in booking 2 seats for the upcoming light & shadows masterclass."
        }
        inq_res = self.client.post("/api/public/inquiries/", inquiry_payload, format="json")
        self.assertEqual(inq_res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(inq_res.data["success"])
        inquiry_id = inq_res.data["id"]

        # 2. Photographer views leads in CRM
        self.client.force_authenticate(user=self.user)
        list_res = self.client.get("/api/inquiries/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(list_res.data["total_inquiries"], 1)

        # 3. Filter by event_type=workshop
        filter_res = self.client.get("/api/inquiries/?event_type=workshop")
        self.assertEqual(filter_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(filter_res.data["inquiries"]), 1)
        self.assertEqual(filter_res.data["inquiries"][0]["clientName"], "Rhea & Kabir")

        # 4. Search query ?search=Kabir
        search_res = self.client.get("/api/inquiries/?search=Kabir")
        self.assertEqual(search_res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(search_res.data["inquiries"]), 1)

        # 5. Patch status and notes in CRM
        patch_res = self.client.patch(f"/api/inquiries/{inquiry_id}/", {
            "status": "contacted",
            "notes": "Sent brochure via WhatsApp and confirmed seat availability"
        }, format="json")
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_res.data["status"], "contacted")
        self.assertEqual(patch_res.data["notes"], "Sent brochure via WhatsApp and confirmed seat availability")

        # 6. Analytics verification
        analytics_res = self.client.get("/api/inquiries/analytics/")
        self.assertEqual(analytics_res.status_code, status.HTTP_200_OK)
        self.assertIn("total_inquiries", analytics_res.data)
        self.assertIn("status_breakdown", analytics_res.data)
        self.assertEqual(analytics_res.data["contacted"], 1)

    def test_07_public_track_view(self):
        """POST /api/public/portfolio/{slug}/track-view/ records live visitor traffic."""
        # Track 1: Mobile visitor from Instagram
        res1 = self.client.post(
            "/api/public/portfolio/sarang_artist/track-view/",
            {
                "session_id": "sess_client_abc_1",
                "page_section": "hero",
                "device_type": "mobile",
                "referrer": "https://instagram.com/p/123",
                "project_id": "proj-udaipur-royal"
            },
            format="json"
        )
        self.assertIn(res1.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])
        self.assertTrue(res1.data.get("tracked") or res1.data.get("success"))
        self.assertTrue(res1.data.get("session_recorded") or res1.data.get("success"))

        # Track 2: Desktop visitor
        res2 = self.client.post(
            "/api/public/portfolio/sarang_artist/track-view/",
            {
                "session_id": "sess_client_desktop_2",
                "page_section": "works",
                "device_type": "desktop",
                "referrer": "https://google.com/search",
                "project_id": "proj-editorial-vogue"
            },
            format="json"
        )
        self.assertIn(res2.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])

        # Track 3: Tablet visitor
        res3 = self.client.post(
            "/api/public/portfolio/sarang_artist/track-view/",
            {
                "session_id": "sess_client_tablet_3",
                "page_section": "contact",
                "device_type": "tablet",
            },
            format="json"
        )
        self.assertIn(res3.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])

        # Track 4: Invalid photographer returns 404
        res4 = self.client.post(
            "/api/public/portfolio/invalid_unknown_photographer/track-view/",
            {"session_id": "sess_test"},
            format="json"
        )
        self.assertEqual(res4.status_code, status.HTTP_404_NOT_FOUND)

    def test_07b_track_view_fallback_and_payload_slug(self):
        """Fallback endpoint POST /api/portfolio/track-view/ with photographer_slug in payload."""
        from portfolio.models import PortfolioView
        res = self.client.post(
            "/api/portfolio/track-view/",
            {
                "photographer_slug": "sarang_artist",
                "session_id": "sess_fallback_test_1",
                "project_id": "proj-royal-palace",
                "project_title": "Ananya & Kabir • Royal Palace Udaipur",
                "page_section": "works",
                "device": "desktop",
                "referrer": "https://instagram.com"
            },
            format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res.data.get("success"))

        # Verify entry in database has SHA-256 IP hash and resolved project title
        visit = PortfolioView.objects.filter(session_id="sess_fallback_test_1").first()
        self.assertIsNotNone(visit)
        self.assertTrue(bool(visit.visitor_ip_hash))
        self.assertEqual(len(visit.visitor_ip_hash), 64)
        self.assertEqual(visit.project_title, "Ananya & Kabir • Royal Palace Udaipur")
        self.assertEqual(visit.device, "desktop")

    def test_08_portfolio_analytics(self):
        """GET /api/portfolio/analytics/ computes live metrics, devices, top projects, and chart points."""
        # 1. Log views
        self.client.post(
            "/api/public/portfolio/sarang_artist/track-view/",
            {"session_id": "sess_a", "device_type": "mobile", "project_id": "proj-1"},
            format="json"
        )
        self.client.post(
            "/api/public/portfolio/sarang_artist/track-view/",
            {"session_id": "sess_b", "device_type": "desktop", "project_id": "proj-1"},
            format="json"
        )
        self.client.post(
            "/api/public/portfolio/sarang_artist/track-view/",
            {"session_id": "sess_b", "device_type": "desktop", "project_id": "proj-2"},
            format="json"
        )

        # 2. Query analytics as authenticated photographer
        self.client.force_authenticate(user=self.user)
        res = self.client.get("/api/portfolio/analytics/?timeframe=7d")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data

        # Check required schema fields
        self.assertIn("total_visitors", data)
        self.assertIn("total_views", data)
        self.assertIn("inquiry_conversion", data)
        self.assertIn("conversion_rate", data)
        self.assertIn("avg_engagement_duration", data)
        self.assertIn("views_by_device", data)
        self.assertIn("top_viewed_projects", data)
        self.assertIn("chart_points", data)
        self.assertIn("chart_labels", data)
        self.assertIn("recent_visitors", data)

        # Total views must be at least 3
        self.assertGreaterEqual(data["total_views"], 3)
        self.assertGreaterEqual(data["total_visitors"], 2)

        # Device breakdown check
        devices = data["views_by_device"]
        self.assertIn("mobile", devices)
        self.assertIn("desktop", devices)
        self.assertIn("tablet", devices)

        # Chart points (7 daily points)
        self.assertEqual(len(data["chart_points"]), 7)
        self.assertEqual(len(data["chart_labels"]), 7)

        # Top projects
        self.assertGreaterEqual(len(data["top_viewed_projects"]), 1)
        top_p = data["top_viewed_projects"][0]
        self.assertIn("id", top_p)
        self.assertIn("title", top_p)
        self.assertIn("views", top_p)
        self.assertIn("inquiries_generated", top_p)

        # Recent visitors list
        self.assertGreaterEqual(len(data["recent_visitors"]), 1)
        rv = data["recent_visitors"][0]
        self.assertIn("id", rv)
        self.assertIn("city", rv)
        self.assertIn("country", rv)
        self.assertIn("time", rv)
        self.assertIn("device", rv)
        self.assertIn("page", rv)

    def test_08b_portfolio_analytics_with_days(self):
        """GET /api/portfolio/analytics/?days=30 returns telemetry response schema."""
        self.client.force_authenticate(user=self.user)
        res = self.client.get("/api/portfolio/analytics/?days=30")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data
        self.assertIn("total_views", data)
        self.assertIn("total_visitors", data)
        self.assertIn("inquiries_count", data)
        self.assertIn("conversion_rate", data)
        self.assertIn("avg_engagement_duration", data)
        self.assertIn("views_by_device", data)
        self.assertIn("chart_labels", data)
        self.assertIn("chart_points", data)
        self.assertIn("top_viewed_projects", data)
        self.assertIn("recent_visitors", data)
        self.assertIn("desktop", data["views_by_device"])
        self.assertIn("mobile", data["views_by_device"])
        self.assertIn("tablet", data["views_by_device"])

    def test_09_showcase_works_plan_quota_enforcement(self):
        """
        Quota enforcement on showcase works (max_portfolio_posts):
        - Standard Quarterly allows max 10 posts. 11th post raises PORTFOLIO_POSTS_LIMIT_REACHED.
        - Studio Premium Elite has max_portfolio_posts=0 (unlimited).
        """
        from portfolio.utils import get_or_create_starter_portfolio
        self.client.force_authenticate(user=self.user)
        config = get_or_create_starter_portfolio(self.user)
        initial_count = config.works.count()

        # Create up to 10 works
        for i in range(initial_count, 10):
            res = self.client.post("/api/portfolio/projects/", {
                "title": f"Showcase Work {i + 1}",
                "category": "weddings"
            }, format="json")
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # 11th creation attempt must be rejected with PORTFOLIO_POSTS_LIMIT_REACHED
        res_limit = self.client.post("/api/portfolio/projects/", {
            "title": "Overflow Showcase Work 11",
            "category": "fashion"
        }, format="json")
        self.assertEqual(res_limit.status_code, status.HTTP_400_BAD_REQUEST)
        error_code = res_limit.data.get("code") or (res_limit.data[0].get("code") if isinstance(res_limit.data, list) else None)
        self.assertEqual(error_code, "PORTFOLIO_POSTS_LIMIT_REACHED")

        # Upgrade user to Studio Premium Elite (max_portfolio_posts = 0 / unlimited)
        self.subscription.plan = self.plan_premium_elite
        self.subscription.save()

        # Now creating the 11th work succeeds
        res_upgrade = self.client.post("/api/portfolio/projects/", {
            "title": "Elite Showcase Work 11",
            "category": "fashion"
        }, format="json")
        self.assertEqual(res_upgrade.status_code, status.HTTP_201_CREATED)

    def test_10_signature_templates_plan_restriction(self):
        """
        Allowed templates restriction (allowed_portfolio_templates):
        - Standard Quarterly allows ['editorial', 'masonry']. Setting cinematic/minimal fails.
        - Studio Premium Elite unlocks all 4 templates.
        """
        self.client.force_authenticate(user=self.user)
        # Reset user plan to Standard Quarterly
        self.subscription.plan = self.plan_standard_3m
        self.subscription.save()

        # 1. Setting 'editorial' or 'masonry' succeeds
        res_ed = self.client.patch("/api/portfolio/config/", {"template_id": "editorial"}, format="json")
        self.assertEqual(res_ed.status_code, status.HTTP_200_OK)

        res_mas = self.client.patch("/api/portfolio/config/", {"template_id": "darkroom-atelier"}, format="json")
        self.assertEqual(res_mas.status_code, status.HTTP_200_OK)

        # 2. Setting 'cinematic' fails on Standard Quarterly
        res_cin = self.client.patch("/api/portfolio/config/", {"template_id": "cinematic"}, format="json")
        self.assertEqual(res_cin.status_code, status.HTTP_400_BAD_REQUEST)
        error_code_cin = res_cin.data.get("code") or (res_cin.data[0].get("code") if isinstance(res_cin.data, list) else None)
        self.assertEqual(error_code_cin, "TEMPLATE_LOCKED_PLAN_REQUIRED")

        # 3. Setting 'minimal' fails on Standard Quarterly
        res_min = self.client.patch("/api/portfolio/config/", {"template_id": "minimal"}, format="json")
        self.assertEqual(res_min.status_code, status.HTTP_400_BAD_REQUEST)
        error_code_min = res_min.data.get("code") or (res_min.data[0].get("code") if isinstance(res_min.data, list) else None)
        self.assertEqual(error_code_min, "TEMPLATE_LOCKED_PLAN_REQUIRED")

        # 4. Upgrade user to Studio Premium Elite with unlocked templates
        self.plan_premium_elite.allowed_portfolio_templates = ['editorial-vogue', 'darkroom-atelier', 'cinematic', 'minimal']
        self.plan_premium_elite.save()
        self.subscription.plan = self.plan_premium_elite
        self.subscription.save()

        # 5. Setting 'cinematic' and 'minimal' now succeeds
        res_cin_elite = self.client.patch("/api/portfolio/config/", {"template_id": "cinematic"}, format="json")
        self.assertEqual(res_cin_elite.status_code, status.HTTP_200_OK)
        self.assertEqual(res_cin_elite.data.get("template_id"), "cinematic")

        res_min_elite = self.client.patch("/api/portfolio/config/", {"template_id": "minimal"}, format="json")
        self.assertEqual(res_min_elite.status_code, status.HTTP_200_OK)
        self.assertEqual(res_min_elite.data.get("template_id"), "minimal")

    def test_11_inquiries_plan_quota_masking(self):
        """
        Inquiry masking (max_inquiries & has_full_inquiry_access):
        - Standard Quarterly (max_inquiries=10, has_full_inquiry_access=False):
          First 10 leads unmasked, 11th and later masked (+91 ********** / ********@*****.com).
        - Standard Annual & Studio Premium Elite:
          All leads unmasked.
        """
        self.client.force_authenticate(user=self.user)
        # Reset user plan to Standard Quarterly
        self.subscription.plan = self.plan_standard_3m
        self.subscription.save()

        # Delete existing inquiries to start clean
        PortfolioInquiry.objects.filter(photographer=self.user).delete()

        # Create 12 inquiries
        for i in range(12):
            PortfolioInquiry.objects.create(
                photographer=self.user,
                client_name=f"Client {i + 1}",
                client_email=f"client{i + 1}@example.com",
                client_phone=f"+91 98765 000{i:02d}",
                event_type="wedding",
                message=f"Inquiry message {i + 1}"
            )

        # GET /api/inquiries/
        list_res = self.client.get("/api/inquiries/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        inquiries = list_res.data["inquiries"]
        self.assertEqual(len(inquiries), 12)

        # First 10 should be unmasked
        for i in range(10):
            self.assertFalse(inquiries[i].get("is_locked"))
            self.assertNotEqual(inquiries[i].get("client_phone"), "+91 **********")
            self.assertNotEqual(inquiries[i].get("client_email"), "********@*****.com")

        # 11th and 12th should be locked and masked
        for i in range(10, 12):
            self.assertTrue(inquiries[i].get("is_locked"))
            self.assertEqual(inquiries[i].get("client_phone"), "+91 **********")
            self.assertEqual(inquiries[i].get("client_email"), "********@*****.com")

        # Upgrade to Standard Annual (has_full_inquiry_access=True, max_inquiries=0)
        self.subscription.plan = self.plan_standard_1y
        self.subscription.save()

        list_res_1y = self.client.get("/api/inquiries/")
        self.assertEqual(list_res_1y.status_code, status.HTTP_200_OK)
        inquiries_1y = list_res_1y.data["inquiries"]
        # All should be unmasked
        for inq in inquiries_1y:
            self.assertFalse(inq.get("is_locked"))
            self.assertNotEqual(inq.get("client_phone"), "+91 **********")
            self.assertNotEqual(inq.get("client_email"), "********@*****.com")



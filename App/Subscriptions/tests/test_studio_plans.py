from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from rest_framework import status

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import Plan, PhotographerSubscription, SubscriptionPayment
from App.management.commands.seed_plans import Command as SeedPlansCommand


class StudioPlansAPITests(TestCase):
    def setUp(self):
        # Seed studio plans first
        SeedPlansCommand().handle()

        self.client = APIClient()

        # Create photographer user & profile
        self.user = User.objects.create_user(
            username="studio_tester",
            email="studio_tester@example.com",
            password="testpassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Apex Studio",
            studio_name="Apex Wedding & Studio",
            email="studio_tester@example.com",
            phone="9876543210",
        )
        self.client.force_authenticate(user=self.user)

    def test_list_plans_public(self):
        """Public endpoint GET /api/plans/ returns all active studio plans matching specs."""
        anon_client = APIClient()
        resp = anon_client.get("/api/plans/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 3)

        plan_ids = [p["id"] for p in resp.data]
        self.assertIn("plan-standard-3m", plan_ids)
        self.assertIn("plan-standard-1y", plan_ids)
        self.assertIn("plan-premium-elite", plan_ids)

        standard_1y = next(p for p in resp.data if p["id"] == "plan-standard-1y")
        self.assertEqual(standard_1y["name"], "Standard Annual")
        self.assertEqual(standard_1y["billing_cycle"], "annual")
        self.assertEqual(standard_1y["period_label"], "For 01 Year")
        self.assertEqual(standard_1y["image_storage"], "200 GB")
        self.assertEqual(standard_1y["video_storage"], "10 GB")
        self.assertEqual(standard_1y["tag"], "MOST POPULAR")
        self.assertIn("200 GB Image Storage", standard_1y["features"])
        self.assertIn("₹800 / Month", standard_1y["billing_text"])

    def test_current_subscription(self):
        """GET /api/plans/current/ retrieves active subscription details and storage breakdown."""
        # Link a plan
        plan_1y = Plan.objects.get(id="plan-standard-1y")
        PhotographerSubscription.objects.create(
            photographer=self.profile,
            plan=plan_1y,
            status="active",
            started_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=365),
            auto_renew=True,
        )

        resp = self.client.get("/api/plans/current/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "active")
        self.assertEqual(resp.data["plan"]["id"], "plan-standard-1y")
        self.assertTrue(resp.data["auto_renew"])
        self.assertGreaterEqual(resp.data["days_remaining"], 364)
        self.assertIn("storage", resp.data)
        self.assertEqual(resp.data["storage"]["limit_bytes"], plan_1y.storage_limit_bytes)

    def test_direct_checkout_upgrade_and_quota_sync(self):
        """POST /api/plans/checkout/ with gateway='direct' instantly activates plan and updates storage limit."""
        elite_plan = Plan.objects.get(id="plan-premium-elite")

        resp = self.client.post(
            "/api/plans/checkout/",
            {"plan_id": "plan-premium-elite", "gateway": "direct"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data.get("direct_activated"))

        # Verify photographer profile storage limit updated
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.get_storage_limit(), elite_plan.storage_limit_bytes)
        self.assertEqual(self.profile.studio_plan.id, "plan-premium-elite")

        # Verify payment record created with status success
        payment = SubscriptionPayment.objects.filter(subscription__photographer=self.profile).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, "success")
        self.assertEqual(payment.plan.id, "plan-premium-elite")

    def test_razorpay_checkout_order_creation(self):
        """POST /api/plans/checkout/ with gateway='razorpay' returns order tokens."""
        resp = self.client.post(
            "/api/plans/checkout/",
            {"plan_id": "plan-standard-1y", "gateway": "razorpay"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("order_id", resp.data)
        self.assertEqual(resp.data["amount"], 9600.0)
        self.assertEqual(resp.data["amount_paise"], 960000)
        self.assertEqual(resp.data["currency"], "INR")
        self.assertIn("key_id", resp.data)

        # Verify pending payment entry created
        payment = SubscriptionPayment.objects.filter(gateway_order_id=resp.data["order_id"]).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, "pending")

    def test_verify_payment_and_quota_activation(self):
        """POST /api/plans/verify/ activates subscription and syncs storage upon signature check."""
        standard_1y = Plan.objects.get(id="plan-standard-1y")

        resp = self.client.post(
            "/api/plans/verify/",
            {
                "plan_id": "plan-standard-1y",
                "gateway_order_id": "order_test_999",
                "gateway_payment_id": "pay_test_888",
                "gateway_signature": "test_signature_valid",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "success")

        # Verify profile has updated limit
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.get_storage_limit(), standard_1y.storage_limit_bytes)

        # Verify subscription is active
        sub = PhotographerSubscription.objects.get(photographer=self.profile)
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub.plan.id, "plan-standard-1y")

    def test_cancel_auto_renew(self):
        """POST /api/plans/cancel/ turns off auto_renew."""
        plan_1y = Plan.objects.get(id="plan-standard-1y")
        sub = PhotographerSubscription.objects.create(
            photographer=self.profile,
            plan=plan_1y,
            status="active",
            auto_renew=True,
        )

        resp = self.client.post("/api/plans/cancel/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["auto_renew"])

        sub.refresh_from_db()
        self.assertFalse(sub.auto_renew)

    def test_subscriptions_url_route_alias(self):
        """Routes are accessible via /api/subscriptions/ as well as /api/plans/."""
        anon_client = APIClient()
        resp = anon_client.get("/api/subscriptions/plans/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 3)

        current_resp = self.client.get("/api/subscriptions/current/")
        self.assertEqual(current_resp.status_code, status.HTTP_200_OK)

    def test_current_subscription_with_cookie_auth(self):
        """Authenticated request using only HTTP-only cookie 'access_token' succeeds without Authorization header."""
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(self.user)
        access_token = str(refresh.access_token)

        cookie_client = APIClient()
        cookie_client.cookies['access_token'] = access_token

        resp = cookie_client.get("/api/plans/current/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "active")
        self.assertIn("plan", resp.data)
        self.assertIn("storage", resp.data)

    def test_current_subscription_unauthenticated_returns_401(self):
        """Unauthenticated request without token or cookie returns 401 Unauthorized."""
        unauth_client = APIClient()
        resp = unauth_client.get("/api/plans/current/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_auto_create_photographer_profile_on_current_subscription(self):
        """A user without an existing PhotographerProfile gets one automatically created when requesting /api/plans/current/."""
        from rest_framework_simplejwt.tokens import RefreshToken
        new_user = User.objects.create_user(
            username="new_photographer",
            email="new_photographer@example.com",
            password="testpassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        refresh = RefreshToken.for_user(new_user)
        cookie_client = APIClient()
        cookie_client.cookies['access_token'] = str(refresh.access_token)

        resp = cookie_client.get("/api/plans/current/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "active")
        self.assertTrue(PhotographerProfile.objects.filter(user=new_user).exists())


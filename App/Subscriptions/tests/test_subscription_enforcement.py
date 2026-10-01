from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.exceptions import PermissionDenied

from App.Auth.auth_models import User
from App.Photographers.photo_models import PhotographerProfile
from App.Subscriptions.sub_models import Plan as StudioPlan, PhotographerSubscription
from App.Storage.storage_models import Gallery
from App.management.commands.seed_plans import Command as SeedPlansCommand
from backend.atelier_plans.subscription_enforcement import (
    update_subscription_expiration_state,
    enforce_active_subscription,
    CurrentSubscriptionSerializer,
)


class SubscriptionEnforcementTests(TestCase):
    def setUp(self):
        SeedPlansCommand().handle()
        self.client = APIClient()

        self.user = User.objects.create_user(
            username="enforce_studio",
            email="enforce_studio@example.com",
            password="testpassword123",
            role=User.Role.PHOTOGRAPHER,
        )
        self.profile = PhotographerProfile.objects.create(
            user=self.user,
            name="Enforce Studio",
            studio_name="Enforce Studio Works",
            email="enforce_studio@example.com",
            phone="9876543211",
        )
        self.client.force_authenticate(user=self.user)

        self.plan_standard = StudioPlan.objects.get(id="plan-standard-3m")
        self.plan_elite = StudioPlan.objects.get(id="plan-premium-elite")

    def test_expired_subscription_serializer_values(self):
        """When subscription has passed expiry_date, serializer must return status='expired', auto_renew=False, days_remaining=0."""
        past_date = timezone.now() - timedelta(days=2)
        sub = PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_standard,
            status="active",
            started_at=past_date - timedelta(days=90),
            expires_at=past_date,
            auto_renew=True,
        )

        serializer = CurrentSubscriptionSerializer(sub)
        data = serializer.data

        self.assertEqual(data["status"], "expired")
        self.assertEqual(data["days_remaining"], 0)
        self.assertFalse(data["auto_renew"])

    def test_update_subscription_expiration_state_function(self):
        """update_subscription_expiration_state updates database row when expiry has lapsed."""
        past_date = timezone.now() - timedelta(days=1)
        sub = PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_standard,
            status="active",
            started_at=past_date - timedelta(days=90),
            expires_at=past_date,
            auto_renew=True,
        )

        updated_sub = update_subscription_expiration_state(sub)
        sub.refresh_from_db()

        self.assertEqual(sub.status, "expired")
        self.assertFalse(sub.auto_renew)

    def test_enforce_active_subscription_expired_raises_403(self):
        """enforce_active_subscription raises PermissionDenied with PLAN_EXPIRED when lapsed."""
        past_date = timezone.now() - timedelta(days=1)
        PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_standard,
            status="active",
            started_at=past_date - timedelta(days=90),
            expires_at=past_date,
            auto_renew=True,
        )

        with self.assertRaises(PermissionDenied) as ctx:
            enforce_active_subscription(self.user, "client galleries")

        detail = ctx.exception.detail
        self.assertEqual(detail["error_code"], "PLAN_EXPIRED")
        self.assertTrue(detail["upgrade_required"])

    def test_gallery_creation_blocked_when_subscription_expired(self):
        """POST /api/galleries/ returns 403 Forbidden with PLAN_EXPIRED when subscription is expired."""
        past_date = timezone.now() - timedelta(days=5)
        PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_standard,
            status="expired",
            started_at=past_date - timedelta(days=90),
            expires_at=past_date,
            auto_renew=False,
        )

        payload = {
            "title": "Summer Wedding 2026",
            "client_name": "Alice & Bob",
            "event_date": "2026-08-15",
            "template_id": "editorial",
        }
        resp = self.client.post("/api/galleries/", payload, format="json")

        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data.get("error_code"), "PLAN_EXPIRED")
        self.assertTrue(resp.data.get("upgrade_required"))

    def test_media_upload_blocked_when_subscription_expired(self):
        """Direct upload init & standard upload endpoints return 403 when subscription is expired."""
        past_date = timezone.now() - timedelta(days=5)
        sub = PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_standard,
            status="expired",
            started_at=past_date - timedelta(days=90),
            expires_at=past_date,
            auto_renew=False,
        )

        gallery = Gallery.objects.create(
            photographer=self.profile,
            title="Pre-existing Gallery",
            client_name="Test Client",
            event_date="2026-05-10",
        )

        # 1. upload-init
        resp_init = self.client.post(
            f"/api/galleries/{gallery.id}/upload-init/",
            {"files": [{"filename": "sample.jpg", "file_size": 1024 * 1024, "mime_type": "image/jpeg"}]},
            format="json",
        )
        self.assertEqual(resp_init.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_init.data.get("error_code"), "PLAN_EXPIRED")

        # 2. standard upload
        resp_upload = self.client.post(
            f"/api/galleries/{gallery.id}/upload/",
            {"section_title": "Ceremony"},
            format="multipart",
        )
        self.assertEqual(resp_upload.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp_upload.data.get("error_code"), "PLAN_EXPIRED")

    def test_live_event_creation_blocked_when_subscription_expired(self):
        """POST /api/events/ returns 403 Forbidden with PLAN_EXPIRED when subscription is expired."""
        past_date = timezone.now() - timedelta(days=3)
        PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_standard,
            status="expired",
            started_at=past_date - timedelta(days=90),
            expires_at=past_date,
            auto_renew=False,
        )

        payload = {
            "title": "Corporate Gala Live",
            "event_date": "2026-11-20",
        }
        resp = self.client.post("/api/events/", payload, format="json")

        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data.get("error_code"), "PLAN_EXPIRED")
        self.assertTrue(resp.data.get("upgrade_required"))

    def test_plan_upgrade_active_blocks_downgrade_and_same_plan(self):
        """Active unexpired subscription blocks downgrades and same plan renewal."""
        future_date = timezone.now() + timedelta(days=60)
        PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_elite,
            status="active",
            started_at=timezone.now(),
            expires_at=future_date,
            auto_renew=True,
        )

        # 1. Attempt same plan
        resp_same = self.client.post("/api/plans/upgrade/", {"plan_id": self.plan_elite.id}, format="json")
        self.assertEqual(resp_same.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp_same.data.get("error_code"), "CURRENT_PLAN_ACTIVE")

        # 2. Attempt downgrade to standard
        resp_down = self.client.post("/api/plans/upgrade/", {"plan_id": self.plan_standard.id}, format="json")
        self.assertEqual(resp_down.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp_down.data.get("error_code"), "DOWNGRADE_NOT_ALLOWED")

    def test_plan_upgrade_expired_permits_any_plan_reactivation(self):
        """Expired subscription permits selection of ANY plan (same tier renewal, lower tier, higher tier)."""
        past_date = timezone.now() - timedelta(days=10)
        PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_elite,
            status="expired",
            started_at=past_date - timedelta(days=365),
            expires_at=past_date,
            auto_renew=False,
        )

        # 1. Select same tier plan (renewal)
        resp_same = self.client.post("/api/plans/upgrade/", {"plan_id": self.plan_elite.id}, format="json")
        self.assertEqual(resp_same.status_code, status.HTTP_200_OK)
        self.assertTrue(resp_same.data.get("is_renewal"))

        # 2. Select lower tier plan (downgrade on expired plan is permitted)
        resp_lower = self.client.post("/api/plans/upgrade/", {"plan_id": self.plan_standard.id}, format="json")
        self.assertEqual(resp_lower.status_code, status.HTTP_200_OK)
        self.assertTrue(resp_lower.data.get("is_renewal"))

        # 3. Direct activation reactivates subscription
        resp_direct = self.client.post(
            "/api/plans/upgrade/",
            {"plan_id": self.plan_standard.id, "gateway": "direct"},
            format="json",
        )
        self.assertEqual(resp_direct.status_code, status.HTTP_200_OK)
        self.assertTrue(resp_direct.data.get("direct_activated"))

        sub = PhotographerSubscription.objects.get(photographer=self.profile)
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub.plan_id, self.plan_standard.id)
        self.assertTrue(sub.days_remaining > 0)
        self.assertTrue(sub.auto_renew)

    def test_can_user_select_plan_rules(self):
        """can_user_select_plan permits any tier when expired or no sub, blocks downgrade when active."""
        from backend.atelier_plans.views_razorpay import can_user_select_plan

        # 1. No subscription -> Allowed
        allowed, msg = can_user_select_plan(self.user, self.plan_elite, PhotographerSubscription)
        self.assertTrue(allowed)

        # 2. Active Elite subscription -> Reject same plan and reject downgrade to standard
        future = timezone.now() + timedelta(days=30)
        sub = PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_elite,
            status="active",
            started_at=timezone.now(),
            expires_at=future,
            auto_renew=True,
        )

        allowed_same, msg_same = can_user_select_plan(self.user, self.plan_elite, PhotographerSubscription)
        self.assertFalse(allowed_same)
        self.assertIn("already have an active subscription", msg_same)

        allowed_down, msg_down = can_user_select_plan(self.user, self.plan_standard, PhotographerSubscription)
        self.assertFalse(allowed_down)
        self.assertIn("higher-tier", msg_down)

        # 3. Expired subscription -> Allowed same plan and allowed standard
        sub.status = "expired"
        sub.expires_at = timezone.now() - timedelta(days=1)
        sub.auto_renew = False
        sub.save()

        allowed_exp_same, _ = can_user_select_plan(self.user, self.plan_elite, PhotographerSubscription)
        self.assertTrue(allowed_exp_same)

        allowed_exp_down, _ = can_user_select_plan(self.user, self.plan_standard, PhotographerSubscription)
        self.assertTrue(allowed_exp_down)

    def test_checkout_expired_plan_allows_same_tier_renewal_and_fallback(self):
        """POST /api/plans/checkout/ allows renewing the same expired tier and returns order_id/subscription_id without 400."""
        past_date = timezone.now() - timedelta(days=5)
        PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_elite,
            status="expired",
            started_at=past_date - timedelta(days=365),
            expires_at=past_date,
            auto_renew=False,
        )

        resp = self.client.post("/api/plans/checkout/", {"plan_id": self.plan_elite.id}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["plan_id"], self.plan_elite.id)
        # Must have either subscription_id or order_id
        has_id = bool(data.get("subscription_id") or data.get("order_id"))
        self.assertTrue(has_id)
        self.assertTrue(data.get("key_id"))

    def test_checkout_active_plan_blocks_downgrade(self):
        """POST /api/plans/checkout/ blocks downgrade while active."""
        future_date = timezone.now() + timedelta(days=60)
        PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_elite,
            status="active",
            started_at=timezone.now(),
            expires_at=future_date,
            auto_renew=True,
        )

        resp = self.client.post("/api/plans/checkout/", {"plan_id": self.plan_standard.id}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_payment_verification_activates_plan_and_supersedes_older_records(self):
        """POST /api/plans/verify/ activates subscription, supersedes older records, and updates storage quota."""
        past_date = timezone.now() - timedelta(days=10)
        old_sub = PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_standard,
            status="expired",
            started_at=past_date - timedelta(days=90),
            expires_at=past_date,
            auto_renew=False,
        )

        verify_payload = {
            "plan_id": self.plan_elite.id,
            "razorpay_payment_id": "pay_test_123456",
            "razorpay_signature": "test_signature_valid",
            "razorpay_order_id": "order_test_987654",
        }

        resp = self.client.post("/api/plans/verify/", verify_payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data.get("status"), "success")

        sub_data = resp.data.get("subscription", {})
        self.assertEqual(sub_data.get("status"), "active")
        self.assertTrue(sub_data.get("auto_renew"))
        self.assertTrue(sub_data.get("days_remaining") > 0)
        self.assertEqual(sub_data.get("storage", {}).get("limit_bytes"), self.plan_elite.storage_limit_bytes)

        # Profile is updated
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.studio_plan_id, self.plan_elite.id)

    def test_auto_renew_false_when_cancel_at_period_end(self):
        """Serializer must return auto_renew=False if cancel_at_period_end is True."""
        future_date = timezone.now() + timedelta(days=20)
        sub = PhotographerSubscription.objects.create(
            user=self.user,
            photographer=self.profile,
            plan=self.plan_standard,
            status="active",
            started_at=timezone.now(),
            expires_at=future_date,
            auto_renew=True,
            cancel_at_period_end=True,
        )

        serializer = CurrentSubscriptionSerializer(sub)
        self.assertFalse(serializer.data["auto_renew"])

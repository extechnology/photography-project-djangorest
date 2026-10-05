from decimal import Decimal
from django.core.management.base import BaseCommand
from culling.models import CullingPricingTier


class Command(BaseCommand):
    help = "Seed initial dynamic pricing plans for AI Culling"

    def handle(self, *args, **options):
        # Remove deprecated tiers if present
        CullingPricingTier.objects.filter(id__in=["tier_starter", "tier_pro", "tier_wedding"]).delete()

        tiers = [
            {
                "id": "cull_single_300",
                "name": "Single Shoot Batch",
                "price": Decimal("149.00"),
                "price_inr": 149,
                "photos_limit": 300,
                "badge": "Single Shoot",
                "description": "Ideal for mini shoots, maternity sessions, or portrait portraits.",
                "features": [
                    "Up to 300 Raw / High-Res Photos",
                    "AI Laplacian Focus Detection",
                    "Perceptual Difference Grouping",
                    "One-Click Gallery Direct Transfer",
                ],
                "is_popular": False,
                "display_order": 1,
            },
            {
                "id": "cull_wedding_1200",
                "name": "Full Event & Wedding",
                "price": Decimal("399.00"),
                "price_inr": 399,
                "photos_limit": 1200,
                "badge": "Most Popular",
                "description": "Engineered for weddings, receptions, and half-day commercial shoots.",
                "features": [
                    "Up to 1,200 Raw / High-Res Photos",
                    "Ultra-Fast Local Multi-threading",
                    "Burst Grouping & Best Pick Engine",
                    "Zero Server File Compression",
                ],
                "is_popular": True,
                "display_order": 2,
            },
            {
                "id": "cull_pro_unlimited",
                "name": "Studio Multi-Day Pro",
                "price": Decimal("899.00"),
                "price_inr": 899,
                "photos_limit": 999999,
                "badge": "Studio Unlimited",
                "description": "For multi-day festivals, corporate conventions, and multi-camera sets.",
                "features": [
                    "Unlimited Photos per session",
                    "Unlimited Bursts & Comparisons",
                    "Bulk Keep/Discard Overrides",
                    "Priority Gallery Sync Engine",
                ],
                "is_popular": False,
                "display_order": 3,
            },
        ]

        for t in tiers:
            obj, created = CullingPricingTier.objects.update_or_create(
                id=t["id"],
                defaults=t,
            )
            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action} tier: {obj.name} (₹{obj.price})"))

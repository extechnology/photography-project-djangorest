from decimal import Decimal
from django.core.management.base import BaseCommand
from culling.models import CullingPricingTier


class Command(BaseCommand):
    help = "Seed initial dynamic pricing plans for AI Culling"

    def handle(self, *args, **options):
        tiers = [
            {
                "id": "tier_starter",
                "name": "Starter Shoot",
                "price": Decimal("149.00"),
                "price_inr": 149,
                "photos_limit": 300,
                "badge": "Up to 300 Photos",
                "description": "Ideal for portrait sessions, mini shoots, and maternity captures.",
                "features": [
                    "Up to 300 Photos per batch",
                    "Dual AI duplicate grouping",
                    "Laplacian sharpness focus score",
                    "1-Click move to gallery",
                ],
                "is_popular": False,
                "display_order": 1,
            },
            {
                "id": "tier_pro",
                "name": "Studio Event",
                "price": Decimal("399.00"),
                "price_inr": 399,
                "photos_limit": 1200,
                "badge": "Up to 1,200 Photos",
                "description": "Best for birthday parties, corporate events, and pre-wedding shoots.",
                "features": [
                    "Up to 1,200 Photos per batch",
                    "High-speed burst clustering",
                    "Direct RAW/JPEG processing",
                    "Side-by-side comparison modal",
                    "1-Click move to gallery",
                ],
                "is_popular": True,
                "display_order": 2,
            },
            {
                "id": "tier_wedding",
                "name": "Grand Wedding",
                "price": Decimal("899.00"),
                "price_inr": 899,
                "photos_limit": 4000,
                "badge": "Up to 4,000 Photos",
                "description": "Full day wedding coverage, multi-camera setups, and mega events.",
                "features": [
                    "Up to 4,000 Photos per batch",
                    "Multi-angle burst culling",
                    "Unlimited keeper moves to gallery",
                    "Highest priority AI processing",
                    "VIP studio support",
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

from django.core.management.base import BaseCommand
from App.Subscriptions.sub_models import Plan


STUDIO_PLANS = [
    {
        "id": "plan-standard-3m",
        "name": "Standard Quarterly",
        "subtitle": "For 03 Months • Ideal For Getting Started",
        "tier": "standard",
        "billing_cycle": "quarterly",
        "duration_months": 3,
        "monthly_price": 800.00,
        "original_monthly_price": 1100.00,
        "total_price": 2400.00,
        "currency": "INR",
        "image_storage_gb": 200,
        "video_storage_gb": 10,
        "storage_limit_bytes": (200 + 10) * 1024 * 1024 * 1024,
        "tag": "",
        "tag_type": "default",
        "cta_text": "Choose Standard (3 Months)",
        "features": [
            "200 GB Image Storage",
            "10 GB Video Delivery",
            "For 03 Months Hosting",
            "Unlimited Client Galleries",
            "All 4 Layout Templates (Editorial, Masonry, Cinematic, Minimal)",
            "PIN Security & Custom Watermark Suite",
            "Priority Delivery Speeds"
        ],
        "is_active": True,
        "sort_order": 1,
    },
    {
        "id": "plan-standard-1y",
        "name": "Standard Annual",
        "subtitle": "For 01 Year • Best Value For Photographers",
        "tier": "standard",
        "billing_cycle": "annual",
        "duration_months": 12,
        "monthly_price": 800.00,
        "original_monthly_price": 1100.00,
        "total_price": 9600.00,
        "currency": "INR",
        "image_storage_gb": 200,
        "video_storage_gb": 10,
        "storage_limit_bytes": (200 + 10) * 1024 * 1024 * 1024,
        "tag": "MOST POPULAR",
        "tag_type": "popular",
        "cta_text": "Choose Standard (1 Year)",
        "features": [
            "200 GB Image Storage",
            "10 GB Video Delivery",
            "For 01 Year Uninterrupted Hosting",
            "Unlimited Client Galleries",
            "All 4 Layout Templates (Editorial, Masonry, Cinematic, Minimal)",
            "PIN Security & Custom Watermark Suite",
            "Priority Delivery Speeds"
        ],
        "is_active": True,
        "sort_order": 2,
    },
    {
        "id": "plan-premium-elite",
        "name": "Studio Premium Elite",
        "subtitle": "For 01 Year • Maximum Storage & Dedicated Video Bandwidth",
        "tier": "premium",
        "billing_cycle": "annual",
        "duration_months": 12,
        "monthly_price": 1800.00,
        "original_monthly_price": 2400.00,
        "total_price": 21600.00,
        "currency": "INR",
        "image_storage_gb": 1000,
        "video_storage_gb": 50,
        "storage_limit_bytes": (1000 + 50) * 1024 * 1024 * 1024,
        "tag": "2X POWER",
        "tag_type": "popular",
        "cta_text": "Choose Studio Premium Elite",
        "features": [
            "1000 GB High-Speed Image Storage",
            "50 GB 4K Video Delivery",
            "Dedicated High-Bandwidth Cloud Delivery",
            "Custom Domain & Studio White-Labeling",
            "Advanced AI Face Search & Tagging",
            "Custom Studio Watermarking Suite",
            "VIP Support & Early Access to New Templates"
        ],
        "is_active": True,
        "sort_order": 3,
    },
]


class Command(BaseCommand):
    help = "Seeds Studio Plans (Standard 3M, Standard 1Y, Studio Premium Elite) into the database."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding Studio Plans..."))
        created_count = 0
        updated_count = 0

        for item in STUDIO_PLANS:
            plan, created = Plan.objects.update_or_create(
                id=item["id"],
                defaults=item
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"  + Created: {plan.name} ({plan.id})"))
            else:
                updated_count += 1
                self.stdout.write(self.style.SUCCESS(f"  * Updated: {plan.name} ({plan.id})"))

        self.stdout.write(
            self.style.SUCCESS(f"Finished seeding Studio Plans: {created_count} created, {updated_count} updated.")
        )

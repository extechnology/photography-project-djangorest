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
            "200 GB High-Speed Image Storage",
            "10 GB 4K Video Delivery",
            "For 03 Months Hosting",
            "Up to 15 Active Client Galleries",
            "90 Days Gallery Access Validity",
            "5 Event Section Albums (30-Day Window)",
            "Editorial & Masonry Gallery Templates",
            "Photographer Portfolio (10 Showcase Posts)",
            "Random 10 Client Inquiries Access (Upgrade to view all)",
            "PIN Security & Custom Watermark Suite",
            "Priority Delivery Speeds"
        ],
        "max_galleries": 15,
        "gallery_expiry_days": 90,
        "face_search_enabled": False,
        "max_events": 5,
        "allowed_templates": ["editorial", "masonry"],
        "allowed_portfolio_templates": ["editorial", "masonry"],
        "max_portfolio_posts": 10,
        "max_inquiries": 10,
        "has_full_inquiry_access": False,
        "can_upgrade_storage": False,
        "max_upgrade_image_gb": 200,
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
            "200 GB High-Speed Image Storage",
            "10 GB 4K Video Delivery",
            "For 01 Year Uninterrupted Hosting",
            "Up to 50 Active Client Galleries",
            "365 Days Gallery Access Validity",
            "AI Biometric Face Search Enabled",
            "25 Event Section Albums (90-Day Window)",
            "Editorial & Masonry Gallery Templates",
            "Photographer Portfolio (30 Showcase Posts)",
            "Full Access to All Client Inquiries",
            "PIN Security & Custom Watermark Suite",
            "Priority Delivery Speeds"
        ],
        "max_galleries": 50,
        "gallery_expiry_days": 365,
        "face_search_enabled": True,
        "max_events": 25,
        "allowed_templates": ["editorial", "masonry"],
        "allowed_portfolio_templates": ["editorial", "masonry"],
        "max_portfolio_posts": 30,
        "max_inquiries": 0,
        "has_full_inquiry_access": True,
        "can_upgrade_storage": False,
        "max_upgrade_image_gb": 200,
        "is_active": True,
        "sort_order": 2,
    },
    {
        "id": "plan-premium-elite",
        "name": "Studio Premium Elite",
        "subtitle": "2xStandard Plan • Maximum Storage & Dedicated Video Bandwidth",
        "tier": "premium",
        "billing_cycle": "annual",
        "duration_months": 12,
        "monthly_price": 1800.00,
        "original_monthly_price": 2200.00,
        "total_price": 21600.00,
        "currency": "INR",
        "image_storage_gb": 600,
        "video_storage_gb": 50,
        "storage_limit_bytes": (600 + 50) * 1024 * 1024 * 1024,
        "tag": "2xStandard Plan",
        "tag_type": "popular",
        "cta_text": "Choose Studio Premium Elite",
        "features": [
            "600 GB Image Storage (Upgradeable to 1000 GB)",
            "50 GB 4K Video Delivery",
            "2x Standard Plan Performance & Quota",
            "Unlimited Client Galleries (No Cap)",
            "Unlimited Gallery Expiry (Permanent)",
            "Dedicated High-Bandwidth Cloud Delivery",
            "VIP AI Face Search & Discovery",
            "Unlimited Event Section Albums",
            "All 4 Layout Templates (Editorial, Masonry, Cinematic, Minimal)",
            "Photographer Portfolio (Unlimited Posts & Custom Domain)",
            "Full & Unlimited Access to All Client Inquiries",
            "Custom Studio Watermarking Suite & White-Labeling",
            "VIP Support & Early Access to New Templates"
        ],
        "max_galleries": 0,
        "gallery_expiry_days": 0,
        "face_search_enabled": True,
        "max_events": 0,
        "allowed_templates": ["editorial", "masonry", "cinematic", "minimal"],
        "allowed_portfolio_templates": ["editorial", "masonry", "cinematic", "minimal"],
        "max_portfolio_posts": 0,
        "max_inquiries": 0,
        "has_full_inquiry_access": True,
        "can_upgrade_storage": True,
        "max_upgrade_image_gb": 1000,
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

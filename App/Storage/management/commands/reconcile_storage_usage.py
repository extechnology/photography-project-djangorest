from django.core.management.base import BaseCommand
from App.Photographers.photo_models import PhotographerProfile
from App.Storage.services.quota_service import StorageQuotaService


class Command(BaseCommand):
    help = "Reconciles photographer storage usage counters against actual Media records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--photographer-id",
            type=int,
            help="Optional ID of specific photographer profile to reconcile.",
        )

    def handle(self, *args, **options):
        photographer_id = options.get("photographer_id")

        if photographer_id:
            profiles = PhotographerProfile.objects.filter(id=photographer_id)
            if not profiles.exists():
                self.stderr.write(self.style.ERROR(f"Photographer profile {photographer_id} not found."))
                return
        else:
            profiles = PhotographerProfile.objects.all()

        self.stdout.write(f"Reconciling storage for {profiles.count()} photographer(s)...")

        for profile in profiles:
            result = StorageQuotaService.reconcile_storage(profile)
            self.stdout.write(
                self.style.SUCCESS(
                    f"[{result['photographer_name']}] Used: {result['storage_used_bytes']} bytes, "
                    f"Reserved: {result['storage_reserved_bytes']} bytes, "
                    f"Remaining: {result['storage_remaining_bytes']} bytes."
                )
            )

        self.stdout.write(self.style.SUCCESS("Storage reconciliation complete."))

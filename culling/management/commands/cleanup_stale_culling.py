# culling/management/commands/cleanup_stale_culling.py
import os
import shutil
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.core.management.base import BaseCommand
from culling.models import CullingSession


class Command(BaseCommand):
    help = "Purges staging directories for sessions older than 7 days"

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=7)
        stale_sessions = CullingSession.objects.filter(
            status__in=["staging", "draft", "analyzed"],
            updated_at__lt=cutoff,
        )

        count = 0
        for s in stale_sessions:
            staging_dir = os.path.join(settings.MEDIA_ROOT, "culling_staging", str(s.id))
            if os.path.exists(staging_dir):
                shutil.rmtree(staging_dir, ignore_errors=True)
            s.delete()
            count += 1

        self.stdout.write(self.style.SUCCESS(f"Cleaned up {count} stale culling sessions."))

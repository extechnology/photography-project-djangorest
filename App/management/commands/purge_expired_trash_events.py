from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from App.LiveEvents.event_models import LiveEvent


class Command(BaseCommand):
    help = 'Permanently delete events that have been in trash for more than 15 days.'

    def handle(self, *args, **options):
        threshold = timezone.now() - timedelta(days=15)
        expired_events = LiveEvent.objects.filter(status='trash', deleted_at__lte=threshold)
        count = expired_events.count()

        for event in expired_events:
            for media in event.media.all():
                try:
                    media.file.delete(save=False)
                    if media.thumbnail:
                        media.thumbnail.delete(save=False)
                except Exception:
                    pass
            event.delete()

        self.stdout.write(self.style.SUCCESS(f'Successfully purged {count} expired trash event(s).'))

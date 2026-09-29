import logging
from django.core.management.base import BaseCommand
from App.LiveEvents.event_models import LiveEvent, EventMedia
from App.LiveEvents.event_tasks import process_face_embeddings_task
from App.Storage.storage_models import Gallery, Media
from App.Storage.services.face_service import FaceService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Re-indexes all LiveEvent photos and Gallery photos with the deep learning YuNet+SFace FaceEngine."

    def add_arguments(self, parser):
        parser.add_argument(
            '--event-id',
            type=str,
            help='Re-index only a specific LiveEvent by UUID or slug',
        )
        parser.add_argument(
            '--gallery-id',
            type=str,
            help='Re-index only a specific Gallery by UUID or slug',
        )

    def handle(self, *args, **options):
        event_filter = options.get('event_id')
        gallery_filter = options.get('gallery_id')

        self.stdout.write(self.style.NOTICE("Starting AI Facial Biometric Re-indexing..."))

        total_event_photos = 0
        total_event_faces = 0

        # 1. Process LiveEvent Media
        event_qs = LiveEvent.objects.all()
        if event_filter:
            event_qs = event_qs.filter(id=event_filter) if len(event_filter) == 36 else event_qs.filter(slug=event_filter)

        for event in event_qs:
            photos = event.media.filter(media_type='photo')
            self.stdout.write(f"Indexing Event: {event.title} ({photos.count()} photos)...")
            for media in photos:
                try:
                    faces_count = process_face_embeddings_task(str(media.id))
                    total_event_photos += 1
                    total_event_faces += faces_count
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Failed to index {media.original_filename}: {e}"))

        # 2. Process Studio Gallery Media
        total_gallery_photos = 0
        total_gallery_faces = 0

        gallery_qs = Gallery.objects.filter(face_search_enabled=True)
        if gallery_filter:
            gallery_qs = gallery_qs.filter(id=gallery_filter) if len(gallery_filter) == 36 else gallery_qs.filter(slug=gallery_filter)

        for gallery in gallery_qs:
            photos = gallery.media_items.filter(deleted_at__isnull=True, media_type='photo')
            self.stdout.write(f"Indexing Gallery: {gallery.title} ({photos.count()} photos)...")
            for media in photos:
                try:
                    faces_count = FaceService.process_and_index_media_faces(media)
                    total_gallery_photos += 1
                    total_gallery_faces += faces_count
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Failed to index {media.original_filename}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Finished! Indexed {total_event_photos} event photos ({total_event_faces} faces) "
            f"and {total_gallery_photos} gallery photos ({total_gallery_faces} faces)."
        ))

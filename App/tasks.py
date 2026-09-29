"""
Celery task discovery for App module.
Aggregates tasks from sub-modules so Celery autodiscovery finds all project tasks.
"""
from App.LiveEvents.event_tasks import (
    process_face_embeddings_task,
    compare_selfie_faces_task,
    purge_expired_trash_events_task,
)
from App.Storage.tasks import (
    process_media_derivatives_and_faces_task,
    generate_bulk_download_archive_task,
)

__all__ = [
    'process_face_embeddings_task',
    'compare_selfie_faces_task',
    'purge_expired_trash_events_task',
    'process_media_derivatives_and_faces_task',
    'generate_bulk_download_archive_task',
]

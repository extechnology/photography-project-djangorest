"""
Celery task discovery module for LiveEvents.
Re-exports tasks from event_tasks so app.autodiscover_tasks() finds them automatically.
"""
from .event_tasks import (
    process_face_embeddings_task,
    compare_selfie_faces_task,
    purge_expired_trash_events_task,
    detect_faces_in_bytes,
    extract_512_dim_features,
)

__all__ = [
    'process_face_embeddings_task',
    'compare_selfie_faces_task',
    'purge_expired_trash_events_task',
    'detect_faces_in_bytes',
    'extract_512_dim_features',
]

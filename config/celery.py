import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")

app.config_from_object(
    "django.conf:settings",
    namespace="CELERY"
)

# Use ExShare queue
app.conf.task_default_queue = "exshare"
app.conf.task_default_exchange = "exshare"
app.conf.task_default_routing_key = "exshare"

# Dedicated Task Routing Queues to prevent head-of-line blocking
app.conf.task_routes = {
    "App.Storage.tasks.process_media_derivatives_and_faces_task": {"queue": "media_processing"},
    "App.Storage.tasks.generate_bulk_download_archive_task": {"queue": "zip_downloads"},
    "App.Storage.tasks.generate_selective_bulk_zip_task": {"queue": "zip_downloads"},
    "App.Storage.tasks.cleanup_expired_reservations_and_jobs_task": {"queue": "maintenance"},
    "events.process_face_embeddings": {"queue": "face_recognition"},
    "events.compare_selfie_faces": {"queue": "face_recognition"},
    "events.purge_expired_trash": {"queue": "maintenance"},
    "culling.tasks.*": {"queue": "ai_culling"},
    "App.Culling.tasks.*": {"queue": "ai_culling"},
    "App.Subscriptions.tasks.*": {"queue": "maintenance"},
}

app.conf.worker_prefetch_multiplier = 1
app.conf.task_acks_late = True

app.autodiscover_tasks()


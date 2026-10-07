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

app.autodiscover_tasks()

# celery -A config worker --loglevel=info --pool=solo
# celery -A config beat --loglevel=INFO
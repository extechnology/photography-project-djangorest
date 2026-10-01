from django.apps import AppConfig


class AppConfig(AppConfig):
    name = 'App'

    def ready(self):
        # Configure SQLite for high concurrency (WAL mode + 30s busy timeout)
        from django.db.backends.signals import connection_created
        from django.dispatch import receiver

        @receiver(connection_created)
        def configure_sqlite(sender, connection, **kwargs):
            if connection.vendor == 'sqlite':
                with connection.cursor() as cursor:
                    cursor.execute('PRAGMA journal_mode = WAL;')
                    cursor.execute('PRAGMA synchronous = NORMAL;')
                    cursor.execute('PRAGMA busy_timeout = 30000;')

        # Validate FaceEngine models on startup (ensures models exist for production/Celery)
        try:
            from App.face_engine import get_model_dir, YUNET_FILENAME, SFACE_FILENAME, ensure_models_exist
            import threading
            m_dir = get_model_dir()
            if not ((m_dir / YUNET_FILENAME).exists() and (m_dir / SFACE_FILENAME).exists()):
                threading.Thread(target=ensure_models_exist, daemon=True).start()
        except Exception:
            pass

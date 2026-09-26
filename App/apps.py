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

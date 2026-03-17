from django.apps import AppConfig


class ArchiveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "archive"
    verbose_name = "Архив"

    def ready(self):
        import archive.signals  # noqa: F401

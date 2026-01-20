from django.apps import AppConfig
from django.db.models.fields.files import FieldFile
import os


class AryuappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "aryuapp"

    def ready(self):
        # Load signals
        import aryuapp.signals  # noqa

        # GLOBAL PATCH — NEVER CRASH ON MISSING FILES
        original_size = FieldFile.size

        def safe_size(self):
            try:
                if not self.name:
                    return 0
                if not os.path.exists(self.path):
                    return 0
                return original_size.__get__(self, FieldFile)()
            except Exception:
                return 0

        FieldFile.size = property(safe_size)
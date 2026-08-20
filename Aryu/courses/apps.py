# courses/apps.py

from django.apps import AppConfig


class CoursesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'courses'

    def ready(self):
        # Register the signal when Django starts
        import courses.signals  # noqa
   
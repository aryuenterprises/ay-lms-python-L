from django.apps import AppConfig
from pathlib import Path

class WebinarBonusConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "webinar_bonus"
    path = str(Path(__file__).resolve().parent)
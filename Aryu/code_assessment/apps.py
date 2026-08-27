"""
Code Assessment Application Configuration.
"""
from django.apps import AppConfig


class CodeAssessmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "code_assessment"
    verbose_name = "Online Code Assessment"

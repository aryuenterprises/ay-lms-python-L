from django.db import models

# from django.conf import settings

# User = settings.AUTH_USER_MODEL
class Bonus(models.Model):
    webinar = models.ForeignKey(
        'webinar.Webinar',
        related_name="bonus",
        on_delete=models.CASCADE
    )

    description = models.CharField()
    created_at = models.DateTimeField(auto_now_add=True)

class BonusFile(models.Model):
    bonus = models.ForeignKey(
        Bonus,
        related_name="files",
        on_delete=models.CASCADE
    )
    file = models.FileField(upload_to="bonus_pdfs/")

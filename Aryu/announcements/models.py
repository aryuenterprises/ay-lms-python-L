from django.db import models

# Create your models here.

class Announcement(models.Model):
    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    content = models.TextField()
    content_pic = models.ImageField(upload_to='announcements/', blank=True, null=True)
    background_pic = models.ImageField(upload_to='announcements/', blank=True, null=True)
    audience = models.CharField(
        max_length=20,
        default="all"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = "aryuapp_announcement"
        ordering = ['-created_at']

    def __str__(self):
        return self.title
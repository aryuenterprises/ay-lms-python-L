from django.db import models
from django.db import models
from django.core.exceptions import ValidationError
import os
# Create your models here.

def validate_image_size(value):

    max_size = 2 * 1024 * 1024  # 2 MB

    if value.size > max_size:
        raise ValidationError("Image size should not exceed 2 MB.")
def validate_file(value):

    ext = os.path.splitext(value.name)[1].lower()

    valid_extensions = ['.pdf', '.doc', '.docx']

    if ext not in valid_extensions:
        raise ValidationError(
            "Only PDF and Word files are allowed."
        )

    max_size = 5 * 1024 * 1024  # 5 MB

    if value.size > max_size:
        raise ValidationError(
            "File size should not exceed 5 MB."
        )

class Resources(models.Model):

    title = models.CharField(max_length=250)
    slug = models.CharField(max_length=250)
    image = models.ImageField(upload_to='resources/',validators=[validate_image_size])
    file = models.FileField(upload_to='resources/',validators=[validate_file])
    status = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)


    
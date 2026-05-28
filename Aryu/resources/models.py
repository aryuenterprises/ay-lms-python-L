from django.db import models
from django.core.exceptions import ValidationError
import os


# =====================================================
# VALIDATIONS
# =====================================================

def validate_image_size(value):

    max_size = 2 * 1024 * 1024

    if value.size > max_size:

        raise ValidationError("Image size should not exceed 2 MB.")


def validate_file(value):

    ext = os.path.splitext(value.name)[1].lower()
    valid_extensions = [".pdf",".doc",".docx"]

    if ext not in valid_extensions:

        raise ValidationError("Only PDF and Word files are allowed.")

    max_size = 5 * 1024 * 1024

    if value.size > max_size:

        raise ValidationError("File size should not exceed 5 MB.")


# =====================================================
# RESOURCES
# =====================================================

class Resources(models.Model):

    title = models.CharField(max_length=250)
    slug = models.CharField(max_length=250)
    image = models.ImageField(upload_to="resources/",validators=[validate_image_size])
    file = models.FileField(upload_to="resources/",validators=[validate_file])
    status = models.CharField(max_length=100)
    form = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):

        return self.title


# =====================================================
# FORM
# =====================================================

# class Form(models.Model):

#     resource = models.ForeignKey(Resources,on_delete=models.CASCADE,related_name="resource_forms")
#     name = models.CharField(max_length=250)
#     email = models.EmailField()
#     phone = models.CharField(max_length=15,null=True,blank=True)
#     city = models.CharField(max_length=255,null=True,blank=True)
#     interesed_course = models.BooleanField(default=True)
#     prefered_course = models.CharField(max_length=255,null=True,blank=True)
#     created_at = models.DateTimeField(auto_now_add=True)

#     def __str__(self):

#         return self.name
from django.db import models


class Ebook(models.Model):
    title = models.CharField(max_length = 550)
    slug = models.SlugField(max_length = 250,unique = True)
    sub_title = models.CharField(max_length = 250, default = True, null = True)
    key = models.CharField(default = True, null = True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    regular_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    ebook_image = models.FileField(upload_to='ebook_images/', null=True, blank=True)
    description = models.TextField()
    pdf = models.FileField(upload_to = 'ebook_pdf/', null = True, blank = True)
    is_paid = models.BooleanField(default = False)
    is_deleted = models.BooleanField(default=False)
    seats_available = models.PositiveIntegerField(default=10)
    created_by = models.CharField(max_length=10, null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)
    language = models.CharField(max_length=50,default="Tamil")
    tags = models.JSONField(null=True, blank=True)
    order = models.IntegerField(null=True, blank=True) 
    youtube = models.URLField(
        blank=True,
        null=True,
        help_text="YouTube/Vimeo embed URL"
    )
    testimonial = models.URLField(
        blank=True,
        null=True,
        help_text="YouTube/Vimeo embed URL"
    )
    popular = models.BooleanField(default=False)
class EbookSEO(models.Model):
    ebook = models.ForeignKey(
        Ebook,
        related_name='seo',   # unique
        on_delete=models.CASCADE
    )
    seo_title = models.CharField(max_length=250)
    seo_description = models.TextField()
    seo_image = models.ImageField(upload_to='seo_images/', null=True, blank=True)


class EbookTool(models.Model):
    ebook = models.ForeignKey(
        Ebook,
        related_name='tools',   # ✅ unique
        on_delete=models.CASCADE
    )
    tool_title = models.CharField(max_length=250)
    tool_image = models.ImageField(upload_to='tool_images/', null=True, blank=True)


class EbookFAQ(models.Model):
    ebook = models.ForeignKey(
        Ebook,
        related_name='faqs',   # ✅ unique
        on_delete=models.CASCADE
    )
    faq_question = models.CharField(max_length=500)
    faq_answer = models.TextField()

def ebook_profile_pic_path(instance, filename):
        reg_id = str(instance.registration_id).replace(" ", "_")
        return f'profile_pics/{reg_id}/{filename}'

class EbookRegistration(models.Model):
    ebook = models.ForeignKey(
        "ebook.Ebook",
        on_delete=models.CASCADE,
        related_name="registrations"
    )

    name = models.CharField(max_length=250, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    password = models.CharField(max_length=250, null=True, blank=True)
    phone = models.CharField(max_length = 100)
    profile_pic = models.ImageField(upload_to=ebook_profile_pic_path, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    is_paid = models.BooleanField(default=False)

    payment_transaction = models.ForeignKey(
    "payments.PaymentTransaction",
    on_delete=models.CASCADE,
    related_name="ebook_registrations",
    null=True,
    blank=True
)

    is_registration_open = models.BooleanField(default=True)
    registered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.phone} - {self.ebook.title}"

    def set_password(self, raw_password):
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        from django.contrib.auth.hashers import check_password
        if not self.password:
            return False
        return check_password(raw_password, self.password)
    
class Reviews(models.Model):
    registration = models.OneToOneField(   #  One review per registration
        EbookRegistration,
        on_delete=models.CASCADE,
        related_name='review',
        null = True
    )

    rating = models.PositiveIntegerField()

    comment = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    is_approved = models.BooleanField(default = False)
    email = models.EmailField()
    

    def __str__(self):
        return f"{self.registration.name} - {self.rating}"
    

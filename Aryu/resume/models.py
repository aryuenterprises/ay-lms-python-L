from django.db import models



class ResumeRegistration(models.Model):
    first_name = models.CharField(max_length = 250)
    last_name = models.CharField(max_length = 250)
    email = models.EmailField(null = True , blank = True)
    phone = models.CharField(max_length = 50 , null = True , blank = True)
    password = models.CharField(max_length = 150 , null = True , blank = True)
    city = models.CharField(max_length = 100 , null = True , blank = True)
    state = models.CharField(max_length = 100 , null = True , blank = True)
    country = models.CharField(max_length = 100 , null = True , blank = True)
    is_verified = models.BooleanField(default=False)
    current_subscription = models.ForeignKey(
        "UserSubscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_users"
    )
    last_login = models.DateTimeField(
        null=True,
        blank=True
    )
    status = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)

    reset_otp_hash = models.CharField(
        max_length=255,
        null=True,
        blank=True
    )

    reset_otp_expiry = models.DateTimeField(
        null=True,
        blank=True
    )

    reset_otp_attempts = models.IntegerField(
        default=0
    )

    reset_verified = models.BooleanField(
        default=False
    )

    class Meta:
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["is_verified"]),
        ]

    def __str__(self):
        return self.first_name
    
class Contact(models.Model):
    full_name = models.CharField(max_length = 100)
    email = models.EmailField(null = True,blank=True)
    phone = models.CharField(max_length = 50 , default = True , null = True)
    message = models.CharField(null = True , default = True)
    created_at = models.DateTimeField(auto_now_add = True)

class Subscription(models.Model):

    name = models.CharField(max_length=100)

    slug = models.SlugField(unique=True, null=True, blank=True)

    description = models.TextField(
        null=True,
        blank=True
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    discount_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    billing_type = models.CharField(
        max_length=20,
        default="monthly"
    )

    duration_days = models.IntegerField(
        default=30
    )

    limit = models.CharField(
        max_length=50,
        default="free"
    )

    order = models.IntegerField(default=0)

    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:

        ordering = ["order"]

    def __str__(self):
        return self.name

class UserSubscription(models.Model):


    user = models.ForeignKey(
        "resume.ResumeRegistration",
        on_delete=models.CASCADE,
        related_name="subscriptions"
    )

    subscription = models.ForeignKey(
        "resume.Subscription",
        on_delete=models.CASCADE
    )

    payment_transaction = models.ForeignKey(
        "payments.PaymentTransaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    start_date = models.DateTimeField()

    end_date = models.DateTimeField(
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        default="active"
    )

    renewal_mail_sent_3_days = models.BooleanField(
        default=False
    )

    renewal_mail_sent_1_day = models.BooleanField(
        default=False
    )

    expiry_mail_sent = models.BooleanField(
        default=False
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:

        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["status"]),
        ]

class ResumeTemplate(models.Model):
    """
    Stores the blueprint of the resume template.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    
    # Links to the subscription tiers. 
    tier = models.CharField(
        max_length=20, 
        default='free',
        help_text="Minimum subscription tier required to use this template."
    )
    
    # Define the structure of the template using JSON.
    # Example: [{"section": "Education", "fields": ["degree", "college", "year"]}, {"section": "Skills", "fields": ["skill_name"]}]
    structure = models.JSONField(
        default=list, 
        help_text="Defines the sections and arbitrary columns for this template."
    )
    
    # You can store HTML/CSS structure here or path to a React/Vue component
    html_markup = models.TextField(null=True, blank=True) 
    
    thumbnail = models.ImageField(upload_to='template_thumbnails/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.get_tier_display()})"

class UserResume(models.Model):
    user = models.ForeignKey(
        'ResumeRegistration', 
        on_delete=models.CASCADE, 
        related_name='resumes'
    )
    template = models.ForeignKey(
        'ResumeTemplate', 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='used_by'
    )
    resume_title = models.CharField(max_length=255, default="My Resume")
    
    # THE OPTIMIZATION: One dictionary to rule them all
    # Example: {"Education": [...], "Experience": [...], "Skills": [...]}
    resume_data = models.JSONField(default=dict)
    
    last_completed_section = models.CharField(max_length=100, null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.first_name}'s {self.resume_title}"


class PaymentHistory(models.Model):
    name = models.CharField(max_length = 100)
    plan = models.DecimalField(max_digits=5 ,decimal_places=2)
    price = models.DecimalField(max_digits =5,decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add = True)
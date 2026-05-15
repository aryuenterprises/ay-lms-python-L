
# Create your models here.
from django.db import models
import uuid
from django.conf import settings

User = settings.AUTH_USER_MODEL


class Webinar(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    slug = models.SlugField(max_length=255, unique=True)
    webinar_image = models.ImageField(upload_to='webinar_images/', null=True, blank=True)

    title = models.CharField(max_length=255)
    sub_title = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField()
    mentor = models.CharField(max_length=100)
    language = models.CharField(max_length=50, default='Tamil')
    video_url = models.URLField(
        blank=True,
        null=True,
        help_text="YouTube/Vimeo embed URL"
    )
    waba_link = models.URLField(blank=True, null=True, help_text="whatsapp redirect url")
    created_by = models.CharField(max_length=50)
    created_by_type = models.CharField(max_length=20,)
    mode = models.BooleanField(default=True, help_text="True for online, False for offline")
    seats_available = models.PositiveIntegerField(default=10)
    scheduled_start = models.DateTimeField()
    registration_link = models.URLField(blank=True, null=True)
    zoom_link = models.URLField(blank=True, null=True)
    zoom_meeting_id = models.CharField(max_length=50, blank=True, null=True)
    zoom_join_url = models.URLField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    regular_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(max_length=20,default='DRAFT')
    webinar_status = models.BooleanField(default=True, help_text="True for active, False for inactive")
    is_paid = models.BooleanField(default=False)
    is_registration_open = models.BooleanField(default=True)
    is_completed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    
    def get_image_url(self):
        if self.webinar_image:
            return f"https://portal.aryuacademy.com/api{self.webinar_image.url}"
        return None

    def __str__(self):
        return self.title
    
class WebinarTool(models.Model):
    webinar = models.ForeignKey(
        Webinar,
        related_name="tools",
        on_delete=models.CASCADE
    )

    tools_title = models.CharField(max_length=100)
    tools_image = models.ImageField(upload_to="tool_images/")
    is_deleted = models.BooleanField(default=False)

    def __str__(self):
        return self.tools_title

class webinar_metadata(models.Model):
    webinar = models.ForeignKey(
        Webinar,
        related_name="metadata",
        on_delete=models.CASCADE
    )

    meta_title = models.CharField(max_length=100)
    meta_description = models.TextField()
    meta_image = models.ImageField(upload_to="webinar_meta_images/")
    is_deleted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.meta_title} → {self.webinar.title}"

class Webinar_FAQ(models.Model):
    webinar = models.ForeignKey(
        Webinar,
        related_name="faqs",
        on_delete=models.CASCADE
    )

    question = models.CharField(max_length=255)
    answer = models.TextField()
    is_deleted = models.BooleanField(default=False)

    def __str__(self):
        return f"FAQ: {self.question} → {self.webinar.title}"

class WebinarRegistration(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    webinar = models.ForeignKey(
        Webinar,
        on_delete=models.CASCADE,
        related_name='registrations',
        db_index=True
    )

    # 🔹 Snapshot fields (what user submitted)
    name = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=15)
    email = models.EmailField(blank=True, null=True)
    course = models.CharField(max_length=100, blank=True, null=True)
    #profession, state, city
    profession = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    wants_reminder = models.BooleanField(default=True)
    is_paid = models.BooleanField(default=False)
    payment_transaction = models.ForeignKey(
        'payments.PaymentTransaction',
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    # 🔹 CRM link (optional but powerful)
    lead = models.ForeignKey(
        'aryuapp.Lead',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='webinar_registrations'
    )
    certificate_sent = models.BooleanField(default=False)
    attended = models.BooleanField(default=False)
    source = models.CharField(
        max_length=100,
        blank=True,
        null = True
    )

    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('webinar', 'phone')
        indexes = [
            models.Index(fields=["-registered_at"]),
            models.Index(fields=["webinar"]),
        ]

    def __str__(self):
        return f"{self.name or 'Unknown'} ({self.phone}) → {self.webinar}"

class WebinarSession(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    webinar = models.OneToOneField(
        Webinar,
        on_delete=models.CASCADE,
        related_name='session',
        db_index=True
    )

    zoom_meeting_id = models.CharField(
        max_length=50,
        help_text="Zoom meeting ID used for attendance sync"
    )

    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    started_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    is_cancelled = models.BooleanField(default=False)

    def is_live(self):
        return self.started_at and not self.ended_at and not self.is_cancelled

class WebinarAttendanceLog(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)

    registration = models.ForeignKey(
        WebinarRegistration,
        on_delete=models.CASCADE,
        related_name="attendance_logs",
        db_index=True,
    )

    join_time = models.DateTimeField()
    leave_time = models.DateTimeField()
    duration_seconds = models.PositiveIntegerField()

    source = models.CharField(
        max_length=20,
        default="zoom"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["join_time"]
        indexes = [
            models.Index(fields=["-registration"]),
        ]


class WebinarAttendanceSummary(models.Model):
    registration = models.OneToOneField(
        WebinarRegistration,
        on_delete=models.CASCADE,
        related_name="attendance_summary",
        db_index=True,
    )

    total_duration_seconds = models.PositiveIntegerField(default=0)
    join_count = models.PositiveIntegerField(default=0)

    first_join_at = models.DateTimeField(null=True, blank=True)
    last_leave_at = models.DateTimeField(null=True, blank=True)

    eligible_for_certificate = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)

class WebinarFeedback(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    webinar = models.ForeignKey(
        Webinar,
        on_delete=models.CASCADE,
        related_name="feedbacks",
        db_index=True,
    )

    registration = models.OneToOneField(
        WebinarRegistration,
        on_delete=models.CASCADE,
        related_name="feedback",
        null=True,
        blank=True,
        db_index=True
    )
    phone = models.CharField(max_length=15,default="91")

     # Overall experience
    overall_rating = models.PositiveSmallIntegerField()  # 1–5
    name = models.CharField(max_length=100, blank=True, null=True)

    # Content & delivery
    content_quality = models.PositiveSmallIntegerField()  # 1–5
    speaker_quality = models.PositiveSmallIntegerField()  # 1–5
    pace_of_session = models.PositiveSmallIntegerField()  # 1–5
    
    # Engagement
    interaction_rating = models.PositiveSmallIntegerField()  # 1–5

    # 🔹 Learning outcome
    learned_something_new = models.BooleanField(default=False)

    # 🔹 Recommendation
    would_recommend = models.BooleanField(default=False)

    # 🔹 Open feedback
    liked_most = models.TextField(blank=True, null=True)
    improvement_suggestions = models.TextField(blank=True, null=True)
    additional_comments = models.TextField(blank=True, null=True)

    #images of the ratings
    rating_screenshot= models.ImageField(upload_to='webinar_feedback_ratings/', null=True, blank=True)

    # 🔹 Business signals
    interested_in_future_webinars = models.BooleanField(default=False)
    interested_in_paid_courses = models.BooleanField(default=False)

    # 🔹 Meta
    submitted_at = models.DateTimeField(auto_now_add=True)
    submitted_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "webinar_feedback"
        unique_together = ("webinar", "registration")

    def __str__(self):
        return f"Feedback → {self.webinar.title}"
    
class Form(models.Model):
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True
    )
    form_image = models.ImageField(upload_to='form_images/', null=True, blank=True)
    slug = models.SlugField(max_length=255, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_by = models.CharField(max_length=50)
    created_by_type = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["created_at"]),
        ]

class Question(models.Model):

    form = models.ForeignKey(Form, related_name="questions", on_delete=models.CASCADE, db_index=True)
    label = models.CharField(max_length=500)
    type = models.CharField(max_length=20)
    is_required = models.BooleanField(default=False)
    order = models.IntegerField()
    validation_rules = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order"]
        indexes = [
            models.Index(fields=["form"]),
            models.Index(fields=["order"]),
        ]

class QuestionOption(models.Model):
    question = models.ForeignKey(Question, related_name="options", on_delete=models.CASCADE, db_index=True)
    value = models.CharField(max_length=255)
    order = models.IntegerField()

    class Meta:
        ordering = ["order"]
        indexes = [
            models.Index(fields=["question"]),
        ]

class Submission(models.Model):
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True
    )
    is_deleted = models.BooleanField(default=False)
    form = models.ForeignKey(Form, on_delete=models.CASCADE, db_index=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["form"]),
            models.Index(fields=["submitted_at"]),
        ]

class Answer(models.Model):
    submission = models.ForeignKey(Submission, related_name="answers", on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)

    value_text = models.TextField(null=True, blank=True)
    value_json = models.JSONField(null=True, blank=True)  # for checkbox
    value_number = models.FloatField(null=True, blank=True)
    value_file = models.FileField(upload_to="form_uploads/", null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=["submission"]),
            models.Index(fields=["question"]),
            models.Index(fields=["question", "value_text"]),
        ]

   



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

    created_by = models.CharField(max_length=50)
    created_by_type = models.CharField(max_length=20,)

    scheduled_start = models.DateTimeField()
    registration_link = models.URLField(blank=True, null=True)
    zoom_link = models.URLField(blank=True, null=True)
    zoom_meeting_id = models.CharField(max_length=50, blank=True, null=True)
    zoom_join_url = models.URLField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    regular_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(max_length=20,default='DRAFT')
    is_paid = models.BooleanField(default=False)
    is_registration_open = models.BooleanField(default=True)
    is_completed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    def can_register(self):
        return (
            self.status in ['DRAFT', 'SCHEDULED']
            and self.is_registration_open
        )

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

    def __str__(self):
        return f"{self.meta_title} → {self.webinar.title}"

class WebinarRegistration(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    webinar = models.ForeignKey(
        Webinar,
        on_delete=models.CASCADE,
        related_name='registrations'
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
    wants_reminder = models.BooleanField(default=False)
    is_paid = models.BooleanField(default=False)
    payment_transaction = models.ForeignKey(
        'aryuapp.PaymentTransaction',
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
        default='webinar'
    )

    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('webinar', 'phone')

    def __str__(self):
        return f"{self.name or 'Unknown'} ({self.phone}) → {self.webinar}"

class WebinarSession(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    webinar = models.OneToOneField(
        Webinar,
        on_delete=models.CASCADE,
        related_name='session'
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
        related_name="attendance_logs"
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

class WebinarAttendanceSummary(models.Model):
    registration = models.OneToOneField(
        WebinarRegistration,
        on_delete=models.CASCADE,
        related_name="attendance_summary"
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
        related_name="feedbacks"
    )

    registration = models.OneToOneField(
        WebinarRegistration,
        on_delete=models.CASCADE,
        related_name="feedback",
        null=True,
        blank=True
    )
    phone = models.CharField(max_length=15)

     # Overall experience
    overall_rating = models.PositiveSmallIntegerField()  # 1–5

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
    
    


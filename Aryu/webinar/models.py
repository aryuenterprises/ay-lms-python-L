
# Create your models here.
from django.db import models
import uuid
from django.conf import settings

User = settings.AUTH_USER_MODEL


class Webinar(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    title = models.CharField(max_length=255)
    description = models.TextField()

    created_by = models.CharField(max_length=50)
    created_by_type = models.CharField(max_length=20,)

    scheduled_start = models.DateTimeField()

    zoom_link = models.URLField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

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


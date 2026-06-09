from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from aryuapp.models import User, Note

# Create your models here.
class Lead(models.Model):


    # BASIC INFO

    name = models.CharField(max_length=150, blank=True, null=True)
    phone = models.CharField(max_length=20, db_index=True)
    alternate_phone = models.CharField(max_length=20, blank=True, null=True)

    email = models.EmailField(blank=True, null=True)

    gender = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    qualification = models.CharField(max_length=150, blank=True, null=True)

    user_type = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )
    message = models.CharField(max_length = 255,blank = True, null =True)


    # ADDRESS INFO

    address = models.TextField(blank=True, null=True)

    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)

    pincode = models.CharField(max_length=20, blank=True, null=True)


    # COURSE / SALES INFO

    course = models.CharField(max_length=200, blank=True, null=True)

    course_interested_in = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    interested = models.BooleanField(default=True)

    reason_to_join = models.TextField(blank=True, null=True)

    reason_not_joining = models.TextField(blank=True, null=True)

    fee_discussed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True
    )

    expected_join_month = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )


    # LEAD SOURCE

    source = models.CharField(max_length=150, blank=True, null=True)

    source_campaign = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    source_platform = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    # Example:
    # Instagram DM
    # WhatsApp
    # Facebook Ads
    # Walk-in
    # Referral
    # YouTube
    source_type = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )


    # FOLLOW-UP INFO

    followup_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_leads"
    )

    handled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_leads"
    )

    followup_date = models.DateField(blank=True, null=True)

    next_followup_date = models.DateField(blank=True, null=True)

    last_contacted_at = models.DateTimeField(blank=True, null=True)


    # TRACKING COUNTS

    no_of_dms = models.PositiveIntegerField(default=0)

    no_of_calls = models.PositiveIntegerField(default=0)

    no_of_followups = models.PositiveIntegerField(default=0)


    # STATUS MANAGEMENT

    status = models.CharField(
        max_length=50,
        default="new",
        db_index=True
    )

    lead_stage = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    priority = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )


    # NOTES


    notes = GenericRelation(
        Note,
        related_query_name="lead_notes"
    )


    # SYSTEM FLAGS

    is_archived = models.BooleanField(default=False)

    is_duplicate = models.BooleanField(default=False)

    is_converted = models.BooleanField(default=False)


    # TIMESTAMPS

    joined_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)


    # META

    class Meta:
        ordering = ["-created_at"]
        db_table = 'aryuapp_lead'
        indexes = [
            models.Index(fields=["phone"]),
            models.Index(fields=["status"]),
            models.Index(fields=["followup_date"]),
            models.Index(fields=["next_followup_date"]),
        ]

    def __str__(self):
        return f"{self.name or 'Unknown'} - {self.phone}"


class LeadCallLog(models.Model):

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="call_logs"
    )

    call_type = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    called_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    call_time = models.DateTimeField(auto_now_add=True)

    duration_seconds = models.PositiveIntegerField(
        default=0
    )

    call_status = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    next_followup_date = models.DateField(
        blank=True,
        null=True
    )

    remarks = models.TextField(
        blank=True,
        null=True
    )

    recording_url = models.FileField(
        upload_to="call-recordings/",
        null=True,
        blank=True
    )

    notes = GenericRelation(
        Note,
        related_query_name="call_log_notes"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    

    class Meta:
        db_table = 'aryuapp_leadcalllog'
        ordering = ["-call_time"]

    def __str__(self):
        return f"{self.lead} - {self.call_status}"


class LeadDMLog(models.Model):

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="dm_logs"
    )

    handled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    platform = models.CharField(max_length=50)

    message_direction = models.CharField(max_length=20)

    message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'aryuapp_leaddmlog'
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.lead} - {self.platform}"


class LeadStatusHistory(models.Model):

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="status_history"
    )

    old_status = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    new_status = models.CharField(
        max_length=50
    )

    changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    remarks = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        db_table = 'aryuapp_leadstatushistory'
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.lead} - {self.old_status} -> {self.new_status}"


class LeadFollowUp(models.Model):

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="followups"
    )

    followup_date = models.DateField()

    followup_time = models.TimeField(
        blank=True,
        null=True
    )

    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=50,
        default="pending"
    )

    notes = GenericRelation(
        Note,
        related_query_name="call_log_notes"
    )

    completed_at = models.DateTimeField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        db_table = 'aryuapp_leadfollowup'
        ordering = ["followup_date"]

    def __str__(self):
        return f"{self.lead} - {self.followup_date}"
  
from django.db import models
from django.utils import timezone
from datetime import timedelta, datetime, time
import string
from datetime import date
from courses.models import Course
# Create your models here.



class ClassSchedule(models.Model):
    BUFFER_MINUTES = 0

    schedule_id = models.AutoField(primary_key=True)
    batch = models.ForeignKey('Batch', on_delete=models.CASCADE, related_name='schedules', null=True, blank=True)
    new_batch = models.ForeignKey(
        'NewBatch',
        on_delete=models.CASCADE,
        related_name='schedules',
        null=True, blank=True
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    trainer = models.ForeignKey('aryuapp.Trainer', on_delete=models.SET_NULL, null=True)
    scheduled_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    duration = models.DurationField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    is_online_class = models.BooleanField(default=False)
    is_class_cancelled = models.BooleanField(default=False)
    actual_end_time = models.DateTimeField(null=True, blank=True)
    meeting_link = models.URLField(max_length=500, null=True, blank=True)
    class_link = models.TextField(max_length=500, null=True, blank=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['trainer']),
            models.Index(fields=['course']),
            models.Index(fields=['created_by']),
            models.Index(fields=['created_by_type']),
            models.Index(fields=['scheduled_date']),
            models.Index(fields=["is_archived"]),
            models.Index(fields=['batch']),
            models.Index(fields=['new_batch']),
        ]
        db_table = "aryuapp_classschedule"

    def save(self, *args, **kwargs):
        if self.start_time and self.end_time:
            start_seconds = self.start_time.hour * 3600 + self.start_time.minute * 60 + self.start_time.second
            end_seconds = self.end_time.hour * 3600 + self.end_time.minute * 60 + self.end_time.second
            if end_seconds < start_seconds:
                end_seconds += 24 * 3600
            self.duration = timedelta(seconds=(end_seconds - start_seconds))
        super().save(*args, **kwargs)

    def scheduled_end_datetime(self):
        """Combine scheduled_date and end_time as a timezone-aware datetime."""
        return datetime.datetime.combine(
            self.scheduled_date,
            self.end_time,
            tzinfo=timezone.get_current_timezone()
        )

    def get_extra_time(self):
        if not self.actual_end_time:
            return timedelta(0)

        threshold = self.scheduled_end_datetime() + timedelta(minutes=self.BUFFER_MINUTES)

        if self.actual_end_time > threshold:
            return self.actual_end_time - threshold

        return timedelta(0)

    def get_planned_duration(self):
        """Return the planned class duration (from start_time to end_time)."""
        start_dt = datetime.datetime.combine(
            self.scheduled_date,
            self.start_time,
            tzinfo=timezone.get_current_timezone()
        )
        end_dt = self.scheduled_end_datetime()
        return end_dt - start_dt

    def get_actual_duration(self):
        """Return actual duration (from start_time to actual_end_time)."""
        if not self.actual_end_time:
            return None
        start_dt = datetime.datetime.combine(
            self.scheduled_date,
            self.start_time,
            tzinfo=timezone.get_current_timezone()
        )
        return self.actual_end_time - start_dt

    def __str__(self):
        return f"{self.course.course_name} - {self.scheduled_date} ({self.start_time}-{self.end_time})"

class RecurringSchedule(models.Model):
    recurring_id = models.AutoField(primary_key=True)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    batch = models.ForeignKey('Batch', on_delete=models.CASCADE, null=True, blank=True)
    new_batch = models.ForeignKey(
        'NewBatch',
        on_delete=models.CASCADE,
        related_name='recurring_schedules',
        null=True, blank=True
    )
    trainer = models.ForeignKey('aryuapp.Trainer', on_delete=models.CASCADE)

    recurrence_type = models.CharField(max_length=20, null=True, blank=True)
    days_of_week = models.JSONField(null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_online_class = models.BooleanField(default=False)
    class_link = models.TextField(max_length=500, null=True, blank=True)

    country = models.CharField(max_length=5, default="IN")
    subdiv = models.CharField(max_length=10, null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['new_batch']),
        ]
        db_table = "aryuapp_recurringschedule"
    
    def __str__(self):
        return f"Recurring {self.course.course_name} ({self.recurrence_type})"
      
class Batch(models.Model):
    batch_id = models.AutoField(primary_key=True)
    batch_name = models.CharField(max_length=100)
    title = models.CharField(max_length=100, null=True, blank=True)
    scheduled_date = models.DateField()
    status = models.BooleanField(default=True, null=True, blank=True)
    notes = models.CharField(max_length=255, null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'batch'
        indexes = [
            models.Index(fields=["is_archived", "status"]),
            models.Index(fields=["created_by", "created_by_type"]),
            models.Index(fields=["created_at"]),
        ]
        
    def save(self, *args, **kwargs):
        if not self.batch_name:
            year = self.scheduled_date.year if self.scheduled_date else date.today().year
            year_suffix = str(year)[-2:]  # '25' from 2025

            # Count batches in this year
            batches_this_year = Batch.objects.filter(scheduled_date__year=year).count()

            # Determine letter and number
            letter_index = batches_this_year // 999  # every 999 batches rolls to next letter
            sequence_number = (batches_this_year % 999) + 1  # 1–999

            # Get corresponding uppercase letter: A, B, C, etc.
            letters = string.ascii_uppercase
            if letter_index >= len(letters):
                raise ValueError("Batch limit exceeded for the year")

            letter = letters[letter_index]
            batch_code = f"AYA-AKIRA-{year_suffix}{letter}{sequence_number:03d}"
            self.batch_name = batch_code

        super().save(*args, **kwargs)
        
    def deactivate_batch(self, batch):
        IST = timezone.get_current_timezone()  # Or pytz.timezone("Asia/Kolkata") if using IST specifically
        now = timezone.now().astimezone(IST)

        # Step 1: Deactivate the batch
        batch.status = False
        batch.save(update_fields=["status"])

        # Step 2: Archive only upcoming schedules
        schedules_qs = ClassSchedule.objects.filter(
            batch=batch,
            is_archived=False
        )

        schedules_to_archive = []

        for sched in schedules_qs:
            start_time = sched.start_time or time(9, 0)
            end_time = sched.end_time or (sched.start_time or time(9, 0)) + timedelta(hours=1)

            start_dt = datetime.combine(sched.scheduled_date, start_time)
            end_dt = datetime.combine(sched.scheduled_date, end_time)
            start_dt = timezone.make_aware(start_dt, IST)
            end_dt = timezone.make_aware(end_dt, IST)

            if end_dt > now:
                schedules_to_archive.append(sched.schedule_id)

        ClassSchedule.objects.filter(schedule_id__in=schedules_to_archive).update(is_archived=True)

    def __str__(self):
        return f"{self.batch_name}"
    
class BatchCourseTrainer(models.Model):
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='batchcoursetrainer')
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    student = models.ForeignKey("aryuapp.Student", on_delete=models.CASCADE, db_column='student_id')
    trainer = models.ForeignKey("aryuapp.Trainer", on_delete=models.CASCADE)

    class Meta:
        indexes = [
            models.Index(fields=["trainer", "batch"]),
            models.Index(fields=["trainer", "student"]),
            models.Index(fields=["batch", "course"]),
        ]
        db_table = "aryuapp_batchcoursetrainer"

    def __str__(self):
        return f"{self.batch.batch_name}: {self.course.course_name} -> {self.trainer.full_name}"
    
class NewBatch(models.Model):
    batch_id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=100)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='new_batches')
    trainers = models.ManyToManyField(
        "aryuapp.Trainer",
        related_name="new_batches",
        blank=True
    )
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    slots = models.PositiveIntegerField(default=0)
    status = models.BooleanField(default=True)
    students = models.ManyToManyField("aryuapp.Student", related_name='new_batches', blank=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["batch_id"])
        ]
        db_table = "aryuapp_newbatch"

    def available_slots(self):
        return self.slots - self.students.count()
    
    def deactivate_batch(self):
        """
        Deactivate the batch and delete only upcoming schedules.
        Past schedules remain untouched.
        """
        IST = timezone.get_current_timezone()
        now = timezone.now().astimezone(IST)

        # Step 1: Mark this batch as archived / deactivated
        self.is_archived = True
        self.save(update_fields=["is_archived"])

        # Step 2: Get only schedules for this batch
        schedules_qs = ClassSchedule.objects.filter(
            new_batch=self,
            is_archived=False
        )

        upcoming_to_delete = []

        for sched in schedules_qs:
            start_dt = datetime.combine(
                sched.scheduled_date,
                sched.start_time or time(9, 0)
            )
            start_dt = timezone.make_aware(start_dt, IST)

            # Only delete schedules whose start time is in the future
            if start_dt > now:
                upcoming_to_delete.append(sched.schedule_id)

        # Step 3: Delete only future schedules
        ClassSchedule.objects.filter(schedule_id__in=upcoming_to_delete).delete()

    def __str__(self):
        return f"{self.title} ({self.course.course_name})"
    
class BatchRecording(models.Model):
    recording_id = models.AutoField(primary_key=True)

    batch = models.ForeignKey(
        "NewBatch",
        on_delete=models.CASCADE,
        related_name="recordings"
    )

    title = models.CharField(max_length=255)
    url = models.URLField(max_length=500)
    status = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "aryuapp_batch_recordings"

    def __str__(self):
        return self.title
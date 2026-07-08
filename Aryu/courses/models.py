from django.db import models
from django.utils import timezone
from datetime import datetime, time
import pytz
from django.core.validators import MaxValueValidator
# Create your models here.

class CourseCategory(models.Model):
    category_id = models.AutoField(primary_key=True)
    category_name = models.CharField(max_length=100)
    category_pic = models.ImageField(upload_to='course_categories/', null=True, blank=True)
    status = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "aryuapp_coursecategory"

    
    def cascade_category_deactivation(self):
        # Deactivate all courses under this category
        courses = Course.objects.filter(course_category=self, status="Active")
        IST = pytz.timezone("Asia/Kolkata")
        now = timezone.now().astimezone(IST)
        from aryuapp.models import NewBatch, ClassSchedule
        for course in courses:
            # Deactivate the course
            course.status = "Inactive"
            course.save(update_fields=["status"])

            # ---- Handle NewBatch only ----
            new_batches = NewBatch.objects.filter(course=course, is_archived=False)

            # Deactivate batches
            new_batches.update(status=False)

            # ---- Archive upcoming schedules (only new_batch) ----
            schedules_qs = ClassSchedule.objects.filter(
                course=course,
                new_batch__in=new_batches,
                is_archived=False
            ).select_related("new_batch")

            schedules_to_archive = []

            for sched in schedules_qs:
                sched_date = sched.scheduled_date
                start_time = sched.start_time or time(0, 0)
                end_time = sched.end_time or time(23, 59, 59)

                start_dt = IST.localize(datetime.combine(sched_date, start_time))
                end_dt = IST.localize(datetime.combine(sched_date, end_time))

                # Archive only future schedules
                if end_dt > now:
                    schedules_to_archive.append(sched.schedule_id)

            if schedules_to_archive:
                ClassSchedule.objects.filter(
                    schedule_id__in=schedules_to_archive
                ).update(is_archived=True)

    def __str__(self):
        return self.category_name
# class StudentCourseList(models.Model):
#     course = models.ForeignKey(
#         "courses.Course",
#         on_delete=models.CASCADE
#     )
#     student_id = models.ForeignKey()

class Course(models.Model):
    course_id = models.AutoField(primary_key=True)
    course_category = models.ForeignKey(
        CourseCategory,
        on_delete=models.CASCADE,
        related_name="courses"
    )
    course_name = models.CharField(max_length=255, null=True, blank=True)
    course_pic = models.ImageField(upload_to="courses/", null=True, blank=True)
    syllabus = models.FileField(upload_to="syllabus/", null=True, blank=True)
    duration = models.CharField(max_length=3, null=True, blank=True)
    duration_type = models.CharField(max_length=150,null=True,blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    internship_duration = models.CharField(max_length=3, null=True, blank=True)
    mode_of_delivery = models.CharField(max_length=100, null=True, blank=True)
    currency_type = models.CharField(max_length=100, null=True, blank=True)
    fee_type = models.CharField(max_length=100, null=True, blank=True)
    fee = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MaxValueValidator(100000)], null=True, blank=True
    )
    status = models.CharField(max_length=20, null=True, blank=True)
    notes = models.CharField(max_length=255, null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    video_url = models.URLField(
        blank=True,
        null=True,
        help_text="YouTube/Vimeo embed URL"
    )

    class Meta:
        db_table = "aryuapp_course"
        indexes = [
            models.Index(fields=['course_id']),
            models.Index(fields=['course_name']),
            models.Index(fields=['created_by', 'created_by_type']),
            models.Index(fields=['status', 'is_archived']),
        ]
    
    def deactivate_course(self, course):
        from aryuapp.models import NewBatch, ClassSchedule
        IST = pytz.timezone("Asia/Kolkata")
        now = timezone.now().astimezone(IST)

        # Step 1: Deactivate the course
        course.status = "Inactive"
        course.save(update_fields=["status"])

        # Step 2: Deactivate related new batches
        new_batches = NewBatch.objects.filter(course=course, is_archived=False)
        new_batches.update(status=False)

        # Step 3: Archive only upcoming schedules linked to NewBatch
        schedules_qs = ClassSchedule.objects.filter(
            course=course,
            new_batch__in=new_batches,
            is_archived=False
        ).select_related("new_batch")

        schedules_to_archive = []

        for sched in schedules_qs:
            sched_date = sched.scheduled_date
            start_time = sched.start_time or time(0, 0)
            end_time = sched.end_time or time(23, 59, 59)

            start_dt = IST.localize(datetime.combine(sched_date, start_time))
            end_dt = IST.localize(datetime.combine(sched_date, end_time))

            # Archive only future schedules
            if end_dt > now:
                schedules_to_archive.append(sched.schedule_id)

        if schedules_to_archive:
            ClassSchedule.objects.filter(
                schedule_id__in=schedules_to_archive
            ).update(is_archived=True)

    def __str__(self):
        return self.course_name

# class CourseVideo(models.Model):
#     video_url = models.URLField(
#         blank=True,
#         null=True,
#         help_text="YouTube/Vimeo embed URL"
#     )
#     # course_id = models.ForeignKey(Course,on_delete = models.CASCADE,related_name='Video')
#     course = models.ForeignKey(Course,on_delete = models.CASCADE,related_name='Video')
#     Title = models.CharField(max_length = 255,null = True,blank = True)
#     created_at =models.DateTimeField(auto_now_add = True)
#     is_archived = models.BooleanField(default=False)

class CourseVideo(models.Model):

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='videos'
    )

    video_url = models.URLField(
        blank=True,
        null=True
    )

    title = models.CharField(
        max_length=255,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    is_archived = models.BooleanField(default=False)

class Topic(models.Model):
    topic_id = models.AutoField(primary_key=True)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='topics')
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    create_by = models.ForeignKey("aryuapp.Trainer", on_delete=models.SET_NULL, null=True, related_name='created_topics', blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "aryuapp_topic"
    

class StudentTopicStatus(models.Model):
    student = models.ForeignKey("aryuapp.Student", on_delete=models.CASCADE, related_name="topic_statuses")
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="student_statuses")
    status = models.BooleanField(default=True)
    ratings = models.IntegerField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = "aryuapp_studenttopicstatus"
    
def syllabus_upload_path(instance, filename):
    return f'courses/{instance.course_id}/syllabus/{filename}'
 
 
class Syllabus(models.Model):
    course = models.ForeignKey(
        'Course',
        related_name='syllabus_items',
        on_delete=models.CASCADE
    )
    file = models.FileField(upload_to=syllabus_upload_path)

    # NEW — add these three lines
    file_name = models.CharField(max_length=255, blank=True)
    file_type = models.CharField(max_length=100, blank=True)
    file_size = models.PositiveIntegerField(default=0)

    title = models.CharField(max_length=255, blank=True, null=True)
    date = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    # NEW — add this method so the fields get populated on save
    def save(self, *args, **kwargs):
        if self.file and (not self.file_name or not self.file_size):
            import mimetypes
            self.file_name = self.file.name.split('/')[-1]
            guessed, _ = mimetypes.guess_type(self.file.name)
            self.file_type = guessed or ''
            self.file_size = self.file.size
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Syllabus({self.id}) - Course {self.course_id}'

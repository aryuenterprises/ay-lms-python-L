from django.db import models
from aryuapp.models import Student
from courses.models import Course
from batches.models import NewBatch


class GoogleReview(models.Model):
    id = models.AutoField(primary_key=True)
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        to_field='student_id',
        db_column='student_id',
        related_name='google_reviews'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='google_reviews'
    )
    batch = models.ForeignKey(
        NewBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='google_reviews'
    )
    is_google_review = models.BooleanField(default=False)
    review_date = models.DateField(null=True, blank=True, db_index=True)
    screenshot =  models.ImageField(upload_to="google_reviews/", null=True, blank=True)
    linkedin_review = models.BooleanField(default=False)
    linkedin_screenshot = models.ImageField(upload_to="linkedin_reviews/", null=True, blank=True)
    facebook_review = models.BooleanField(default=False)
    facebook_screenshot = models.ImageField(upload_to="facebook_reviews/", null=True, blank=True)
    trustpilot_review = models.BooleanField(default=False)
    trustpilot_screenshot = models.ImageField(upload_to="trustpilot_reviews/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'google_reviews'
        ordering = ['-review_date', '-created_at']
        indexes = [
            models.Index(fields=['review_date', 'course', 'batch']),
            models.Index(fields=['student', 'is_google_review']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['student', 'course', 'batch'], name='unique_student_course_batch_review')
        ]

    def __str__(self):
        return f"GoogleReview #{self.id} - Student {self.student_id}"

from django.db import models

# Create your models here.

class Feedback(models.Model):
    student_id = models.CharField(max_length=50)
    student_name = models.CharField(max_length=100)
    trainer_name = models.CharField(max_length=100)
    rating = models.PositiveIntegerField()  # e.g., 1 to 5
    comments = models.TextField()
    suggestions = models.TextField(blank=True, null=True)
    submitted_date = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = 'feedback'

    def __str__(self):
        return f"{self.student_name} → {self.trainer_name} ({self.rating}/5)"
    
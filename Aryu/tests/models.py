from django.db import models
from aryuapp.models import Student, Trainer
from courses.models import Course
# Create your models here.


class Test(models.Model):
    test_id = models.AutoField(primary_key=True)
    test_name = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(max_length=255, null=True, blank=True)
    duration = models.CharField(max_length=10, null=True, blank=True)  # in minutes
    total_marks = models.PositiveIntegerField(null=True, blank=True)
    pass_mark = models.IntegerField(null=True, blank=True)
    status= models.BooleanField(default=True)
    course_id = models.ForeignKey(Course, on_delete=models.CASCADE)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'aryuapp_test'

class TestQuestions(models.Model):
    question_id = models.AutoField(primary_key=True)
    test_id = models.ForeignKey(
        Test,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="test_questions"
    )
    question = models.CharField(max_length=255, null=True, blank=True)
    type = models.CharField(max_length=20) #mcq, written
    options = models.JSONField(max_length=255,null=True, blank=True, help_text="MCQ options from frontend")
    marks = models.PositiveBigIntegerField(null=True, blank=True)
    written_answer = models.TextField(null=True, blank=True, help_text="Correct answer for written questions")
    mcq_correct_option = models.CharField(max_length=255, null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'aryuapp_testquestions'

    def __str__(self):
        return f"{self.question} ({self.type})"

class StudentAnswers(models.Model):
    answer_id = models.AutoField(primary_key=True)
    student_id = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="student_answers",
        null=True, blank=True
    )
    question_id = models.ForeignKey(TestQuestions, on_delete=models.CASCADE, related_name="student_answers")
    test_id = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="student_test_answers")
    selected_option = models.TextField(null=True, blank=True)
    written_answer = models.TextField(null=True, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    question_text = models.TextField(null=True, blank=True)
    options_snapshot = models.JSONField(null=True, blank=True)
    correct_answer_snapshot = models.TextField(null=True, blank=True)
    marks_snapshot = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = 'aryuapp_studentanswers'

class TestResult(models.Model):
    result_id = models.AutoField(primary_key=True)
    student_id = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="test_results")
    test_id = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="test_results")
    score = models.PositiveIntegerField(null=True, blank=True)
    time_taken = models.DurationField(null=True, blank=True)
    evaluated_by = models.ForeignKey(
        Trainer,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="evaluated_results"
    )
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'aryuapp_testresult'



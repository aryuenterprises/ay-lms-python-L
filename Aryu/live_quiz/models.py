import uuid
import secrets
from django.db import models
from django.utils import timezone
from .common.models import SoftDeleteModel


class AdminUser(SoftDeleteModel):
    username = models.CharField(max_length=100, unique=True)
    password = models.CharField(max_length=255)
    role = models.CharField(max_length=50, default="quiz_admin")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'livequiz"."admin_user'

    def set_password(self, raw):
        import hashlib
        self.password = hashlib.sha256(raw.encode()).hexdigest()

    def verify_password(self, raw):
        import hashlib
        return self.password == hashlib.sha256(raw.encode()).hexdigest()

    def __str__(self):
        return self.username



class Room(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    max_participants = models.PositiveIntegerField(default=50)
    start_at = models.DateTimeField()
    started = models.BooleanField(default=False)

    current_question = models.ForeignKey(
        "Question", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by= models.CharField(max_length=100)
    updated_by = models.CharField(max_length=100)

    class Meta:
        db_table = 'livequiz"."room'

    def __str__(self):
        return self.title


class Question(SoftDeleteModel):

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField()
    question_type = models.CharField(max_length=20)
    text = models.TextField()
    config = models.JSONField()
    mark = models.PositiveIntegerField()
    timer_seconds = models.PositiveIntegerField(default=30)
    created_by = models.CharField(max_length=100)
    updated_by = models.CharField(max_length=100)

    class Meta:
        db_table = 'livequiz"."question'
        ordering = ["order"]

    def __str__(self):
        return f"{self.room.title} - Q{self.order}"


class Participant(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="participants")

    name = models.CharField(max_length=200)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)

    token = models.CharField(max_length=100, unique=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'livequiz"."participant'

    def generate_token(self):
        self.token = secrets.token_hex(32)

    def __str__(self):
        return self.name


class Answer(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")

    response = models.JSONField()
    is_correct = models.BooleanField(default=False)
    time_taken = models.FloatField()
    score = models.IntegerField(default=0)

    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'livequiz"."answer'
        unique_together = ("participant", "question")

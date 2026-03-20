from django.db import models
from aryuapp.models import Student, Trainer, User, SubAdmin, Assignment
from batches.models import ClassSchedule
from courses.models import Topic, Course
from tests.models import Test
from django.utils import timezone


# Create your models here.

class Notification(models.Model):
    id = models.AutoField(primary_key=True)
    super_admin = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    sub_admin = models.ForeignKey(SubAdmin, on_delete=models.CASCADE, null=True, blank=True)
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True)
    assignment = models.ForeignKey(Assignment, on_delete=models.SET_NULL, null=True, blank=True)
    test = models.ForeignKey(Test, on_delete=models.SET_NULL, null=True, blank=True)
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True)
    schedule = models.ForeignKey(ClassSchedule, on_delete=models.SET_NULL, null=True, blank=True)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "aryuapp_notification"

    def __str__(self):
        target = self.student.registration_id if self.student else self.trainer.employee_id
        return f"Notification → {target}: {self.message[:30]}"
    
class ChatRoom(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="chat_rooms")
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE, related_name="chat_rooms")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "aryuapp_chatroom"
        unique_together = ("student", "trainer")

    def __str__(self):
        return f"Room: {self.student.registration_id} ↔ {self.trainer.employee_id}"

class Message(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    sender_type = models.CharField(max_length=20)
    sender_id = models.CharField(max_length=50)
    content = models.TextField(null=True, blank=True)
    upload = models.FileField(upload_to='chat/uploades/', null=True, blank=True)
    audio_file = models.FileField(upload_to="chat/audio/", blank=True, null=True)
    is_read = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "aryuapp_message"

    def __str__(self):
        return f"{self.sender_type}({self.sender_id}): {self.content[:20]}"
  


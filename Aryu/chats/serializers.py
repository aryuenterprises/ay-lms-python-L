from .models import ChatRoom, Message, Notification
from rest_framework import serializers
from aryuapp.models import Submission, SubmissionReply
from tests.models import StudentAnswers, TestResult
from courses.models import StudentTopicStatus

class NotificationSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    course_id = serializers.SerializerMethodField()
    topic_id = serializers.SerializerMethodField()
    assignment_id = serializers.SerializerMethodField()
    test_id = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'student', 'student_name', 'course_id', 'assignment_id', 'topic_id', 'test_id',
            'trainer', 'sub_admin', 'message', 'is_read', 'created_at'
        ]

    def get_student_name(self, obj):
        if obj.student:
            return f"{obj.student.first_name} {obj.student.last_name}"
        return None

    def get_course_id(self, obj):
        try:
            """
            Return course_id for submission/submission_reply, topic status,
            test submission, and test result notifications.
            """
            if not obj.message or not obj.student:
                return None

            msg_lower = obj.message.lower()

            # --- Submission / Submission Reply notifications ---
            if msg_lower.startswith("submission"):
                submission = (
                    Submission.objects.filter(student=obj.student)
                    .select_related("assignment__course")
                    .order_by("-assignment__course__course_id")
                    .first()
                )
                if submission and submission.assignment and submission.assignment.course:
                    return submission.assignment.course.course_id

            # --- Topic status notifications ---
            elif "topic status" in msg_lower:
                sts = (
                    StudentTopicStatus.objects.filter(student=obj.student)
                    .select_related("topic__course")
                    .order_by("-updated_at")
                    .first()
                )
                if sts and sts.topic and sts.topic.course:
                    return sts.topic.course.course_id

            # --- Test submission notifications ---
            elif msg_lower.startswith("test_submission"):
                ans = (
                    StudentAnswers.objects.filter(student_id=obj.student)
                    .select_related("test_id__course_id")
                    .order_by("-submitted_at")
                    .first()
                )
                if ans and ans.test_id and ans.test_id.course_id:
                    return ans.test_id.course_id.course_id  # course_id field

            # --- Test result notifications ---
            elif msg_lower.startswith("test_result"):
                result = (
                    TestResult.objects.filter(student_id=obj.student)
                    .select_related("test_id__course_id")
                    .order_by("-evaluated_at")
                    .first()
                )
                if result and result.test_id and result.test_id.course_id:
                    return result.test_id.course_id.course_id  # course_id field

            return None

        except Exception as e:
            return {'success': False, 'message': str(e)}

    def get_topic_id(self, obj):
        """
        Only return topic_id for topic status notifications.
        """
        if obj.message and obj.student:
            if "topic status" in obj.message.lower():
                sts = (
                    StudentTopicStatus.objects.filter(student=obj.student)
                    .select_related("topic")
                    .order_by("-updated_at")  # most recent status
                    .first()
                )
                if sts and sts.topic:
                    return sts.topic.topic_id
        return None
    
    def get_test_id(self, obj):
        if obj.test:
            return obj.test.test_id
        return None

    def get_assignment_id(self, obj):
        
        if obj.message and obj.student:
            message_lower = obj.message.lower()
            if "submission" in message_lower:
                reply_or_submission = (
                    SubmissionReply.objects
                    .filter(submission__student=obj.student)
                    .select_related("submission__assignment")
                    .order_by("-date")
                    .first()
                )

                if not reply_or_submission:
                    reply_or_submission = (
                        Submission.objects
                        .filter(student=obj.student)
                        .select_related("assignment")
                        .order_by("-date")
                        .first()
                    )

                if reply_or_submission and reply_or_submission.submission and reply_or_submission.submission.assignment:
                    return reply_or_submission.submission.assignment.id  # reply_or_submission.submission.assignment.id

                if isinstance(reply_or_submission, Submission) and reply_or_submission.assignment:
                    return reply_or_submission.assignment.id

        return None


class ChatRoomSerializer(serializers.ModelSerializer):
    student = serializers.CharField(source="student.registration_id")
    trainer = serializers.CharField(source="trainer.employee_id")
    student_name = serializers.SerializerMethodField()
    trainer_name = serializers.SerializerMethodField()
    student_profile_pic = serializers.SerializerMethodField()
    trainer_profile_pic = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = [
            "id",
            "student",
            "student_name",
            "trainer",
            "trainer_name",
            "student_profile_pic",
            "trainer_profile_pic",
            "created_at",
        ]

    def get_student_profile_pic(self, obj):
        if obj.student and obj.student.profile_pic:
            return 'https://aylms.aryuprojects.com/api' + obj.student.profile_pic.url
        return None

    def get_trainer_profile_pic(self, obj):
        if obj.trainer and obj.trainer.profile_pic:
            return 'https://aylms.aryuprojects.com/api' + obj.trainer.profile_pic.url
        return None

    def get_student_name(self, obj):
        if obj.student:
            return f"{obj.student.first_name} {obj.student.last_name}".strip()
        return None

    def get_trainer_name(self, obj):
        if obj.trainer:
            return obj.trainer.full_name if hasattr(obj.trainer, "full_name") else f"{obj.trainer.first_name} {obj.trainer.last_name}".strip()
        return None

class MessageSerializer(serializers.ModelSerializer):
    upload_url = serializers.SerializerMethodField(read_only=True)  # for display
    audio_file_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "room", "sender_type", "sender_id", "content", 'upload', 'upload_url', 'audio_file', 'audio_file_url', "is_read", "is_deleted", "created_at", "updated_at"]

    def get_upload_url(self, obj):
        if obj.upload:
            return 'https://aylms.aryuprojects.com/api' + obj.upload.url
        return None

    def get_audio_file_url(self, obj):
        if obj.audio_file:
            return 'https://aylms.aryuprojects.com/api' + obj.audio_file.url
        return None

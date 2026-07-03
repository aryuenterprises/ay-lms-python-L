from .models import *
from rest_framework import serializers
from decimal import Decimal, InvalidOperation
import mimetypes
from django.apps import apps
import os
import re
import uuid
import magic
import json
import zipfile
from aryuapp.models import Assignment
from aryuapp.models import Submission




class CourseCategorySerializer(serializers.ModelSerializer):
    notes = serializers.SerializerMethodField()
    class Meta:
        model = CourseCategory
        fields = '__all__'
    
    def get_notes(self, obj):

        notes = getattr(obj, "prefetched_notes", [])

        return [
            {
                "note_id": note.id,
                "reason": note.reason,
                "created_by": note.created_by,
                "status": note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes
            if note.object_id == obj.pk
        ]

    def validate_category_name(self, value):
        request = self.context.get('request')
        trainer_id = getattr(request.user, 'trainer_id', None)  # or trainer_id if admin model uses trainer_id

        # Alphabet and space only
        if not re.match(r'^[A-Za-z ]+$', value):
            raise serializers.ValidationError("Category name can only contain alphabets and spaces.")

        # Check uniqueness for the same admin
        qs = CourseCategory.objects.filter(
            category_name__iexact=value,
            created_by=trainer_id,
            is_archived=False
        )
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError("You already have a category with this name.")

        return value
    
    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

            if role in ["trainer", "admin"]:
                validated_data["created_by"] = getattr(request.user, "trainer_id", None)
                validated_data["created_by_type"] = role

            elif role == "super_admin":
                validated_data["created_by"] = getattr(request.user, "user_id", None)
                validated_data["created_by_type"] = role

            elif role == "student":
                validated_data["created_by"] = getattr(request.user, "student_id", None)
                validated_data["created_by_type"] = role

            else:
                validated_data["created_by"] = getattr(request.user, "user_id", None)
                validated_data["created_by_type"] = role
        return super().create(validated_data)

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)

        # Check if category was deactivated
        if 'status' in validated_data and not validated_data['status']:
            instance.cascade_category_deactivation()

        return instance

class CourseListSerializer(serializers.ModelSerializer):

    course_category = serializers.SlugRelatedField(
        slug_field="category_name",
        read_only=True
    )

    category_details = CourseCategorySerializer(
        source="course_category",
        read_only=True
    )

    course_pic_url = serializers.SerializerMethodField()
    duration_list = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            "course_id",
            "course_name",
            "course_category",
            "category_details",
            "course_pic",
            "course_pic_url",
            "notes",
            "currency_type",
            "fee_type",
            "duration_list",
            "mode_of_delivery",
            "fee",
            "status",
            "is_archived",
            "is_featured",
        ]

    def get_course_pic_url(self, obj):
        if obj.course_pic:
            return f"https://portal.aryuacademy.com/api{obj.course_pic.url}"
        return None
    def get_duration_list(self,obj):
        if obj.duration:
            duration_value = obj.duration
            duration_type = getattr(obj, "duration_type")  # default to month if field not set
            return [{"duration":duration_value, "duration_type":duration_type}]
        return []

class CaseInsensitiveSlugRelatedField(serializers.SlugRelatedField):
    def to_internal_value(self, data):
        try:
            return self.get_queryset().get(**{f"{self.slug_field}__iexact": data})
        except self.get_queryset().model.DoesNotExist:
            self.fail('does_not_exist', slug_name=self.slug_field, value=data)

class CourseSerializer(serializers.ModelSerializer):
    course_category = CaseInsensitiveSlugRelatedField(
    slug_field='category_name',
    queryset=CourseCategory.objects.filter(is_archived=False),
)
    category_details = CourseCategorySerializer(source='course_category', read_only=True)
    syllabus_info = serializers.SerializerMethodField()
    syllabus_url = serializers.SerializerMethodField()
    course_pic = serializers.ImageField(required=False, allow_null=True)
    course_pic_url = serializers.SerializerMethodField()
    batches = serializers.SerializerMethodField()
    topic = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()
    assignment = serializers.SerializerMethodField()
    # duration_list = serializers.JSONField(write_only=True, required=False)
    # duration_type = serializers.CharField(read_only=True)
    duration_list = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()




    class Meta:
        model = Course
        fields = [
            'course_id', 'course_name', 'course_category', 'category_details',
            'course_pic', 'course_pic_url', 'notes', 'currency_type', 'fee_type',
            'topic', 'syllabus', 'syllabus_url','syllabus_info', 'assignment', 'batches',
            'duration_list','mode_of_delivery', 'fee', 'status', 'is_archived', 'is_featured', 'created_by', 'created_at',
            'video_url',
        ]
    def get_video_url(self, obj):
        if obj.video_url and hasattr(obj.video_url, 'url'):
            return 'https://portal.aryuacademy.com/api/' + obj.video_url.url
        return None


        
    def get_notes(self, obj):
    
        from aryuapp.models import Note

        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model='course'
        ).order_by('-created_at')

        # Convert "true"/"false" to boolean
        def convert_status(value):
            if isinstance(value, str):
                if value.lower() == "true":
                    return True
                if value.lower() == "false":
                    return False
            return value

        return [
            {
                "note_id": note.id,
                "reason": note.reason,
                "created_by": note.created_by,
                "status": note.status,
                "created_at": note.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for note in notes_qs
        ]


    def get_duration_list(self, obj):
        if obj.duration and obj.duration_type:
            return [
                {
                    "duration": obj.duration,
                    "duration_type": obj.duration_type
                }
            ]
        return []
    def get_batches(self, obj):
        batches_qs = obj.new_batches.filter(is_archived=False, status=True)
        return [
            {
                "batch_id": b.batch_id,
                "title": b.title,
                "start_date": b.start_date,
                "end_date": b.end_date,
                "start_time": b.start_time,
                "end_time": b.end_time,
               "trainers": [
                    {
                        "trainer_id": t.trainer_id,
                        "trainer_name": t.full_name,
                        "employee_id": t.employee_id,
                    }
                    for t in b.trainers.all()
                ]
            } for b in batches_qs
        ]
    
    def get_course_pic_url(self, obj):
        if obj.course_pic and hasattr(obj.course_pic, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.course_pic.url
        return None
    
    def get_syllabus_url(self, obj):
        if obj.syllabus and hasattr(obj.syllabus, 'url'):
            return 'https://portal.aryuacademy.com/api' + obj.syllabus.url
        return None
    def get_syllabus_info(self, obj):
        if obj.syllabus:
            return [{
                "id": obj.course_id,
                "date": None,
                "syllabus": self.get_syllabus_url(obj)
            }]
        return []
    
    def get_assignment(self, obj):
        assignments = Assignment.objects.filter(
            course=obj,
            is_archived=False
        ).order_by("id")

        assignment_data = []

        for assignment in assignments:

            submission_qs = (
                Submission.objects.filter(
                    assignment=assignment,
                    is_archived=False
                )
                .select_related("student")
                .prefetch_related("replies")
                .order_by("-date")
            )

            submissions = []

            for submission in submission_qs:

                profile_pic = None
                if submission.student.profile_pic:
                    try:
                        profile_pic = (
                            "https://portal.aryuacademy.com/api"
                            + submission.student.profile_pic.url
                        )
                    except Exception:
                        profile_pic = None

                submissions.append({
                    "id": submission.id,
                    "student": {
                        "registration_id": submission.student.registration_id,
                        "student_name": f"{submission.student.first_name} {submission.student.last_name or ''}".strip(),
                        "first_name": submission.student.first_name,
                        "last_name": submission.student.last_name,
                        "profile_pic": profile_pic,
                    },
                    "text": submission.text,
                    "file": submission.file.url if submission.file else None,
                    "file_url": (
                        "https://portal.aryuacademy.com/api" + submission.file.url
                        if submission.file else None
                    ),
                    "date": submission.date.strftime("%Y-%m-%d %H:%M:%S"),
                    "status": submission.status,
                    "replies": [
                        {
                            "id": reply.id,
                            "text": reply.text,
                            "created_at": reply.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        for reply in submission.replies.all()
                    ]
                })

            assignment_data.append({
                "id": assignment.id,
                "title": assignment.title,
                "course": assignment.course.course_id,
                "assigned_by": assignment.assigned_by_id,
                "status": assignment.status,
                "submission_count": submission_qs.count(),
                "submissions": submissions
            })

        return assignment_data

    def validate_fee(self, value):
        if value is None:
            return value

        # Ensure value is int, float, or Decimal (reject strings/characters)
        if not isinstance(value, (int, float, Decimal)):
            raise serializers.ValidationError("Fee must be a number.")

        # Convert safely to Decimal
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise serializers.ValidationError("Fee must be a valid numeric value.")

        # Check maximum
        if value > Decimal('100000'):
            raise serializers.ValidationError("Fee cannot be more than 100,000.")

        # Check non-negative
        if value < 0:
            raise serializers.ValidationError("Fee cannot be negative.")

        return value
    
    def get_topic(self, obj):
        student = self.context.get("student")  # Could be None
        topics = Topic.objects.filter(course=obj, is_archived=False).order_by('created_date')

        # Prefetch StudentTopicStatus only if student is provided
        if student:
            sts_qs = StudentTopicStatus.objects.filter(student=student, topic__in=topics)
            sts_map = {sts.topic_id: sts for sts in sts_qs}
        else:
            sts_map = {}

        topic_data = []

        for topic in topics:
            topic_serialized = TopicSerializer(topic, context=self.context).data

            if student and topic.topic_id in sts_map:
                sts = sts_map[topic.topic_id]
                topic_serialized['student_comment'] = sts.notes
                topic_serialized['student_rating'] = sts.ratings
            else:
                topic_serialized['student_comment'] = None
                topic_serialized['student_rating'] = None

            topic_data.append(topic_serialized)

        return topic_data
    
    # def validate_duration(self, value):
    #     if value:
    #         try:
    #             months = int(value)
    #             if months < 1 or months > 12:
    #                 raise serializers.ValidationError("Duration must be between 1 and 12 months.")
    #         except ValueError:
    #             raise serializers.ValidationError("Duration must be a number (months).")
    #     return value
    from rest_framework import serializers

    def validate_duration(self, value, duration_type=None):
        """
        Validate duration based on duration_type ('month' or 'week').
        - If month: must be between 1 and 12
        - If week: must be between 1 and 52
        """
        if value is None:
            return value  # allow empty if needed

        try:
            duration = int(value)
        except ValueError:
            raise serializers.ValidationError("Duration must be a number.")

        if duration_type == "month":
            if duration < 1 or duration > 12:
                raise serializers.ValidationError("Duration must be between 1 and 12 months.")
        elif duration_type == "week":
            if duration < 1 or duration > 52:
                raise serializers.ValidationError("Duration must be between 1 and 52 weeks.")
        else:
            raise serializers.ValidationError("Invalid duration_type. Must be 'month' or 'week'.")

        return duration
    
    def validate(self, data):
        course_name = data.get('course_name')
        request = self.context.get('request')
        course_category = data.get('course_category')
        trainer_id = getattr(request.user, 'trainer_id', None)

        # Check duplicate course under same category for same creator
        if course_name and course_category:
            qs = Course.objects.filter(
                course_name__iexact=course_name,
                course_category=course_category,
                created_by=trainer_id,
                is_archived=False
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise serializers.ValidationError({
                    'course_name': 'This course already exists under the selected category.'
                })

        # Prevent activating course if category is inactive
        course_status = data.get('status')
        if self.instance:
            # If updating, use current value if not provided
            course_status = course_status if course_status is not None else self.instance.status
            course_category = course_category or self.instance.course_category

        if course_status is True and course_category and not course_category.status:
            raise serializers.ValidationError({
                'status': 'Cannot activate this course because the selected category is inactive.'
            })

        return data



    def create(self, validated_data):
        request = self.context.get("request")

        # ✅ get from validated_data OR request.data
        duration_list = validated_data.pop('duration_list', None)

        if not duration_list and request:
            raw = request.data.get('duration_list')
            if raw:
                try:
                    duration_list = json.loads(raw)
                except Exception:
                    duration_list = None

        # ✅ extract values
        if duration_list:
            duration_data = duration_list[0]

            validated_data['duration'] = duration_data.get('duration')

            validated_data['duration_type'] = (
                duration_data.get('duration_type') or 'month'
            )

        # ✅ created_by logic
        if request and request.user:
            role = getattr(request.user, "user_type", None)

            if role in ["trainer", "admin"]:
                validated_data["created_by"] = getattr(request.user, "trainer_id", None)
            elif role == "super_admin":
                validated_data["created_by"] = getattr(request.user, "user_id", None)
            elif role == "student":
                validated_data["created_by"] = getattr(request.user, "student_id", None)
            else:
                validated_data["created_by"] = getattr(request.user, "user_id", None)

            validated_data["created_by_type"] = role

        return super().create(validated_data)
    def update(self, instance, validated_data):
        # Capture status before update
        old_status = instance.status

        # Update the course instance
        instance = super().update(instance, validated_data)

        # Cascade deactivation if course is being set to Inactive
        new_status = validated_data.get('status', old_status)
        if new_status == "Inactive" and old_status != "Inactive":
            instance.deactivate_course(instance)

        return instance


class CourseSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ['course_id', 'course_name', 'course_pic', 'course_category']

class CourseVideoSerializer(serializers.ModelSerializer):
    class Meta:
        model=CourseVideo
        fields = "__all__"

class TopicSerializer(serializers.ModelSerializer):
    create_by = serializers.SlugRelatedField(
        slug_field='employee_id',
        queryset=apps.get_model("aryuapp", "Trainer").objects.all(),
        allow_null=True,
        required=False
    )
    course = serializers.PrimaryKeyRelatedField(read_only=True)  # make course read-only

    class Meta:
        model = Topic
        fields = ['topic_id','course','title','description','created_date','create_by','is_archived', 'created_at', 'created_by']
        read_only_fields = ['created_date', 'course', 'topic_id']
        
    
    # def save(self, **kwargs):
    #     if "description" in self.validated_data:
    #         self.validated_data["description"] = escape(
    #             self.validated_data["description"]
    #         )

    #     return super().save(**kwargs)

    def create(self, validated_data):
        request = self.context.get("request")

        if request and request.user:
            role = getattr(request.user, "user_type", None)

            if role in ["trainer", "admin"]:
                validated_data["created_by"] = getattr(request.user, "trainer_id", None)
                validated_data["created_by_type"] = role

            elif role == "super_admin":
                validated_data["created_by"] = getattr(request.user, "user_id", None)
                validated_data["created_by_type"] = role

            elif role == "student":
                validated_data["created_by"] = getattr(request.user, "student_id", None)
                validated_data["created_by_type"] = role

        return super().create(validated_data)
        
class StudentTopicStatusSerializer(serializers.ModelSerializer):
    topic_title = serializers.CharField(source='topic.title', read_only=True)
    course_id = serializers.IntegerField(source='topic.course.course_id', read_only=True)
    registration_id = serializers.CharField(write_only=True, required=False)
    updated_at = serializers.DateTimeField(read_only=True, format='%Y-%m-%d %H:%M:%S')

    class Meta:
        model = StudentTopicStatus
        fields = [
            'id',
            'student',          # Now writable
            'ratings',
            'registration_id',
            'topic',
            'notes',
            'topic_title',
            'course_id',
            'status',
            'updated_at'
        ]
        read_only_fields = ['updated_at']  # student NOT read-only anymore

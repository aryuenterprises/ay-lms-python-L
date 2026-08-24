from .models import *
from rest_framework import serializers
from datetime import datetime, time
from django.utils import timezone
import calendar
from collections import defaultdict
import holidays
from aryuapp.models import TrainerAttendance, Trainer, Student
from rest_framework.response import Response
from django.conf import settings



class BatchCourseTrainerSerializer(serializers.ModelSerializer):
    course_id = serializers.IntegerField(source='course.course_id')
    trainer_employee_id = serializers.CharField(source='trainer.employee_id')
    course_name = serializers.CharField(source='course.course_name', read_only=True)
    trainer_name = serializers.CharField(source='trainer.full_name', read_only=True)
    student_id = serializers.CharField(source='student.student_id', read_only=True)
    registration_id = serializers.CharField(source='student.registration_id', read_only=True)
    first_name = serializers.CharField(source='student.first_name', read_only=True)
    last_name = serializers.CharField(source='student.last_name', read_only=True)
    category_id = serializers.IntegerField(source='course.course_category.category_id', read_only=True)

    class Meta:
        model = BatchCourseTrainer
        fields = ['course_id', 'trainer_employee_id', 'category_id', 'course_name', 'trainer_name', 'student_id','registration_id', 'first_name', 'last_name']
        read_only_fields = ['course_name', 'trainer_name', 'registration_id', 'first_name', 'last_name']
    
class ClassScheduleSerializer(serializers.ModelSerializer):
    trainer_name = serializers.SerializerMethodField()
    course_name = serializers.CharField(source='course.course_name', read_only=True)
    batch_name = serializers.CharField(source='batch.batch_name', read_only=True)
    status_info = serializers.SerializerMethodField()
    start_time = serializers.TimeField(required=False)
    end_time = serializers.TimeField(required=False)
    scheduled_date = serializers.DateField(format='%Y-%m-%d', required=False)
    employee_id = serializers.CharField(write_only=True, required=False)
    title = serializers.SerializerMethodField()
    new_batch_id = serializers.IntegerField(source='new_batch.batch_id', read_only=True)
    batch_id = serializers.IntegerField(source='batch.batch_id', read_only=True)
    course_id = serializers.IntegerField(source='course.course_id', read_only=True)
    notes = serializers.SerializerMethodField()

    course_trainer_assignments = serializers.SerializerMethodField()

    class Meta:
        model = ClassSchedule
        fields = [
            'schedule_id', 'class_link', 'course_id', 'course_name', 'new_batch_id', 'new_batch',
            'batch_id', 'batch_name', 'title', 'employee_id', 'trainer_name',
            'scheduled_date', 'start_time', 'end_time', 'duration', 'is_class_cancelled', 'notes',
            'is_archived', 'is_online_class', 'status_info', 'course_trainer_assignments', 'meeting_link', 'created_at', 'created_by',
        ]
        read_only_fields = [ 'duration', 'meeting_link']
        
    def get_title(self, obj):
        if hasattr(obj, "batch") and obj.batch:
            return obj.batch.title

        if hasattr(obj, "new_batch") and obj.new_batch:
            return obj.new_batch.title

        return None

    def get_notes(self, obj):

        from aryuapp.models import Note

        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model='classschedule'
        ).order_by('-created_at')

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

    def validate_employee_id(self, value):
        try:
            return Trainer.objects.get(employee_id=value)
        except Trainer.DoesNotExist:
            raise serializers.ValidationError("Invalid employee_id. Trainer not found.")
        
    def validate_batch_id(self, value):
        batch = None

        # Try Batch table
        try:
            batch = Batch.objects.get(batch_id=value)
        except Batch.DoesNotExist:
            batch = None

        # Try NewBatch table
        if batch is None:
            try:
                batch = NewBatch.objects.get(batch_id=value)
            except NewBatch.DoesNotExist:
                raise serializers.ValidationError("Batch ID not found in Batch")

        # Validate
        if batch.is_archived:
            raise serializers.ValidationError("Cannot create schedule for deleted batch.")

        if not batch.status:
            raise serializers.ValidationError("Cannot Create Schedule for Inactive Batch.")

        return batch
    
    def validate(self, data):
        course = data.get("course")
        batch = data.get("batch")

        # If updating, get existing values
        if self.instance:
            if not course:
                course = self.instance.course
            if not batch:
                batch = self.instance.batch

        # ---------- Validation 1: Course Category Active ----------
        if course and course.course_category and not course.course_category.status:
            raise serializers.ValidationError({
                "course": "Cannot create schedule because the course's category is inactive."
            })

        # ---------- Validation 2: Course Active ----------
        if course and course.status == "Inactive":
            raise serializers.ValidationError({
                "course": "Cannot create schedule because this course is inactive."
            })

        # ---------- Validation 3: Batch Active ----------
        if batch and not batch.status:
            raise serializers.ValidationError({
                "batch": "Cannot create schedule because this batch is inactive."
            })

        return data


    # --------------------------------------------------
    #  CREATE (Batch + NewBatch handling)
    # --------------------------------------------------
    def create(self, validated_data):
        request = self.context.get("request")

        # -------- Identify created_by and created_by_type ----------
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

            else:
                validated_data["created_by"] = getattr(request.user, "user_id", None)
                validated_data["created_by_type"] = role

        # ---------- Extract IDs from request ----------
        trainer_id = validated_data.pop("employee_id", None)
        batch_id = validated_data.pop("batch_id", None)

        # ---------- Assign trainer instance ----------
        if trainer_id:
            validated_data["trainer"] = Trainer.objects.get(pk=trainer_id)

        # ---------- Fetch the batch from BOTH tables ----------
        if batch_id:
            batch = None

            # Try Batch
            try:
                batch = Batch.objects.get(pk=batch_id)
            except Batch.DoesNotExist:
                pass

            # Try NewBatch
            if batch is None:
                try:
                    batch = NewBatch.objects.get(pk=batch_id)
                except NewBatch.DoesNotExist:
                    raise serializers.ValidationError({
                        "batch_id": "Batch not found in Batch or NewBatch."
                    })

            # Assign batch instance
            validated_data["batch"] = batch

        # ---------- Create schedule ----------
        class_schedule = super().create(validated_data)
        return class_schedule

    def get_trainer_name(self, obj):
        return obj.trainer.full_name if obj.trainer else None

    def get_status_info(self, obj):
        now = datetime.now()
        scheduled_start = datetime.combine(obj.scheduled_date, obj.start_time)
        scheduled_end = datetime.combine(obj.scheduled_date, obj.end_time)

        attendance_exists = TrainerAttendance.objects.filter(
            trainer=obj.trainer,
            course=obj.course,
            date__date=obj.scheduled_date
        ).exists()

        if attendance_exists and scheduled_start <= now <= scheduled_end:
            return "Ongoing"
        elif now > scheduled_end:
            # Class has ended
            attendance_exists = TrainerAttendance.objects.filter(
                trainer=obj.trainer,
                course=obj.course,
                date__date=obj.scheduled_date
            ).exists()
            return "Done" if attendance_exists else "Missed"
        else:
            return "Upcoming"

    def get_course_trainer_assignments(self, obj):
        # Directly filter BatchCourseTrainer for this class's course and trainer
        assignments = BatchCourseTrainer.objects.select_related('course', 'trainer', 'student').filter(
            batch_id=obj.batch_id,
            course_id=obj.course_id,
            trainer_id=obj.trainer_id
        )

        return [
            {
                "course_id": a.course.course_id,
                "trainer_employee_id": a.trainer.employee_id,
                "course_name": a.course.course_name,
                "trainer_name": a.trainer.full_name,
                "registration_id": a.student.registration_id,
                "student_names": f"{a.student.first_name} {a.student.last_name}"
            }
            for a in assignments
        ]
        
class RecurringScheduleSerializer(serializers.ModelSerializer):
    
    employee_id = serializers.CharField(write_only=True)

    # API input: "batch"
    # Model field: "new_batch"
    batch = serializers.PrimaryKeyRelatedField(
        source="new_batch",
        queryset=NewBatch.objects.filter(is_archived=False),
        required=True
    )

    class Meta:
        model = RecurringSchedule
        fields = "__all__"
        read_only_fields = ["trainer"]

    def create(self, validated_data):

        # ---------------- TRAINER ----------------
        employee_id = validated_data.pop("employee_id")

        try:
            trainer = Trainer.objects.get(employee_id=employee_id)
        except Trainer.DoesNotExist:
            raise serializers.ValidationError({"employee_id": "Trainer not found"})

        validated_data["trainer"] = trainer

        # ---------------- NEW BATCH ----------------
        new_batch = validated_data["new_batch"]

        if new_batch.is_archived:
            raise serializers.ValidationError({"batch": f"Batch '{new_batch.title}' is archived."})

        if not new_batch.status:
            raise serializers.ValidationError({"batch": f"Batch '{new_batch.title}' is inactive."})

        # ---------------- COURSE ----------------
        course = validated_data.get("course")

        if course:
            if course.status.lower() != "active":
                raise serializers.ValidationError({"course": f"Course '{course.course_name}' is inactive."})

            if course.course_category and not course.course_category.status:
                raise serializers.ValidationError(
                    {"course": f"Category '{course.course_category.category_name}' is inactive."}
                )

        # ---------------- CREATED BY ----------------
        request = self.context.get("request")
        role = getattr(request.user, "user_type", None)

        if request and request.user:
            if role in ["tutor", "admin"]:
                validated_data["created_by"] = str(getattr(request.user, "trainer_id", None))
            elif role == "super_admin":
                validated_data["created_by"] = str(getattr(request.user, "user_id", None))
            elif role == "student":
                validated_data["created_by"] = str(getattr(request.user, "student_id", None))
            else:
                validated_data["created_by"] = str(request.user.id)

            validated_data["created_by_type"] = role

        # ------------ CREATE RECURRING ROW ------------
        recurrence = super().create(validated_data)

        # ------------ GENERATE CHILD SCHEDULES ------------
        self.generate_schedules(new_batch, trainer, course, validated_data)

        return recurrence

    # ==========================================================
    #   INTERNAL FUNCTIONS -- NOW INCLUDED
    # ==========================================================

    def generate_schedules(self, batch, trainer, course, data):

        country = data.get("country", "IN")
        subdiv = data.get("subdiv", None)

        try:
            years = range(data["start_date"].year, data["end_date"].year + 1)
            public_holidays = holidays.CountryHoliday(country, subdiv=subdiv, years=years)
        except:
            public_holidays = {}

        current_date = data["start_date"]
        end_date = data["end_date"]

        recurrence_type = data.get("recurrence_type", "").lower()
        custom_days = [d.upper() for d in data.get("days_of_week", [])]
        days_map = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

        # Single-day
        if recurrence_type == "day":
            self._create_schedule(batch, trainer, course, data, current_date)
            return
        
        max_days = 365 * 2  # 2 years max
        loop_counter = 0

        # Multi-day
        while current_date <= end_date:
            loop_counter += 1
            if loop_counter > max_days:
                raise serializers.ValidationError(
                    "Recurrence range too large. Choose a shorter time period of maximum 2 years."
                )

            if current_date in public_holidays:
                current_date += timedelta(days=1)
                continue

            weekday = current_date.weekday()
            create_flag = True

            if recurrence_type == "daily":
                create_flag = True

            elif recurrence_type == "weekly":
                create_flag = weekday == data["start_date"].weekday()

            elif recurrence_type == "custom_days":
                create_flag = days_map[weekday] in custom_days

            if create_flag:
                self._create_schedule(batch, trainer, course, data, current_date)

            current_date += timedelta(days=1)

    def _create_schedule(self, batch, trainer, course, data, date):

        exists = ClassSchedule.objects.filter(
            new_batch=batch,
            trainer=trainer,
            course=course,
            scheduled_date=date,
            is_archived=False
        ).filter(
            start_time__lt=data["end_time"],
            end_time__gt=data["start_time"]
        ).exists()

        if exists:
            raise serializers.ValidationError(
                {"non_field_errors": f"Schedule already exists on {date}."}
            )

        ClassSchedule.objects.create(
            new_batch=batch,      # Store only in new_batch
            batch=None,           # No legacy batch
            trainer=trainer,
            course=course,
            scheduled_date=date,
            start_time=data["start_time"],
            end_time=data["end_time"],
            is_online_class=data.get("is_online_class", False),
            class_link=data.get("class_link", ""),
            created_by=data["created_by"],
            created_by_type=data["created_by_type"]
        )

class ClassScheduleSimpleSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source="course.course_name", read_only=True)
    trainer_name = serializers.CharField(source="trainer.full_name", read_only=True)
    title = serializers.CharField(source="NewBatch.title", read_only=True )
    status = serializers.SerializerMethodField()

    class Meta:
        model = ClassSchedule
        fields = ["schedule_id", "scheduled_date", "course_name", 'start_time', 'end_time', 'status', "trainer_name",  "title"]
        
    def get_status(self, sched):
        current_time = timezone.now()
        start_time = getattr(sched, "start_time", None) or time(9, 0)

        # Start datetime aware
        class_start_dt = timezone.make_aware(
            datetime.combine(sched.scheduled_date, start_time),
            timezone.get_current_timezone()
        )

        # End datetime
        if sched.duration:
            class_end_dt = class_start_dt + sched.duration
        else:
            if sched.end_time:
                class_end_dt = timezone.make_aware(
                    datetime.combine(sched.scheduled_date, sched.end_time),
                    timezone.get_current_timezone()
                )
            else:
                class_end_dt = class_start_dt + timedelta(hours=1)

        # Status logic
        if current_time < class_start_dt:
            return "upcoming"
        elif class_start_dt <= current_time <= class_end_dt:
            return "ongoing"
        elif class_end_dt < current_time:
            attendance_exists = TrainerAttendance.objects.filter(
                trainer=sched.trainer,
                batch=sched.batch,
                course=sched.course,
                date__date=sched.scheduled_date,
            ).exists()
            return "done" if attendance_exists else "missed"
        return "missed"

class BatchSerializer(serializers.ModelSerializer):
    course_trainer_assignments = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField()),
        write_only=True,
        required=False
    )
    scheduled_date = serializers.DateField(format='%Y-%m-%d')
    schedules = ClassScheduleSimpleSerializer(many=True, read_only=True)
    notes = serializers.SerializerMethodField()
    class Meta:
        model = Batch
        fields = [
            'batch_id', 'batch_name', 'title', 'scheduled_date','schedules',
            'end_date', 'is_archived', 'status', 'course_trainer_assignments', 'created_at', 'created_by', 'notes'
        ]
        read_only_fields = ['batch_id', 'batch_name']

    def get_notes(self, obj):

        from aryuapp.models import Note

        notes_qs = Note.objects.filter(
            object_id=obj.pk,
            content_type__model='batch'
        ).order_by('-created_at')

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

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # --- Duration ---
        start = instance.scheduled_date
        end = instance.end_date
        if start and end:
            duration_days = (end - start).days + 1
            months = duration_days // 30
            days = duration_days % 30
            if months:
                data['duration'] = f"{months} Months {days} Days"
            else:
                data['duration'] = f"{days} Days"
        else:
            data['duration'] = None

        # --- Sorted schedules (date desc) ---
        sorted_schedules = instance.schedules.all().order_by('-scheduled_date', '-start_time')
        data['schedules'] = ClassScheduleSimpleSerializer(sorted_schedules, many=True).data
    
        # --- Weekly Schedule (group by weekday) ---
        schedule_by_day = defaultdict(list)
        for sch in instance.schedules.all():
            day_name = calendar.day_name[sch.scheduled_date.weekday()]  # Monday, Tuesday, etc
            st = sch.start_time.strftime("%I:%M %p")
            et = sch.end_time.strftime("%I:%M %p")
            schedule_by_day[day_name].append(f"{st}-{et}")

        # Merge into strings per day
        weekly_display = []
        weekday_order = {day: i for i, day in enumerate(calendar.day_name)}
        for day in sorted(schedule_by_day.keys(), key=lambda x: weekday_order[x]):
            times = ", ".join(schedule_by_day[day])
            weekly_display.append(f"{day} {times}")

        data['weekly_schedule'] = weekly_display

        # --- course_trainer_assignments ---
        data['course_trainer_assignments'] = [
            {
                'category_id': bct.course.course_category.category_id,
                "course_id": bct.course.course_id,
                "course_name": bct.course.course_name,
                "employee_id": bct.trainer.employee_id,
                "trainer_name": bct.trainer.full_name,
                "student_id": bct.student.student_id,
                "registration_id": bct.student.registration_id,
                "name": f"{bct.student.first_name} {bct.student.last_name}".strip()
            }
            for bct in BatchCourseTrainer.objects.filter(batch=instance)
                .select_related('course', 'trainer', 'student')
        ]

        return data

    def create(self, validated_data):
        trainer_map = validated_data.pop('course_trainer_assignments', [])
        
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

        batch = super().create(validated_data)

        for entry in trainer_map:
            course_id = entry.get('course_id')
            employee_id = entry.get('employee_id')
            student_id = entry.get('student_id')

            try:
                trainer = Trainer.objects.get(employee_id=employee_id)
                student = Student.objects.get(student_id=student_id)
            except (Trainer.DoesNotExist, Student.DoesNotExist):
                raise serializers.ValidationError({
                    'course_trainer_assignments': f"Invalid trainer or student: ({employee_id}, {student_id})"
                })

            BatchCourseTrainer.objects.create(
                batch=batch,
                course_id=course_id,
                trainer=trainer,
                student=student
            )

        return batch

    def update(self, instance, validated_data):
        # Capture status before update
        old_status = instance.status

        # Pop trainer mapping if provided
        trainer_map = validated_data.pop('course_trainer_assignments', None)

        # Update batch fields
        batch = super().update(instance, validated_data)

        # Handle trainer assignments
        if trainer_map is not None:
            # Clear previous assignments only if new data provided
            instance.batchcoursetrainer.all().delete()

            for entry in trainer_map:
                course_id = entry.get('course_id')
                employee_id = entry.get('employee_id')
                student_id = entry.get('student_id')

                try:
                    trainer = Trainer.objects.get(employee_id=employee_id)
                    student = Student.objects.get(student_id=student_id)
                except (Trainer.DoesNotExist, Student.DoesNotExist):
                    raise serializers.ValidationError({
                        'course_trainer_assignments': f"Invalid trainer or student: ({employee_id}, {student_id})"
                    })

                BatchCourseTrainer.objects.create(
                    batch=batch,
                    course_id=course_id,
                    trainer=trainer,
                    student=student
                )

        # Cascade deactivation if batch is set to False
        new_status = validated_data.get('status', old_status)
        if new_status is False and old_status != False:
            instance.deactivate_batch(instance)

        return batch
                   
    
class NewBatchSerializer(serializers.ModelSerializer):
    course = serializers.PrimaryKeyRelatedField(queryset=Course.objects.all())
    

    # Request
    trainers = serializers.SerializerMethodField(read_only=True)

    trainer_ids = serializers.PrimaryKeyRelatedField(
        source="trainers",
        queryset=Trainer.objects.filter(is_archived=False),
        many=True,
        write_only=True,
        required=False
    )

    # Correct M2M Field
    students = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Student.objects.filter(is_archived=False),
        required=False
    )
    start_time = serializers.TimeField(
        input_formats=['%I:%M:%S %p', '%H:%M:%S','%I:%M:%P']
        )

    end_time = serializers.TimeField(
        input_formats=['%I:%M:%S %p', '%H:%M:%S' , '%I:%M:%P']
        )

    class Meta:
        model = NewBatch
        fields = [
            'batch_id', 'title', 'course', 'trainers','trainer_ids',
            'start_date', 'end_date', 'start_time', 'end_time',
            'slots', 'status', 'students',
            'created_by', 'created_by_type', 'created_at', 'is_archived'
        ]
        read_only_fields = ['batch_id', 'created_by', 'created_by_type', 'created_at']
    def get_trainers(self, obj):
        from aryuapp.serializer import TrainerPreviewSerializer

        return TrainerPreviewSerializer(
            obj.trainers.all(),
            many=True
        ).data

    def validate(self, attrs):
        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')
        start_time = attrs.get('start_time')
        end_time = attrs.get('end_time')
        slots = attrs.get('slots')

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError({'end_date': 'End date must be after start date.'})

        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError({'end_time': 'End time must be after start time.'})

        if slots is not None and slots <= 0:
            raise serializers.ValidationError({'slots': 'Slots must be greater than zero.'})

        return attrs

    def create(self, validated_data):
        students = validated_data.pop('students', [])
        trainers = validated_data.pop('trainers',[])
        slots = validated_data.get("slots", 0)

        if len(students) > slots and slots == 0:
            raise serializers.ValidationError({
                "students": "Cannot add students. Slots are full."
            })

        request = self.context.get("request")
        role = getattr(request.user, "user_type", None) if request and request.user else None

        # --------- FIXED: created_by always stores ID (not username) ---------
        if request and request.user:
            if role == "trainer":
                validated_data["created_by"] = str(getattr(request.user, "trainer_id", None))

            elif role == "admin":
                # Admin does NOT have admin_id – they have trainer_id
                validated_data["created_by"] = str(getattr(request.user, "trainer_id", None))

            elif role == "super_admin":
                validated_data["created_by"] = str(getattr(request.user, "user_id", None))

            elif role == "student":
                validated_data["created_by"] = str(getattr(request.user, "student_id", None))

            else:
                # fallback to user.id always
                validated_data["created_by"] = str(getattr(request.user, "user_id", None))

            validated_data["created_by_type"] = role
        # --------------------------------------------------------------

        batch = NewBatch.objects.create(**validated_data)

        if trainers:
            batch.trainers.set(trainers)

        if students:
            if batch.available_slots() <= 0 and len(students) > 0:
                raise serializers.ValidationError({
                    "students": "Cannot add students. Slots are full."
                })
            batch.students.set(students)

        return batch

    def update(self, instance, validated_data):
        students = validated_data.pop("students", None)
        trainers = validated_data.pop("trainers", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        if students is not None:
            instance.students.set(students)

        if trainers is not None:
            instance.trainers.set(trainers)

        return instance 
    
class BatchRecordingSerializer(serializers.ModelSerializer):

    class Meta:
        model = BatchRecording
        fields = "__all__"

    def get_url(self, obj):
        if obj.url:
            return f"{settings.MEDIA_BASE_URL}{obj.url.url}"

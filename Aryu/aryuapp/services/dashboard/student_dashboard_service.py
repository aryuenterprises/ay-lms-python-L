from concurrent.futures import ThreadPoolExecutor
from datetime import date
from django.db.models import Count, Q, Min, Max
from django.core.cache import cache
from datetime import datetime, timedelta, time
from django.utils import timezone
from announcements.models import Announcement
from aryuapp.models import (
    Student,
    Attendance,
    Assignment,
    Submission,
    Course,
)
from batches.models import ClassSchedule
from django.db.models import F, ExpressionWrapper, DateTimeField, Q
from django.contrib.postgres.aggregates import StringAgg
from batches.models import NewBatch
class   StudentDashboardService:

    CACHE_TIMEOUT = 60

    def __init__(self, student_id):
        self.student_id = student_id
        self.student = Student.objects.only(
            "student_id",
            "registration_id",
            "first_name",
            "last_name",
            "email",
            "profile_pic"
        ).filter(student_id=student_id).first()

    # ---------------------------------------------------------
    # DASHBOARD BUILDER
    # ---------------------------------------------------------

    def get_dashboard(self):

        cache_key = f"student_dashboard_{self.student_id}"
        cached = cache.get(cache_key)

        if cached:
            return cached

        with ThreadPoolExecutor(max_workers=6) as executor:

            profile = executor.submit(self.get_profile)
            attendance = executor.submit(self.get_attendance_stats)
            progress = executor.submit(self.get_course_progress)
            assignments = executor.submit(self.get_assignment_stats)
            schedules = executor.submit(self.get_class_schedules)
            upcoming = executor.submit(self.get_upcoming_classes)
            announcements = executor.submit(self.get_announcements)

        data = {
            "profile": profile.result(),
            "attendance": attendance.result(),
            "course_progress": progress.result(),
            "assignments": assignments.result(),
            "schedules": schedules.result(),
            "upcoming_classes": upcoming.result(),
            "announcements": announcements.result()
        }

        cache.set(cache_key, data, self.CACHE_TIMEOUT)

        return data

    # ---------------------------------------------------------
    # PROFILE
    # ---------------------------------------------------------

    def get_profile(self):

        if not self.student:
            return {}

        return {
            "student_name": f"{self.student.first_name}",
            "student_id": self.student.registration_id,
            "email": self.student.email,
            "profile_pic": f"https://portal.aryuacademy.com/api/media/{self.student.profile_pic}",
            "badge": None
        }

    # ---------------------------------------------------------
    # COURSE PROGRESS
    # ---------------------------------------------------------

    def get_course_progress(self):
        student_id = self.student_id

        batches = (
            NewBatch.objects.filter(
                students__student_id=student_id,
                is_archived=False,
                course__is_archived=False,
            )
            .select_related("course")
            .prefetch_related("trainers", "course__topics")
            .distinct()
        )

        results = []

        for batch in batches:
            course = batch.course

            total_topics = course.topics.filter(
                is_archived=False
            ).count()

            completed_topics = course.topics.filter(
                is_archived=False,
                student_statuses__student_id=student_id,
                student_statuses__status=True
            ).distinct().count()

            progress_percent = (
                completed_topics / total_topics * 100
                if total_topics else 0
            )

            days = (batch.end_date - batch.start_date).days

            if days >= 30:
                duration = f"{round(days / 30)} Months"
            else:
                duration = f"{days} Days"

            trainer_names = ", ".join(
                trainer.full_name
                for trainer in batch.trainers.all()
            )

            results.append({
                "course_id": course.course_id,
                "course_name": course.course_name,
                "batch_id": batch.batch_id,
                "batch_name": batch.title,
                "trainer_name": trainer_names if trainer_names else None,
                "duration": duration,
                "start_time": batch.start_time.strftime("%H:%M") if batch.start_time else None,
                "end_time": batch.end_time.strftime("%H:%M") if batch.end_time else None,
                "total_topics": total_topics,
                "completed_topics": completed_topics,
                "progress_percent": round(progress_percent, 2),
            })

        return results
    # ---------------------------------------------------------
    # ATTENDANCE
    # ---------------------------------------------------------

    def get_attendance_stats(self):
        now = timezone.now()

        courses = Course.objects.filter(
            Q(new_batches__students=self.student_id) |
            Q(batchcoursetrainer__student_id=self.student_id),
            is_archived=False
        ).distinct()

        attendance_by_course = []

        for course in courses:

            schedules = ClassSchedule.objects.filter(
                Q(new_batch__students=self.student_id) |
                Q(batch__batchcoursetrainer__student_id=self.student_id),
                course=course,
                is_archived=False
            ).annotate(
                end_datetime=ExpressionWrapper(
                    F("scheduled_date") + F("end_time"),
                    output_field=DateTimeField()
                )
            )

            # Completed classes
            completed_schedules = schedules.filter(
                end_datetime__lt=now
            )

            # Upcoming / Ongoing classes
            upcoming_schedules = schedules.filter(
                end_datetime__gte=now
            )

            total = completed_schedules.count()

            cancelled = completed_schedules.filter(
                is_class_cancelled=True
            ).count()

            attended = Attendance.objects.filter(
                student_id=self.student_id,
                schedule_id__in=completed_schedules.values_list(
                    "schedule_id",
                    flat=True
                )
            ).values("schedule_id").distinct().count()

            absent = max(0, total - attended - cancelled)

            percentage = (
                (attended / total) * 100
                if total else 0
            )

            attendance_by_course.append({
                "course_id": course.course_id,
                "course_name": course.course_name,
                "total_classes": total,
                "attended": attended,
                "absent": absent,
                "cancelled_classes": cancelled,
                "percentage": round(percentage, 2),
                "upcoming_classes_count": upcoming_schedules.count()
            })

        return attendance_by_course

    def get_attendance_with_upcoming(self):
        now = timezone.now()

        courses = Course.objects.filter(
            Q(new_batches__students=self.student_id) |
            Q(batchcoursetrainer__student_id=self.student_id),
            is_archived=False
        ).distinct()

        result = []

        for course in courses:

            schedules = ClassSchedule.objects.filter(
                Q(new_batch__students=self.student_id) |
                Q(batch__batchcoursetrainer__student_id=self.student_id),
                course=course,
                is_archived=False
            ).annotate(
                end_datetime=ExpressionWrapper(
                    F("scheduled_date") + F("end_time"),
                    output_field=DateTimeField()
                )
            )

            # Completed classes
            completed_schedules = schedules.filter(
                end_datetime__lt=now
            )

            # Upcoming / Ongoing classes
            upcoming_qs = schedules.filter(
                end_datetime__gte=now
            )

            total = completed_schedules.count()

            cancelled = completed_schedules.filter(
                is_class_cancelled=True
            ).count()

            attended = Attendance.objects.filter(
                student_id=self.student_id,
                schedule_id__in=completed_schedules.values_list(
                    "schedule_id",
                    flat=True
                )
            ).values("schedule_id").distinct().count()

            absent = max(0, total - attended - cancelled)

            percentage = (
                (attended / total) * 100
                if total else 0
            )

            upcoming_classes_count = upcoming_qs.count()

            upcoming_classes = upcoming_qs.select_related(
                "course",
                "trainer",
                "new_batch"
            ).values(
                "scheduled_date",
                "start_time",
                "class_link",
                "course__course_name",
                "trainer__full_name",
                "new_batch__title"
            ).order_by(
                "scheduled_date",
                "start_time"
            )[:3]

            result.append({
                "course_id": course.course_id,
                "course_name": course.course_name,
                "total_classes": total,
                "attended": attended,
                "absent": absent,
                "cancelled_classes": cancelled,
                "percentage": round(percentage, 2),
                "upcoming_classes_count": upcoming_classes_count,
                "upcoming_classes": list(upcoming_classes)
            })

        return result
    # ---------------------------------------------------------
    # ASSIGNMENTS
    # ---------------------------------------------------------

    def get_assignment_stats(self):
        courses = Course.objects.filter(
            Q(new_batches__students=self.student_id) |
            Q(batchcoursetrainer__student_id=self.student_id),
            is_archived=False
        ).distinct()

        result = []

        for course in courses:
            # ✅ all assignments for this course
            assignments = Assignment.objects.filter(
                course=course,
                is_archived=False
            )

            total = assignments.count()

            # ✅ completed assignments
            completed = Submission.objects.filter(
                student_id=self.student_id,
                assignment__in=assignments
            ).values('assignment_id').distinct().count()

            pending = total - completed

            result.append({
                "course_id": course.course_id,
                "course_name": course.course_name,
                "total_assignments": total,
                "completed_assignments": completed,
                "pending_assignments": pending
            })

        return result

        for assignment in assignments:
            result.append({
                "assignment_id": assignment.id,   # ✅ correct field
                "assignment_name": assignment.title,
                # "description": assignment.description,
                "course_id": assignment.course.course_id if assignment.course else None,
                "course_name": assignment.course.course_name if assignment.course else None,
                "status": "Completed" if assignment.id in submitted_ids else "Pending"
            })

        return result  
        

    # ---------------------------------------------------------
    # ALL CLASS SCHEDULES
    # ---------------------------------------------------------

    def get_class_schedules(self):

        student_id = self.student_id
        tz = timezone.get_current_timezone()
        now = timezone.now()

        # -----------------------------
        # Fetch schedules
        # -----------------------------
        schedules = list(
            ClassSchedule.objects
            .filter(
                Q(new_batch__students=student_id) |
                Q(batch__batchcoursetrainer__student_id=student_id),
                is_archived=False
            )
            .select_related("course", "batch", "new_batch")
            .values(
                "schedule_id",
                "scheduled_date",
                "start_time",
                "end_time",
                "duration",
                "is_class_cancelled",
                "course__course_name",
                "batch__batch_name",
                "batch__title",
                "new_batch__title"
            )
            .order_by("-scheduled_date", "-start_time")
        )

        # -----------------------------
        # Fetch attendance logs
        # -----------------------------
        attendance_logs = list(
            Attendance.objects.filter(
                student_id=student_id,
                status__in=["Login", "Logout", "Present"]
            ).values_list("date", flat=True)
        )

        # normalize timezone
        attendance_set = set()
        for att in attendance_logs:
            if timezone.is_naive(att):
                att = timezone.make_aware(att, tz)
            attendance_set.add(att)

        result = []

        for sched in schedules:

            start_time = sched["start_time"] or time(9, 0)

            class_start = timezone.make_aware(
                datetime.combine(sched["scheduled_date"], start_time),
                tz
            )

            if sched["end_time"]:
                class_end = timezone.make_aware(
                    datetime.combine(sched["scheduled_date"], sched["end_time"]),
                    tz
                )
            else:
                duration = sched["duration"] or timedelta(hours=1)
                class_end = class_start + duration

            # attendance check
            attended = any(
                (class_start - timedelta(minutes=5))
                <= att <=
                (class_end + timedelta(minutes=5))
                for att in attendance_set
            )

            # status logic
            if sched["is_class_cancelled"]:
                status = "cancelled"

            elif now < class_start:
                status = "upcoming"

            elif class_start <= now <= class_end:
                status = "ongoing"

            elif attended:
                status = "completed"

            else:
                status = "missed"

            batch_name = (
                sched["batch__batch_name"]
                or sched["batch__title"]
                or sched["new_batch__title"]
            )

            result.append({
                "schedule_id": sched["schedule_id"],
                "course_name": sched["course__course_name"],
                "batch_name": batch_name,
                "scheduled_date": sched["scheduled_date"],
                "start_time": start_time.strftime("%I:%M %p"),
                "end_time": class_end.strftime("%I:%M %p"),
                "status": status
            })

        return result

    # ---------------------------------------------------------
    # UPCOMING CLASSES
    # ---------------------------------------------------------

    def get_upcoming_classes(self):

        schedules = (
            ClassSchedule.objects
            .filter(
                new_batch__students=self.student_id,
                scheduled_date__gte=date.today(),
                is_archived=False
            )
            .select_related("course", "trainer", "new_batch")
            .values(
                "scheduled_date",
                "start_time",
                "class_link",
                "course__course_name",
                "trainer__full_name",
                "new_batch__title"
            )
            .order_by("scheduled_date", "start_time")[:3]
        )

        return list(schedules)

    # ---------------------------------------------------------
    # ANNOUNCEMENTS
    # ---------------------------------------------------------

    def get_announcements(self):
        data = list(
            Announcement.objects
            .filter(
                audience__in=["all", "students"],
                is_archived=False
            )
            .values(
                "title",
                "content",
                "created_at",
                "content_pic",
                "background_pic",
            )
            .order_by("-created_at")[:5]
        )

        for item in data:
            if item["content_pic"]:
                item["content_pic_url"] = f"https://portal.aryuacademy.com/api/media/{item['content_pic']}"
            else:
                item["content_pic_url"] = None

            if item["background_pic"]:
                item["background_pic_url"] = f"https://portal.aryuacademy.com/api/media/{item['background_pic']}"
            else:
                item["background_pic_url"] = None

        return data

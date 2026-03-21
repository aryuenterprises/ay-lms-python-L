from .models import *
from .serializers import *
from rest_framework.exceptions import ValidationError
from aryuapp.auth import CustomJWTAuthentication
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated 
from collections import defaultdict
from datetime import datetime, time, timedelta
from rest_framework.decorators import action
import time
from datetime import datetime, timedelta, time
from django.utils import timezone
from django.contrib.auth.hashers import *
from django.db.models import Q, F, Prefetch
from aryuapp.mixins import *
from courses.models import CourseCategory
from aryuapp.views import has_permission
from aryuapp.utils import cache_api, delete_cache_pattern
# Create your views here.


class ClassScheduleView(LoggingMixin, viewsets.ModelViewSet, NotesMixin):
    serializer_class = ClassScheduleSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'schedule_id'

    def get_queryset(self):
        user = self.request.user
        qs = ClassSchedule.objects.filter(is_archived=False)

        # ---------------- SUPER ADMIN ----------------
        if user.user_type == "super_admin":
            super_admin_id = str(user.user_id)

            admin_ids = list(
                Trainer.objects.filter(
                    created_by=super_admin_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )
            admin_ids = [str(a) for a in admin_ids]

            trainer_ids = list(
                Trainer.objects.filter(
                    created_by__in=admin_ids,
                    created_by_type="admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )
            trainer_ids = [str(t) for t in trainer_ids]

            allowed_creators = admin_ids + trainer_ids + [super_admin_id]

            qs = qs.filter(
                Q(created_by__in=allowed_creators) |
                Q(trainer__trainer_id__in=trainer_ids)
            )

        # ---------------- ADMIN ----------------
        elif user.user_type == "admin" and getattr(user, "trainer_id", None):
            admin_trainer_id = str(user.trainer_id)

            trainer_ids = list(
                Trainer.objects.filter(
                    created_by=admin_trainer_id,
                    created_by_type="admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )
            trainer_ids = [str(t) for t in trainer_ids]

            qs = qs.filter(
                Q(created_by=admin_trainer_id) |
                Q(trainer__trainer_id__in=trainer_ids)
            )

        # ---------------- TRAINER ----------------
        elif user.user_type in ["tutor", "trainer"]:
            trainer_id = str(user.trainer_id)
            qs = qs.filter(trainer__trainer_id=trainer_id)

        return qs.select_related('batch', 'course', 'trainer').order_by('-scheduled_date')

    def list(self, request, *args, **kwargs):
        try:
            user = request.user
            user_type = user.user_type.lower()
            user_id = str(user.user_id)
            trainer_id = str(getattr(user, "trainer_id", None))
            allowed_types = ["super_admin", "admin"]
            if user_type not in allowed_types:
                return Response({
                    "success": False,
                    "message": "You are not authorized to access this API"
                }, status=200)
            
            now = timezone.now()

            schedule_qs = (
                self.get_queryset()
                .select_related("batch", "new_batch", "trainer", "course", "course__course_category")
                .prefetch_related(
                    Prefetch(
                        "batch__batchcoursetrainer",
                        queryset=BatchCourseTrainer.objects.select_related(
                            "course", "trainer", "student"
                        ),
                        to_attr="old_assignments"
                    ),
                    Prefetch(
                        "new_batch__students",
                        queryset=Student.objects.only("registration_id", "first_name", "last_name"),
                        to_attr="new_students"
                    )
                )
            )

            # ---------------- MONTH & YEAR FILTER ----------------
            month = request.query_params.get("month")
            year = request.query_params.get("year")

            if month and year:
                try:
                    month = int(month)
                    year = int(year)

                    schedule_qs = schedule_qs.filter(
                        scheduled_date__year=year,
                        scheduled_date__month=month
                    )
                except ValueError:
                    return Response({
                        "success": False,
                        "message": "Invalid month or year"
                    }, status=400)

            schedule_data = []

            for sched in schedule_qs:
                start_time = sched.start_time or time(9, 0)
                class_start = timezone.make_aware(datetime.combine(sched.scheduled_date, start_time))
                class_end = class_start + (sched.duration or timedelta(hours=1))

                if sched.end_time:
                    class_end = timezone.make_aware(datetime.combine(sched.scheduled_date, sched.end_time))

                if sched.is_class_cancelled:
                    status_info = "cancelled"
                elif now < class_start:
                    status_info = "upcoming"
                elif class_start <= now <= class_end:
                    status_info = "ongoing"
                else:
                    status_info = "completed"

                assignments_list = []

                # OLD ASSIGNMENTS (prefetched)
                for a in getattr(sched.batch, "old_assignments", []):
                    assignments_list.append({
                        "course_id": a.course.course_id,
                        "course_name": a.course.course_name,
                        "trainer_employee_id": a.trainer.employee_id,
                        "trainer_name": a.trainer.full_name,
                        "registration_id": a.student.registration_id,
                        "student_name": f"{a.student.first_name} {a.student.last_name}".strip(),
                        "batch_type": "old",
                    })

                # NEW BATCH ASSIGNMENTS (prefetched)
                if sched.new_batch:
                    for ns in sched.new_batch.new_students:
                        assignments_list.append({
                            "course_id": sched.new_batch.course.course_id if sched.new_batch.course else None,
                            "course_name": sched.new_batch.course.course_name if sched.new_batch.course else None,
                            "trainer_employee_id": sched.new_batch.trainer.employee_id if sched.new_batch.trainer else None,
                            "trainer_name": sched.new_batch.trainer.full_name if sched.new_batch.trainer else None,
                            "registration_id": ns.registration_id,
                            "student_name": f"{ns.first_name} {ns.last_name}".strip(),
                            "batch_type": "new",
                        })

                schedule_data.append({
                    "schedule_id": sched.schedule_id,
                    "course_id": sched.course.course_id if sched.course else None,
                    "course_name": sched.course.course_name if sched.course else None,
                    "category_name": sched.course.course_category.category_name
                        if sched.course and sched.course.course_category else None,

                    "batch_type": "old" if sched.batch else "new" if sched.new_batch else None,
                    "batch_id": sched.batch.batch_id if sched.batch else (
                        sched.new_batch.batch_id if sched.new_batch else None),
                    "batch_name": sched.batch.batch_name if sched.batch else None,
                    "title": (
                        sched.new_batch.title if sched.new_batch
                        else sched.batch.title if sched.batch
                        else None
                    ),
                    "start_date": sched.new_batch.start_date if sched.new_batch else None,
                    "end_date": sched.new_batch.end_date if sched.new_batch else None,

                    "trainer_employee_id": sched.trainer.employee_id if sched.trainer else None,
                    "trainer_name": sched.trainer.full_name if sched.trainer else None,

                    "scheduled_date": sched.scheduled_date,
                    "start_time": sched.start_time,
                    "end_time": sched.end_time,

                    "is_class_cancelled": sched.is_class_cancelled,
                    "is_online_class": sched.is_online_class,
                    "class_link": sched.class_link,

                    "course_trainer_assignments": assignments_list,
                    "status_info": status_info,
                    'is_archived': sched.is_archived,
                })

            # ------------------ Hierarchy-based Active Data ------------------
            batch_filter = Q(is_archived=False, status=True)
            course_filter = Q(is_archived=False, status__iexact="Active")
            category_filter = Q(is_archived=False)

            if user_type == "super_admin":
                user_id_str = str(user_id)

                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_id_str,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

                admin_ids_str = [str(i) for i in admin_ids]

                ownership_q = (
                    Q(created_by=user_id_str, created_by_type="super_admin") |
                    Q(created_by__in=admin_ids_str, created_by_type="admin")
                )

                batch_filter &= ownership_q
                course_filter &= ownership_q
                category_filter &= ownership_q


            elif user_type == "admin":
                trainer_id_str = str(trainer_id)

                super_admin_id = Trainer.objects.filter(
                    trainer_id=trainer_id
                ).values_list("created_by", flat=True).first()

                super_admin_id_str = str(super_admin_id) if super_admin_id else None

                ownership_q = (
                    Q(created_by=trainer_id_str, created_by_type="admin") |
                    Q(created_by=super_admin_id_str, created_by_type="super_admin")
                )

                batch_filter &= ownership_q
                course_filter &= ownership_q
                category_filter &= ownership_q


            # ------------------- Fetch batches -------------------
            batch_qs = NewBatch.objects.filter(batch_filter).select_related(
                "course", "course__course_category", "trainer"
            )

            batch_data = [
                {
                    "batch_id": b.batch_id,
                    "title": b.title,
                    "start_date": b.start_date,
                    "end_date": b.end_date,
                    "start_time": b.start_time,
                    "end_time": b.end_time,
                    "employee_id": b.trainer.employee_id if b.trainer else None,
                    "trainer_name": b.trainer.full_name if b.trainer else None,
                    "trainer_id": b.trainer.trainer_id if b.trainer else None,
                    "course_id": b.course.course_id if b.course else None,
                    "course_name": b.course.course_name if b.course else None,
                }
                for b in batch_qs
            ]


            # ------------------- Fetch courses with batches -------------------
            course_qs = Course.objects.filter(course_filter).select_related("course_category")
            course_data = [
                {
                    "course_id": c.course_id,
                    "course_name": c.course_name,
                    "category_id": c.course_category.category_id if c.course_category else None,
                    "category_name": c.course_category.category_name if c.course_category else None,
                } for c in course_qs
            ]

            # ------------------- Fetch trainers -------------------
            trainer_qs = Trainer.objects.filter(is_archived=False, status__iexact="Active", user_type='tutor')
            if user_type == "super_admin":
                trainer_qs = trainer_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user_type == "admin":
                trainer_qs = trainer_qs.filter(created_by=trainer_id)

            trainer_data = [
                {
                    "trainer_id": t.trainer_id,
                    "employee_id": t.employee_id,
                    "full_name": t.full_name,
                } for t in trainer_qs
            ]

            # ------------------- Categories -------------------
            category_qs = CourseCategory.objects.filter(category_filter).order_by("category_name")
            category_data = [
                {
                    "category_id": cat.category_id,
                    "category_name": cat.category_name,
                } for cat in category_qs
            ]

            # ------------------- Return response -------------------
            return Response({
                "success": True,
                "message": "Class schedule retrieved successfully",
                "Class_Schedule": schedule_data,
                "Batches": batch_data,          # Flat list
                "Courses": course_data,         # Courses with batches inside
                "Trainers": trainer_data,
                "Categories": category_data,
            })

        except Exception as e:
            return Response({"success": False, "message": str(e)})

    @cache_api(prefix="retrive_schedules", timeout=300)
    def retrieve(self, request, *args, **kwargs):
        try:
            sched = self.get_object()
            serializer = self.get_serializer(sched)
            return Response({
                "success": True,
                "message": "Schedule retrieved successfully.",
                "data": serializer.data
            }, status=200)
        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=200)
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
        # Collect all errors
            errors = []
            for field, msgs in serializer.errors.items():
                for msg in msgs:
                    if field == "non_field_errors":
                        errors.append(msg)
                    else:
                        errors.append(f"{field}: {msg}")

            return Response({
                "success": False,
                "message": " | ".join(errors)  # shows all missing/invalid fields
            }, status=status.HTTP_200_OK)

        class_schedule = serializer.save()
        return Response({
            "success": True,
            "message": "Class schedule created successfully.",
            "data": self.get_serializer(class_schedule).data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        try:
            partial = kwargs.pop('partial', False)
            sched = self.get_object()
            serializer = self.get_serializer(sched, data=request.data, partial=partial, context={'request': request})
            serializer.is_valid(raise_exception=True)
            serializer.save()

            # Save notes if provided in request
            notes_text = request.data.get("notes")
            if notes_text:
                mixin = NotesMixin()
                mixin.save_notes(sched, notes_text, request=request)

            return Response({
                "success": True,
                "message": "Schedule updated successfully",
                "data": serializer.data
            })
        except Exception as e:
            return Response({"success": False, "message": str(e)})

    def archive(self, request, schedule_id=None):
        try:
            class_schedule = ClassSchedule.objects.get(schedule_id=schedule_id)
            class_schedule.is_archived = True
            class_schedule.save()
            delete_cache_pattern("schedules*")
            return Response({'success': True, 'message': 'Class schedule deleted successfully.'}, status=200)
        except ClassSchedule.DoesNotExist:
            return Response({'success': False, 'message': 'Class schedule not found, but no error raised.'}, status=200)

    @cache_api(prefix="trainer_schedules", timeout=300)
    @action(detail=False, methods=['get'], url_path='schedules')
    def schedules(self, request, employee_id=None):
        from datetime import datetime, timedelta, time as dtime
        try:
            user = self.request.user
            now = timezone.now()

            # ------------------ BASE QUERYSET ------------------
            qs = ClassSchedule.objects.filter(
                trainer__employee_id=employee_id,
                is_archived=False
            ).all().select_related(
                "batch",
                "new_batch",
                "course",
                "trainer"
            ).order_by(
                "-scheduled_date",
                "-start_time"
            )

            # ------------------ MONTH & YEAR FILTER ------------------
            month = request.query_params.get("month")
            year = request.query_params.get("year")
            if month and year:
                try:
                    month_i = int(month)
                    year_i = int(year)
                    qs = qs.filter(
                        scheduled_date__year=year_i,
                        scheduled_date__month=month_i
                    )
                except ValueError:
                    return Response({
                        "success": False,
                        "message": "Invalid month or year"
                    }, status=400)

            # Materialize schedules to list to avoid re-evaluating queryset
            schedules = list(qs)

            # If no schedules return quickly (but still return batches/courses/trainers below)
            if not schedules:
                # compute batches/courses/trainer lists below from trainer id
                pass

            # For each schedule we will check attendance within [start-5min, end+5min]
            window_starts = []
            window_ends = []
            for sched in schedules:
                start_time = getattr(sched, "start_time", None) or dtime(9, 0)
                # class start dt
                class_start_dt = timezone.make_aware(
                    datetime.combine(sched.scheduled_date, start_time),
                    timezone.get_current_timezone()
                )

                # compute class end
                class_end_dt = class_start_dt + timedelta(hours=1)
                try:
                    if getattr(sched, "end_time", None):
                        class_end_dt = timezone.make_aware(
                            datetime.combine(sched.scheduled_date, sched.end_time),
                            timezone.get_current_timezone()
                        )
                    elif getattr(sched, "duration", None):
                        class_end_dt = class_start_dt + sched.duration
                except Exception:
                    class_end_dt = class_start_dt + timedelta(hours=1)

                buffer = timedelta(minutes=5)
                window_starts.append(class_start_dt - buffer)
                window_ends.append(class_end_dt + buffer)

            if window_starts and window_ends:
                global_start = min(window_starts)
                global_end = max(window_ends)
            else:
                # no schedules: fallback to today window
                global_start = timezone.now() - timedelta(days=1)
                global_end = timezone.now() + timedelta(days=1)

            # ------------------ BULK FETCH ATTENDANCE for all relevant trainers/batches/courses ------------------
            trainer_obj = None
            if schedules:
                trainer_obj = schedules[0].trainer  # all schedules are for same trainer.employee_id

            attendance_map = defaultdict(list)  # key => list of attendance rows
            if trainer_obj:
                attendance_qs = TrainerAttendance.objects.filter(
                    trainer=trainer_obj,
                    date__gte=global_start,
                    date__lte=global_end,
                    status__in=["Login", "Logout", "Present"]
                ).select_related("batch", "course", "trainer").order_by("-date")

                # Group attendance by (batch_id, course_id)
                for att in attendance_qs:
                    key = (getattr(att.batch, "batch_id", None), getattr(att.course, "course_id", None))
                    attendance_map[key].append(att)

            # ------------------ PRELOAD OLD-BATCH ASSIGNMENTS (BatchCourseTrainer) ------------------
            old_batch_ids = [sched.batch.batch_id for sched in schedules if getattr(sched, "batch", None)]
            old_batch_ids = list(set(old_batch_ids))

            bct_map = defaultdict(list)
            if old_batch_ids:
                bct_qs = BatchCourseTrainer.objects.filter(
                    batch__batch_id__in=old_batch_ids,
                    trainer__employee_id=employee_id
                ).select_related("course", "trainer", "student")

                for bct in bct_qs:
                    bid = getattr(bct.batch, "batch_id", None)
                    bct_map[bid].append(bct)

            # ------------------ PRELOAD NEW-BATCH STUDENTS ------------------
            new_batch_ids = [sched.new_batch.batch_id for sched in schedules if getattr(sched, "new_batch", None)]
            new_batch_ids = list(set(new_batch_ids))

            newbatch_students_map = {}
            if new_batch_ids:
                nb_qs = NewBatch.objects.filter(batch_id__in=new_batch_ids).prefetch_related("students")
                for nb in nb_qs:
                    newbatch_students_map[nb.batch_id] = list(nb.students.all().values("registration_id", "first_name", "last_name"))

            # ------------------ BUILD schedule_data (single loop, no DB hits inside) ------------------
            schedule_data = []
            current_time = timezone.now()

            for sched in schedules:
                start_time = getattr(sched, 'start_time', None) or dtime(9, 0)
                class_start_dt = timezone.make_aware(
                    datetime.combine(sched.scheduled_date, start_time),
                    timezone.get_current_timezone()
                )

                # compute class end as above
                class_end_dt = class_start_dt + timedelta(hours=1)
                try:
                    if getattr(sched, 'end_time', None):
                        class_end_dt = timezone.make_aware(
                            datetime.combine(sched.scheduled_date, sched.end_time),
                            timezone.get_current_timezone()
                        )
                    elif getattr(sched, 'duration', None):
                        class_end_dt = class_start_dt + sched.duration
                except Exception:
                    class_end_dt = class_start_dt + timedelta(hours=1)

                buffer = timedelta(minutes=5)
                window_start = class_start_dt - buffer
                window_end = class_end_dt + buffer

                key = (getattr(sched.batch, "batch_id", None), getattr(sched.course, "course_id", None))
                attendance_for_key = attendance_map.get(key, [])

                # Determine status_info
                if sched.is_class_cancelled:
                    status_info = 'cancelled'
                elif current_time < class_start_dt:
                    status_info = "upcoming"
                elif class_start_dt <= current_time <= class_end_dt:
                    status_info = "ongoing"
                else:
                    # completed if any attendance exists in window, else missed
                    # attendance_for_key already contains attendances in global window; filter by schedule window
                    exists_in_window = any((a.date >= window_start and a.date <= window_end) for a in attendance_for_key)
                    status_info = "completed" if exists_in_window else "missed"

                old_batch = getattr(sched, "batch", None)
                new_batch = getattr(sched, "new_batch", None)
                batch_obj = old_batch if old_batch else new_batch
                batch_name = old_batch.batch_name if old_batch else (new_batch.title if new_batch else None)

                # ------------------ ASSIGNMENTS: old_batch -> from bct_map, new_batch -> from newbatch_students_map
                if old_batch:
                    assignments_list = []
                    bct_list = bct_map.get(old_batch.batch_id, [])
                    for a in bct_list:
                        student = a.student
                        assignments_list.append({
                            "course_id": a.course.course_id if a.course else None,
                            "course_name": a.course.course_name if a.course else None,
                            "employee_id": a.trainer.employee_id if a.trainer else None,
                            "trainer_name": a.trainer.full_name if a.trainer else None,
                            "registration_id": student.registration_id if student else None,
                            "student_name": f"{getattr(student,'first_name','')} {getattr(student,'last_name','')}".strip()
                        })
                elif new_batch:
                    assignments_list = []
                    students_vals = newbatch_students_map.get(new_batch.batch_id, [])
                    for s in students_vals:
                        assignments_list.append({
                            "course_id": getattr(sched.course, "course_id", None),
                            "course_name": getattr(sched.course, "course_name", None),
                            "employee_id": sched.trainer.employee_id if sched.trainer else None,
                            "trainer_name": sched.trainer.full_name if sched.trainer else None,
                            "registration_id": s.get("registration_id"),
                            "student_name": f"{s.get('first_name','')} {s.get('last_name','')}".strip()
                        })
                else:
                    assignments_list = []

                # latest_log and attendance_status
                # filter attendance_for_key to schedule window and pick latest by date
                in_window_att = [a for a in attendance_for_key if a.date >= window_start and a.date <= window_end]
                in_window_att.sort(key=lambda x: x.date, reverse=True)
                latest_log = in_window_att[0] if in_window_att else None
                attendance_status = latest_log.status if latest_log else None

                schedule_data.append({
                    "schedule_id": getattr(sched, "schedule_id", None),
                    "course_id": getattr(sched.course, "course_id", None),
                    "course_name": getattr(sched.course, "course_name", None),
                    "batch_id": getattr(batch_obj, "batch_id", None),
                    "batch_name": batch_name,
                    "title": getattr(batch_obj, "title", None),
                    "trainer_id": sched.trainer.employee_id if sched.trainer else None,
                    "trainer_name": sched.trainer.full_name if sched.trainer else None,
                    "scheduled_date": getattr(sched, "scheduled_date", None),
                    "class_link": getattr(sched, "class_link", None),
                    "course_trainer_assignments": assignments_list,
                    "start_time": sched.start_time,
                    "end_time": sched.end_time,
                    "is_class_cancelled": sched.is_class_cancelled,
                    "attendance_status": attendance_status,
                    "status_info": status_info,
                })

            # ------------------ HIERARCHY FILTERED BATCHES ------------------
            # New system batches for this trainer only
            new_batch_qs = NewBatch.objects.filter(
                trainer__employee_id=employee_id,
                is_archived=False,
                status=True
            ).select_related("trainer", "course").order_by("batch_id")

            # Old batches where trainer is linked via BatchCourseTrainer
            old_batch_ids_for_trainer = BatchCourseTrainer.objects.filter(
                trainer__employee_id=employee_id
            ).values_list("batch__batch_id", flat=True).distinct()

            old_batch_qs = Batch.objects.filter(
                batch_id__in=old_batch_ids_for_trainer,
                is_archived=False
            )


            # Combine: ensure same structure as before
            batch_data = []
            for b in new_batch_qs:
                batch_data.append({
                    "batch_id": b.batch_id,
                    "title": b.title,
                    "start_date": b.start_date,
                    "end_date": b.end_date,
                    "start_time": b.start_time,
                    "end_time": b.end_time,
                    "employee_id": b.trainer.employee_id if b.trainer else None,
                    "trainer_name": b.trainer.full_name if b.trainer else None,
                    "trainer_id": b.trainer.trainer_id if b.trainer else None,
                    "course_id": b.course.course_id if b.course else None,
                    "course_name": b.course.course_name if b.course else None,
                })

            for b in old_batch_qs:

                # get the course used by old batch
                bct_course = BatchCourseTrainer.objects.filter(batch=b).select_related("course").first()
                course_obj = bct_course.course if bct_course else None

                # get trainer (through batchcoursetrainer)
                bct_trainer = BatchCourseTrainer.objects.filter(batch=b).select_related("trainer").first()
                trainer_obj = bct_trainer.trainer if bct_trainer else None

                # time comes only from schedules, not from batch table
                sched = ClassSchedule.objects.filter(batch=b).order_by("start_time").first()

                batch_data.append({
                    "batch_id": b.batch_id,
                    "title": b.title,
                    "start_date": b.scheduled_date,
                    "end_date": b.end_date,

                    # old batch does NOT have time → take from schedule if exists
                    "start_time": sched.start_time if sched else None,
                    "end_time": sched.end_time if sched else None,

                    "employee_id": trainer_obj.employee_id if trainer_obj else None,
                    "trainer_name": trainer_obj.full_name if trainer_obj else None,
                    "trainer_id": trainer_obj.trainer_id if trainer_obj else None,

                    "course_id": course_obj.course_id if course_obj else None,
                    "course_name": course_obj.course_name if course_obj else None,
                })

            # ------------------ COURSES ------------------
            old_course_ids = BatchCourseTrainer.objects.filter(
                trainer__employee_id=employee_id
            ).values_list('course_id', flat=True)

            new_course_ids = NewBatch.objects.filter(
                trainer__employee_id=employee_id,
                is_archived=False
            ).values_list('course_id', flat=True)

            course_ids = list(set(list(old_course_ids) + list(new_course_ids)))

            course_data = Course.objects.filter(
                course_id__in=course_ids,
                is_archived=False,
                status__iexact='Active'
            ).order_by('course_id').values('course_id', 'course_name', "course_category")

            # ------------------ HIERARCHY FILTERED TRAINERS ------------------
            user_type = user.user_type.lower() if getattr(user, "user_type", None) else ""
            user_id = str(getattr(user, "user_id", ""))  # safe fallback
            trainer_id = str(getattr(user, "trainer_id", ""))

            batch_for_hierarchy = NewBatch.objects.filter(is_archived=False, status=True)
            trainer_queryset = Trainer.objects.filter(is_archived=False, status__iexact='Active')

            if user_type == "super_admin":
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )
                trainer_ids = list(
                    Trainer.objects.filter(
                        created_by__in=admin_ids,
                        created_by_type="admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )
                allowed_creators = [user_id] + admin_ids

                batch_for_hierarchy = batch_for_hierarchy.filter(
                    created_by__in=allowed_creators,
                    created_by_type__in=["super_admin", "admin"]
                )
                
                trainer_queryset = trainer_queryset.filter(
                    trainer_id__in=trainer_ids + admin_ids
                )

            elif user_type == "admin" and trainer_id:
                super_admin_id = Trainer.objects.filter(
                    trainer_id=trainer_id
                ).values_list("created_by", flat=True).first()

                trainer_ids = list(
                    Trainer.objects.filter(
                        created_by=trainer_id,
                        created_by_type="admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

                batch_for_hierarchy = batch_for_hierarchy.filter(
                    Q(created_by=trainer_id, created_by_type="admin") |
                    Q(created_by=super_admin_id, created_by_type="super_admin")
                )
                
                trainer_queryset = trainer_queryset.filter(trainer_id__in=trainer_ids)

            trainer_data = list(trainer_queryset.order_by('employee_id').values(
                'employee_id', 'full_name', 'trainer_id'
            ))

            # ------------------ FINAL RESPONSE ------------------
            return Response({
                "success": True,
                "message": f"Class schedules for employee {employee_id}" if employee_id else "Class schedules",
                "Class_Schedule": schedule_data,
                "Batches": list(batch_data),
                "Trainers": trainer_data,
                "Courses": list(course_data),
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "success": False,
                "message": f"{str(e)}"
            }, status=status.HTTP_200_OK)

class RecurringScheduleView(viewsets.ModelViewSet, LoggingMixin):
    queryset = RecurringSchedule.objects.all().order_by('-recurring_id')
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    serializer_class = RecurringScheduleSerializer
    
    def create(self, request, *args, **kwargs):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            recurring_schedule = serializer.save()
            return Response({
                "success": True,
                "message": "Recurring schedule created successfully.",
                "data": self.get_serializer(recurring_schedule).data
            }, status=201)

        except ValidationError as ve:
            # Extract first error string from dict
            detail = ve.detail
            message = ""
            if isinstance(detail, dict):
                # Get first key's first error message
                first_key = list(detail.keys())[0]
                first_error = detail[first_key]
                if isinstance(first_error, list):
                    message = first_error[0]
                else:
                    message = str(first_error)
            elif isinstance(detail, list):
                message = detail[0]
            else:
                message = str(detail)

            return Response({
                "success": False,
                "message": message
            }, status=200)

        except Exception as e:
            return Response({
                "success": False,
                "message": f"Something went wrong: {str(e)}"
            }, status=200)

class BatchViewSet(LoggingMixin, viewsets.ModelViewSet, NotesMixin):
    queryset = Batch.objects.all()
    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'batch_id'

    def get_queryset(self):
        user = self.request.user
        qs = Batch.objects.filter(is_archived=False).prefetch_related("schedules__course", "schedules__trainer")

        if user.user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id, 
                    created_by_type="super_admin", 
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )
            courses = Course.objects.filter(is_archived=False)  # remove status__iexact="Active"
            courses = courses.filter(
                Q(created_by_type="super_admin", created_by=user_created_id) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )
            qs = qs.filter(batchcoursetrainer__course__in=courses).distinct()

        elif user.user_type == "admin" and getattr(user, "trainer_id", None):
            trainer_id = user.trainer_id
            courses = Course.objects.filter(is_archived=False, created_by=trainer_id)  # remove status__iexact="Active"
            qs = qs.filter(batchcoursetrainer__course__in=courses).distinct()

        return qs.order_by('-batch_id')

    def list(self, request, *args, **kwargs):
        user = request.user
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        try:
            user_created_id = getattr(user, "trainer_id", None)  # For admin
            if user.user_type == "super_admin":
                user_created_id = getattr(user, "user_id", None)

            # Get admin IDs for super_admin
            admin_ids = []
            if user.user_type == "super_admin" and user_created_id:
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_created_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

            # --- Students ---
            student_qs = Student.objects.filter(is_archived=False, status=True)
            if user.user_type == "super_admin":
                student_qs = student_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                student_qs = student_qs.filter(created_by=user_created_id)

            student_list = [
                {
                    "registration_id": s.registration_id,
                    "student_id": s.student_id,
                    "full_name": f"{s.first_name} {s.last_name}"
                }
                for s in student_qs
            ]

            # --- Trainers ---
            trainer_qs = Trainer.objects.filter(is_archived=False, status__iexact="Active", user_type='tutor')
            if user.user_type == "super_admin":
                trainer_qs = trainer_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                trainer_qs = trainer_qs.filter(created_by=user_created_id)

            # --- Courses ---
            course_qs = Course.objects.filter(is_archived=False, status__iexact="Active")
            if user.user_type == "super_admin":
                course_qs = course_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                course_qs = course_qs.filter(created_by=user_created_id)

            # --- Categories ---
            category_qs = CourseCategory.objects.filter(is_archived=False, status=True)
            if user.user_type == "super_admin":
                category_qs = category_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin" and user_created_id:
                category_qs = category_qs.filter(created_by=user_created_id)

            return Response({
                "success": True,
                "message": "Active Batch list",
                "count": queryset.count(),
                "data": serializer.data,
                "active_category": list(category_qs.values("category_id", "category_name")),
                "active_student": student_list,
                "active_trainer": list(trainer_qs.values("employee_id", "full_name")),
                "active_course": list(course_qs.values("course_id", "course_name", "course_category_id")),
            })

        except Exception as e:
            return Response({
                "success": False,
                "message": f"Something went wrong: {str(e)}"
            }, status=200)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        user = request.user

        # Ensure module_id points to Batch
        batch_module = ModulePermission.objects.filter(module__iexact="Batch").first()
        if not batch_module:
            return Response({"success": False, "message": "Batch module not found"}, status=200)

        if not has_permission(user, module_id=batch_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)
        
        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "success": False,
                "message": error_message
            }, status=status.HTTP_200_OK)
        
        batch = serializer.save()
        return Response({
            "success": True,
            "message": "Batch created successfully.",
            "data": self.get_serializer(batch).data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        user = request.user

        batch_module = ModulePermission.objects.filter(module__iexact="Batch").first()
        if not batch_module:
            return Response({"success": False, "message": "Batch module not found"}, status=200)

        if not has_permission(user, module_id=batch_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)

        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)

        # Save notes if provided in request
        notes_text = request.data.get("notes")
        if notes_text:
            mixin = NotesMixin()
            mixin.save_notes(instance, notes_text, request=request)

        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "success": False,
                "message": error_message
            }, status=status.HTTP_200_OK)
        
        linked_courses = Course.objects.filter(
            batchcoursetrainer__batch=instance,
            is_archived=False
        ).distinct()

        for course in linked_courses:
            if course.status.lower() != "active":
                return Response({
                    "success": False,
                    "message": f"Cannot activate batch because course '{course.course_name}' is inactive."
                }, status=200)

            if course.course_category and not course.course_category.status:
                return Response({
                    "success": False,
                    "message": f"Cannot activate batch because category '{course.course_category.category_name}' is inactive."
                }, status=200)
        
        batch = serializer.save()

        # Save notes again after successful update (optional)
        if notes_text:
            self.save_notes(batch, notes_text, request=request)

        return Response({
            "success": True,
            "message": "Batch updated successfully.",
            "data": self.get_serializer(batch).data
        })

    def is_archived(self, request, *args, **kwargs):
        try:
            batch = self.get_object()
            batch.is_archived = True  # Soft delete by archiving
            batch.save()
            return Response({
                "success": True,
                "message": "Batch deleted successfully."
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                "success": False,
                "message": f"Failed to delete batch: {str(e)}"
            }, status=status.HTTP_200_OK)

class NewBatchViewSet(LoggingMixin, viewsets.ViewSet, NotesMixin):
    lookup_field = 'batch_id'
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    queryset = NewBatch.objects.filter(is_archived=False)
    serializer_class = NewBatchSerializer

    def get_serializer(self, *args, **kwargs):
        kwargs.setdefault("context", {"request": self.request})
        return self.serializer_class(*args, **kwargs)

    # FIXED: Don't return Response here
    def get_object(self):
        pk = self.kwargs.get('pk')
        try:
            return NewBatch.objects.get(batch_id=pk, is_archived=False)
        except NewBatch.DoesNotExist:
            return Response({"success": False, "message": "Batch not found"}, status=status.HTTP_200_OK)
    
    from django.contrib.contenttypes.models import ContentType
    
    def list(self, request):
        try:
            user = request.user
            user_type = str(getattr(user, "user_type", "")).lower()
            user_id = str(getattr(user, "user_id", None))
            trainer_id = str(getattr(user, "trainer_id", None))

            batch_filter = Q(is_archived=False)
            course_filter = Q(is_archived=False, status="Active")
            category_filter = Q(is_archived=False, status=True)

            admin_ids = []

            if user_type == "super_admin":
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )

                batch_filter &= Q(created_by=user_id, created_by_type="super_admin") | Q(created_by__in=admin_ids, created_by_type="admin")
                course_filter &= Q(created_by=user_id, created_by_type="super_admin") | Q(created_by__in=admin_ids, created_by_type="admin")
                category_filter &= Q(created_by=user_id, created_by_type="super_admin") | Q(created_by__in=admin_ids, created_by_type="admin")

            elif user_type == "admin" and trainer_id:
                super_admin_id = Trainer.objects.filter(trainer_id=trainer_id).values_list("created_by", flat=True).first()
                batch_filter &= Q(created_by=trainer_id, created_by_type="admin") | Q(created_by=super_admin_id, created_by_type="super_admin")
                course_filter &= Q(created_by=trainer_id, created_by_type="admin") | Q(created_by=super_admin_id, created_by_type="super_admin")
                category_filter &= Q(created_by=trainer_id, created_by_type="admin") | Q(created_by=super_admin_id, created_by_type="super_admin")

            # -------- FETCH ALL DATA ONCE --------

            old_batches = list(
                Batch.objects.filter(batch_filter)
                .select_related()
                .order_by("-created_at")
            )

            new_batches = list(
                NewBatch.objects.filter(is_archived=False)
                .select_related("course__course_category", "trainer")
                .prefetch_related("students")
                .order_by("-created_at")
            )

            old_batch_ids = [b.batch_id for b in old_batches]
            new_batch_ids = [b.batch_id for b in new_batches]

            # -------- PREFETCH ASSIGNMENTS --------

            assignments = BatchCourseTrainer.objects.filter(
                batch_id__in=old_batch_ids
            ).select_related("course", "trainer", "student", "course__course_category")

            assignment_map = {}
            for a in assignments:
                assignment_map.setdefault(a.batch_id, []).append(a)

            # -------- PREFETCH SCHEDULES --------

            old_schedules = ClassSchedule.objects.filter(
                batch_id__in=old_batch_ids
            ).select_related("course", "trainer")

            new_schedules = ClassSchedule.objects.filter(
                new_batch_id__in=new_batch_ids,
                is_archived=False
            ).select_related("course", "trainer")

            schedule_old_map = {}
            for s in old_schedules:
                schedule_old_map.setdefault(s.batch_id, []).append({
                    "schedule_id": s.schedule_id,
                    "course_id": s.course_id,
                    "course__course_name": s.course.course_name if s.course else None,
                    "trainer_id": s.trainer_id,
                    "trainer__full_name": s.trainer.full_name if s.trainer else None,
                    "scheduled_date": s.scheduled_date,
                    "start_time": s.start_time,
                    "end_time": s.end_time
                })

            schedule_new_map = {}
            for s in new_schedules:
                schedule_new_map.setdefault(s.new_batch_id, []).append({
                    "schedule_id": s.schedule_id,
                    "course_id": s.course_id,
                    "course__course_name": s.course.course_name if s.course else None,
                    "trainer_id": s.trainer_id,
                    "trainer__full_name": s.trainer.full_name if s.trainer else None,
                    "scheduled_date": s.scheduled_date,
                    "start_time": s.start_time,
                    "end_time": s.end_time
                })

            # -------- PREFETCH NOTES --------

            from django.contrib.contenttypes.models import ContentType

            batch_ct = ContentType.objects.get_for_model(Batch)

            notes = Note.objects.filter(
                object_id__in=old_batch_ids + new_batch_ids,
                content_type=batch_ct
            ).order_by("-created_at")

            notes_map = {}
            for n in notes:
                notes_map.setdefault(n.object_id, []).append(n)

            # -------- BUILD RESPONSE --------

            unified_batches = []

            # OLD BATCHES
            for b in old_batches:

                assigns = assignment_map.get(b.batch_id, [])

                trainer_data = None
                course_data = None
                students_data = []

                if assigns:
                    first = assigns[0]

                    if first.course:
                        course_data = {
                            "course_id": first.course.course_id,
                            "course_name": first.course.course_name
                        }

                    if first.trainer:
                        trainer_data = {
                            "trainer_id": first.trainer.trainer_id,
                            "trainer_name": first.trainer.full_name
                        }

                    for a in assigns:
                        if a.student:
                            students_data.append({
                                "student_id": a.student.student_id,
                                "full_name": f"{a.student.first_name} {a.student.last_name}".strip(),
                                "registration_id": a.student.registration_id
                            })

                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": getattr(n.created_by, "username", "") if n.created_by else "",
                        "created_at": n.created_at.strftime("%Y-%m-%d %I:%M:%S %p")
                    }
                    for n in notes_map.get(b.batch_id, [])
                ]

                unified_batches.append({
                    "id": b.batch_id,
                    "title": b.title,
                    "course": course_data.get("course_id") if course_data else None,
                    "course_name": course_data.get("course_name") if course_data else None,
                    "trainer_id": trainer_data.get("trainer_id") if trainer_data else None,
                    "trainer_name": trainer_data.get("trainer_name") if trainer_data else None,
                    "start_date": getattr(b, "start_date", None),
                    "end_date": getattr(b, "end_date", None),
                    "start_time": getattr(b, "start_time", None),
                    "end_time": getattr(b, "end_time", None),
                    "slots": getattr(b, "slots", None),
                    "created_at": b.created_at,
                    "status": b.status,
                    "created_by": b.created_by,
                    "created_by_type": b.created_by_type,
                    "is_archived": b.is_archived,
                    "available_slots": getattr(b, "available_slots", None),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "schedules": schedule_old_map.get(b.batch_id, []),
                    "source": "old"
                })

            # NEW BATCHES
            for nb in new_batches:

                students_data = [
                    {
                        "student_id": s.student_id,
                        "full_name": f"{s.first_name} {s.last_name}".strip(),
                        "registration_id": s.registration_id
                    }
                    for s in nb.students.all()
                ]

                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": n.created_by if n.created_by else "",
                        "created_by_type": n.created_by_type,
                        "status": n.status,
                        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M"),
                    }
                    for n in notes_map.get(nb.batch_id, [])
                ]

                unified_batches.append({
                    "id": nb.batch_id,
                    "title": nb.title,
                    "course": nb.course.course_id if nb.course else None,
                    "course_name": nb.course.course_name if nb.course else None,
                    "category": nb.course.course_category.category_id if nb.course and nb.course.course_category else None,
                    "trainer_id": nb.trainer.trainer_id if nb.trainer else None,
                    "trainer_name": nb.trainer.full_name if nb.trainer else None,
                    "start_date": nb.start_date,
                    "end_date": nb.end_date,
                    "start_time": nb.start_time,
                    "end_time": nb.end_time,
                    "slots": nb.slots,
                    "created_at": nb.created_at,
                    "created_by": nb.created_by,
                    "created_by_type": nb.created_by_type,
                    "is_archived": nb.is_archived,
                    "status": nb.status,
                    "available_slots": nb.available_slots(),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "schedules": schedule_new_map.get(nb.batch_id, []),
                    "source": "new"
                })

            unified_batches = sorted(unified_batches, key=lambda x: x["created_at"], reverse=True)

            # -------- ACTIVE DATA --------

            user_created_id = getattr(user, "trainer_id", None)
            if user.user_type == "super_admin":
                user_created_id = getattr(user, "user_id", None)

            student_qs = Student.objects.filter(is_archived=False, status=True)

            if user.user_type == "super_admin":
                student_qs = student_qs.filter(
                    Q(created_by_type="super_admin", created_by=user_created_id) |
                    Q(created_by_type="admin", created_by__in=admin_ids)
                )
            elif user.user_type == "admin":
                student_qs = student_qs.filter(created_by=user_created_id)

            student_list = [
                {
                    "registration_id": s.registration_id,
                    "student_id": s.student_id,
                    "full_name": f"{s.first_name} {s.last_name}"
                }
                for s in student_qs
            ]

            trainer_qs = Trainer.objects.filter(
                is_archived=False,
                status__iexact="Active",
                user_type="tutor"
            )

            category_qs = CourseCategory.objects.filter(category_filter)
            course_qs = Course.objects.filter(course_filter)

            return Response({
                "success": True,
                "message": "Unified batch list retrieved successfully.",
                "batches": unified_batches,
                "active_student": student_list,
                "active_trainer": list(trainer_qs.values("employee_id", "full_name", "trainer_id")),
                "active_category": list(category_qs.values("category_id", "category_name")),
                "active_course": list(course_qs.values("course_id", "course_name", "course_category_id"))
            })

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            })

    def retrieve(self, request, batch_id=None):
        
        batch = NewBatch.objects.filter(batch_id=batch_id, is_archived=False).first()
        batch_type = "new" if batch else "old"

        if not batch:
            batch = Batch.objects.filter(batch_id=batch_id, is_archived=False).first()
            if not batch:
                return Response({"success": False, "message": "Batch not found"}, status=200)
            batch_type = "old"

        serializer = NewBatchSerializer(batch, context={"request": request}) if batch_type == "new" else BatchSerializer(batch, context={"request": request})
        return Response({"success": True, "data": serializer.data}, status=200)
    
    @action(detail=False, methods=['get'], url_path='trainer/(?P<trainer_id>[^/.]+)')
    def trainer_batches(self, request, trainer_id):
        try:
            trainer_id = str(trainer_id)

            unified_batches = []

            # ----------------------------
            # OLD BATCHES
            # ----------------------------
            assigned_old_batch_ids = BatchCourseTrainer.objects.filter(
                trainer__trainer_id=trainer_id
            ).values_list("batch_id", flat=True)

            old_batches = Batch.objects.filter(
                batch_id__in=assigned_old_batch_ids,
                is_archived=False
            ).order_by("-created_at")

            for b in old_batches:
                assignments = BatchCourseTrainer.objects.filter(batch=b)

                # students
                students_data = []
                for a in assignments:
                    if a.student:
                        students_data.append({
                            "student_id": a.student.student_id,
                            "registration_id": a.student.registration_id,
                            "full_name": f"{a.student.first_name} {a.student.last_name}".strip()
                        })

                # trainer + course
                trainer_data = None
                course_data = None
                if assignments.exists():
                    first = assignments.first()
                    trainer_data = {
                        "trainer_id": first.trainer.trainer_id if first.trainer else None,
                        "trainer_name": first.trainer.full_name if first.trainer else None
                    }
                    course_data = {
                        "course_id": first.course.course_id if first.course else None,
                        "course_name": first.course.course_name if first.course else None
                    }

                # schedules
                schedules = ClassSchedule.objects.filter(batch=b).values(
                    "schedule_id",
                    "course_id",
                    "course__course_name",
                    "trainer_id",
                    "trainer__full_name",
                    "scheduled_date",
                    "start_time",
                    "end_time",
                )

                # notes
                note_ct = ContentType.objects.get_for_model(Batch)
                old_notes = Note.objects.filter(
                    object_id=b.batch_id,
                    content_type=note_ct
                ).order_by("-created_at")

                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": getattr(n.created_by, "username", ""),
                        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M")
                    }
                    for n in old_notes
                ]

                unified_batches.append({
                    "id": b.batch_id,
                    "title": b.title,
                    "course": course_data.get("course_id") if course_data else None,
                    "course_name": course_data.get("course_name") if course_data else None,
                    "category": None,
                    "trainer": trainer_data.get("trainer_id") if trainer_data else None,
                    "trainer_name": trainer_data.get("full_name") if trainer_data else None,
                    "start_date": b.scheduled_date,
                    "end_date": b.end_date,
                    "start_time": b.start_time if hasattr(b, "start_time") else None,
                    "end_time": b.end_time if hasattr(b, "end_time") else None,
                    "slots": b.slots if hasattr(b, "slots") else None,
                    "created_at": b.created_at,
                    "created_by": b.created_by,
                    "created_by_type": b.created_by_type,
                    "status": b.status,
                    "is_archived": b.is_archived,
                    "available_slots": getattr(b, "available_slots", None),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "schedules": list(schedules),
                    "source": "old"
                })

            new_batches = NewBatch.objects.filter(
                trainer__trainer_id=trainer_id,
                is_archived=False
            ).order_by("-created_at")

            for nb in new_batches:

                # students
                students_data = [
                    {
                        "student_id": s.student_id,
                        "registration_id": s.registration_id,
                        "full_name": f"{s.first_name} {s.last_name}".strip()
                    }
                    for s in nb.students.all()
                ]

                # schedules
                schedules = ClassSchedule.objects.filter(
                    batch__batch_id=nb.batch_id
                ).annotate(
                    course_name=F("course__course_name"),
                    trainer_name=F("trainer__full_name")
                ).values(
                    "schedule_id",
                    "course_id",
                    "course__course_name",
                    "trainer_id",
                    "trainer__full_name",
                    "scheduled_date",
                    "start_time",
                    "end_time",
                )

                # notes
                note_ct = ContentType.objects.get_for_model(NewBatch)
                new_notes = Note.objects.filter(
                    object_id=nb.pk,
                    content_type=note_ct
                ).order_by("-created_at")

                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": n.created_by,
                        "created_by_type": n.created_by_type,
                        "status": n.status,
                        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M"),
                    }
                    for n in new_notes
                ]

                unified_batches.append({
                    "id": nb.batch_id,
                    "title": nb.title,
                    "course": nb.course.course_id if nb.course else None,
                    "category": nb.course.course_category.category_id if nb.course and nb.course.course_category else None,
                    "course_name": nb.course.course_name if nb.course else None,
                    "trainer": nb.trainer.trainer_id if nb.trainer else None,
                    "trainer_name": nb.trainer.full_name if nb.trainer else None,
                    "start_date": nb.start_date,
                    "end_date": nb.end_date,
                    "start_time": nb.start_time,
                    "end_time": nb.end_time,
                    "slots": nb.slots,
                    "status": nb.status,
                    "created_at": nb.created_at,
                    "created_by": nb.created_by,
                    "created_by_type": nb.created_by_type,
                    "is_archived": nb.is_archived,
                    "available_slots": nb.available_slots(),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "schedules": list(schedules),
                    "source": "new"
                })

            trainer_id = trainer_id
            # Get all courses assigned to this trainer via NewBatch
            assigned_course_ids = NewBatch.objects.filter(
                trainer__trainer_id=trainer_id,
                is_archived=False,
                status=True
            ).values_list("course_id", flat=True).distinct()
            
            course_queryset = Course.objects.filter(
                course_id__in=assigned_course_ids,
                is_archived=False,
                status__iexact='Active'
            )
            
            course_data = course_queryset.annotate(
                category_id=F('course_category__category_id')).values('course_id', 'course_name', 'category_id')
            
            category_ids = course_queryset.values_list('course_category__category_id', flat=True).distinct()
            
            categories = CourseCategory.objects.filter(category_id__in=category_ids).values(
                'category_id', 'category_name'
            )
            
            # From NEW batches (NewBatch -> students M2M)
            new_batches = NewBatch.objects.filter(
                trainer__trainer_id=trainer_id,
                is_archived=False
            ).order_by("-created_at")

            for nb in new_batches:

                # students
                students_data = [
                    {
                        "student_id": s.student_id,
                        "registration_id": s.registration_id,
                        "full_name": f"{s.first_name} {s.last_name}".strip()
                    }
                    for s in nb.students.all()
                ]

            return Response({
                "success": True,
                "message": "Trainer filtered batches retrieved successfully.",
                "batches": unified_batches,
                "active_course": course_data,
                "assigned_students": students_data,
                'active_category': categories
            })

        except Exception as e:
            return Response({"success": False, "message": str(e)})
        
    @action(detail=False, methods=['get'], url_path='student/(?P<student_id>[^/.]+)')
    def student_batches(self, request, student_id):
        try:
            student_id = str(student_id)
            unified_batches = []

            # ---------------- OLD BATCHES ----------------
            assigned_old_batch_ids = BatchCourseTrainer.objects.filter(
                student__student_id=student_id
            ).values_list("batch_id", flat=True)

            old_batches = Batch.objects.filter(
                batch_id__in=assigned_old_batch_ids,
                is_archived=False
            ).order_by("-created_at")

            for b in old_batches:
                assignments = BatchCourseTrainer.objects.filter(batch=b, student__student_id=student_id)

                students_data = [
                    {
                        "student_id": a.student.student_id,
                        "full_name": f"{a.student.first_name} {a.student.last_name}".strip(),
                        "trainer_id": a.trainer.trainer_id if a.trainer else None,
                        "trainer_name": a.trainer.full_name if a.trainer else None,
                        "course_id": a.course.course_id if a.course else None
                    }
                    for a in assignments
                ]

                # Notes
                note_ct = ContentType.objects.get_for_model(Batch)
                notes_qs = Note.objects.filter(object_id=b.batch_id, content_type=note_ct).order_by("-created_at")
                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": getattr(n.created_by, "username", ""),
                        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M")
                    } for n in notes_qs
                ]

                # Schedules
                schedules = ClassSchedule.objects.filter(batch=b).values(
                    "schedule_id",
                    "course_id",
                    "course__course_name",
                    "trainer_id",
                    "trainer__full_name",
                    "scheduled_date",
                    "start_time",
                    "end_time",
                )

                unified_batches.append({
                    "id": b.batch_id,
                    "title": b.title,
                    "course": assignments.first().course.course_id if assignments.exists() else None,
                    "category": assignments.first().course.course_category.category_id if assignments.exists() and assignments.first().course.course_category else None,
                    "course_name": assignments.first().course.course_name if assignments.exists() else None,
                    "trainer": assignments.first().trainer.trainer_id if assignments.exists() else None,
                    "trainer_name": assignments.first().trainer.full_name if assignments.exists() else None,
                    "start_date": getattr(b, "start_date", None),
                    "end_date": getattr(b, "end_date", None),
                    "start_time": getattr(b, "start_time", None),
                    "end_time": getattr(b, "end_time", None),
                    "slots": getattr(b, "slots", None),
                    "created_at": b.created_at,
                    "created_by": b.created_by,
                    "created_by_type": b.created_by_type,
                    "is_archived": b.is_archived,
                    "available_slots": getattr(b, "available_slots", None),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "schedules": list(schedules),
                    "source": "old"
                })

            # ---------------- NEW BATCHES ----------------
            new_batches = NewBatch.objects.filter(
                students__student_id=student_id,
                is_archived=False
            ).order_by("-created_at")

            for nb in new_batches:
                students_data = [
                    {
                        "student_id": s.student_id,
                        "registration_id": s.registration_id,
                        "full_name": f"{s.first_name} {s.last_name}".strip()
                    } for s in nb.students.all()
                ]

                # Notes
                note_ct = ContentType.objects.get_for_model(NewBatch)
                notes_qs = Note.objects.filter(object_id=nb.pk, content_type=note_ct).order_by("-created_at")

                def convert_status(value):
                    if isinstance(value, str):
                        if value.lower() == "true":
                            return True
                        if value.lower() == "false":
                            return False
                    return value

                notes_data = [
                    {
                        "note_id": n.id,
                        "reason": n.reason,
                        "created_by": n.created_by,
                        "created_by_type": getattr(n, "created_by_type", None),
                        "status": convert_status(getattr(n, "status", None)),
                        "created_at": n.created_at.strftime("%Y-%m-%d %H:%M"),
                    }
                    for n in notes_qs
                ]

                # Schedules
                schedules = ClassSchedule.objects.filter(batch__batch_id=nb.batch_id).annotate(
                    course_name=F("course__course_name"),
                    trainer_name=F("trainer__full_name")
                ).values(
                    "schedule_id",
                    "course_id",
                    "course__course_name",
                    "trainer_id",
                    "trainer__full_name",
                    "scheduled_date",
                    "start_time",
                    "end_time",
                )

                unified_batches.append({
                    "id": nb.batch_id,
                    "title": nb.title,
                    "course": nb.course.course_id if nb.course else None,
                    "category": nb.course.course_category.category_id if nb.course and nb.course.course_category else None,
                    "course_name": nb.course.course_name if nb.course else None,
                    "trainer": nb.trainer.trainer_id if nb.trainer else None,
                    "trainer_name": nb.trainer.full_name if nb.trainer else None,
                    "start_date": nb.start_date,
                    "end_date": nb.end_date,
                    "start_time": nb.start_time,
                    "end_time": nb.end_time,
                    "slots": nb.slots,
                    "created_at": nb.created_at,
                    "created_by": nb.created_by,
                    "created_by_type": nb.created_by_type,
                    "is_archived": nb.is_archived,
                    "available_slots": nb.available_slots(),
                    "students": students_data or None,
                    "notes": notes_data or None,
                    "schedules": list(schedules),
                    "source": "new"
                })
            
            

            new_batches = NewBatch.objects.filter(
                students__student_id=student_id,
                is_archived=False
            ).order_by("-created_at")
            
            trainer_data = [
                {
                    "trainer_id": nb.trainer.trainer_id,
                    "employee_id": nb.trainer.employee_id if nb.trainer.employee_id else None,
                    "trainer_name": nb.trainer.full_name,
                }
                for nb in new_batches
                if nb.trainer
            ]

            student_id = str(student_id)
            # ------------------ ALL ACTIVE COURSES ------------------
            course_queryset = Course.objects.filter(is_archived=False, status__iexact='Active')

            # ------------------ STUDENT ASSIGNED COURSE IDS ------------------
            old_course_ids = BatchCourseTrainer.objects.filter(
                student__student_id=student_id
            ).values_list('course_id', flat=True)

            new_course_ids = NewBatch.objects.filter(
                students__student_id=student_id,
                is_archived=False
            ).values_list('course_id', flat=True)

            assigned_course_ids = set(list(old_course_ids) + list(new_course_ids))

            # ------------------ FILTER COURSES BASED ON STUDENT ------------------
            course_queryset = course_queryset.filter(course_id__in=assigned_course_ids)

            # ------------------ GET COURSE DATA ------------------
            course_data = course_queryset.annotate(
                category_id=F('course_category__category_id')).values('course_id', 'course_name', 'category_id')

            # ------------------ GET UNIQUE CATEGORIES ------------------
            category_ids = course_queryset.values_list('course_category__category_id', flat=True).distinct()
            categories = CourseCategory.objects.filter(category_id__in=category_ids).values(
                'category_id', 'category_name'
            )

            return Response({
                "success": True,
                "message": f"All batches for student {student_id} retrieved successfully.",
                "batches": unified_batches,
                "trainer": trainer_data,
                'active_courses': list(course_data),
                'categories': list(categories),
            })

        except Exception as e:
            return Response({"success": False, "message": str(e)})

    def create(self, request, *args, **kwargs):
        try:
            data = request.data.copy()

            # ----------------- Validate slots -----------------
            slots = int(data.get("slots", 0))
            if slots <= 0:
                return Response(
                    {"success": False, "message": "Slots must be greater than 0"},
                    status=200
                )

            # ----------------- Validate students -----------------
            student_ids = data.get("students", [])

            if student_ids:
                if not isinstance(student_ids, list):
                    return Response(
                        {"success": False, "message": "Students must be a list"},
                        status=200
                    )

                if len(student_ids) > slots:
                    return Response(
                        {
                            "success": False,
                            "message": f"Only {slots} slots available but {len(student_ids)} students given"
                        },
                        status=200
                    )

                valid_students = Student.objects.filter(
                    pk__in=student_ids, is_archived=False
                )

                if valid_students.count() != len(student_ids):
                    return Response(
                        {
                            "success": False,
                            "message": "Some students are invalid or archived"
                        },
                        status=200
                    )

            # ----------------- Validate Course -----------------
            course_id = data.get("course")
            if course_id:
                if not Course.objects.filter(pk=course_id).exists():
                    return Response(
                        {"success": False, "message": "Invalid course"},
                        status=200
                    )

            # ----------------- Validate Trainer -----------------
            trainer_id = data.get("trainer")
            if trainer_id:
                if not Trainer.objects.filter(pk=trainer_id).exists():
                    return Response(
                        {"success": False, "message": "Invalid trainer"},
                        status=200
                    )

            # ----------------- Create Batch -----------------
            serializer = NewBatchSerializer(data=data, context={'request': request})
            serializer.is_valid(raise_exception=True)

            batch = serializer.save()

            return Response(
                {
                    "success": True,
                    "message": "Batch created successfully",
                    "data": NewBatchSerializer(batch, context={"request": request}).data
                },
                status=200
            )

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    def update(self, request, batch_id=None):
        try:
            batch = NewBatch.objects.filter(batch_id=batch_id, is_archived=False).first()
            if not batch:
                return Response({"success": False, "message": "Batch not found"}, status=200)

            data = request.data

            # ---------- Update Course ----------
            course_id = data.get("course")
            if course_id:
                course = Course.objects.filter(pk=course_id).first()
                if not course:
                    return Response({"success": False, "message": "Invalid course"}, status=200)
                batch.course = course

            # ---------- Update Trainer ----------
            trainer_id = data.get("trainer")
            if trainer_id:
                trainer = Trainer.objects.filter(pk=trainer_id).first()
                if not trainer:
                    return Response({"success": False, "message": "Invalid trainer"}, status=200)
                batch.trainer = trainer

            # ---------- Update normal fields ----------
            for key, value in data.items():
                if key in ["course", "trainer", "students"]:
                    continue
                if hasattr(batch, key):
                    setattr(batch, key, value)

            # ---------- Update Students (M2M) ----------
            student_ids = data.get("students")

            # If students key is missing → keep existing students
            if student_ids is None:
                student_ids = list(batch.students.values_list("pk", flat=True))

            # Ensure list type
            if not isinstance(student_ids, list):
                return Response({"success": False, "message": "Students must be a list"}, status=200)

            # Validate slots
            slots = int(data.get("slots", batch.slots))
            if slots <= 0:
                return Response({"success": False, "message": "Slots must be greater than 0"}, status=200)

            if len(student_ids) > slots:
                return Response({
                    "success": False,
                    "message": f"Only {slots} slots available but {len(student_ids)} given"
                }, status=200)

            # Validate students exist
            valid_students = Student.objects.filter(pk__in=student_ids, is_archived=False)
            if len(valid_students) != len(student_ids):
                return Response({
                    "success": False,
                    "message": "Some students are invalid or archived"
                }, status=200)

            # Apply M2M update
            batch.students.set(valid_students)

            batch.save()

            serializer = NewBatchSerializer(batch, context={"request": request})

            return Response({
                "success": True,
                "message": "Batch updated successfully",
                "data": serializer.data
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    def is_archived(self, request, batch_id=None, *args, **kwargs):
        try:
            pk = int(batch_id)
            batch = NewBatch.objects.filter(batch_id=pk, is_archived=False).first()
            batch_type = "new" if batch else "old"

            if not batch:
                from .models import Batch  # old batch model
                batch = Batch.objects.filter(batch_id=pk, is_archived=False).first()
                if not batch:
                    return Response({
                        "success": False,
                        "message": "Batch not found"
                    }, status=status.HTTP_200_OK)
                batch_type = "old"

            batch.is_archived = True
            batch.save()

            return Response({
                "success": True,
                "message": f"{'New' if batch_type=='new' else 'Old'} batch archived successfully",
            }, status=status.HTTP_200_OK)

        except ValueError:
            return Response({
                "success": False,
                "message": "Invalid batch ID"
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

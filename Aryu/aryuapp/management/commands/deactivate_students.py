import datetime
from django.core.management.base import BaseCommand
from django.utils.timezone import now
from datetime import timedelta
from django.db.models import Q, Count,F
from aryuapp.models import Student, NewBatch, Course, Settings

class Command(BaseCommand):
    help = "Automatically deactivate students based on settings.deactivation_options"

    def handle(self, *args, **kwargs):
        settings = Settings.objects.first()
        if not settings:
            self.stdout.write("No settings found. Skipping deactivation.")
            return

        options = settings.deactivation_options or []
        today = now().date()
        deactivated_count = 0

        if "after_batch_completion" in options:
            today = datetime.datetime.today().date()

            # All ended batches
            ended_batches = NewBatch.objects.filter(
                end_date__lt=today,
                is_archived=False
            ).values_list('batch_id', flat=True)

            ended_batches_set = set(ended_batches)

            # All active students enrolled in at least one batch
            students_in_batches = Student.objects.filter(
                new_batches__isnull=False,
                status=True,
                is_archived=False
            ).distinct()

            students_to_deactivate = []

            # Check every student
            for student in students_in_batches:
                # Get all batch IDs student is enrolled in
                student_batches = student.new_batches.filter(
                    is_archived=False
                ).values_list('batch_id', flat=True)

                student_batch_set = set(student_batches)

                # If ALL batches for student are ended → Deactivate
                if student_batch_set and student_batch_set.issubset(ended_batches_set):
                    students_to_deactivate.append(student.student_id)

            # Bulk update
            if students_to_deactivate:
                deactivated_count = Student.objects.filter(
                    student_id__in=students_to_deactivate
                ).update(status=False)

            else:
                deactivated_count = 0

        elif "after_course_completion" in options:
            today = datetime.datetime.today().date()

            # Find courses where ALL NEW batches have ended
            ended_courses = Course.objects.filter(
                new_batches__is_archived=False
            ).annotate(
                total_batches=Count('new_batches'),
                ended_batches=Count('new_batches', filter=Q(new_batches__end_date__lt=today))
            ).filter(
                total_batches=F('ended_batches')  # All batches ended
            ).values_list('course_id', flat=True)

            ended_course_ids = set(ended_courses)

            # Students enrolled in any new batch course
            students_in_courses = Student.objects.filter(
                new_batches__course__isnull=False,
                status=True,
                is_archived=False
            ).distinct()

            students_to_deactivate = []

            # Check student course completion
            for student in students_in_courses:
                # All courses student belongs to
                student_courses = student.new_batches.filter(
                    is_archived=False
                ).values_list('course_id', flat=True)

                student_course_set = set(student_courses)

                # If ALL courses for this student are completed → deactivate
                if student_course_set and student_course_set.issubset(ended_course_ids):
                    students_to_deactivate.append(student.student_id)

            # Bulk update
            if students_to_deactivate:
                deactivated_count = Student.objects.filter(
                    student_id__in=students_to_deactivate
                ).update(status=False)
            else:
                deactivated_count = 0

        elif "1_year_deactivation" in options:
            one_year_ago = today - timedelta(days=365)

            # Get all active, non-archived students whose joining date is more than 1 year ago
            students_to_deactivate = Student.objects.filter(
                joining_date__lte=one_year_ago,
                status=True,
                is_archived=False
            )

            # Bulk update
            if students_to_deactivate.exists():
                deactivated_count = students_to_deactivate.update(status=False)

        elif "no_deactivation" in options:
            self.stdout.write("No deactivation option selected. Skipping.")

        else:
            self.stdout.write("Unknown deactivation option. Skipping.")

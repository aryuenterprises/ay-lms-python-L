import sys
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from aryuapp.models import Student, StudentCourse, Attendance
from payments.models import PaymentTransaction


class Command(BaseCommand):
    help = "Identify and safely purge or archive dummy/test student records from the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            default=False,
            help="Execute the purge operation. If not specified, runs in dry-run mode.",
        )
        parser.add_argument(
            "--soft-delete",
            action="store_true",
            default=False,
            help="Soft delete by setting is_archived=True and status=False instead of hard deletion.",
        )
        parser.add_argument(
            "--hard-delete",
            action="store_true",
            default=False,
            help="Permanently delete matching records and their cascades.",
        )

    def handle(self, *args, **options):
        commit = options["commit"]
        soft_delete = options["soft_delete"]
        hard_delete = options["hard_delete"]

        # Default action if commit is specified without soft/hard flag is soft-delete
        if commit and not (soft_delete or hard_delete):
            soft_delete = True

        self.stdout.write(self.style.MIGRATE_HEADING("=== Test Student Record Identification & Cleanup ==="))

        # Build Q filter for test signatures
        specific_ids = [431]
        specific_reg_ids = ["AYA0826050"]
        specific_emails = [
            "pycloud1003@gmail.com",
            "wocekicyby@gmail.com",
        ]

        test_email_keywords = [
            "test",
            "dummy",
            "example.com",
            "fake",
            "pycloud",
            "sample",
            "aryutechnologies.com",
        ]

        test_name_keywords = [
            "test",
            "dummy",
            "sample",
            "breanna",
            "a vero elit",
        ]

        q_filter = Q(student_id__in=specific_ids) | Q(registration_id__in=specific_reg_ids) | Q(email__in=specific_emails)

        for kw in test_email_keywords:
            q_filter |= Q(email__icontains=kw)

        for kw in test_name_keywords:
            q_filter |= Q(first_name__icontains=kw) | Q(last_name__icontains=kw)

        # Invalid DOB filters (e.g., DOB in the far future or far past)
        q_filter |= Q(dob__year__gt=2100) | Q(dob__year__lt=1900)

        test_students_qs = Student.objects.filter(q_filter).distinct()
        total_found = test_students_qs.count()

        self.stdout.write(f"\nFound {self.style.WARNING(str(total_found))} matching test/placeholder student record(s).\n")

        if total_found == 0:
            self.stdout.write(self.style.SUCCESS("No test student records found. Database is clean."))
            return

        # Print detailed list
        self.stdout.write(f"{'ID':<8} | {'Reg ID':<14} | {'Name':<25} | {'Email':<35} | {'Created At'}")
        self.stdout.write("-" * 95)

        student_ids = []
        for s in test_students_qs:
            student_ids.append(s.student_id)
            name = f"{s.first_name or ''} {s.last_name or ''}".strip()
            created = s.created_at.strftime('%Y-%m-%d') if s.created_at else "-"
            self.stdout.write(f"{s.student_id:<8} | {s.registration_id or '-':<14} | {name:<25} | {s.email or '-':<35} | {created}")

        self.stdout.write("-" * 95)

        if not commit:
            self.stdout.write(
                self.style.WARNING(
                    "\n[DRY-RUN MODE] No database changes were made.\n"
                    "To execute cleanup, run:\n"
                    "  python manage.py purge_test_students --commit --soft-delete\n"
                    "  OR\n"
                    "  python manage.py purge_test_students --commit --hard-delete\n"
                )
            )
            return

        # Execute in atomic transaction
        with transaction.atomic():
            if hard_delete:
                # Count related cascades for reporting
                related_sc = StudentCourse.objects.filter(student_id__in=student_ids).count()
                related_att = Attendance.objects.filter(student_id__in=student_ids).count()
                related_payments = PaymentTransaction.objects.filter(student_id__in=student_ids).count()

                deleted_count, _ = test_students_qs.delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n[HARD DELETE COMMITTED] Successfully deleted {total_found} test student record(s) "
                        f"and cascaded relations (StudentCourses: {related_sc}, Attendance: {related_att}, Payments: {related_payments})."
                    )
                )
            else:
                updated_count = test_students_qs.update(is_archived=True, status=False)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n[SOFT DELETE COMMITTED] Successfully archived {updated_count} test student record(s) "
                        f"(set is_archived=True and status=False)."
                    )
                )

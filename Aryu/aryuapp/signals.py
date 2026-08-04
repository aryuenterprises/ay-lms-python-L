# /home/aryu_user/Arun/academystaging-python/Aryu/aryuapp/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Student, Submission, Trainer, SubAdmin, SubmissionReply, User, StudentTicket, TicketReply
from chats.models import Notification
from chats.serializers import NotificationSerializer
from tests.models import StudentAnswers, TestResult
from .utils import send_welcome_email
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from courses.models import StudentTopicStatus
from batches.models import NewBatch, ClassSchedule


@receiver(post_save, sender=Notification)
def push_realtime_notification(sender, instance, created, **kwargs):
    if not created:
        return

    channel_layer = get_channel_layer()
    serializer = NotificationSerializer(instance).data

    groups = []

    if instance.student:
        groups.append(f"notifications_student_{instance.student.registration_id}")

    if instance.trainer:
        # trainer can be a regular trainer OR an admin (user_type="admin")
        if getattr(instance.trainer, "user_type", None) == "admin":
            groups.append(f"notifications_admin_{instance.trainer.employee_id}")
        else:
            groups.append(f"notifications_tutor_{instance.trainer.employee_id}")

    if instance.sub_admin:
        groups.append(f"notifications_employer_{instance.sub_admin.employer_id}")

    # FIXED — was missing entirely before
    if instance.super_admin:
        groups.append(f"notifications_super_admin_{instance.super_admin.id}")

    for group_name in groups:
        try:
            async_to_sync(channel_layer.group_send)(
                group_name,
                {"type": "notify", "notification": serializer}
            )
        except Exception:
            pass  # Never crash a DB save because of a WebSocket push failure


# @receiver(post_save, sender=Student)
# def send_student_welcome(sender, instance, created, **kwargs):
#     if created:
#         send_welcome_email(instance)

@receiver(post_save, sender=StudentAnswers)
def notify_trainer_on_test_submission(sender, instance, created, **kwargs):
    if not created or not instance.student_id or not instance.test_id:
        return

    student = instance.student_id
    test = instance.test_id
    course = test.course

    # ----------------------------------
    # 1. Get batches (NEW LOGIC)
    # ----------------------------------
    batches = NewBatch.objects.filter(
        students=student,
        course=course,
        is_archived=False,
        status=True
    ).select_related("trainer")

    if not batches.exists():
        return

    # ----------------------------------
    # 2. Notify trainer (avoid duplicates)
    # ----------------------------------
    notified_trainers = set()

    for batch in batches:
        trainer = batch.trainer

        if trainer and trainer.id not in notified_trainers:
            notified_trainers.add(trainer.id)

            Notification.objects.create(
                trainer=trainer,
                student=student,
                test=test,
                course=course,
                message=(
                    f"test_submission: Student {student.first_name} {student.last_name} "
                    f"submitted answers for Test '{test.test_name}' in Course '{course.course_name}'."
                ),
            )

    # ----------------------------------
    # 3. SAFE COMPANY LOOKUP
    # ----------------------------------
    company_ids = {
        getattr(student.employee, "company_id", None) if hasattr(student, "employee") else None,
        getattr(student.school_student, "company_id", None) if hasattr(student, "school_student") else None,
        getattr(student.college_student, "company_id", None) if hasattr(student, "college_student") else None,
        getattr(student.jobseeker, "company_id", None) if hasattr(student, "jobseeker") else None,
    }
    company_ids.discard(None)

    # ----------------------------------
    # 4. Notify sub-admins
    # ----------------------------------
    for company_id in company_ids:
        sub_admins = SubAdmin.objects.filter(
            company_id=company_id,
            status=True,
            is_archived=False
        ).only("id")

        for sub_admin in sub_admins:
            Notification.objects.create(
                student=student,
                test=test,
                course=course,
                sub_admin=sub_admin,
                message=(
                    f"test_submission: Student {student.first_name} {student.last_name} "
                    f"submitted answers for Test '{test.test_name}'."
                ),
            )

@receiver(post_save, sender=SubmissionReply)
def notify_student_on_reply(sender, instance, created, **kwargs):
    if not created:
        return

    submission = instance.submission
    if not submission or not submission.student or not submission.assignment:
        return


    student = submission.student
    assignment = submission.assignment
    course = assignment.course
    trainer = instance.trainer

    # Notify student directly
    Notification.objects.create(
        student=student,
        trainer=trainer,
        assignment=assignment,
        course=course,
        message=(
            f"submission_reply: Trainer {trainer.full_name if trainer else 'Unknown'} "
            f"reviewed your submission for '{assignment.title}' in course '{course.course_name}'."
        )
    )

    # Find active batches linking this student + course
    assigned_batches = NewBatch.objects.filter(
        students=student,
        course=course,
        is_archived=False
    ).only("batch_id")

    # Collect sub-admin notifications for related companies
    company_ids = set()

    if hasattr(student, 'employee') and student.employee.company_id:
        company_ids.add(student.employee.company_id)
    if hasattr(student, 'school_student') and student.school_student.company_id:
        company_ids.add(student.school_student.company_id)
    if hasattr(student, 'college_student') and student.college_student.company_id:
        company_ids.add(student.college_student.company_id)
    if hasattr(student, 'jobseeker') and student.jobseeker.company_id:
        company_ids.add(student.jobseeker.company_id)

    # Notify sub-admins of each related company
    for company_id in company_ids:
        sub_admins = SubAdmin.objects.filter(
            company_id=company_id,
            status=True,
            is_archived=False
        )
        for sub_admin in sub_admins:
            Notification.objects.create(
                student=student,
                sub_admin=sub_admin,
                trainer=trainer,
                assignment=assignment,
                course=course,
                message=(
                    f"submission_reply: Trainer {trainer.full_name if trainer else 'Unknown'} "
                    f"reviewed student {student.first_name} {student.last_name}'s submission "
                    f"for '{assignment.title}' (Course: {course.course_name})."
                )
            )


@receiver(post_save, sender=ClassSchedule)
def notify_student_on_class_schedule(sender, instance, created, **kwargs):
    if not created:
        return

    new_batch = instance.new_batch  # Only use new_batch
    course = instance.course
    trainer = instance.trainer

    if not (new_batch and course and trainer):
        return

    # Notify all students in the new batch
    for student in new_batch.students.all():
        # Notify student
        Notification.objects.create(
            student=student,
            trainer=trainer,
            message=(
                f"Class: Your new class for course '{course.course_name}' "
                f"is scheduled on {instance.scheduled_date.strftime('%d-%m-%Y')}."
            )
        )

        # Notify sub-admins of student's company/school/college/job
        companies = []
        if hasattr(student, 'employee') and student.employee.company_id:
            companies.append(student.employee.company_id)
        if hasattr(student, 'school_student') and student.school_student.company_id:
            companies.append(student.school_student.company_id)
        if hasattr(student, 'college_student') and student.college_student.company_id:
            companies.append(student.college_student.company_id)
        if hasattr(student, "jobseeker") and student.jobseeker and student.jobseeker.company_id:
            companies.append(student.jobseeker.company_id)

        for company in companies:
            sub_admins = company.sub_admins.all()
            for sub_admin in sub_admins:
                Notification.objects.create(
                    student=student,
                    sub_admin=sub_admin,
                    message=(
                        f"Class: A new class is scheduled for your student "
                        f"{student.first_name} {student.last_name} in course '{course.course_name}' "
                        f"on {instance.scheduled_date.strftime('%d-%m-%Y')}."
                    )
                )

        # Notify trainer
        Notification.objects.create(
            trainer=trainer,
            student=student,
            message=(
                f"Class: You have been scheduled to conduct a class for course "
                f"'{course.course_name}' on {instance.scheduled_date.strftime('%d-%m-%Y')}."
            )
        )


# @receiver(post_save, sender=ClassSchedule)
# def generate_meet_link(sender, instance, created, **kwargs):
#     if instance.is_online_class and not instance.meeting_link:
#         start_dt = datetime.datetime.combine(instance.scheduled_date, instance.start_time)
#         end_dt = datetime.datetime.combine(instance.scheduled_date, instance.end_time)

#         meet_link = create_meet_event(
#             summary=f"Class for {instance.course.course_name}",
#             start_datetime=start_dt,
#             end_datetime=end_dt,
#             attendees=[]  # trainer/student emails here
#         )
#         instance.meeting_link = meet_link
#         instance.save(update_fields=['meeting_link'])

@receiver(post_save, sender=StudentTopicStatus)
def notify_on_topic_status(sender, instance, created, **kwargs):
    student = instance.student
    topic = instance.topic
    course = topic.course

    # ----------------------------------
    # 1. Get assigned batches (NEW LOGIC)
    # ----------------------------------
    assigned_batches = NewBatch.objects.filter(
        students=student,
        course=course,
        is_archived=False,
        status=True
    ).select_related("trainer")

    if not assigned_batches.exists():
        return

    # ----------------------------------
    # 2. Notify trainers (avoid duplicates)
    # ----------------------------------
    notified_trainers = set()

    for batch in assigned_batches:
        trainer = batch.trainer

        if trainer and trainer.trainer_id not in notified_trainers:
            notified_trainers.add(trainer.trainer_id)

            Notification.objects.create(
                trainer=trainer,
                student=student,
                course=course,
                is_read=False,
                message=(
                    f"Student {student.first_name} {student.last_name} updated topic '{topic.title}' "
                    f"in course '{course.course_name}'."
                )
            )

    # ----------------------------------
    # 3. Collect company IDs (optimized)
    # ----------------------------------
    company_ids = {
        getattr(student.employee, "company_id", None) if hasattr(student, "employee") else None,
        getattr(student.school_student, "company_id", None) if hasattr(student, "school_student") else None,
        getattr(student.college_student, "company_id", None) if hasattr(student, "college_student") else None,
        getattr(student.jobseeker, "company_id", None) if hasattr(student, "jobseeker") else None,
    }
    company_ids.discard(None)

    # ----------------------------------
    # 4. Notify sub-admins
    # ----------------------------------
    for company_id in company_ids:
        sub_admins = SubAdmin.objects.filter(
            company_id=company_id,
            status=True,
            is_archived=False
        ).only("id")

        for sub_admin in sub_admins:
            Notification.objects.create(
                student=student,
                sub_admin=sub_admin,
                course=course,
                message=(
                    f"Student {student.first_name} {student.last_name} updated topic '{topic.title}' "
                    f"in course '{course.course_name}'."
                )
            )

@receiver(post_save, sender=StudentAnswers)
def notify_trainer_on_test_submission(sender, instance, created, **kwargs):
    if not created or not instance.student_id or not instance.test_id:
        return

    student = instance.student_id
    test = instance.test_id
    course = test.course

    # ----------------------------------
    # 1. Get batches (NEW LOGIC)
    # ----------------------------------
    batches = NewBatch.objects.filter(
        students=student,
        course=course,
        is_archived=False,
        status=True
    ).select_related("trainer")

    if not batches.exists():
        return

    # ----------------------------------
    # 2. Notify trainer (avoid duplicates)
    # ----------------------------------
    notified_trainers = set()

    for batch in batches:
        trainer = batch.trainer

        if trainer and trainer.id not in notified_trainers:
            notified_trainers.add(trainer.id)

            Notification.objects.create(
                trainer=trainer,
                student=student,
                test=test,
                course=course,
                message=(
                    f"test_submission: Student {student.first_name} {student.last_name} "
                    f"submitted answers for Test '{test.test_name}' in Course '{course.course_name}'."
                ),
            )

    # ----------------------------------
    # 3. SAFE COMPANY LOOKUP
    # ----------------------------------
    company_ids = {
        getattr(student.employee, "company_id", None) if hasattr(student, "employee") else None,
        getattr(student.school_student, "company_id", None) if hasattr(student, "school_student") else None,
        getattr(student.college_student, "company_id", None) if hasattr(student, "college_student") else None,
        getattr(student.jobseeker, "company_id", None) if hasattr(student, "jobseeker") else None,
    }
    company_ids.discard(None)

    # ----------------------------------
    # 4. Notify sub-admins
    # ----------------------------------
    for company_id in company_ids:
        sub_admins = SubAdmin.objects.filter(
            company_id=company_id,
            status=True,
            is_archived=False
        ).only("id")

        for sub_admin in sub_admins:
            Notification.objects.create(
                student=student,
                test=test,
                course=course,
                sub_admin=sub_admin,
                message=(
                    f"test_submission: Student {student.first_name} {student.last_name} "
                    f"submitted answers for Test '{test.test_name}'."
                ),
            )


@receiver(post_save, sender=TestResult)
def notify_student_on_test_result(sender, instance, created, **kwargs):
    if not created or not instance.student_id or not instance.test_id:
        return

    student = instance.student_id
    test = instance.test_id
    course = test.course

    # ----------------------------------
    # 1. Get trainer from NewBatch
    # ----------------------------------
    batches = NewBatch.objects.filter(
        students=student,
        course=course,
        is_archived=False,
        status=True
    ).select_related("trainer")

    trainer = None
    if batches.exists():
        # take first trainer (or modify if multiple needed)
        trainer = batches.first().trainer

    # ----------------------------------
    # 2. Notify student
    # ----------------------------------
    Notification.objects.create(
        student=student,
        trainer=trainer,
        test=test,
        course=course,
        message=(
            f"test_result: Trainer {trainer.full_name if trainer else 'System'} "
            f"published your result for Test '{test.test_name}'. "
            f"Your score: {instance.score}/{test.total_marks}."
        ),
    )

    # ----------------------------------
    # 3. SAFE COMPANY LOOKUP
    # ----------------------------------
    company_ids = {
        getattr(student.employee, "company_id", None) if hasattr(student, "employee") else None,
        getattr(student.school_student, "company_id", None) if hasattr(student, "school_student") else None,
        getattr(student.college_student, "company_id", None) if hasattr(student, "college_student") else None,
        getattr(student.jobseeker, "company_id", None) if hasattr(student, "jobseeker") else None,
    }
    company_ids.discard(None)

    # ----------------------------------
    # 4. Notify sub-admins
    # ----------------------------------
    for company_id in company_ids:
        sub_admins = SubAdmin.objects.filter(
            company_id=company_id,
            status=True,
            is_archived=False
        ).only("id")

        for sub_admin in sub_admins:
            Notification.objects.create(
                student=student,
                test=test,
                course=course,
                sub_admin=sub_admin,
                message=(
                    f"test_result: Student {student.first_name} {student.last_name} "
                    f"result published for Test '{test.test_name}'."
                ),
            )


def get_student_admin_and_superadmin(student: Student):
    if not student:
        return None, None

    admin = None
    super_admin = None

    if student.created_by_type == "admin":
        admin = Trainer.objects.filter(
            trainer_id=student.created_by,
            user_type="admin"
        ).first()

        if admin and admin.created_by_type == "super_admin":
            super_admin = User.objects.filter(
                id=admin.created_by,
                user_type="super_admin"
            ).first()

    elif student.created_by_type == "super_admin":
        super_admin = User.objects.filter(
            id=student.created_by,
            user_type="super_admin"
        ).first()

    return admin, super_admin


# ---------- 1. New Ticket → notify admin + super_admin ----------

@receiver(post_save, sender=StudentTicket)
def create_ticket_notifications(sender, instance, created, **kwargs):
    if not created:
        return

    ticket = instance

    # CASE 1: LMS Student Ticket
    if ticket.student:
        admin, super_admin = get_student_admin_and_superadmin(ticket.student)

        if super_admin:
            Notification.objects.create(
                super_admin=super_admin,
                message=f"ticket:new: Ticket created by {ticket.student.first_name}",
            )

        if admin:
            Notification.objects.create(
                trainer=admin,
                message=f"ticket:new: Ticket created by {ticket.student.first_name}",
            )

    # CASE 2: Webinar Ticket (no hierarchy)
    elif ticket.webinar_participant:

        # Option A (Recommended):
        # Notify ALL super admins

        super_admins = User.objects.filter(user_type="super_admin")

        for sa in super_admins:
            Notification.objects.create(
                super_admin=sa,
                message=f"webinar_ticket:new: Ticket from {ticket.webinar_participant.name}",
            )

        # Option B (If webinar has assigned admin)
        # If your Webinar model has created_by / owner
        # you can notify that person instead


# ---------- 2. Reply → notify the correct side ----------

@receiver(post_save, sender=TicketReply)
def create_ticket_reply_notifications(sender, instance, created, **kwargs):
    if not created:
        return

    reply = instance
    ticket = reply.ticket

    # =========================
    # CASE 1: LMS STUDENT TICKET
    # =========================
    if ticket.student:

        student = ticket.student
        admin, super_admin = get_student_admin_and_superadmin(student)

        # STUDENT replied → notify admin + super_admin
        if reply.student:
            if admin:
                Notification.objects.create(
                    trainer=admin,
                    message=f"ticket:reply: Student replied on Ticket #{ticket.ticket_id}"
                )

            if super_admin:
                Notification.objects.create(
                    super_admin=super_admin,
                    message=f"ticket:reply: Student replied on Ticket #{ticket.ticket_id}"
                )

        # ADMIN replied → notify student
        elif reply.trainer:
            Notification.objects.create(
                student=student,
                message=f"ticket:reply: Admin replied on your Ticket #{ticket.ticket_id}"
            )

        # SUPER ADMIN replied → notify student
        elif reply.super_admin:
            Notification.objects.create(
                student=student,
                message=f"ticket:reply: Super Admin replied on your Ticket #{ticket.ticket_id}"
            )

    # =========================
    # CASE 2: WEBINAR TICKET
    # =========================
    elif ticket.webinar_participant:

        participant = ticket.webinar_participant

        # Webinar student replied → notify all super admins
        if reply.student is None and reply.trainer is None and reply.super_admin is None:
            # (In webinar flow, reply won't have student/trainer FK usually)
            super_admins = User.objects.filter(user_type="super_admin")

            for sa in super_admins:
                Notification.objects.create(
                    super_admin=sa,
                    message=f"webinar_ticket:reply: Reply on Ticket #{ticket.ticket_id}"
                )

        # Admin replied → notify webinar participant (if you support it)
        elif reply.super_admin or reply.trainer:
            # If you have notification system for webinar participants,
            # you can create a custom logic here.
            pass



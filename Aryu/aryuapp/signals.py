from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import *
from .serializer import NotificationSerializer, MessageSerializer
from django.core.files.storage import default_storage
import pyclamd
from .utils import send_welcome_email
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer







@receiver(post_save, sender=Message)
def send_new_chat_message(sender, instance, created, **kwargs):
    if not created:
        return

    channel_layer = get_channel_layer()
    serializer = MessageSerializer(instance).data

    room_group_name = f"chat_{instance.room.id}"

    async_to_sync(channel_layer.group_send)(
        room_group_name,
        {
            "type": "chat_message",
            "message": serializer,
        }
    )

@receiver(post_save, sender=Notification)
def push_realtime_notification(sender, instance, created, **kwargs):
    if not created:
        return

    channel_layer = get_channel_layer()
    serializer = NotificationSerializer(instance).data

    # Identify recipient group
    if instance.student:
        group_name = f"notifications_student_{instance.student.registration_id}"
    elif instance.trainer:
        group_name = f"notifications_tutor_{instance.trainer.employee_id}"
    elif instance.sub_admin:
        group_name = f"notifications_employer_{instance.sub_admin.employer_id}"
    else:
        return

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "notify",
            "notification": serializer,
        }
    )


@receiver(post_save, sender=Student)
def send_student_welcome(sender, instance, created, **kwargs):
    if created:
        send_welcome_email(instance)

@receiver(post_save, sender=Submission)
def notify_trainer_on_submission(sender, instance, created, **kwargs):
    if created and instance.student and instance.assignment:
        student = instance.student
        assignment = instance.assignment

        # Get batches that include this student and are active
        assigned_batches = Batch.objects.filter(
            batchcoursetrainer__student=student,
            batchcoursetrainer__course=assignment.course,
            is_archived=False
        ).distinct()

        for batch in assigned_batches:
            batch_ct = batch.batchcoursetrainer.filter(
                student=student,
                course=assignment.course
            ).first()

            # Notify the trainer
            if batch_ct and batch_ct.trainer:
                Notification.objects.create(
                    trainer=batch_ct.trainer,
                    student=student,
                    message=f"submission: Student {student.first_name} {student.last_name} submitted assignment '{assignment.title}' in course '{assignment.course.course_name}'."
                )

            # Notify sub-admins of student's company (employee / school / college)
            companies = set()
            if hasattr(student, 'employee') and student.employee.company_id:
                companies.add(student.employee.company_id)
            if hasattr(student, 'school_student') and student.school_student.company_id:
                companies.add(student.school_student.company_id)
            if hasattr(student, 'college_student') and student.college_student.company_id:
                companies.add(student.college_student.company_id)
            if hasattr(student, 'jobseeker') and student.jobseeker.company_id:
                companies.add(student.jobseeker.company_id)

            for company in companies:
                sub_admins = company.sub_admins.filter(status=True, is_archived=False)
                for sub_admin in sub_admins:
                    Notification.objects.create(
                        student=student,
                        sub_admin=sub_admin,  # You need to add a sub_admin ForeignKey in Notification
                        message=f"submission: Student {student.first_name} {student.last_name} submitted assignment '{assignment.title}'."
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
    assigned_batches = Batch.objects.filter(
        batchcoursetrainer__student=student,
        batchcoursetrainer__course=course,
        is_archived=False
    ).distinct()

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

    # Find active batches where student belongs to this course
    assigned_batches = Batch.objects.filter(
        batchcoursetrainer__student=student,
        batchcoursetrainer__course=course,
        is_archived=False
    ).distinct()

    # Notify all trainers for these batches
    for batch in assigned_batches:
        batch_cts = batch.batchcoursetrainer.filter(student=student, course=course)
        for batch_ct in batch_cts:
            trainer = batch_ct.trainer
            if trainer and student:
                Notification.objects.create(
                    trainer=trainer,
                    student=student,
                    is_read=False,
                    message=(
                        f"Student {student.first_name} {student.last_name} updated their topic status '{topic.title}' "
                        f"in course '{course.course_name}' under batch '{batch.batch_name}'."
                    )
                )

    # Collect all Company objects associated with this student
    companies = []

    # Check each possible subtype
    if hasattr(student, "employee"):
        if student.employee.company_id:
            companies.append(student.employee.company_id)

    if hasattr(student, "school_student"):
        if student.school_student.company_id:
            companies.append(student.school_student.company_id)

    if hasattr(student, "college_student"):
        if student.college_student.company_id:
            companies.append(student.college_student.company_id)

    if hasattr(student, "jobseeker"):
        if student.jobseeker.company_id:
            companies.append(student.jobseeker.company_id)

    # Remove duplicates
    companies = list(set(companies))

    # Notify sub-admins for each company
    for company in companies:
        sub_admins = company.sub_admins.filter(status=True, is_archived=False)
        for sub_admin in sub_admins:
            Notification.objects.create(
                student=student,
                sub_admin=sub_admin,
                message=(
                    f"Student {student.first_name} {student.last_name} updated their topic status '{topic.title}' "
                    f"in course '{course.course_name}'."
                )
            )

@receiver(post_save, sender=StudentAnswers)
def notify_trainer_on_test_submission(sender, instance, created, **kwargs):
    if not created or not instance.student_id or not instance.test_id:
        return

    student = instance.student_id
    test = instance.test_id
    course = test.course_id

    # Trainer notification (unchanged)
    batch_ct = (
        BatchCourseTrainer.objects
        .filter(student=student, course=course, batch__is_archived=False)
        .select_related("trainer")
        .first()
    )

    if batch_ct and batch_ct.trainer:
        trainer = batch_ct.trainer
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

    # ---------------- SAFE COMPANY LOOKUP ----------------
    employee_obj = getattr(student, "employee", None)
    school_obj = getattr(student, "school_student", None)
    college_obj = getattr(student, "college_student", None)
    job_obj = getattr(student, "jobseeker", None)

    company_ids = set()

    for obj in [employee_obj, school_obj, college_obj, job_obj]:
        if obj and getattr(obj, "company_id", None):
            company_ids.add(obj.company_id)

    # Notify sub-admins
    for company in company_ids:
        for sub_admin in company.sub_admins.filter(status=True, is_archived=False):
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
    course = test.course_id

    # Trainer
    batch_ct = (
        BatchCourseTrainer.objects
        .filter(student=student, course=course, batch__is_archived=False)
        .select_related("trainer")
        .first()
    )
    trainer = batch_ct.trainer if batch_ct else None

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

    # ---------------- SAFE COMPANY LOOKUP ----------------
    employee_obj = getattr(student, "employee", None)
    school_obj = getattr(student, "school_student", None)
    college_obj = getattr(student, "college_student", None)
    job_obj = getattr(student, "jobseeker", None)

    company_ids = set()

    for obj in [employee_obj, school_obj, college_obj, job_obj]:
        if obj and getattr(obj, "company_id", None):
            company_ids.add(obj.company_id)

    # Notify sub-admins
    for company in company_ids:
        for sub_admin in company.sub_admins.filter(status=True, is_archived=False):
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

    admin = None
    super_admin = None

    # Case 1: Student created by ADMIN
    if student.created_by_type == "admin":
        admin = Trainer.objects.filter(trainer_id=student.created_by, user_type="admin").first()
        if admin and admin.created_by_type == "super_admin":
            super_admin = User.objects.filter(id=admin.created_by, user_type="super_admin").first()

    # Case 2: Student created directly by SUPER ADMIN
    elif student.created_by_type == "super_admin":
        super_admin = User.objects.filter(id=student.created_by, user_type="super_admin").first()

    return admin, super_admin


# ---------- 1. New Ticket → notify admin + super_admin ----------

@receiver(post_save, sender=StudentTicket)
def create_ticket_notifications(sender, instance, created, **kwargs):
    if not created:
        return

    ticket = instance
    student = ticket.student

    admin, super_admin = get_student_admin_and_superadmin(student)

    # Super admin notification
    if super_admin:
        Notification.objects.create(
            super_admin=super_admin,
            message=f"ticket:new: Ticket #{ticket.ticket_id} created by {student.first_name}",
        )

    # Admin notification
    if admin:
        Notification.objects.create(
            trainer=admin,
            message=f"ticket:new: Ticket #{ticket.ticket_id} created by {student.first_name}",
        )


# ---------- 2. Reply → notify the correct side ----------

@receiver(post_save, sender=TicketReply)
def create_ticket_reply_notifications(sender, instance, created, **kwargs):
    if not created:
        return

    reply = instance
    ticket = reply.ticket
    student = ticket.student

    admin, super_admin = get_student_admin_and_superadmin(student)

    # CASE A: Student replied → notify admin + super_admin
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

    # CASE B: Admin replied → notify student only
    elif reply.trainer:
        Notification.objects.create(
            student=student,
            message=f"ticket:reply:by Admin - Admin replied on your Ticket #{ticket.ticket_id}"
        )

    # CASE C: Super admin replied → notify student only
    elif reply.super_admin:
        Notification.objects.create(
            student=student,
            message=f"ticket:reply:by Admin - Super Admin replied on your Ticket #{ticket.ticket_id}"
        )

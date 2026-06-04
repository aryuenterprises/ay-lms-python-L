from celery import shared_task
from resume.models import ResumeRegistration

@shared_task
def resume_reg(registration_id):

    try:
        registration = ResumeRegistration.objects.get(
            id=registration_id
        )

        # send email here
        # generate PDF here
        # upload file here
        # whatsapp notification here

    except ResumeRegistration.DoesNotExist:
        pass
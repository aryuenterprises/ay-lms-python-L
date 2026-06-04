from celery import shared_task
from resume.views import ResumeRegistration
@shared_task
def resume_reg(registraion_id):
    print("registration_id",registraion_id)

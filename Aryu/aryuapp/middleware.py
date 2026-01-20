from django.utils.deprecation import MiddlewareMixin
from django.contrib.sessions.models import Session
from django.utils.timezone import now
from django.db import connection
from django.core.cache import cache
from django.utils.timezone import now, localtime
import datetime
from .models import *


class AutoLogoutMiddleware(MiddlewareMixin):
    def process_request(self, request):
        last_cleared = cache.get("last_auto_logout")
        current_time = now()

        # If cache is empty or 30 minutes passed since last clear
        if not last_cleared or (current_time - last_cleared) >= timedelta(minutes=30):
            Session.objects.all().delete()
            cache.set("last_auto_logout", current_time, timeout=1800)  # 30 minutes

        return None

def auto_logout_trainers():
    today = localtime().date()
    end_of_day = datetime.combine(today, datetime.time(23, 59, 59))

    active_trainers = (TrainerAttendance.objects
                       .filter(date__date=today, status__iexact='login')
                       .exclude(trainer__trainerattendance__status__iexact='logout'))

    for log in active_trainers:
        TrainerAttendance.objects.create(
            trainer=log.trainer,
            batch=log.batch,
            course=log.course,
            status="Logout",
            date=end_of_day
        )

class DBCleanupMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        try:
            connection.close()
        except:
            pass

        return response
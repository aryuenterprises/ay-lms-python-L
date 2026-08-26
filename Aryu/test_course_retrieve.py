import os
import sys
import django

# Setup django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Aryu.settings")
django.setup()

from django.conf import settings
if 'testserver' not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append('testserver')

from rest_framework.test import APIRequestFactory, force_authenticate
from django.contrib.auth import get_user_model
from courses.views import CourseViewSet

def main():
    with open("test_retrieve_output.txt", "w") as f:
        f.write("Starting retrieve test...\n")
        User = get_user_model()
        test_email = "tamilselvi12022004@gmail.com"
        user = User.objects.filter(email__iexact=test_email).first()
        if not user:
            msg = "Test user not found.\n"
            f.write(msg)
            sys.stderr.write(msg)
            return

        factory = APIRequestFactory()
        # Test retrieve for course 120
        request = factory.get('/courses/120')
        force_authenticate(request, user=user)

        view = CourseViewSet.as_view({'get': 'retrieve'})
        try:
            response = view(request, course_id=120)
            msg = f"Response status: {response.status_code}\nResponse data: {response.data}\n"
            f.write(msg)
            sys.stderr.write(msg)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            msg = f"EXCEPTION RAISED:\n{tb}\n"
            f.write(msg)
            sys.stderr.write(msg)

if __name__ == "__main__":
    main()

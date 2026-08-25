import os
import sys
import django

# Setup django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Aryu.settings")
django.setup()

from rest_framework.test import APIRequestFactory, force_authenticate
from django.contrib.auth import get_user_model
from courses.views import CourseViewSet

def main():
    with open("test_courses_output.txt", "w") as f:
        f.write("Starting test...\n")
        User = get_user_model()
        test_email = "tamilselvi12022004@gmail.com"
        user = User.objects.filter(email__iexact=test_email).first()
        if not user:
            msg = "Test user not found.\n"
            f.write(msg)
            sys.stderr.write(msg)
            return

        factory = APIRequestFactory()
        request = factory.get('/courses')
        force_authenticate(request, user=user)

        view = CourseViewSet.as_view({'get': 'list'})
        try:
            response = view(request)
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

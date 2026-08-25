import os
import sys
import django
import jwt

# Setup django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Aryu.settings")
django.setup()

from django.conf import settings
if 'testserver' not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append('testserver')

from rest_framework.test import APIRequestFactory
from aryuapp.views import StudentCourseViewSet

def main():
    payload = {
        "user_type": "student",
        "username": "tamilselvi12022004@gmail.com",
        "user_id": 446,
        "registration_id": "REG446",
        "student_id": 446,
        "first_name": "Tamilselvi"
    }
    
    # Generate token
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
    auth_header = f"Bearer {token}"

    factory = APIRequestFactory()
    
    with open("test_student_courses_output.txt", "w") as f:
        request = factory.get('/student_profile/446/courses', HTTP_AUTHORIZATION=auth_header)
        view = StudentCourseViewSet.as_view({'get': 'list_courses'})
        f.write("Testing list_courses view...\n")
        try:
            res = view(request, student_id=446)
            f.write(f"Response: {res.status_code}\n")
            f.write(f"Data: {res.data}\n")
        except Exception as e:
            import traceback
            f.write(f"Crashed:\n{traceback.format_exc()}\n")

if __name__ == "__main__":
    main()

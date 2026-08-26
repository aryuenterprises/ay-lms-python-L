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
from courses.views import CourseViewSet

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
    
    with open("test_jwt_user_output.txt", "w") as f:
        # Test List
        request = factory.get('/courses', HTTP_AUTHORIZATION=auth_header)
        view_list = CourseViewSet.as_view({'get': 'list'})
        f.write("Testing list view...\n")
        try:
            res_list = view_list(request)
            f.write(f"List response: {res_list.status_code}\n")
            f.write(f"List data: {res_list.data}\n\n")
        except Exception as e:
            import traceback
            f.write(f"List crashed:\n{traceback.format_exc()}\n\n")

        # Test Retrieve Course 120
        request_ret = factory.get('/courses/120', HTTP_AUTHORIZATION=auth_header)
        view_retrieve = CourseViewSet.as_view({'get': 'retrieve'})
        f.write("Testing retrieve view (120)...\n")
        try:
            res_retrieve = view_retrieve(request_ret, course_id=120)
            f.write(f"Retrieve response: {res_retrieve.status_code}\n")
            f.write(f"Retrieve data: {res_retrieve.data}\n\n")
        except Exception as e:
            import traceback
            f.write(f"Retrieve crashed:\n{traceback.format_exc()}\n\n")

if __name__ == "__main__":
    main()

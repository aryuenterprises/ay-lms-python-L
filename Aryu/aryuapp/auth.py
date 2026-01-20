# aryuapp -> auth.py
import jwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

SECRET_KEY = 'django-insecure-e-ar=#hq&(q0ujnwofc!%8#in(2z1osso65+(8i+&elo=cn4$k'

class CustomJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return None

        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Token expired')
        except jwt.InvalidTokenError:
            raise AuthenticationFailed('Invalid token')
        # create a simple user-like object
        class JWTUser:
            def __init__(self, payload):
                self.payload = payload
                self.user_type = payload.get("user_type")
                self.username = payload.get("username")
                self.user_id = payload.get("user_id")
                self.role_id = payload.get("role_id")
                self.role_name = payload.get("role_name")
                self.permissions = payload.get("permissions", [])
                self.is_authenticated = True

                # Attach IDs based on role
                if self.user_type == "student":
                    self.registration_id = payload.get("registration_id")
                    self.student_id = payload.get("student_id")
                    
                elif self.user_type == "tutor":
                    self.trainer_id = payload.get("trainer_id")
                    self.employee_id = payload.get("employee_id")
                elif self.user_type == "admin":
                    self.admin_id = payload.get("employee_id")
                    self.trainer_id = payload.get("trainer_id")
                elif self.user_type == "employer":
                    self.employer_id = payload.get("employer_id")
                elif self.user_type == "superadmin":
                    self.admin_id = payload.get("admin_id")
                    self.username = payload.get("username")
                    self.user_id = payload.get("user_id")

        user = JWTUser(payload)
        # store raw payload in request if you want
        request.user_data = payload

        return (user, None)


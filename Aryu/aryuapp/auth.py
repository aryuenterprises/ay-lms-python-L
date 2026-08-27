# aryuapp -> auth.py
import jwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings

SECRET_KEY = settings.SECRET_KEY

class CustomJWTAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return 'Bearer realm="api"'

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

        if payload.get("token_type") == "refresh":
            raise AuthenticationFailed('Cannot use refresh token as access token')
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

                # =================================================
                # REQUIRED FOR DRF
                # =================================================

                self.id = payload.get("user_id")

                self.pk = payload.get("user_id")

                # =================================================
                # ADMIN FLAGS
                # =================================================

                self.is_staff = (
                    self.user_type in ["admin", "super_admin"]
                )

                self.is_superuser = (
                    self.user_type == "super_admin"
                )

                # =================================================
                # USER TYPE DATA
                # =================================================

                if self.user_type == "student":

                    self.registration_id = payload.get(
                        "registration_id"
                    )

                    self.student_id = payload.get(
                        "student_id"
                    )

                    self.first_name = payload.get(
                        "first_name"
                    )

                elif self.user_type == "tutor":

                    self.trainer_id = payload.get(
                        "trainer_id"
                    )

                    self.employee_id = payload.get(
                        "employee_id"
                    )

                    self.full_name = payload.get(
                        "full_name"
                    )
                elif self.user_type == "resume_user":
                    self.first_name = payload.get(
                        "first_name"
                    )
                    self.last_name = payload.get(
                        "last_name"
                    )
                    self.email = payload.get(
                        "email"
                    )
                    self.id = payload.get(
                        "id"
                    )

                elif self.user_type == "admin":

                    self.admin_id = payload.get(
                        "employee_id"
                    )

                    self.trainer_id = payload.get(
                        "trainer_id"
                    )

                    self.full_name = payload.get(
                        "full_name"
                    )

                elif self.user_type == "employer":

                    self.employer_id = payload.get(
                        "employer_id"
                    )

                    self.company_name = payload.get(
                        "company_name"
                    )

                    self.full_name = payload.get(
                        "full_name"
                    )

                elif self.user_type == "super_admin":

                    self.admin_id = payload.get("admin_id")
                    self.username = payload.get("username")
                    self.user_id = payload.get("user_id")
                    self.full_name = payload.get("full_name")

            # =====================================================
            # OPTIONAL HELPERS
            # =====================================================

            def __str__(self):

                return self.username or "JWTUser"

            def has_perm(self, perm, obj=None):

                return perm in self.permissions

            def has_module_perms(self, app_label):

                return True

        user = JWTUser(payload)
        # store raw payload in request if you want
        request.user_data = payload

        return (user, None)


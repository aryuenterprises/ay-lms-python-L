# live_quiz/authentication.py
import jwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


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


class LiveQuizJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth = request.headers.get("Authorization")

        if not auth or not auth.startswith("Bearer "):
            return None

        token = auth.split(" ")[1]

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user = JWTUser(payload)
            request.user_data = payload
            return (user, None)

        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Token expired")
        except jwt.InvalidTokenError:
            raise AuthenticationFailed("Invalid token")

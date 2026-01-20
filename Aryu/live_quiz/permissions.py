from rest_framework.permissions import BasePermission


class IsLiveQuizAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user:
            return False

        return user.get("role") in [
            "super_admin",
            "quiz_admin",
            "host"
        ]

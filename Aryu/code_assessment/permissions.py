"""
Permissions and authentication helpers for Code Assessment module.
Directly resolves and validates existing aryuapp.Student identity.
"""
from rest_framework import permissions
from aryuapp.models import Student


def resolve_authenticated_student(request):
    """
    Resolves the existing aryuapp.Student model instance for the authenticated requester.
    Returns: Student instance or None
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None

    # 1. If request.user is already an instance of Student
    if isinstance(user, Student):
        return user

    # 2. Try resolving via student_id attribute or pk
    student_id = (
        getattr(user, "student_id", None)
        or getattr(user, "id", None)
        or getattr(user, "pk", None)
    )
    if student_id and str(student_id).isdigit():
        student = Student.objects.filter(student_id=int(student_id), is_archived=False).first()
        if student:
            return student

    # 3. Try resolving via email attribute or JWT payload email
    email = getattr(user, "email", None)
    if not email and hasattr(user, "payload") and isinstance(user.payload, dict):
        email = user.payload.get("email")

    if email:
        student = Student.objects.filter(email__iexact=email, is_archived=False).first()
        if student:
            return student

    # 4. Try resolving via username
    username = getattr(user, "username", None)
    if username:
        student = Student.objects.filter(username=username, is_archived=False).first()
        if student:
            return student

    return None


def is_staff_or_admin_user(user):
    """
    Checks if the user has administrative or staff access.
    """
    if not user or not user.is_authenticated:
        return False

    return bool(
        getattr(user, "is_staff", False)
        or getattr(user, "is_superuser", False)
        or getattr(user, "user_type", "") in ("admin", "super_admin", "staff")
    )


class IsAuthenticatedStudentOrStaff(permissions.BasePermission):
    """
    Allows access to authenticated users (students or staff).
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class IsSubmissionOwnerOrStaff(permissions.BasePermission):
    """
    Strict IDOR protection: Students can only view their own submissions.
    Staff and Admins can view any submission.
    """

    def has_object_permission(self, request, view, obj):
        if is_staff_or_admin_user(request.user):
            return True

        student = resolve_authenticated_student(request)
        if not student:
            return False

        return obj.student_id == student.student_id


class IsAdminOrStaff(permissions.BasePermission):
    """
    Restricts administrative actions to staff/admins.
    """

    def has_permission(self, request, view):
        return is_staff_or_admin_user(request.user)

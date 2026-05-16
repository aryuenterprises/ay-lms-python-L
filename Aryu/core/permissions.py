# core/permissions.py
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework import status
from aryuapp.models import User

class IsStudent(BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, 'user_type', None) == 'student'

class IsTrainer(BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, 'user_type', None) in ['tutor', 'trainer']

class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, 'user_type', None) in ['admin', 'super_admin']

class IsAdminOrTrainer(BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, 'user_type', None) in ['admin', 'super_admin', 'tutor', 'trainer']

class IsSelfOrAdmin(BasePermission):
    """Fixes IDOR — student can only see own profile."""
    def has_object_permission(self, request, view, obj):
        user = request.user
        user_type = getattr(user, 'user_type', None)

        if user_type in ['admin', 'super_admin']:
            return True

        if user_type == 'student':
            student_id = getattr(user, 'student_id', None)
            return obj.student_id == student_id

        if user_type in ['tutor', 'trainer']:
            # Trainer can only see students in their batches
            trainer_id = getattr(user, 'trainer_id', None)
            from batches.models import NewBatch
            return NewBatch.objects.filter(
                trainer__trainer_id=trainer_id,
                students__student_id=obj.student_id
            ).exists()

        return False
    
class IsSuperAdmin(BasePermission):

    def has_permission(self, request, view):

        return (
            request.user.is_authenticated
            and getattr(request.user, "user_type", "") == "super_admin"
        )


class IsAdminOrSuperAdmin(BasePermission):

    def has_permission(self, request, view):

        return (
            request.user.is_authenticated
            and getattr(
                request.user,
                "user_type",
                ""
            ) in ["admin", "super_admin"]
        )
    
def verify_admin_privileges(request, allowed_types=["super_admin", "admin"]):
    """
    Common DB-backed authority verification gateway.
    Returns (db_user_type, None) if successful, or (None, Response) if unauthorized.
    """
    user = request.user
    
    # 1. Framework authentication fallback
    if not user or not user.is_authenticated:
        return None, Response({
            "success": False,
            "message": "Unable to process request."
        }, status=status.HTTP_403_FORBIDDEN)

    try:
        # 2. HARD DATABASE GATE: Force read direct from disk state
        db_user = User.objects.filter(id=user.user_id, is_archived=False).values('user_type').first()
        
        if not db_user or db_user['user_type'] not in allowed_types:
            return None, Response({
                "success": False,
                "message": "Unable to process request."
            }, status=status.HTTP_403_FORBIDDEN)
            
        return db_user['user_type'], None
        
    except Exception:
        return None, Response({
            "success": False,
            "message": "Unable to process request."
        }, status=status.HTTP_403_FORBIDDEN)
    

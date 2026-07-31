# core/permissions.py
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework import status
from aryuapp.models import User


# ==========================================
# 1. Dynamic Module & Action Permission Guard
# ==========================================
class HasModulePermission(BasePermission):
    """
    Checks if the user has specific module permissions (read, create, update, delete).
    
    Usage on ViewSet:
        permission_classes = [IsAuthenticated, HasModulePermission]
        required_module = "BootCamp"  # or "Batch", "Course", "Transcation History", etc.
    """
    
    ACTION_MAP = {
        'GET': 'read',
        'POST': 'create',
        'PUT': 'update',
        'PATCH': 'update',
        'DELETE': 'delete'
    }

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        user_type = str(getattr(request.user, "user_type", "")).lower()

        # Super Admin bypasses module-level restrictions
        if user_type == "super_admin":
            return True

        required_module = getattr(view, 'required_module', None)
        # If no module constraint specified on the ViewSet, allow access
        if not required_module:
            return True

        required_action = self.ACTION_MAP.get(request.method)
        if not required_action:
            return False

        # Extract permissions list from user object (populated by CustomJWTAuthentication)
        user_permissions = getattr(request.user, 'permissions', [])

        for perm in user_permissions:
            module_name = str(perm.get('module_name', '')).strip().lower()
            if module_name == required_module.lower():
                allowed_actions = perm.get('allowed_actions', [])
                if required_action in allowed_actions:
                    return True

        return False


# ==========================================
# 2. Basic Role Permissions
# ==========================================
class IsStudent(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user 
            and request.user.is_authenticated 
            and getattr(request.user, 'user_type', None) == 'student'
        )


class IsTrainer(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user 
            and request.user.is_authenticated 
            and getattr(request.user, 'user_type', None) in ['tutor', 'trainer']
        )


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user 
            and request.user.is_authenticated 
            and getattr(request.user, 'user_type', None) in ['admin', 'super_admin']
        )


class IsAdminOrTrainer(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user 
            and request.user.is_authenticated 
            and getattr(request.user, 'user_type', None) in ['admin', 'super_admin', 'tutor', 'trainer']
        )


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "user_type", "") == "super_admin"
        )


class IsAdminOrSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "user_type", "") in ["admin", "super_admin"]
        )


# ==========================================
# 3. Object-Level Access Control (IDOR Prevention)
# ==========================================
class IsSelfOrAdmin(BasePermission):
    """Prevents IDOR — ensures users only access their authorized objects."""
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        user_type = getattr(user, 'user_type', None)

        if user_type in ['admin', 'super_admin']:
            return True

        if user_type == 'student':
            student_id = getattr(user, 'student_id', None)
            return getattr(obj, 'student_id', None) == student_id

        if user_type in ['tutor', 'trainer']:
            trainer_id = getattr(user, 'trainer_id', None)
            from batches.models import NewBatch
            return NewBatch.objects.filter(
                trainer__trainer_id=trainer_id,
                students__student_id=getattr(obj, 'student_id', None)
            ).exists()

        return False


# ==========================================
# 4. Helper Verification Function
# ==========================================
def verify_admin_privileges(request, allowed_types=None):
    """
    Common DB-backed authority verification gateway.
    Returns (db_user_type, None) if successful, or (None, Response) if unauthorized.
    """
    if allowed_types is None:
        allowed_types = ["super_admin", "admin"]

    user = request.user

    if not user or not user.is_authenticated:
        return None, Response({
            "success": False,
            "message": "Unable to process request."
        }, status=status.HTTP_403_FORBIDDEN)

    try:
        user_id = getattr(user, 'user_id', getattr(user, 'id', None))
        if not user_id:
            return None, Response({
                "success": False,
                "message": "Unable to process request."
            }, status=status.HTTP_403_FORBIDDEN)

        db_user = User.objects.filter(id=user_id, is_archived=False).values('user_type').first()

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
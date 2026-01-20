# mixins.py
from .models import *
from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from django.utils import timezone
from django.db.models import CharField
from rest_framework.response import Response
from django.utils.timezone import localtime

class LoggingMixin:

    def perform_create(self, serializer):
        obj = serializer.save()
        identifier = self._get_obj_identifier(obj)
        self.log_action(self.request, action="CREATE", description=f"Created {self.__class__.__name__} - {identifier}")
        return obj

    def perform_update(self, serializer):
        obj = serializer.save()
        identifier = self._get_obj_identifier(obj)
        self.log_action(self.request, action="UPDATE", description=f"Updated {self.__class__.__name__} - {identifier}")
        return obj

    def perform_destroy(self, instance):
        identifier = self._get_obj_identifier(instance)
        self.log_action(self.request, action="DELETE", description=f"Deleted {self.__class__.__name__} - {identifier}")
        instance.delete()

    def log_action(self, request, action, description=None):
        user = getattr(request, 'user_data', None)
        if not user:
            return

        user_id = user.get('registration_id') or user.get('employee_id')
        username = user.get('username')
        user_type = user.get('user_type')

        UserActivityLog.objects.create(
            user_id=user_id,
            username=username,
            user_type=user_type,
            action=action,
            description=description or ""
        )

    def _get_obj_identifier(self, obj):
        
        if hasattr(obj, 'student') and obj.student:
            return f"{obj.student.registration_id}"
        elif hasattr(obj, 'trainer') and obj.trainer:
            return f"{obj.trainer.full_name} ({obj.trainer.employee_id})"
        elif hasattr(obj, 'title'):
            return getattr(obj, 'title')
        elif hasattr(obj, 'name'):
            return getattr(obj, 'name')
        return str(getattr(obj, 'id', 'unknown'))


class NotesMixin:
    def save_notes(self, instance, notes_text, request=None):
        if not notes_text:
            return  
        
        for field in Note._meta.fields:
            if isinstance(field, CharField):
                max_len = field.max_length
                if notes_text and len(notes_text) > max_len:
                    raise ValidationError({
                        field.name: f"{field.name.replace('_', ' ').title()} cannot exceed {max_len} characters."
                    })

        # Get user data from request
        user = getattr(request, "user", None)

        created_by = None
        created_by_type = None

        if user and hasattr(user, "user_type"):
            if user.user_type == "super_admin":
                created_by = str(user.user_id)
                created_by_type = "super_admin"
            elif user.user_type in ["admin", "trainer"]:
                created_by = str(user.trainer_id)
                created_by_type = user.user_type
        
        final_status = None

        # Case 1: Boolean status -> convert to string
        if hasattr(instance, "status") and isinstance(instance.status, bool):
            final_status = "True" if instance.status else "False"

        # Case 2: String status -> use directly
        elif hasattr(instance, "status") and isinstance(instance.status, str):
            final_status = instance.status

        # Optional: is_active field exists
        elif hasattr(instance, "is_active"):
            final_status = "True" if instance.is_active else "False"

        content_type = ContentType.objects.get_for_model(instance)

        Note.objects.create(
            content_type=content_type,
            object_id=instance.pk,
            note_text=notes_text,
            reason=notes_text,
            created_by=created_by,
            created_by_type=created_by_type,
            created_at=timezone.now(),
            status = final_status
        )

    def get_notes_reasons(self, instance, request=None):
        content_type = ContentType.objects.get_for_model(instance)
        notes_qs = Note.objects.filter(
            content_type=content_type,
            object_id=instance.pk
        ).order_by('-created_at')

        notes_data = []

        for note in notes_qs:
            created_by_name = "Unknown"

            try:
                if note.created_by:
                    created_by_value = note.created_by.strip()
                    user_type = (note.created_by_type or '').lower()

                    # If stored value is numeric (ID)
                    if created_by_value.isdigit():
                        created_by_id = int(created_by_value)

                        if user_type == 'student':
                            student = Student.objects.filter(id=created_by_id).first()
                            if student:
                                created_by_name = f"{student.first_name} {student.last_name}".strip()

                        elif user_type == 'trainer':
                            trainer = Trainer.objects.filter(id=created_by_id).first()
                            if trainer:
                                created_by_name = f"{trainer.first_name} {trainer.last_name}".strip()

                        else:  # Admin/super_admin in User table
                            user = User.objects.filter(id=created_by_id).first()
                            if user:
                                created_by_name = getattr(user, 'full_name', user.username)

                    else:
                        # If stored value is username (like "super_admin")
                        user = User.objects.filter(username=created_by_value).first()
                        if user:
                            created_by_name = getattr(user, 'full_name', user.username)

            except Exception as e:
                print(f"⚠️ Error resolving created_by for note {note.id}: {e}")
                return Response({'status': False, "message": str(e)}, status=200)

            notes_data.append({
                "id": note.id,
                "note_text": note.note_text,
                "reason": note.reason,
                "content_type": note.content_type.model,
                "created_by_name": created_by_name,
            })

        return notes_data



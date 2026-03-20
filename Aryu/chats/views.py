import requests
from rest_framework.views import APIView
from .models import *
from .serializers import *
from aryuapp.serializer import TrainerSimpleSerializer, SubmissionStudentSerializer
from aryuapp.auth import CustomJWTAuthentication
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated , AllowAny
from rest_framework.decorators import action, api_view
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
import jwt
from django.conf import settings
from django.contrib.auth.hashers import *
from django.db.models import Q, Max

# Create your views here.


class NotificationListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        token = self._get_token_from_header(request)
        if not token:
            return Response({"success": False, "message": "Authorization token missing."}, status=200)

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return Response({"success": False, "message": "Token expired."}, status=200)
        except jwt.InvalidTokenError:
            return Response({"success": False, "message": "Invalid token."}, status=200)

        user_type = payload.get("user_type")
        if not user_type:
            return Response({"success": False, "message": "User type missing in token."}, status=200)

        try:
            if user_type == "student":
                return self._get_student_notifications(payload)

            elif user_type == "tutor":
                return self._get_trainer_notifications(payload)

            elif user_type == "employer":
                return self._get_sub_admin_notifications(payload)
            elif user_type == "admin":
                return self._get_admin_notifications(payload)

            elif user_type == "super_admin":
                return self._get_super_admin_notifications(payload)


            else:
                return Response({"success": False, "message": "Unknown user type."}, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    def _get_token_from_header(self, request):
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header.split(" ")[1]
        return None

    # -------------------------------------------------------------
    # STUDENT NOTIFICATIONS + UNREAD MESSAGE COUNT
    # -------------------------------------------------------------
    def _get_student_notifications(self, payload):
        registration_id = payload.get("registration_id")
        if not registration_id:
            return Response({"success": False, "message": "Student ID missing."}, status=200)

        notifications = Notification.objects.filter(
            student__registration_id=registration_id,
            is_read=False
        ).filter(
            Q(message__icontains='reviewed your submission') |
            Q(message__icontains='Your new class') |
            Q(message__startswith='test_result:') |
            Q(message__icontains='ticket:reply:by Admin') 
        ).order_by("-created_at")

        # NEW → unread message count
        unread_message_count = self._get_unread_message_count_student(registration_id)

        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "success": True,
            "notifications": serializer.data,
            "count": notifications.count(),
            "unread_messages": unread_message_count
        }, status=200)

    # -------------------------------------------------------------
    # TRAINER NOTIFICATIONS + UNREAD MESSAGE COUNT
    # -------------------------------------------------------------
    def _get_trainer_notifications(self, payload):
        employee_id = payload.get("employee_id")
        if not employee_id:
            return Response({"success": False, "message": "Trainer ID missing."}, status=200)

        notifications = Notification.objects.filter(
            trainer__employee_id=employee_id,
            is_read=False
        ).filter(
            Q(message__startswith='submission:') |
            Q(message__icontains='submitted assignment') |
            Q(message__startswith='topic:') |
            Q(message__icontains='updated their topic') |
            Q(message__startswith='class:') |
            Q(message__icontains='class is scheduled') |
            Q(message__startswith='test_submission:')
        ).order_by("-created_at")

        # NEW → unread message count
        unread_message_count = self._get_unread_message_count_trainer(employee_id)

        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "success": True,
            "notifications": serializer.data,
            "count": notifications.count(),
            "unread_messages": unread_message_count
        }, status=200)

    # -------------------------------------------------------------
    # SUB ADMIN NOTIFICATIONS (NO MESSAGE COUNT)
    # -------------------------------------------------------------
    def _get_sub_admin_notifications(self, payload):
        employer_id = payload.get("employer_id")
        if not employer_id:
            return Response({"success": False, "message": "Employer ID missing."}, status=200)

        notifications = Notification.objects.filter(
            sub_admin__employer_id=employer_id,
            is_read=False
        ).filter(
            Q(message__startswith='submission:') |
            Q(message__startswith='submission_reply:') |
            Q(message__startswith='topic:') |
            Q(message__icontains='updated their topic') |
            Q(message__startswith='class:')
        ).order_by("-created_at")

        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "success": True,
            "notifications": serializer.data,
            "count": notifications.count(),
            "unread_messages": 0
        }, status=200)
    
    def _get_admin_notifications(self, payload):
        """
        Admin (Trainer with user_type='admin') notification list.
        We will use the trainer__employee_id field from JWT.
        """
        employee_id = payload.get("employee_id")
        if not employee_id:
            return Response({"success": False, "message": "Admin employee_id missing."}, status=200)

        notifications = Notification.objects.filter(
            trainer__employee_id=employee_id,
            is_read=False
        ).filter(
            # Ticket-specific notifications for admin
            Q(message__startswith='ticket:new:') |
            Q(message__startswith='ticket:reply:')
        ).order_by("-created_at")

        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "success": True,
            "notifications": serializer.data,
            "count": notifications.count(),
            "unread_messages": 0  # If you later want admin chat unread, you can add similar to trainer
        }, status=200)
    
    def _get_super_admin_notifications(self, payload):
        """
        Super admin (User with user_type='super_admin') notification list.
        """
        super_admin_id = payload.get("user_id")
        if not super_admin_id:
            return Response({"success": False, "message": "Super admin ID missing."}, status=200)

        notifications = Notification.objects.filter(
            super_admin_id=super_admin_id,
            is_read=False
        ).filter(
            # Ticket-specific notifications for super admin
            Q(message__startswith='ticket:new:') |
            Q(message__startswith='ticket:reply:')
        ).order_by("-created_at")

        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            "success": True,
            "notifications": serializer.data,
            "count": notifications.count(),
            "unread_messages": 0
        }, status=200)

    def _get_unread_message_count_student(self, registration_id):
        return Message.objects.filter(
            room__student__registration_id=registration_id,
            is_read=False
        ).count()

    def _get_unread_message_count_trainer(self, employee_id):
        return Message.objects.filter(
            room__trainer__employee_id=employee_id,
            is_read=False
        ).count()

class AdminChatLogViewSet(viewsets.ViewSet):
    
    @action(detail=False, methods=["get"], url_path="chat-logs")
    def admin_chat_logs(self, request):
        try:
            user_type = getattr(request.user, "user_type", None)

            # Allow admin + super_admin only
            if user_type not in ["admin", "super_admin"]:
                return Response({
                    "success": False,
                    "message": "Only admins & super admins can view chat logs"
                }, status=200)

            # Fetch all chat rooms
            chat_rooms = ChatRoom.objects.all().select_related("student", "trainer")

            final_data = []

            for room in chat_rooms:
                messages = room.messages.filter(is_deleted=False).order_by("created_at")
                messages_data = MessageSerializer(messages, many=True).data

                # Latest message
                last_msg = room.messages.filter(is_deleted=False).order_by("-created_at").first()
                last_message_data = MessageSerializer(last_msg).data if last_msg else None

                final_data.append({
                    "room_id": room.id,
                    "student": {
                        "id": room.student.registration_id,
                        "student_name": f"{room.student.first_name} {room.student.last_name}",
                        "profile_pic": (
                            request.build_absolute_uri(room.student.profile_pic.url)
                            if room.student.profile_pic else None
                        )
                    },
                    "trainer": {
                        "id": room.trainer.employee_id,
                        "trainer_name": (
                            room.trainer.full_name
                            if hasattr(room.trainer, "full_name")
                            else f"{room.trainer.first_name} {room.trainer.last_name}"
                        ),
                        "profile_pic": (
                            request.build_absolute_uri(room.trainer.profile_pic.url)
                            if room.trainer.profile_pic else None
                        )
                    },
                    "created_at": room.created_at,
                    "last_message": last_message_data,
                    "messages": messages_data
                })

            return Response({
                "success": True,
                "total_rooms": len(final_data),
                "chat_logs": final_data
            }, status=200)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=200)

@api_view(["POST"])
def mark_notification_read(request):
    notif_id = request.data.get("id")
    try:
        notif = Notification.objects.get(id=notif_id)
        notif.is_read = True
        notif.save()
        return Response({"success": True, "message": "Notification marked as read"})
    except Notification.DoesNotExist:
        return Response({"success": False, "message": "Notification not found"}, status=status.HTTP_200_OK)
    
class ChatRoomViewSet(viewsets.ModelViewSet):
    queryset = ChatRoom.objects.all()
    serializer_class = ChatRoomSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def list(self, request, *args, **kwargs):
        try:
            user_type = getattr(request.user, "user_type", None)

            # --- CASE 1: Student ---
            if user_type == "student":
                registration_id = getattr(request.user, "registration_id", None)
                student = Student.objects.filter(registration_id=registration_id).first()

                if not student:
                    return Response({"success": False, "message": "Student not found"}, status=200)

                chat_rooms = (
                    ChatRoom.objects.filter(student=student)
                    .annotate(last_msg_time=Max("messages__created_at"))
                    .order_by("-last_msg_time", "-created_at")
                )

                chat_data = self.get_serializer(chat_rooms, many=True).data

                # Inject last_message + unread_count
                enriched_chat_data = []
                for chatroom, serialized in zip(chat_rooms, chat_data):
                    last_message = chatroom.messages.filter(is_deleted=False).order_by("-created_at").first()
                    serialized["last_message"] = {
                        "id": last_message.id,
                        "content": last_message.content,
                        "sender_type": last_message.sender_type,
                        "sender_id": last_message.sender_id,
                        "created_at": last_message.created_at,
                    } if last_message else None

                    serialized["unread_count"] = chatroom.messages.filter(
                        is_read=False,
                        is_deleted=False,
                        sender_type="trainer"
                    ).count()

                    enriched_chat_data.append(serialized)

                assigned_trainers = (
                    NewBatch.objects.filter(students=student)
                    .select_related("trainer", "course")
                )

                trainer_map = {}
                for bct in assigned_trainers:
                    trainer = bct.trainer
                    if trainer.employee_id not in trainer_map:
                        trainer_map[trainer.employee_id] = {
                            "trainer": TrainerSimpleSerializer(trainer).data,

                        }

                return Response({
                    "success": True,
                    "message": "Chat rooms and assigned trainers fetched successfully",
                    "chat_rooms": chat_data,
                    "assigned_trainers": list(trainer_map.values()),
                    "last_message": enriched_chat_data
                }, status=200)

            # --- CASE 2: Trainer ---
            elif user_type == "tutor":
                employee_id = getattr(request.user, "employee_id", None)
                trainer = Trainer.objects.filter(employee_id=employee_id).first()

                if not trainer:
                    return Response({"success": False, "message": "Trainer not found"}, status=200)
                
                chat_rooms = (
                    ChatRoom.objects.filter(trainer=trainer)
                    .annotate(last_msg_time=Max("messages__created_at"))
                    .order_by("-last_msg_time", "-created_at")
                )

                chat_data = self.get_serializer(chat_rooms, many=True).data

                # 🔹 Inject last_message + unread_count
                enriched_chat_data = []
                for chatroom, serialized in zip(chat_rooms, chat_data):
                    last_message = chatroom.messages.filter(is_deleted=False).order_by("-created_at").first()
                    serialized["last_message"] = {
                        "id": last_message.id,
                        "content": last_message.content,
                        "sender_type": last_message.sender_type,
                        "sender_id": last_message.sender_id,
                        "created_at": last_message.created_at,
                    } if last_message else None

                    serialized["unread_count"] = chatroom.messages.filter(
                        is_read=False,
                        is_deleted=False,
                        sender_type="student"
                    ).count()

                    enriched_chat_data.append(serialized)

                assigned_batches = (
                    NewBatch.objects.filter(trainer=trainer)
                    .select_related("trainer", "course")
                )

                student_map = {}

                for batch in assigned_batches:
                    for student in batch.students.all():
                        if student.registration_id not in student_map:
                            serialized_student = SubmissionStudentSerializer(student).data
                            student_map[student.registration_id] = {
                                "student_id": student.registration_id,
                                "student_name": f"{student.first_name} {student.last_name}",
                                "profile_pic": serialized_student["profile_pic"],
                            }
 
                return Response({
                    "success": True,
                    "message": "Assigned students fetched successfully",
                    "chat_rooms": chat_data,
                    "assigned_students": list(student_map.values()),
                    "last_message": enriched_chat_data
                }, status=200)

            # --- CASE 3: Others ---
            return Response({"success": False, "message": "Only students and trainers can access this"}, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    def create(self, request, *args, **kwargs):
        try:
            student_id = request.data.get("student_id")
            trainer_id = request.data.get("trainer_id")

            if not student_id or not trainer_id:
                return Response(
                    {"success": False, "message": "student_id and trainer_id are required"},
                    status=status.HTTP_200_OK
                )

            student = Student.objects.filter(registration_id=student_id).first()
            trainer = Trainer.objects.filter(employee_id=trainer_id).first()

            if not student:
                return Response(
                    {"success": False, "message": "Student not found"},
                    status=status.HTTP_200_OK
                )

            if not trainer:
                return Response(
                    {"success": False, "message": "Trainer not found"},
                    status=status.HTTP_200_OK
                )

            room, created = ChatRoom.objects.get_or_create(student=student, trainer=trainer)
            serializer = self.get_serializer(room)

            return Response(
                {"success": True, "message": "Chat room created", "data": serializer.data},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_200_OK
            )

    @action(detail=False, methods=["get"], url_path=r'(?P<student_id>[^/.]+)/eduthuko')
    def student_chat_logs(self, request, student_id=None):
        try:
            user_type = getattr(request.user, "user_type", None)
            if user_type != "admin":
                return Response(
                    {"success": False, "message": "Only admins can view chat logs"},
                    status=status.HTTP_200_OK
                )

            # Get student
            student = Student.objects.filter(student_id=student_id).first()
            if not student:
                return Response(
                    {"success": False, "message": "Student not found"},
                    status=status.HTTP_200_OK
                )

            # Fetch all chatrooms for this student
            chat_rooms = ChatRoom.objects.filter(student=student).select_related("trainer")
            data = []

            for room in chat_rooms:
                trainer_data = TrainerSimpleSerializer(room.trainer).data if room.trainer else None
                messages = Message.objects.filter(room=room, is_deleted=False).order_by("created_at")
                messages_data = MessageSerializer(messages, many=True).data

                data.append({
                    "room_id": room.id,
                    "trainer": trainer_data,
                    "messages": messages_data
                })

            return Response({
                "success": True,
                "student": SubmissionStudentSerializer(student).data,
                "chat_rooms": data
            }, status=200)

        except Exception as e:
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_200_OK
            )

class MessageViewSet(viewsets.ModelViewSet):
    queryset = Message.objects.all().order_by("created_at")
    serializer_class = MessageSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def list(self, request, room_id=None):
        try:
            messages = Message.objects.filter(room_id=room_id).order_by("created_at")
            serializer = self.get_serializer(messages, many=True)
            return Response({"success": True, "message": "Messages fetched successfully", "data": serializer.data}, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)
        
    def create(self, request, room_id=None):
        try:
            # Pass request.data and request.FILES
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(room_id=room_id)

            return Response({
                "success": True,
                "message": "Message sent successfully",
                "data": serializer.data
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    def unread_messages(self, request, room_id=None):
        messages = Message.objects.filter(room_id=room_id, is_read=False, is_deleted=False)
        return Response({"unread_count": messages.count()})

    def mark_as_read(self, request, room_id=None):
        reader_type = request.data.get("reader_type")
        reader_id = request.data.get("reader_id")

        if not reader_type or not reader_id:
            return Response({"success": False, "message": "reader_type and reader_id required"}, status=200)

        # Mark only messages in this room that are not read
        Message.objects.filter(room_id=room_id, is_read=False).update(is_read=True)

        return Response({"success": True, "message": f"All messages in room {room_id} marked as read"}, status=200)

    @action(detail=True, methods=["put"], url_path="edit")
    def edit_message(self, request, pk=None):
        """ Allow only sender to edit their own message """
        message = self.get_object()
        sender_type = request.data.get("sender_type")
        sender_id = request.data.get("sender_id")

        if message.sender_type != sender_type or message.sender_id != sender_id:
            return Response({ "success": False, "message": "You can only edit your own message"}, status=status.HTTP_200_OK)

        message.content = request.data.get("content", message.content)
        message.save()
        return Response(MessageSerializer(message).data)

    @action(detail=True, methods=["delete"], url_path="delete")
    def delete_message(self, request, pk=None):
        """ Soft delete: mark message as deleted """
        message = self.get_object()
        sender_type = request.data.get("sender_type")
        sender_id = request.data.get("sender_id")

        if message.sender_type != sender_type or message.sender_id != sender_id:
            return Response({ "success": False, "message": "You can only delete your own message"}, status=status.HTTP_200_OK)

        message.is_deleted = True
        message.content = "This message was deleted"
        message.save()
        return Response({ "success": True, "status": "message deleted"}, status=status.HTTP_200_OK)

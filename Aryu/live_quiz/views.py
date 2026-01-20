import secrets
from django.utils import timezone
from django.db.models import Sum
from datetime import timedelta
from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.views import APIView
from django.contrib.auth import authenticate
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
import jwt
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from .common.utils import get_actor_from_request
from .common.base import BaseViewSet
from.authentication import LiveQuizJWTAuthentication
from .permissions import IsLiveQuizAdmin
from .models import *
from .serializers import *




class LiveQuizAdminLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return Response(
                {"success": False, "message": "Username and password required"},
                status=400
            )

        # ------------------------------------------------
        # 1️⃣ Check aryuapp.users (main system admins)
        # ------------------------------------------------
        user = authenticate(username=username, password=password)
        if user and user.is_active:
            payload = {
                "source": "aryuapp",
                "user_id": user.id,
                "username": user.username,
                "role": (
                    user.role.name if user.role else user.user_type
                ),
                "exp": int((timezone.now() + timedelta(hours=1)).timestamp()),
            }

            token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

            return Response({
                "success": True,
                "token": token,
                "user": {
                    "username": user.username,
                    "role": payload["role"],
                    "source": "aryuapp",
                }
            })

        # ------------------------------------------------
        # 2️⃣ Check live_quiz.admin_user (quiz-only admins)
        # ------------------------------------------------
        admin = AdminUser.objects.filter(username=username, is_active=True).first()
        if admin and admin.verify_password(password):
            payload = {
                "source": "live_quiz",
                "admin_id": admin.id,
                "username": admin.username,
                "role": admin.role,
                "exp": int((timezone.now() + timedelta(hours=1)).timestamp()),
            }

            token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

            return Response({
                "success": True,
                "token": token,
                "user": {
                    "username": admin.username,
                    "role": admin.role,
                    "source": "live_quiz",
                }
            })

        return Response(
            {"success": False, "message": "Invalid admin credentials"},
            status=401
        )


class AdminUserViewSet(BaseViewSet):

    def list(self, request):
        admins = AdminUser.objects.all()
        serializer = AdminUserSerializer(admins, many=True)
        return self.success(
            message="Admins fetched successfully",
            data=serializer.data
        )

    def retrieve(self, request, pk=None):
        admin = get_object_or_404(AdminUser, pk=pk)
        serializer = AdminUserSerializer(admin)
        return self.success(
            message="Admin details fetched successfully",
            data=serializer.data
        )

    def create(self, request):
        serializer = AdminUserSerializer(data=request.data)
        if not serializer.is_valid():
            return self.error(serializer.errors)

        serializer.save()
        return self.success(
            message="Admin created successfully",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED
        )

    def update(self, request, pk=None):
        admin = get_object_or_404(AdminUser, pk=pk)
        serializer = AdminUserSerializer(admin, data=request.data)
        if not serializer.is_valid():
            return self.error(serializer.errors)

        serializer.save()
        return self.success(
            message="Admin updated successfully",
            data=serializer.data
        )

    def destroy(self, request, pk=None):
        admin = get_object_or_404(AdminUser, pk=pk)
        admin.delete()
        return self.success(message="Admin deleted successfully")

class RoomViewSet(BaseViewSet):

    def list(self, request):
        rooms = Room.objects.all()
        serializer = RoomSerializer(rooms, many=True)
        return self.success(
            message="Rooms fetched successfully",
            data=serializer.data
        )

    def retrieve(self, request, pk=None):
        room = get_object_or_404(Room, pk=pk)
        serializer = RoomSerializer(room)
        return self.success(
            message="Room details fetched successfully",
            data=serializer.data
        )

    def create(self, request):
        serializer = RoomSerializer(data=request.data)
        if not serializer.is_valid():
            return self.error(serializer.errors)

        actor = get_actor_from_request(request)
        serializer.save(created_by=actor, updated_by=actor)

        return self.success(
            message="Room created successfully",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED
        )

    # ✅ PUT (FULL UPDATE)
    def update(self, request, pk=None):
        room = get_object_or_404(Room, pk=pk)
        serializer = RoomSerializer(room, data=request.data)  # full update
        if not serializer.is_valid():
            return self.error(serializer.errors)

        actor = get_actor_from_request(request)
        serializer.save(updated_by=actor)

        return self.success(
            message="Room updated successfully",
            data=serializer.data
        )

    # ✅ PATCH (PARTIAL UPDATE — EVEN IF ALL FIELDS PASSED)
    def partial_update(self, request, pk=None):
        room = get_object_or_404(Room, pk=pk)
        serializer = RoomSerializer(
            room,
            data=request.data,
            partial=True  # 🔑 THIS IS THE KEY
        )

        if not serializer.is_valid():
            return self.error(serializer.errors)

        actor = get_actor_from_request(request)
        serializer.save(updated_by=actor)

        return self.success(
            message="Room updated successfully",
            data=serializer.data
        )

    def destroy(self, request, pk=None):
        room = get_object_or_404(Room, pk=pk)
        room.delete()
        return self.success(message="Room deleted successfully")

    @action(detail=True, methods=["post"])
    def start_quiz(self, request, pk=None):
        room = get_object_or_404(Room, pk=pk)
        room.started = True
        room.save(update_fields=["started"])

        return self.success(message="Quiz started successfully")


class QuestionViewSet(BaseViewSet):

    def list(self, request):
        room_id = request.query_params.get("room")
        queryset = Question.objects.select_related("room")

        if room_id:
            queryset = queryset.filter(room_id=room_id)

        serializer = QuestionSerializer(queryset, many=True)
        return self.success(
            message="Questions fetched successfully",
            data=serializer.data
        )

    def retrieve(self, request, pk=None):
        question = get_object_or_404(Question, pk=pk)
        serializer = QuestionSerializer(question)
        return self.success(
            message="Question fetched successfully",
            data=serializer.data
        )

    def create(self, request):
        serializer = QuestionSerializer(data=request.data)
        if not serializer.is_valid():
            return self.error(serializer.errors)

        actor = get_actor_from_request(request)
        serializer.save(created_by=actor, updated_by=actor)

        return self.success(
            message="Question created successfully",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED
        )

    # ✅ PUT (FULL UPDATE)
    def update(self, request, pk=None):
        question = get_object_or_404(Question, pk=pk)
        serializer = QuestionSerializer(question, data=request.data)  # full update
        if not serializer.is_valid():
            return self.error(serializer.errors)

        actor = get_actor_from_request(request)
        serializer.save(updated_by=actor)

        return self.success(
            message="Question updated successfully",
            data=serializer.data
        )

    # ✅ PATCH (PARTIAL UPDATE — EVEN IF ALL FIELDS PASSED)
    def partial_update(self, request, pk=None):
        question = get_object_or_404(Question, pk=pk)
        serializer = QuestionSerializer(
            question,
            data=request.data,
            partial=True  # 🔑 THIS IS THE KEY
        )

        if not serializer.is_valid():
            return self.error(serializer.errors)

        actor = get_actor_from_request(request)
        serializer.save(updated_by=actor)

        return self.success(
            message="Question updated successfully",
            data=serializer.data
        )

    def destroy(self, request, pk=None):
        question = get_object_or_404(Question, pk=pk)
        question.delete()
        return self.success(message="Question deleted successfully")


class ParticipantViewSet(viewsets.ModelViewSet):
    queryset = Participant.objects.select_related("room")
    serializer_class = ParticipantSerializer

    def perform_destroy(self, instance):
        instance.delete()


class JoinRoomView(APIView):
    def post(self, request, room_id):
        room = Room.objects.get(id=room_id)

        if room.started:
            return Response({"error": "Quiz already started"}, status=400)

        if timezone.now() < room.start_at:
            return Response({"error": "Quiz not started yet"}, status=400)

        if room.participants.count() >= room.max_participants:
            return Response({"error": "Room full"}, status=400)

        serializer = ParticipantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        participant = Participant(room=room, **serializer.validated_data)
        participant.generate_token()
        participant.save()

        return Response({"token": participant.token})


class FinalLeaderboardView(APIView):
    def get(self, request, room_id):
        data = (
            Participant.objects
            .filter(room_id=room_id)
            .annotate(score=Sum("answers__score"))
            .order_by("-score")
        )

        return Response([
            {"name": p.name, "score": p.score or 0}
            for p in data
        ])

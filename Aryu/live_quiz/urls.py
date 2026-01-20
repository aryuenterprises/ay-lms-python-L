from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()

router.register("admins", AdminUserViewSet, basename="admins")
router.register("rooms", RoomViewSet, basename="rooms")
router.register("questions", QuestionViewSet, basename="questions")
router.register("participants", ParticipantViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("join/<uuid:room_id>/", JoinRoomView.as_view()),
    path("leaderboard/<uuid:room_id>/", FinalLeaderboardView.as_view()),
]

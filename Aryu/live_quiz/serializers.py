from rest_framework import serializers
from .models import *


class AdminUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = AdminUser
        fields = "__all__"

    def create(self, data):
        user = AdminUser(username=data["username"])
        user.set_password(data["password"])
        user.save()
        return user

class RoomSerializer(serializers.ModelSerializer):

    class Meta:
        model = Room
        fields = "__all__"
        read_only_fields = [
            "id",
            "created_by",
            "updated_by",
            "created_at",
            "started",
            "current_question",
        ]


class QuestionSerializer(serializers.ModelSerializer):

    class Meta:
        model = Question
        fields = "__all__"
        read_only_fields = [
            "id",
            "created_by",
            "updated_by",
        ]

    def validate(self, data):
        qtype = data["question_type"]
        config = data["config"]

        if qtype in ["mcq", "radio"]:
            if "choices" not in config or "correct" not in config:
                raise serializers.ValidationError(
                    f"{qtype.upper()} requires choices & correct"
                )

        if qtype == "poll":
            if "choices" not in config:
                raise serializers.ValidationError("Poll requires choices")

        if qtype == "tf":
            if "correct" not in config or not isinstance(config["correct"], bool):
                raise serializers.ValidationError("TF requires boolean correct")

        if qtype == "match":
            if "pairs" not in config or not isinstance(config["pairs"], dict):
                raise serializers.ValidationError("Match requires pairs dict")

        return data


class ParticipantCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = ["name", "email", 'phone', 'city','country']

class RoomSummarySerializer(serializers.Serializer):
    room_id = serializers.UUIDField()
    title = serializers.CharField()
    description = serializers.CharField()
    total_questions = serializers.IntegerField()
    total_marks = serializers.IntegerField()
    max_participants = serializers.IntegerField()
    start_at = serializers.DateTimeField()
    started = serializers.BooleanField()

class ParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = "__all__"


class AnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Answer
        fields = "__all__"

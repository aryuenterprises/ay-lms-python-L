from rest_framework import serializers
from .models import *
from aryuapp.serializer import CourseSimpleSerializer, StudentDetailSerializer



class TestSerializer(serializers.ModelSerializer):
    course = CourseSimpleSerializer(source="course_id", read_only=True)
    test_completion = serializers.SerializerMethodField()

    class Meta:
        model = Test
        fields = [
            'test_id', 'test_name', 'description', 'duration', 'pass_mark', 'status',
            'total_marks', 'test_completion', 'course_id', 'course', 'is_archived', 'created_at', 'created_by'
        ]
        
    def create(self, validated_data):
        request = self.context.get("request")
        
        if request and request.user:
            role = getattr(request.user, "user_type", None)  # or from JWT payload

            if role in ["trainer", "admin"]:
                validated_data["created_by"] = getattr(request.user, "trainer_id", None)
                validated_data["created_by_type"] = role

            elif role == "super_admin":
                validated_data["created_by"] = getattr(request.user, "user_id", None)
                validated_data["created_by_type"] = role

            elif role == "student":
                validated_data["created_by"] = getattr(request.user, "student_id", None)
                validated_data["created_by_type"] = role

            else:
                validated_data["created_by"] = getattr(request.user, "user_id", None)
                validated_data["created_by_type"] = role
        return super().create(validated_data)
    
    def get_test_completion(self, obj):
        request = self.context.get("request")
        student = getattr(request.user, "student", None)  # 🔹 student linked with user

        if not student:
            return False  # not a student account

        return TestResult.objects.filter(student=student, test=obj).exists()

class TestQuestionsSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    
    class Meta:
        model = TestQuestions
        fields = ['question_id', 'test_id', 'question', 'type', 'options', 'marks', 'written_answer', 'mcq_correct_option', 'is_archived', 'created_at', 'created_by']

    def validate(self, data):
        q_type = data.get('type')
        if q_type.lower() == 'mcq' and not data.get('options'):
            raise serializers.ValidationError("MCQ questions must have options")
        return data

    def create(self, validated_data):
        request = self.context.get('request')
        if request and hasattr(request.user, 'trainer_id'):
            validated_data['created_by'] = request.user.trainer_id
        return super().create(validated_data)

class StudentAnswersSerializer(serializers.ModelSerializer):
    submitted_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    
    class Meta:
        model = StudentAnswers
        fields = [
            'answer_id',
            'student_id',
            'question_id',
            'test_id',
            'submitted_at',
            'selected_option',
            'written_answer',
            'is_correct'
        ]

    def validate_written_answer(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Written answer cannot be empty or spaces only")
        return value.strip()
    
    def create(self, validated_data):
        question = validated_data.get("question_id")

        # Snapshot question text
        validated_data["question_text"] = question.question

        # Determine the type of question
        if question.type == "mcq":
            # Save MCQ options and correct answer snapshot
            validated_data["options_snapshot"] = question.options
            validated_data["correct_answer_snapshot"] = question.mcq_correct_option
            validated_data["written_answer"] = None
        elif question.type == "written":
            # Save written answer snapshot in the existing field
            validated_data["correct_answer_snapshot"] = question.written_answer
            validated_data["options_snapshot"] = None

        return super().create(validated_data)

class TestResultSerializer(serializers.ModelSerializer):
    student = serializers.SerializerMethodField()
    submitted_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    evaluated_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', read_only=True)
    evaluated_by = serializers.SerializerMethodField()
    answers = serializers.SerializerMethodField()

    class Meta:
        model = TestResult
        fields = [
            'result_id', 'student_id', 'student', 'test_id',
            'evaluated_by', 'score', 'percentage', 'status',
            'time_taken', 'submitted_at', 'evaluated_at', 'answers'
        ]

    def get_student(self, obj):
        return StudentDetailSerializer(obj.student_id).data

    def get_evaluated_by(self, obj):
        if obj.evaluated_by:
            return {
                "employee_id": obj.evaluated_by.employee_id,
                "name": obj.evaluated_by.full_name
            }
        return None
    
    def get_answers(self, obj):
        student_answers = obj.student_id.student_answers.filter(test_id=obj.test_id)
        data = []
        for ans in student_answers:
            data.append({
                "answer_id": ans.answer_id,
                "question_id": ans.question_id.question_id if ans.question_id else None,
                "question": ans.question_text,
                "type": ans.question_id.type if ans.question_id else None,
                "options": ans.options_snapshot,
                "correct_answer": ans.correct_answer_snapshot,
                "submitted_answer": {
                    "selected_option": ans.selected_option,
                    "written_answer": ans.written_answer,
                    "is_correct": ans.is_correct
                },
                "submitted_at": ans.submitted_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        return data

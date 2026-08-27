"""
Serializers for Online Code Assessment REST APIs.
Directly uses the existing aryuapp.Student model for student identity.
"""
from rest_framework import serializers
from .constants import (
    DIFFICULTY_CHOICES,
    LANGUAGE_CHOICES,
    SUPPORTED_LANGUAGES,
    MAX_SOURCE_CODE_BYTES,
    MAX_STDIN_BYTES,
)
from .models import (
    CodingProblem,
    CodingTestCase,
    CodingAssessment,
    AssessmentProblem,
    AssessmentAttempt,
    CodeSubmission,
    SubmissionTestCaseResult,
)
from .validators import (
    validate_source_code_size,
    validate_stdin_size,
    validate_supported_language_choice,
)


class CodingTestCaseSampleSerializer(serializers.ModelSerializer):
    """
    Public serializer for sample test cases visible to students.
    """
    class Meta:
        model = CodingTestCase
        fields = [
            "id",
            "input_data",
            "expected_output",
            "is_sample",
            "explanation",
            "order",
        ]


class CodingTestCaseAdminSerializer(serializers.ModelSerializer):
    """
    Full serializer for staff/admin test case management (includes hidden test cases).
    """
    class Meta:
        model = CodingTestCase
        fields = "__all__"


class CodingProblemListSerializer(serializers.ModelSerializer):
    """
    Summary serializer for listing coding problems.
    """
    acceptance_rate = serializers.ReadOnlyField()

    class Meta:
        model = CodingProblem
        fields = [
            "id",
            "title",
            "slug",
            "difficulty",
            "tags",
            "supported_languages",
            "total_submissions_count",
            "accepted_submissions_count",
            "acceptance_rate",
            "created_at",
        ]


class CodingProblemDetailSerializer(serializers.ModelSerializer):
    """
    Detailed problem serializer for students.
    CRITICAL: NEVER exposes hidden test cases. Only returns sample test cases.
    """
    acceptance_rate = serializers.ReadOnlyField()
    sample_test_cases = serializers.SerializerMethodField()

    class Meta:
        model = CodingProblem
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "difficulty",
            "constraints",
            "input_format",
            "output_format",
            "sample_explanation",
            "time_limit_ms",
            "memory_limit_mb",
            "supported_languages",
            "starter_code",
            "tags",
            "sample_test_cases",
            "total_submissions_count",
            "accepted_submissions_count",
            "acceptance_rate",
            "created_at",
        ]

    def get_sample_test_cases(self, obj):
        sample_cases = obj.test_cases.filter(is_sample=True).order_by("order", "id")
        return CodingTestCaseSampleSerializer(sample_cases, many=True).data


class CodingProblemAdminSerializer(serializers.ModelSerializer):
    """
    Admin serializer with full management capabilities and all test cases.
    """
    test_cases = CodingTestCaseAdminSerializer(many=True, read_only=True)
    acceptance_rate = serializers.ReadOnlyField()

    class Meta:
        model = CodingProblem
        fields = "__all__"


class CodeRunRequestSerializer(serializers.Serializer):
    """
    Validates requests to execute code against sample test cases or custom input.
    """
    language = serializers.CharField(max_length=30)
    source_code = serializers.CharField(validators=[validate_source_code_size])
    custom_input = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        validators=[validate_stdin_size],
    )

    def validate_language(self, value):
        validate_supported_language_choice(value)
        return value


class CodeSubmissionCreateSerializer(serializers.Serializer):
    """
    Validates submission creation requests.
    NOTE: student_id is never accepted from the frontend; it is resolved via authentication.
    """
    problem_id = serializers.IntegerField(required=True)
    assessment_id = serializers.IntegerField(required=False, allow_null=True)
    language = serializers.CharField(max_length=30)
    source_code = serializers.CharField(validators=[validate_source_code_size])

    def validate_language(self, value):
        validate_supported_language_choice(value)
        return value


class SubmissionTestCaseResultSerializer(serializers.ModelSerializer):
    """
    Serializer for individual test case results.
    Guarantees hidden test case input/output is not leaked to students.
    """
    test_case_id = serializers.IntegerField(source="test_case.id", read_only=True)
    is_sample = serializers.BooleanField(source="test_case.is_sample", read_only=True)

    class Meta:
        model = SubmissionTestCaseResult
        fields = [
            "id",
            "test_case_id",
            "is_sample",
            "status",
            "execution_time_ms",
            "memory_used_kb",
            "stdout",
            "stderr",
            "error_message",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        is_staff = request and (
            getattr(request.user, "is_staff", False)
            or getattr(request.user, "is_superuser", False)
        )

        # Redact stdout/stderr for hidden test cases if viewer is not staff/admin
        if not is_staff and not instance.test_case.is_sample:
            data["stdout"] = ""
            data["stderr"] = ""

        return data


class CodeSubmissionDetailSerializer(serializers.ModelSerializer):
    """
    Comprehensive serializer for submission details, evaluation status, and test outcomes.
    Retrieves student information dynamically from existing Student model relationship.
    """
    student_id = serializers.IntegerField(source="student.student_id", read_only=True)
    student_name = serializers.CharField(source="student.__str__", read_only=True)
    student_email = serializers.CharField(source="student.email", read_only=True)
    student_registration_id = serializers.CharField(source="student.registration_id", read_only=True)

    problem_title = serializers.CharField(source="problem.title", read_only=True)
    problem_slug = serializers.CharField(source="problem.slug", read_only=True)
    test_case_results = SubmissionTestCaseResultSerializer(many=True, read_only=True)

    class Meta:
        model = CodeSubmission
        fields = [
            "id",
            "student_id",
            "student_name",
            "student_email",
            "student_registration_id",
            "problem",
            "problem_title",
            "problem_slug",
            "assessment",
            "language",
            "source_code",
            "status",
            "score",
            "total_test_cases",
            "passed_test_cases",
            "execution_time_ms",
            "memory_used_kb",
            "error_message",
            "compile_output",
            "test_case_results",
            "submitted_at",
            "completed_at",
        ]


class CodeSubmissionListSerializer(serializers.ModelSerializer):
    """
    Compact serializer for listing submissions.
    """
    student_id = serializers.IntegerField(source="student.student_id", read_only=True)
    problem_title = serializers.CharField(source="problem.title", read_only=True)
    problem_slug = serializers.CharField(source="problem.slug", read_only=True)

    class Meta:
        model = CodeSubmission
        fields = [
            "id",
            "student_id",
            "problem",
            "problem_title",
            "problem_slug",
            "assessment",
            "language",
            "status",
            "score",
            "passed_test_cases",
            "total_test_cases",
            "execution_time_ms",
            "submitted_at",
            "completed_at",
        ]


class AssessmentProblemSerializer(serializers.ModelSerializer):
    """
    Represents problems attached to an assessment.
    """
    problem_title = serializers.CharField(source="problem.title", read_only=True)
    problem_slug = serializers.CharField(source="problem.slug", read_only=True)
    difficulty = serializers.CharField(source="problem.difficulty", read_only=True)

    class Meta:
        model = AssessmentProblem
        fields = [
            "id",
            "problem",
            "problem_title",
            "problem_slug",
            "difficulty",
            "order",
            "points",
        ]


class AssessmentAttemptSerializer(serializers.ModelSerializer):
    """
    Serializer for tracking a student's attempt on an assessment.
    """
    student_id = serializers.IntegerField(source="student.student_id", read_only=True)
    student_name = serializers.CharField(source="student.__str__", read_only=True)
    assessment_title = serializers.CharField(source="assessment.title", read_only=True)

    class Meta:
        model = AssessmentAttempt
        fields = [
            "id",
            "student_id",
            "student_name",
            "assessment",
            "assessment_title",
            "score",
            "is_passed",
            "is_completed",
            "started_at",
            "completed_at",
        ]


class CodingAssessmentListSerializer(serializers.ModelSerializer):
    """
    Summary serializer for assessments list.
    """
    problems_count = serializers.IntegerField(source="assessment_problems.count", read_only=True)
    course_name = serializers.CharField(source="course.course_name", read_only=True)

    class Meta:
        model = CodingAssessment
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "course",
            "course_name",
            "duration_minutes",
            "passing_percentage",
            "problems_count",
            "start_time",
            "end_time",
            "is_active",
            "created_at",
        ]


class CodingAssessmentDetailSerializer(serializers.ModelSerializer):
    """
    Detailed assessment serializer with attached problem list.
    """
    problems = AssessmentProblemSerializer(source="assessment_problems", many=True, read_only=True)
    course_name = serializers.CharField(source="course.course_name", read_only=True)

    class Meta:
        model = CodingAssessment
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "course",
            "course_name",
            "duration_minutes",
            "passing_percentage",
            "problems",
            "start_time",
            "end_time",
            "is_active",
            "created_at",
        ]

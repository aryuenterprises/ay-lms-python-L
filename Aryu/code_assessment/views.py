"""
REST API ViewSets and endpoints for Online Code Assessment.
Directly integrates with the existing aryuapp.Student model.
"""
import logging
from django.db.models import Q
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from .constants import STATUS_QUEUED
from .models import (
    CodingProblem,
    CodingTestCase,
    CodingAssessment,
    CodeSubmission,
    AssessmentAttempt,
)
from .permissions import (
    IsAuthenticatedStudentOrStaff,
    IsSubmissionOwnerOrStaff,
    IsAdminOrStaff,
    resolve_authenticated_student,
    is_staff_or_admin_user,
)
from .serializers import (
    CodingProblemListSerializer,
    CodingProblemDetailSerializer,
    CodingProblemAdminSerializer,
    CodingTestCaseAdminSerializer,
    CodingAssessmentListSerializer,
    CodingAssessmentDetailSerializer,
    AssessmentAttemptSerializer,
    CodeRunRequestSerializer,
    CodeSubmissionCreateSerializer,
    CodeSubmissionListSerializer,
    CodeSubmissionDetailSerializer,
)
from .services.execution_service import ExecutionService
from .services.submission_service import SubmissionService
from .services.assessment_service import AssessmentService

logger = logging.getLogger(__name__)


class ProblemViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Public and student API for browsing, testing, and submitting coding problems.
    Hidden test cases are NEVER exposed via this ViewSet.
    """
    lookup_field = "slug"
    lookup_value_regex = "[^/]+"
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = CodingProblem.objects.filter(is_active=True)

        # Filters: difficulty, tag, course
        difficulty = self.request.query_params.get("difficulty")
        if difficulty:
            queryset = queryset.filter(difficulty=difficulty.lower())

        tag = self.request.query_params.get("tag")
        if tag:
            queryset = queryset.filter(tags__contains=[tag])

        course_id = self.request.query_params.get("course_id")
        if course_id:
            queryset = queryset.filter(courses__course_id=course_id)

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(description__icontains=search)
            )

        return queryset.distinct()

    def get_object(self):
        lookup_val = self.kwargs.get(self.lookup_field)
        queryset = self.filter_queryset(self.get_queryset())

        # Allow lookup by integer ID or slug string
        if str(lookup_val).isdigit():
            obj = queryset.filter(Q(id=lookup_val) | Q(slug=lookup_val)).first()
        else:
            obj = queryset.filter(slug=lookup_val).first()

        if not obj:
            from rest_framework.exceptions import NotFound
            raise NotFound("Coding problem not found.")

        self.check_object_permissions(self.request, obj)
        return obj

    def get_serializer_class(self):
        if self.action == "retrieve":
            return CodingProblemDetailSerializer
        return CodingProblemListSerializer

    @action(
        detail=True,
        methods=["post"],
        url_path="run",
        permission_classes=[IsAuthenticatedStudentOrStaff],
    )
    def run_code(self, request, slug=None):
        """
        Executes student code against visible sample test cases or custom input.
        Returns immediate execution feedback. Does NOT alter submission records or problem stats.
        """
        problem = self.get_object()
        serializer = CodeRunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        language = data["language"]
        source_code = data["source_code"]
        custom_input = data.get("custom_input")

        service = ExecutionService()
        result = service.run_sample_code(
            problem=problem,
            language=language,
            source_code=source_code,
            custom_input=custom_input,
        )

        return Response(result, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="submit",
        permission_classes=[IsAuthenticatedStudentOrStaff],
    )
    def submit_solution(self, request, slug=None):
        """
        Submits solution for official evaluation against all test cases.
        Directly links the submission to the authenticated Student model record.
        """
        problem = self.get_object()
        student = resolve_authenticated_student(request)

        if not student and not is_staff_or_admin_user(request.user):
            return Response(
                {"detail": "Authenticated student profile not found. A valid Student record is required to submit solutions."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = CodeSubmissionCreateSerializer(
            data={
                "problem_id": problem.id,
                "assessment_id": request.data.get("assessment_id"),
                "language": request.data.get("language"),
                "source_code": request.data.get("source_code"),
            }
        )
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        assessment = None
        if data.get("assessment_id"):
            assessment = CodingAssessment.objects.filter(
                pk=data["assessment_id"], is_active=True
            ).first()

        submission = SubmissionService.create_submission(
            student=student,
            problem=problem,
            language=data["language"],
            source_code=data["source_code"],
            assessment=assessment,
        )

        return Response(
            {
                "submission_id": submission.id,
                "status": submission.status,
                "student_id": student.student_id if student else None,
                "message": "Submission received and queued for evaluation.",
                "submitted_at": submission.submitted_at,
            },
            status=status.HTTP_201_CREATED,
        )


class SubmissionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for retrieving submissions and polling evaluation results.
    Strict IDOR protection: Students can ONLY view their own submissions.
    """
    permission_classes = [IsAuthenticatedStudentOrStaff, IsSubmissionOwnerOrStaff]

    def get_queryset(self):
        # Staff can view all submissions; students only their own
        if is_staff_or_admin_user(self.request.user):
            queryset = CodeSubmission.objects.all()
        else:
            student = resolve_authenticated_student(self.request)
            if not student:
                return CodeSubmission.objects.none()
            queryset = CodeSubmission.objects.filter(student=student)

        problem_id = self.request.query_params.get("problem_id")
        if problem_id:
            queryset = queryset.filter(problem_id=problem_id)

        assessment_id = self.request.query_params.get("assessment_id")
        if assessment_id:
            queryset = queryset.filter(assessment_id=assessment_id)

        return queryset.select_related("student", "problem", "assessment").prefetch_related("test_case_results")

    def get_serializer_class(self):
        if self.action == "retrieve" or self.action == "result":
            return CodeSubmissionDetailSerializer
        return CodeSubmissionListSerializer

    @action(detail=True, methods=["get"], url_path="result")
    def result(self, request, pk=None):
        """
        Endpoint for polling submission status and retrieving the detailed test results.
        """
        submission = self.get_object()
        serializer = CodeSubmissionDetailSerializer(
            submission, context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class AssessmentViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for listing and retrieving coding assessments.
    """
    lookup_field = "slug"
    lookup_value_regex = "[^/]+"
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = CodingAssessment.objects.filter(is_active=True)

        course_id = self.request.query_params.get("course_id")
        if course_id:
            queryset = queryset.filter(course__course_id=course_id)

        return queryset.select_related("course").prefetch_related(
            "assessment_problems__problem"
        )

    def get_object(self):
        lookup_val = self.kwargs.get(self.lookup_field)
        queryset = self.filter_queryset(self.get_queryset())

        if str(lookup_val).isdigit():
            obj = queryset.filter(Q(id=lookup_val) | Q(slug=lookup_val)).first()
        else:
            obj = queryset.filter(slug=lookup_val).first()

        if not obj:
            from rest_framework.exceptions import NotFound
            raise NotFound("Assessment not found.")

        self.check_object_permissions(self.request, obj)
        return obj

    def get_serializer_class(self):
        if self.action == "retrieve":
            return CodingAssessmentDetailSerializer
        return CodingAssessmentListSerializer

    @action(
        detail=True,
        methods=["get"],
        url_path="summary",
        permission_classes=[IsAuthenticatedStudentOrStaff],
    )
    def student_summary(self, request, slug=None):
        """
        Returns student's progress and aggregate score on this assessment.
        """
        assessment = self.get_object()
        student = resolve_authenticated_student(request)

        if not student:
            return Response(
                {"detail": "Authenticated student profile not found."},
                status=status.HTTP_403_FORBIDDEN,
            )

        summary = AssessmentService.get_assessment_summary(
            assessment=assessment,
            student=student,
        )
        return Response(summary, status=status.HTTP_200_OK)


# =============================================================================
# ADMIN / INSTRUCTOR VIEWSETS
# =============================================================================

class AdminProblemViewSet(viewsets.ModelViewSet):
    """
    Full administrative CRUD for Coding Problems.
    """
    queryset = CodingProblem.objects.all().prefetch_related("test_cases")
    serializer_class = CodingProblemAdminSerializer
    permission_classes = [IsAdminOrStaff]


class AdminTestCaseViewSet(viewsets.ModelViewSet):
    """
    Administrative CRUD for test cases (including hidden test cases).
    """
    queryset = CodingTestCase.objects.all().select_related("problem")
    serializer_class = CodingTestCaseAdminSerializer
    permission_classes = [IsAdminOrStaff]

    def get_queryset(self):
        qs = super().get_queryset()
        problem_id = self.request.query_params.get("problem_id")
        if problem_id:
            qs = qs.filter(problem_id=problem_id)
        return qs


class AdminAssessmentViewSet(viewsets.ModelViewSet):
    """
    Administrative CRUD for Coding Assessments.
    """
    queryset = CodingAssessment.objects.all().prefetch_related("assessment_problems__problem")
    serializer_class = CodingAssessmentDetailSerializer
    permission_classes = [IsAdminOrStaff]

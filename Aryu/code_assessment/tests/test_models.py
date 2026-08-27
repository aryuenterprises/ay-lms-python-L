"""
Unit tests for Code Assessment models with direct aryuapp.Student relationships.
"""
from django.test import TestCase
from aryuapp.models import Student
from ..models import (
    CodingProblem,
    CodingTestCase,
    CodingAssessment,
    AssessmentProblem,
    AssessmentAttempt,
    CodeSubmission,
    SubmissionTestCaseResult,
)
from ..constants import (
    DIFFICULTY_EASY,
    LANGUAGE_PYTHON,
    LANGUAGE_JAVASCRIPT,
    STATUS_QUEUED,
    STATUS_ACCEPTED,
)


def create_test_student(first_name="Test", last_name="Student", email="student@example.com", username="teststudent"):
    return Student.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        username=username,
        contact_no="9876543210",
        current_address="123 Test St",
        permanent_address="123 Test St",
        city="Chennai",
        state="Tamil Nadu",
        country="India",
        converter="test",
    )


class CodeAssessmentModelsTestCase(TestCase):
    """
    Tests model instantiation, validation, properties, and constraints.
    """

    def setUp(self):
        self.student = create_test_student()
        self.problem = CodingProblem.objects.create(
            title="Two Sum Problem",
            description="Given an array of integers, return indices of the two numbers such that they add up to a target.",
            difficulty=DIFFICULTY_EASY,
            constraints="2 <= nums.length <= 10^4",
            input_format="Line 1: space-separated integers\nLine 2: target integer",
            output_format="Space-separated indices",
            time_limit_ms=2000,
            memory_limit_mb=128,
            supported_languages=[LANGUAGE_PYTHON, LANGUAGE_JAVASCRIPT],
            starter_code={
                LANGUAGE_PYTHON: "def two_sum(nums, target):\n    pass\n",
            },
            tags=["array", "hash-table"],
        )

    def test_problem_creation_and_auto_slug(self):
        """Verify problem is created with automated slug and default values."""
        self.assertEqual(self.problem.slug, "two-sum-problem")
        self.assertEqual(self.problem.difficulty, DIFFICULTY_EASY)
        self.assertTrue(self.problem.is_active)
        self.assertEqual(self.problem.total_submissions_count, 0)
        self.assertEqual(self.problem.acceptance_rate, 0.0)

    def test_problem_acceptance_rate_calculation(self):
        """Verify acceptance rate percentage property."""
        self.problem.total_submissions_count = 10
        self.problem.accepted_submissions_count = 7
        self.problem.save()
        self.assertEqual(self.problem.acceptance_rate, 70.0)

    def test_submission_directly_references_existing_student(self):
        """Verify CodeSubmission directly references aryuapp.Student and has no redundant info fields."""
        sub = CodeSubmission.objects.create(
            student=self.student,
            problem=self.problem,
            language=LANGUAGE_PYTHON,
            source_code="print('0 1')",
            status=STATUS_QUEUED,
        )
        self.assertEqual(sub.student, self.student)
        self.assertEqual(sub.student_id, self.student.student_id)
        self.assertEqual(sub.student.email, "student@example.com")
        self.assertFalse(hasattr(sub, "student_name"))
        self.assertFalse(hasattr(sub, "student_email"))

    def test_assessment_attempt_directly_references_existing_student(self):
        """Verify AssessmentAttempt directly references aryuapp.Student."""
        assessment = CodingAssessment.objects.create(
            title="Full Stack Coding Assessment",
            duration_minutes=60,
            passing_percentage=60.00,
        )
        attempt = AssessmentAttempt.objects.create(
            student=self.student,
            assessment=assessment,
            score=80.00,
            is_passed=True,
            is_completed=True,
        )
        self.assertEqual(attempt.student, self.student)
        self.assertEqual(attempt.assessment, assessment)
        self.assertTrue(attempt.is_passed)

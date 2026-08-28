"""
Tests for Submissions list, detail, and result polling endpoints using existing Student model.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from aryuapp.models import Student
from ..models import (
    CodingProblem,
    CodingTestCase,
    CodeSubmission,
)
from ..constants import (
    DIFFICULTY_EASY,
    LANGUAGE_PYTHON,
    STATUS_ACCEPTED,
)
from ..services.execution_service import ExecutionService

User = get_user_model()


def create_test_student(first_name="Alice", last_name="Student", email="alice@aryu.com", username="student_alice"):
    student = Student.objects.create(
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
    user = User.objects.create_user(
        username=username,
        email=email,
        password="Password123!",
    )
    return student, user


class SubmissionAPITestCase(TestCase):
    """
    Tests submission tracking, evaluation, and result status serialization with Student model.
    """

    def setUp(self):
        self.client = APIClient()
        self.student, self.user = create_test_student()
        self.client.force_authenticate(user=self.user)

        self.problem = CodingProblem.objects.create(
            title="Sum Array",
            description="Sum all numbers in the array.",
            difficulty=DIFFICULTY_EASY,
            supported_languages=[LANGUAGE_PYTHON],
            is_active=True,
        )

        # Sample test case
        self.tc1 = CodingTestCase.objects.create(
            problem=self.problem,
            input_data="1 2 3",
            expected_output="6",
            is_sample=True,
            is_hidden=False,
            order=1,
        )

        # Hidden test case
        self.tc2 = CodingTestCase.objects.create(
            problem=self.problem,
            input_data="10 20 30 40",
            expected_output="100",
            is_sample=False,
            is_hidden=True,
            order=2,
        )

    def test_submission_evaluation_and_result_polling(self):
        """Verify complete evaluation and result retrieval referencing Student."""
        sub = CodeSubmission.objects.create(
            student=self.student,
            problem=self.problem,
            language=LANGUAGE_PYTHON,
            source_code="import sys\nnums = [int(x) for x in sys.stdin.read().split()]\nprint(sum(nums))",
        )

        # Evaluate submission via ExecutionService
        service = ExecutionService()
        evaluated_sub = service.evaluate_submission(sub.id)

        self.assertEqual(evaluated_sub.status, STATUS_ACCEPTED)
        self.assertEqual(evaluated_sub.score, 100.00)
        self.assertEqual(evaluated_sub.passed_test_cases, 2)
        self.assertEqual(evaluated_sub.total_test_cases, 2)

        # Poll result via API
        response = self.client.get(f"/api/code-assessment/submissions/{sub.id}/result/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], STATUS_ACCEPTED)
        self.assertEqual(response.data["student_id"], self.student.student_id)
        self.assertEqual(response.data["student_email"], self.student.email)

        # Verify hidden test case output is redacted for students
        results = response.data["test_case_results"]
        self.assertEqual(len(results), 2)
        hidden_res = [r for r in results if not r["is_sample"]][0]
        self.assertEqual(hidden_res["stdout"], "")
        self.assertEqual(hidden_res["stderr"], "")

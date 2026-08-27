"""
API tests for Problem list, detail, run code, and submit solution endpoints with existing Student integration.
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
    DIFFICULTY_MEDIUM,
    DIFFICULTY_HARD,
    LANGUAGE_PYTHON,
    LANGUAGE_JAVASCRIPT,
)

User = get_user_model()


def create_test_student(first_name="Coder", last_name="Student", email="coder@example.com", username="coder_student"):
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


class ProblemAPITestCase(TestCase):
    """
    Tests problem browsing, sample code execution, and solution submission endpoints.
    """

    def setUp(self):
        self.client = APIClient()
        self.student, self.user = create_test_student()
        self.client.force_authenticate(user=self.user)

        # Create problems
        self.prob_easy = CodingProblem.objects.create(
            title="Two Sum",
            description="Find indices of two numbers that add up to target.",
            difficulty=DIFFICULTY_EASY,
            supported_languages=[LANGUAGE_PYTHON, LANGUAGE_JAVASCRIPT],
            tags=["array", "math"],
            is_active=True,
        )

        self.prob_hard = CodingProblem.objects.create(
            title="Median of Two Sorted Arrays",
            description="Find the median of two sorted arrays in O(log(m+n)).",
            difficulty=DIFFICULTY_HARD,
            supported_languages=[LANGUAGE_PYTHON],
            tags=["array", "binary-search"],
            is_active=True,
        )

        # Sample test case
        self.sample_tc = CodingTestCase.objects.create(
            problem=self.prob_easy,
            input_data="2 7 11 15\n9",
            expected_output="0 1",
            is_sample=True,
            is_hidden=False,
            explanation="2 + 7 = 9",
            order=1,
        )

        # Hidden test case (NEVER exposed to students)
        self.hidden_tc = CodingTestCase.objects.create(
            problem=self.prob_easy,
            input_data="3 2 4\n6",
            expected_output="1 2",
            is_sample=False,
            is_hidden=True,
            order=2,
        )

    def test_list_problems_returns_only_active_problems(self):
        """Verify list endpoint returns active problems."""
        response = self.client.get("/api/code-assessment/problems/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 2)

    def test_retrieve_problem_detail_hides_hidden_test_cases(self):
        """CRITICAL: Problem detail MUST NOT return hidden test cases in API payload."""
        response = self.client.get(f"/api/code-assessment/problems/{self.prob_easy.slug}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        sample_cases = response.data.get("sample_test_cases", [])
        self.assertEqual(len(sample_cases), 1)
        self.assertEqual(sample_cases[0]["input_data"], "2 7 11 15\n9")

        # Confirm hidden test case content is absent from response
        self.assertNotIn("3 2 4", str(response.data))

    def test_run_code_against_sample_cases(self):
        """Verify POST /run/ executes against sample cases and returns output."""
        payload = {
            "language": LANGUAGE_PYTHON,
            "source_code": "print('0 1')",
        }
        response = self.client.post(
            f"/api/code-assessment/problems/{self.prob_easy.slug}/run/",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertTrue(response.data["results"][0]["passed"])

    def test_submit_solution_links_to_authenticated_student(self):
        """Verify POST /submit/ queues submission and binds directly to Student record."""
        payload = {
            "language": LANGUAGE_PYTHON,
            "source_code": "print('TWO_SUM')",
        }
        response = self.client.post(
            f"/api/code-assessment/problems/{self.prob_easy.slug}/submit/",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("submission_id", response.data)

        submission_id = response.data["submission_id"]
        sub = CodeSubmission.objects.get(pk=submission_id)
        self.assertEqual(sub.student, self.student)
        self.assertEqual(sub.student_id, self.student.student_id)

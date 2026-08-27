"""
Security tests for Code Assessment module.
Validates sandbox defenses, boundary constraints, and isolation against malicious payloads.
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
    MAX_SOURCE_CODE_BYTES,
    MAX_STDIN_BYTES,
)

User = get_user_model()


def create_test_student():
    student = Student.objects.create(
        first_name="Security",
        last_name="Tester",
        email="security_tester@aryu.com",
        username="sec_tester",
        contact_no="9876543210",
        current_address="123 Test St",
        permanent_address="123 Test St",
        city="Chennai",
        state="Tamil Nadu",
        country="India",
        converter="test",
    )
    user = User.objects.create_user(
        username="sec_tester",
        email="security_tester@aryu.com",
        password="StrongPassword123!",
    )
    return student, user


class CodeAssessmentSecurityTestCase(TestCase):
    """
    Security test suite covering malicious inputs, resource limits, and data leakage defense with Student model.
    """

    def setUp(self):
        self.client = APIClient()
        self.student, self.user = create_test_student()
        self.client.force_authenticate(user=self.user)

        self.problem = CodingProblem.objects.create(
            title="Secure Vault Problem",
            difficulty=DIFFICULTY_EASY,
            supported_languages=[LANGUAGE_PYTHON],
            is_active=True,
        )

        # Sample test case
        self.sample_tc = CodingTestCase.objects.create(
            problem=self.problem,
            input_data="public_input_1",
            expected_output="public_output_1",
            is_sample=True,
            is_hidden=False,
            order=1,
        )

        # Secret hidden test case
        self.hidden_tc = CodingTestCase.objects.create(
            problem=self.problem,
            input_data="TOP_SECRET_HIDDEN_INPUT_9988",
            expected_output="TOP_SECRET_HIDDEN_OUTPUT_9988",
            is_sample=False,
            is_hidden=True,
            order=2,
        )

    def test_hidden_test_cases_never_leaked_in_problem_detail(self):
        """CRITICAL: Hidden test inputs/outputs must NEVER appear in public problem APIs."""
        response = self.client.get(f"/api/code-assessment/problems/{self.problem.slug}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_str = str(response.content)
        self.assertIn("public_input_1", response_str)
        self.assertNotIn("TOP_SECRET_HIDDEN_INPUT_9988", response_str)
        self.assertNotIn("TOP_SECRET_HIDDEN_OUTPUT_9988", response_str)

    def test_no_duplicate_student_fields_on_models(self):
        """Verify models do not have redundant student_name, student_email, or student_phone fields."""
        self.assertFalse(hasattr(CodeSubmission, "student_name"))
        self.assertFalse(hasattr(CodeSubmission, "student_email"))
        self.assertFalse(hasattr(CodeSubmission, "student_phone"))
        self.assertTrue(hasattr(CodeSubmission, "student"))

    def test_oversized_source_code_rejected_at_api_boundary(self):
        """Verify payloads exceeding MAX_SOURCE_CODE_BYTES are rejected before reaching runner."""
        huge_code = "print('hello')\n" + ("# filler\n" * 10000)
        self.assertGreater(len(huge_code.encode("utf-8")), MAX_SOURCE_CODE_BYTES)

        payload = {
            "language": LANGUAGE_PYTHON,
            "source_code": huge_code,
        }

        # Test on /run/
        run_resp = self.client.post(
            f"/api/code-assessment/problems/{self.problem.slug}/run/",
            data=payload,
            format="json",
        )
        self.assertEqual(run_resp.status_code, status.HTTP_400_BAD_REQUEST)

        # Test on /submit/
        sub_resp = self.client.post(
            f"/api/code-assessment/problems/{self.problem.slug}/submit/",
            data=payload,
            format="json",
        )
        self.assertEqual(sub_resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oversized_stdin_rejected_at_api_boundary(self):
        """Verify custom inputs exceeding MAX_STDIN_BYTES are rejected."""
        huge_input = "A" * (MAX_STDIN_BYTES + 1000)

        payload = {
            "language": LANGUAGE_PYTHON,
            "source_code": "print('hello')",
            "custom_input": huge_input,
        }

        response = self.client.post(
            f"/api/code-assessment/problems/{self.problem.slug}/run/",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unsupported_language_rejected(self):
        """Verify arbitrary/unsupported language identifiers are rejected."""
        payload = {
            "language": "malicious_bash_script",
            "source_code": "rm -rf /",
        }

        response = self.client.post(
            f"/api/code-assessment/problems/{self.problem.slug}/run/",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_client_cannot_inject_authoritative_score_or_status(self):
        """Verify client cannot specify their own score or accepted status."""
        payload = {
            "language": LANGUAGE_PYTHON,
            "source_code": "print('hacked')",
            "status": "accepted",
            "score": 100.0,
            "passed_test_cases": 999,
        }

        response = self.client.post(
            f"/api/code-assessment/problems/{self.problem.slug}/submit/",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        sub_id = response.data["submission_id"]
        sub = CodeSubmission.objects.get(pk=sub_id)

        # Server-side model must NOT use client-supplied score or accepted status
        self.assertNotEqual(sub.status, "accepted")
        self.assertEqual(float(sub.score), 0.0)

    def test_malicious_source_code_handled_without_application_compromise(self):
        """Verify malicious exploration attempts (env, files, sockets) do not crash Django."""
        attack_payloads = [
            "import os\nprint(os.environ)",
            "import socket\ns = socket.socket()\ns.connect(('127.0.0.1', 5432))",
            "with open('/etc/passwd') as f: print(f.read())",
            "import subprocess\nsubprocess.run(['cat', '.env'])",
        ]

        for attack_code in attack_payloads:
            response = self.client.post(
                f"/api/code-assessment/problems/{self.problem.slug}/run/",
                data={
                    "language": LANGUAGE_PYTHON,
                    "source_code": attack_code,
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(response.data["success"])

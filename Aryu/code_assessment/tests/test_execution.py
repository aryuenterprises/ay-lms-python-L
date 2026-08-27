"""
Unit tests for code execution service, runner abstractions, and output comparison logic.
"""
from django.test import TestCase
from aryuapp.models import Student
from ..models import CodingProblem, CodingTestCase, CodeSubmission
from ..constants import (
    DIFFICULTY_EASY,
    LANGUAGE_PYTHON,
    STATUS_ACCEPTED,
    STATUS_WRONG_ANSWER,
    STATUS_COMPILE_ERROR,
    STATUS_RUNTIME_ERROR,
    STATUS_TIME_LIMIT_EXCEEDED,
    STATUS_MEMORY_LIMIT_EXCEEDED,
)
from ..services.execution_service import (
    ExecutionService,
    normalize_output,
    compare_outputs,
)
from ..services.runners.mock_runner import MockCodeRunner


def create_test_student():
    return Student.objects.create(
        first_name="Exec",
        last_name="Tester",
        email="exec_tester@example.com",
        username="exec_tester",
        contact_no="9876543210",
        current_address="123 Test St",
        permanent_address="123 Test St",
        city="Chennai",
        state="Tamil Nadu",
        country="India",
        converter="test",
    )


class ExecutionServiceTestCase(TestCase):
    """
    Tests output normalizer, comparison algorithms, and execution service flows with Student model.
    """

    def setUp(self):
        self.student = create_test_student()
        self.problem = CodingProblem.objects.create(
            title="Palindrome Check",
            difficulty=DIFFICULTY_EASY,
            supported_languages=[LANGUAGE_PYTHON],
            time_limit_ms=2000,
            memory_limit_mb=128,
            is_active=True,
        )

        CodingTestCase.objects.create(
            problem=self.problem,
            input_data="racecar",
            expected_output="true",
            is_sample=True,
            is_hidden=False,
            order=1,
        )

        CodingTestCase.objects.create(
            problem=self.problem,
            input_data="hello",
            expected_output="false",
            is_sample=False,
            is_hidden=True,
            order=2,
        )

    def test_output_normalization_and_comparison(self):
        """Verify deterministic output comparison with trailing whitespace and CRLF."""
        self.assertTrue(compare_outputs("true", "true"))
        self.assertTrue(compare_outputs("true   \r\n\n", "true"))
        self.assertTrue(compare_outputs("line1  \r\nline2  \r\n", "line1\nline2"))
        self.assertFalse(compare_outputs("true", "false"))

    def test_evaluate_successful_submission(self):
        """Verify successful full evaluation across public and hidden test cases."""
        sub = CodeSubmission.objects.create(
            student=self.student,
            problem=self.problem,
            language=LANGUAGE_PYTHON,
            source_code="print('PALINDROME')",
        )

        service = ExecutionService(runner=MockCodeRunner())
        evaluated = service.evaluate_submission(sub.id)

        self.assertEqual(evaluated.status, STATUS_ACCEPTED)
        self.assertEqual(evaluated.score, 100.00)
        self.assertEqual(evaluated.passed_test_cases, 2)
        self.assertEqual(evaluated.total_test_cases, 2)

        # Confirm problem counters updated
        self.problem.refresh_from_db()
        self.assertEqual(self.problem.total_submissions_count, 1)
        self.assertEqual(self.problem.accepted_submissions_count, 1)

    def test_evaluate_compile_error_submission(self):
        """Verify compile errors halt test case execution and mark submission status."""
        sub = CodeSubmission.objects.create(
            student=self.student,
            problem=self.problem,
            language=LANGUAGE_PYTHON,
            source_code="def broken( SIMULATE_COMPILE_ERROR",
        )

        service = ExecutionService(runner=MockCodeRunner())
        evaluated = service.evaluate_submission(sub.id)

        self.assertEqual(evaluated.status, STATUS_COMPILE_ERROR)
        self.assertEqual(evaluated.score, 0.00)
        self.assertIn("SyntaxError", evaluated.compile_output)

    def test_evaluate_runtime_error_submission(self):
        """Verify runtime errors are recorded without breaking the system."""
        sub = CodeSubmission.objects.create(
            student=self.student,
            problem=self.problem,
            language=LANGUAGE_PYTHON,
            source_code="1 / 0  # SIMULATE_RUNTIME_ERROR",
        )

        service = ExecutionService(runner=MockCodeRunner())
        evaluated = service.evaluate_submission(sub.id)

        self.assertEqual(evaluated.status, STATUS_RUNTIME_ERROR)
        self.assertEqual(evaluated.score, 0.00)

    def test_evaluate_timeout_submission(self):
        """Verify time limit exceeded is captured accurately."""
        sub = CodeSubmission.objects.create(
            student=self.student,
            problem=self.problem,
            language=LANGUAGE_PYTHON,
            source_code="while True: pass  # SIMULATE_TIMEOUT",
        )

        service = ExecutionService(runner=MockCodeRunner())
        evaluated = service.evaluate_submission(sub.id)

        self.assertEqual(evaluated.status, STATUS_TIME_LIMIT_EXCEEDED)

"""
Execution and evaluation service for coding problems and submissions.
"""
import logging
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from .runners import (
    BaseCodeRunner,
    MockCodeRunner,
    IsolatedRunnerClient,
    DockerSandboxRunner,
)
from ..constants import (
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_COMPLETED,
    STATUS_ACCEPTED,
    STATUS_WRONG_ANSWER,
    STATUS_COMPILE_ERROR,
    STATUS_RUNTIME_ERROR,
    STATUS_TIME_LIMIT_EXCEEDED,
    STATUS_MEMORY_LIMIT_EXCEEDED,
    STATUS_SYSTEM_ERROR,
    MAX_STDOUT_BYTES,
    MAX_STDERR_BYTES,
)
from ..models import (
    CodingProblem,
    CodingTestCase,
    CodeSubmission,
    SubmissionTestCaseResult,
)

logger = logging.getLogger(__name__)


def get_default_runner() -> BaseCodeRunner:
    """
    Factory function returning the configured code execution runner.
    """
    backend = getattr(settings, "CODE_RUNNER_BACKEND", "mock").lower()

    if backend == "isolated" or getattr(settings, "CODE_RUNNER_ENDPOINT", None):
        return IsolatedRunnerClient()
    elif backend == "docker":
        return DockerSandboxRunner()
    return MockCodeRunner()


def normalize_output(text: str) -> str:
    """
    Normalizes program output for deterministic comparison:
    - Normalizes CRLF to LF
    - Strips trailing whitespace per line
    - Strips leading/trailing newlines
    """
    if text is None:
        return ""
    lines = [line.rstrip() for line in str(text).replace("\r\n", "\n").split("\n")]
    # Remove empty trailing lines
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines).strip()


def compare_outputs(actual: str, expected: str) -> bool:
    """
    Compares normalized actual output with expected test case output.
    """
    return normalize_output(actual) == normalize_output(expected)


def sanitize_output(text: str, max_bytes: int = MAX_STDOUT_BYTES) -> str:
    """
    Truncates output safely to prevent JSON payload explosions.
    """
    if not text:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return f"{truncated}\n... [Output truncated: exceeded {max_bytes} bytes]"
    return text


class ExecutionService:
    """
    Service coordinating code execution, testing, and submission scoring.
    """

    def __init__(self, runner: BaseCodeRunner = None):
        self.runner = runner or get_default_runner()

    def run_sample_code(
        self,
        problem: CodingProblem,
        language: str,
        source_code: str,
        custom_input: str = None,
    ) -> dict:
        """
        Executes code against visible sample test cases or custom user input.
        Does NOT expose or run hidden test cases.
        """
        time_limit_ms = problem.time_limit_ms
        memory_limit_mb = problem.memory_limit_mb

        if custom_input is not None:
            # Custom input run
            result = self.runner.execute(
                source_code=source_code,
                language=language,
                stdin=custom_input,
                time_limit_ms=time_limit_ms,
                memory_limit_mb=memory_limit_mb,
            )

            return {
                "success": True,
                "is_custom_input": True,
                "status": result.status,
                "stdout": sanitize_output(result.stdout),
                "stderr": sanitize_output(result.stderr, MAX_STDERR_BYTES),
                "compile_output": sanitize_output(result.compile_output),
                "execution_time_ms": result.time_ms,
                "memory_used_kb": result.memory_kb,
                "error_message": result.error_message,
            }

        # Run against all sample test cases for the problem
        sample_cases = problem.test_cases.filter(is_sample=True).order_by("order", "id")

        if not sample_cases.exists():
            # If no sample test cases defined, run with empty stdin
            result = self.runner.execute(
                source_code=source_code,
                language=language,
                stdin="",
                time_limit_ms=time_limit_ms,
                memory_limit_mb=memory_limit_mb,
            )
            return {
                "success": True,
                "is_custom_input": False,
                "status": result.status,
                "results": [
                    {
                        "test_case_id": None,
                        "status": result.status,
                        "passed": result.status == STATUS_COMPLETED,
                        "input": "",
                        "expected_output": "",
                        "stdout": sanitize_output(result.stdout),
                        "stderr": sanitize_output(result.stderr, MAX_STDERR_BYTES),
                        "compile_output": sanitize_output(result.compile_output),
                        "execution_time_ms": result.time_ms,
                    }
                ],
            }

        case_results = []
        all_passed = True
        overall_status = STATUS_COMPLETED

        for tc in sample_cases:
            result = self.runner.execute(
                source_code=source_code,
                language=language,
                stdin=tc.input_data,
                time_limit_ms=time_limit_ms,
                memory_limit_mb=memory_limit_mb,
            )

            if result.status == STATUS_COMPILE_ERROR:
                return {
                    "success": True,
                    "status": STATUS_COMPILE_ERROR,
                    "compile_output": sanitize_output(result.compile_output),
                    "results": [],
                }

            passed = (
                result.status == STATUS_COMPLETED
                and compare_outputs(result.stdout, tc.expected_output)
            )

            tc_status = STATUS_ACCEPTED if passed else (
                result.status if result.status != STATUS_COMPLETED else STATUS_WRONG_ANSWER
            )

            if not passed:
                all_passed = False
                if overall_status == STATUS_COMPLETED:
                    overall_status = tc_status

            case_results.append({
                "test_case_id": tc.id,
                "order": tc.order,
                "status": tc_status,
                "passed": passed,
                "input": tc.input_data,
                "expected_output": tc.expected_output,
                "stdout": sanitize_output(result.stdout),
                "stderr": sanitize_output(result.stderr, MAX_STDERR_BYTES),
                "execution_time_ms": result.time_ms,
                "explanation": tc.explanation,
            })

        return {
            "success": True,
            "status": STATUS_ACCEPTED if all_passed else overall_status,
            "results": case_results,
        }

    def evaluate_submission(self, submission_id: int) -> CodeSubmission:
        """
        Full evaluation of an official code submission against all test cases (sample + hidden).
        Calculates final score and updates problem statistics.
        """
        try:
            submission = CodeSubmission.objects.select_related("problem").get(pk=submission_id)
        except CodeSubmission.DoesNotExist:
            logger.error("Submission %s not found for evaluation", submission_id)
            return None

        problem = submission.problem
        test_cases = problem.test_cases.all().order_by("order", "id")
        total_cases = test_cases.count()

        submission.status = STATUS_RUNNING
        submission.total_test_cases = total_cases
        submission.save(update_fields=["status", "total_test_cases"])

        if total_cases == 0:
            submission.status = STATUS_ACCEPTED
            submission.score = 100.00
            submission.passed_test_cases = 0
            submission.completed_at = timezone.now()
            submission.save()
            return submission

        passed_count = 0
        peak_time_ms = 0
        peak_memory_kb = 0
        first_failure_status = None
        first_failure_msg = ""
        compile_output = ""

        results_to_create = []

        for tc in test_cases:
            result = self.runner.execute(
                source_code=submission.source_code,
                language=submission.language,
                stdin=tc.input_data,
                time_limit_ms=problem.time_limit_ms,
                memory_limit_mb=problem.memory_limit_mb,
            )

            peak_time_ms = max(peak_time_ms, result.time_ms)
            peak_memory_kb = max(peak_memory_kb, result.memory_kb)

            if result.status == STATUS_COMPILE_ERROR:
                compile_output = result.compile_output
                first_failure_status = STATUS_COMPILE_ERROR
                first_failure_msg = "Compilation failed."

                results_to_create.append(
                    SubmissionTestCaseResult(
                        submission=submission,
                        test_case=tc,
                        status=STATUS_COMPILE_ERROR,
                        execution_time_ms=result.time_ms,
                        memory_used_kb=result.memory_kb,
                        error_message="Compile Error",
                    )
                )
                break

            is_correct = (
                result.status == STATUS_COMPLETED
                and compare_outputs(result.stdout, tc.expected_output)
            )

            if is_correct:
                case_status = STATUS_ACCEPTED
                passed_count += 1
            else:
                case_status = (
                    result.status if result.status != STATUS_COMPLETED else STATUS_WRONG_ANSWER
                )
                if not first_failure_status:
                    first_failure_status = case_status
                    first_failure_msg = result.error_message or (
                        "Wrong Answer" if case_status == STATUS_WRONG_ANSWER else case_status
                    )

            # Security: For hidden test cases, DO NOT store student stdout/stdin in result
            # Only store stdout for sample test cases
            stdout_to_store = sanitize_output(result.stdout) if tc.is_sample else ""
            stderr_to_store = sanitize_output(result.stderr, MAX_STDERR_BYTES) if tc.is_sample else ""

            results_to_create.append(
                SubmissionTestCaseResult(
                    submission=submission,
                    test_case=tc,
                    status=case_status,
                    execution_time_ms=result.time_ms,
                    memory_used_kb=result.memory_kb,
                    stdout=stdout_to_store,
                    stderr=stderr_to_store,
                    error_message=result.error_message,
                )
            )

        # Bulk create test case results
        SubmissionTestCaseResult.objects.bulk_create(results_to_create)

        # Finalize submission status and score
        final_score = round((passed_count / total_cases) * 100.0, 2)
        if passed_count == total_cases:
            final_status = STATUS_ACCEPTED
        else:
            final_status = first_failure_status or STATUS_WRONG_ANSWER

        with transaction.atomic():
            submission.status = final_status
            submission.score = final_score
            submission.passed_test_cases = passed_count
            submission.execution_time_ms = peak_time_ms
            submission.memory_used_kb = peak_memory_kb
            submission.compile_output = sanitize_output(compile_output)
            submission.error_message = first_failure_msg
            submission.completed_at = timezone.now()
            submission.save()

            # Atomically update problem counts
            CodingProblem.objects.filter(pk=problem.pk).update(
                total_submissions_count=F("total_submissions_count") + 1,
                accepted_submissions_count=F("accepted_submissions_count") + (1 if final_status == STATUS_ACCEPTED else 0),
            )

        logger.info(
            "Submission #%s evaluated: status=%s, score=%s, passed=%s/%s",
            submission.id, final_status, final_score, passed_count, total_cases
        )

        return submission

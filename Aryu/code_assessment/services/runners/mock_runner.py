"""
Mock code execution runner for deterministic testing and environments without Docker/Judge0.
Does not execute untrusted student code directly.
"""
from .base import BaseCodeRunner, ExecutionResult
from ...constants import (
    STATUS_COMPLETED,
    STATUS_COMPILE_ERROR,
    STATUS_RUNTIME_ERROR,
    STATUS_TIME_LIMIT_EXCEEDED,
    STATUS_MEMORY_LIMIT_EXCEEDED,
)


class MockCodeRunner(BaseCodeRunner):
    """
    Mock runner that simulates execution outputs based on deterministic input cues
    or simple mock responses without running untrusted code in Django.
    """

    def __init__(self, default_stdout: str = None, default_status: str = STATUS_COMPLETED):
        self.default_stdout = default_stdout
        self.default_status = default_status

    def execute(
        self,
        source_code: str,
        language: str,
        stdin: str = "",
        time_limit_ms: int = 2000,
        memory_limit_mb: int = 128,
    ) -> ExecutionResult:
        # Simulation hooks for testing various runner outcomes
        code_str = source_code.strip()

        if "SIMULATE_COMPILE_ERROR" in code_str:
            return ExecutionResult(
                status=STATUS_COMPILE_ERROR,
                compile_output="SyntaxError: invalid syntax (simulated)",
                exit_code=1,
            )

        if "SIMULATE_RUNTIME_ERROR" in code_str:
            return ExecutionResult(
                status=STATUS_RUNTIME_ERROR,
                stderr="ZeroDivisionError: division by zero (simulated)",
                exit_code=1,
            )

        if "SIMULATE_TIMEOUT" in code_str:
            return ExecutionResult(
                status=STATUS_TIME_LIMIT_EXCEEDED,
                time_ms=time_limit_ms + 100,
                error_message="Time Limit Exceeded",
            )

        if "SIMULATE_MEMORY_LIMIT" in code_str:
            return ExecutionResult(
                status=STATUS_MEMORY_LIMIT_EXCEEDED,
                memory_kb=(memory_limit_mb + 10) * 1024,
                error_message="Memory Limit Exceeded",
            )

        # Echo or mock stdout
        if self.default_stdout is not None:
            stdout = self.default_stdout
        elif "TWO_SUM" in code_str or "two_sum" in code_str or "print('0 1')" in code_str or 'print("0 1")' in code_str:
            # Common demo logic for test cases
            if "2 7 11 15" in stdin and "9" in stdin:
                stdout = "0 1"
            elif "3 2 4" in stdin and "6" in stdin:
                stdout = "1 2"
            elif "3 3" in stdin and "6" in stdin:
                stdout = "0 1"
            else:
                stdout = "0 1"
        elif "PALINDROME" in code_str or "is_palindrome" in code_str:
            clean = stdin.strip().lower()
            stdout = "true" if clean == clean[::-1] else "false"
        elif "sum(" in code_str or "SUM" in code_str:
            try:
                nums = [int(x) for x in stdin.split()]
                stdout = str(sum(nums))
            except Exception:
                stdout = stdin.strip()
        else:
            stdout = stdin.strip()

        return ExecutionResult(
            status=self.default_status,
            stdout=stdout,
            time_ms=15,
            memory_kb=18240,
            exit_code=0,
        )

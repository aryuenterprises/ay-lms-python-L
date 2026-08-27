"""
Base abstraction for secure code execution runners.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionResult:
    """
    Standardized result data returned by any code execution runner.
    """
    status: str
    stdout: str = ""
    stderr: str = ""
    compile_output: str = ""
    time_ms: int = 0
    memory_kb: int = 0
    exit_code: int = 0
    error_message: str = ""


class BaseCodeRunner(ABC):
    """
    Abstract interface for sandboxed code execution.
    Implementations must guarantee isolation from the host and Django application.
    """

    @abstractmethod
    def execute(
        self,
        source_code: str,
        language: str,
        stdin: str = "",
        time_limit_ms: int = 2000,
        memory_limit_mb: int = 128,
    ) -> ExecutionResult:
        """
        Executes code inside an isolated ephemeral sandbox.

        :param source_code: User-submitted source code
        :param language: Language identifier (python, javascript, java, cpp, c)
        :param stdin: Input string for the program
        :param time_limit_ms: Execution timeout in milliseconds
        :param memory_limit_mb: Memory ceiling in megabytes
        :return: ExecutionResult
        """
        pass

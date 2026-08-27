"""
HTTP/RPC client to interact with an isolated remote code runner service (e.g. Judge0 / microservice sandbox).
"""
import logging
import requests
from django.conf import settings
from .base import BaseCodeRunner, ExecutionResult
from ...constants import (
    STATUS_COMPLETED,
    STATUS_COMPILE_ERROR,
    STATUS_RUNTIME_ERROR,
    STATUS_TIME_LIMIT_EXCEEDED,
    STATUS_MEMORY_LIMIT_EXCEEDED,
    STATUS_SYSTEM_ERROR,
    LANGUAGE_PYTHON,
    LANGUAGE_JAVASCRIPT,
    LANGUAGE_JAVA,
    LANGUAGE_CPP,
    LANGUAGE_C,
)

logger = logging.getLogger(__name__)

# Judge0 language ID mappings
JUDGE0_LANGUAGE_MAP = {
    LANGUAGE_PYTHON: 71,       # Python 3.8.1+
    LANGUAGE_JAVASCRIPT: 63,   # JavaScript (Node.js 12.14.0+)
    LANGUAGE_JAVA: 62,         # Java (OpenJDK 13.0.1+)
    LANGUAGE_CPP: 54,          # C++ (GCC 9.2.0)
    LANGUAGE_C: 50,            # C (GCC 9.2.0)
}


class IsolatedRunnerClient(BaseCodeRunner):
    """
    Communicates with a dedicated sandboxed execution service via authenticated HTTP.
    Ensures Django never executes untrusted code locally.
    """

    def __init__(self, endpoint_url: str = None, auth_token: str = None, timeout_seconds: int = 15):
        self.endpoint_url = (
            endpoint_url
            or getattr(settings, "CODE_RUNNER_ENDPOINT", "http://127.0.0.1:2358")
        ).rstrip("/")
        self.auth_token = auth_token or getattr(settings, "CODE_RUNNER_AUTH_TOKEN", "")
        self.timeout_seconds = timeout_seconds

    def execute(
        self,
        source_code: str,
        language: str,
        stdin: str = "",
        time_limit_ms: int = 2000,
        memory_limit_mb: int = 128,
    ) -> ExecutionResult:
        """
        Sends code execution request to the isolated runner microservice.
        """
        headers = {
            "Content-Type": "application/json",
        }
        if self.auth_token:
            headers["X-Auth-Token"] = self.auth_token

        # Judge0 submission format
        lang_id = JUDGE0_LANGUAGE_MAP.get(language, 71)
        payload = {
            "source_code": source_code,
            "language_id": lang_id,
            "stdin": stdin,
            "cpu_time_limit": round(time_limit_ms / 1000.0, 2),
            "memory_limit": memory_limit_mb * 1024,  # KB
        }

        try:
            url = f"{self.endpoint_url}/submissions?wait=true"
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout_seconds)

            if response.status_code not in (200, 201):
                logger.error("Runner API returned error: %s - %s", response.status_code, response.text)
                return ExecutionResult(
                    status=STATUS_SYSTEM_ERROR,
                    error_message=f"Runner returned status code {response.status_code}",
                )

            data = response.json()
            status_id = data.get("status", {}).get("id")

            # Judge0 status mappings:
            # 3: Accepted, 4: Wrong Answer, 5: Time Limit Exceeded, 6: Compilation Error,
            # 7-12: Runtime Errors, 13: Internal Error, 14: Exec Format Error
            if status_id == 6:
                return ExecutionResult(
                    status=STATUS_COMPILE_ERROR,
                    compile_output=data.get("compile_output") or "",
                    exit_code=data.get("exit_code") or 1,
                )
            elif status_id == 5:
                return ExecutionResult(
                    status=STATUS_TIME_LIMIT_EXCEEDED,
                    time_ms=int(float(data.get("time") or 0) * 1000),
                    error_message="Time Limit Exceeded",
                )
            elif status_id in (7, 8, 9, 10, 11, 12):
                return ExecutionResult(
                    status=STATUS_RUNTIME_ERROR,
                    stderr=data.get("stderr") or "",
                    error_message=data.get("status", {}).get("description", "Runtime Error"),
                    exit_code=data.get("exit_code") or 1,
                )

            time_ms = int(float(data.get("time") or 0) * 1000)
            memory_kb = int(data.get("memory") or 0)

            return ExecutionResult(
                status=STATUS_COMPLETED,
                stdout=data.get("stdout") or "",
                stderr=data.get("stderr") or "",
                time_ms=time_ms,
                memory_kb=memory_kb,
                exit_code=data.get("exit_code") or 0,
            )

        except requests.exceptions.Timeout:
            logger.error("IsolatedRunnerClient timed out contacting runner at %s", self.endpoint_url)
            return ExecutionResult(
                status=STATUS_TIME_LIMIT_EXCEEDED,
                error_message="Runner connection timed out",
            )
        except Exception as exc:
            logger.error("IsolatedRunnerClient request failed: %s", exc)
            return ExecutionResult(
                status=STATUS_SYSTEM_ERROR,
                error_message="Could not communicate with code runner service",
            )

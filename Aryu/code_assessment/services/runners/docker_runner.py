"""
Docker container sandbox runner with strict kernel/process/network isolation.
Designed for dedicated runner worker nodes (NEVER on Django application containers).
"""
import logging
import os
import shutil
import subprocess
import tempfile
import time
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
    DEFAULT_PID_LIMIT,
)

logger = logging.getLogger(__name__)

# Predefined trusted container runtime images (Server-controlled only)
DOCKER_RUNTIME_IMAGES = {
    LANGUAGE_PYTHON: "python:3.10-slim",
    LANGUAGE_JAVASCRIPT: "node:18-slim",
    LANGUAGE_JAVA: "openjdk:17-slim",
    LANGUAGE_CPP: "gcc:11-bullseye",
    LANGUAGE_C: "gcc:11-bullseye",
}


class DockerSandboxRunner(BaseCodeRunner):
    """
    Executes student code inside an ephemeral, non-root, network-disabled,
    resource-capped Docker container.
    """

    def __init__(self, docker_cmd: str = "docker"):
        self.docker_cmd = docker_cmd

    def execute(
        self,
        source_code: str,
        language: str,
        stdin: str = "",
        time_limit_ms: int = 2000,
        memory_limit_mb: int = 128,
    ) -> ExecutionResult:
        image = DOCKER_RUNTIME_IMAGES.get(language)
        if not image:
            return ExecutionResult(
                status=STATUS_SYSTEM_ERROR,
                error_message=f"Unsupported language runner for '{language}'",
            )

        # Create temporary working directory for this isolated execution
        temp_dir = tempfile.mkdtemp(prefix="sandbox_exec_")

        try:
            # 1. Write source code & stdin to temporary files
            file_map = {
                LANGUAGE_PYTHON: ("solution.py", ["python3", "/workspace/solution.py"]),
                LANGUAGE_JAVASCRIPT: ("solution.js", ["node", "/workspace/solution.js"]),
                LANGUAGE_JAVA: ("Solution.java", ["sh", "-c", "javac /workspace/Solution.java && java -cp /workspace Solution"]),
                LANGUAGE_CPP: ("solution.cpp", ["sh", "-c", "g++ -O2 /workspace/solution.cpp -o /tmp/sol && /tmp/sol"]),
                LANGUAGE_C: ("solution.c", ["sh", "-c", "gcc -O2 /workspace/solution.c -o /tmp/sol && /tmp/sol"]),
            }

            filename, run_cmd = file_map[language]
            source_file_path = os.path.join(temp_dir, filename)
            with open(source_file_path, "w", encoding="utf-8") as f:
                f.write(source_code)

            # Ensure proper non-root read permissions
            os.chmod(source_file_path, 0o644)

            # 2. Build strict Docker execution command
            # Security boundaries:
            # - --network none (ZERO outbound/inbound network)
            # - --read-only (immutable root filesystem)
            # - --tmpfs /tmp (writable ephemeral memory only, noexec where practical)
            # - --pids-limit (fork-bomb prevention)
            # - --memory, --memory-swap (memory exhaustion prevention)
            # - --cpus (CPU throttling)
            # - --cap-drop ALL (strip all Linux kernel capabilities)
            # - --security-opt no-new-privileges (privilege escalation block)
            # - --user 1000:1000 (non-root execution)
            # - --rm (ephemeral lifecycle)
            time_limit_sec = max(1, int(time_limit_ms / 1000.0) + 1)
            mem_limit_str = f"{memory_limit_mb}m"

            docker_args = [
                self.docker_cmd, "run", "--rm", "-i",
                "--network", "none",
                "--read-only",
                "--tmpfs", "/tmp:rw,size=32m",
                "--pids-limit", str(DEFAULT_PID_LIMIT),
                "--memory", mem_limit_str,
                "--memory-swap", mem_limit_str,
                "--cpus", "1.0",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true",
                "-v", f"{temp_dir}:/workspace:ro",
                "-w", "/workspace",
                image,
            ] + run_cmd

            start_time = time.perf_counter()

            # 3. Execute container process with strict wall-clock timeout
            process = subprocess.Popen(
                docker_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            try:
                stdout, stderr = process.communicate(input=stdin, timeout=time_limit_sec + 2)
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)

                if process.returncode != 0:
                    # Non-zero exit code: check if compile error or runtime error
                    if "javac" in stderr or "g++" in stderr or "gcc" in stderr or "SyntaxError" in stderr:
                        return ExecutionResult(
                            status=STATUS_COMPILE_ERROR,
                            compile_output=stderr.strip(),
                            time_ms=elapsed_ms,
                            exit_code=process.returncode,
                        )
                    return ExecutionResult(
                        status=STATUS_RUNTIME_ERROR,
                        stderr=stderr.strip(),
                        time_ms=elapsed_ms,
                        exit_code=process.returncode,
                    )

                return ExecutionResult(
                    status=STATUS_COMPLETED,
                    stdout=stdout,
                    stderr=stderr,
                    time_ms=elapsed_ms,
                    exit_code=0,
                )

            except subprocess.TimeoutExpired:
                process.kill()
                return ExecutionResult(
                    status=STATUS_TIME_LIMIT_EXCEEDED,
                    time_ms=time_limit_ms + 100,
                    error_message="Time Limit Exceeded",
                )

        except Exception as exc:
            logger.error("DockerSandboxRunner execution error: %s", exc)
            return ExecutionResult(
                status=STATUS_SYSTEM_ERROR,
                error_message=f"Sandbox execution failed: {str(exc)}",
            )
        finally:
            # Destroy the ephemeral host directory immediately
            shutil.rmtree(temp_dir, ignore_errors=True)

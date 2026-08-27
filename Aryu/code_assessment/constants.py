"""
Constants, choices, and configuration limits for Code Assessment module.
"""

# Difficulty choices
DIFFICULTY_EASY = "easy"
DIFFICULTY_MEDIUM = "medium"
DIFFICULTY_HARD = "hard"

DIFFICULTY_CHOICES = [
    (DIFFICULTY_EASY, "Easy"),
    (DIFFICULTY_MEDIUM, "Medium"),
    (DIFFICULTY_HARD, "Hard"),
]

# Supported programming languages
LANGUAGE_PYTHON = "python"
LANGUAGE_JAVASCRIPT = "javascript"
LANGUAGE_JAVA = "java"
LANGUAGE_CPP = "cpp"
LANGUAGE_C = "c"

SUPPORTED_LANGUAGES = [
    LANGUAGE_PYTHON,
    LANGUAGE_JAVASCRIPT,
    LANGUAGE_JAVA,
    LANGUAGE_CPP,
    LANGUAGE_C,
]

LANGUAGE_CHOICES = [
    (LANGUAGE_PYTHON, "Python 3"),
    (LANGUAGE_JAVASCRIPT, "JavaScript (Node.js)"),
    (LANGUAGE_JAVA, "Java (OpenJDK)"),
    (LANGUAGE_CPP, "C++ (GCC)"),
    (LANGUAGE_C, "C (GCC)"),
]

# Language Metadata & Configurations
LANGUAGE_CONFIG = {
    LANGUAGE_PYTHON: {
        "display_name": "Python 3",
        "version": "3.10",
        "file_name": "solution.py",
        "default_time_limit_ms": 2000,
        "default_memory_limit_mb": 128,
        "starter_code": (
            "import sys\n\n"
            "def solve():\n"
            "    # Read input from stdin\n"
            "    lines = sys.stdin.read().splitlines()\n"
            "    if not lines:\n"
            "        return\n"
            "    # Write your solution here\n"
            "    print(lines[0])\n\n"
            "if __name__ == '__main__':\n"
            "    solve()\n"
        ),
    },
    LANGUAGE_JAVASCRIPT: {
        "display_name": "JavaScript (Node.js)",
        "version": "18.x",
        "file_name": "solution.js",
        "default_time_limit_ms": 2000,
        "default_memory_limit_mb": 128,
        "starter_code": (
            "const fs = require('fs');\n\n"
            "function solve() {\n"
            "    const input = fs.readFileSync('/dev/stdin', 'utf-8').trim();\n"
            "    if (!input) return;\n"
            "    // Write your solution here\n"
            "    console.log(input);\n"
            "}\n\n"
            "solve();\n"
        ),
    },
    LANGUAGE_JAVA: {
        "display_name": "Java (OpenJDK)",
        "version": "17",
        "file_name": "Solution.java",
        "default_time_limit_ms": 3000,
        "default_memory_limit_mb": 256,
        "starter_code": (
            "import java.util.Scanner;\n\n"
            "public class Solution {\n"
            "    public static void main(String[] args) {\n"
            "        Scanner scanner = new Scanner(System.in);\n"
            "        if (scanner.hasNext()) {\n"
            "            String line = scanner.nextLine();\n"
            "            System.out.println(line);\n"
            "        }\n"
            "    }\n"
            "}\n"
        ),
    },
    LANGUAGE_CPP: {
        "display_name": "C++ (GCC)",
        "version": "11.x",
        "file_name": "solution.cpp",
        "default_time_limit_ms": 1500,
        "default_memory_limit_mb": 128,
        "starter_code": (
            "#include <iostream>\n"
            "#include <string>\n\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    ios_base::sync_with_stdio(false);\n"
            "    cin.tie(NULL);\n"
            "    string line;\n"
            "    if (getline(cin, line)) {\n"
            "        cout << line << \"\\n\";\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        ),
    },
    LANGUAGE_C: {
        "display_name": "C (GCC)",
        "version": "11.x",
        "file_name": "solution.c",
        "default_time_limit_ms": 1500,
        "default_memory_limit_mb": 128,
        "starter_code": (
            "#include <stdio.h>\n"
            "#include <string.h>\n\n"
            "int main() {\n"
            "    char buffer[1024];\n"
            "    if (fgets(buffer, sizeof(buffer), stdin)) {\n"
            "        printf(\"%s\", buffer);\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        ),
    },
}

# Submission / Execution Statuses
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_ACCEPTED = "accepted"
STATUS_WRONG_ANSWER = "wrong_answer"
STATUS_COMPILE_ERROR = "compile_error"
STATUS_RUNTIME_ERROR = "runtime_error"
STATUS_TIME_LIMIT_EXCEEDED = "time_limit_exceeded"
STATUS_MEMORY_LIMIT_EXCEEDED = "memory_limit_exceeded"
STATUS_OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
STATUS_SYSTEM_ERROR = "system_error"
STATUS_CANCELLED = "cancelled"

SUBMISSION_STATUS_CHOICES = [
    (STATUS_QUEUED, "Queued"),
    (STATUS_RUNNING, "Running"),
    (STATUS_COMPLETED, "Completed"),
    (STATUS_ACCEPTED, "Accepted"),
    (STATUS_WRONG_ANSWER, "Wrong Answer"),
    (STATUS_COMPILE_ERROR, "Compile Error"),
    (STATUS_RUNTIME_ERROR, "Runtime Error"),
    (STATUS_TIME_LIMIT_EXCEEDED, "Time Limit Exceeded"),
    (STATUS_MEMORY_LIMIT_EXCEEDED, "Memory Limit Exceeded"),
    (STATUS_OUTPUT_LIMIT_EXCEEDED, "Output Limit Exceeded"),
    (STATUS_SYSTEM_ERROR, "System Error"),
    (STATUS_CANCELLED, "Cancelled"),
]

TEST_CASE_STATUS_CHOICES = [
    (STATUS_QUEUED, "Queued"),
    (STATUS_RUNNING, "Running"),
    (STATUS_ACCEPTED, "Accepted"),
    (STATUS_WRONG_ANSWER, "Wrong Answer"),
    (STATUS_TIME_LIMIT_EXCEEDED, "Time Limit Exceeded"),
    (STATUS_MEMORY_LIMIT_EXCEEDED, "Memory Limit Exceeded"),
    (STATUS_RUNTIME_ERROR, "Runtime Error"),
    (STATUS_SYSTEM_ERROR, "System Error"),
]

TERMINAL_STATUSES = {
    STATUS_ACCEPTED,
    STATUS_WRONG_ANSWER,
    STATUS_COMPILE_ERROR,
    STATUS_RUNTIME_ERROR,
    STATUS_TIME_LIMIT_EXCEEDED,
    STATUS_MEMORY_LIMIT_EXCEEDED,
    STATUS_OUTPUT_LIMIT_EXCEEDED,
    STATUS_SYSTEM_ERROR,
    STATUS_CANCELLED,
}

# Security & Resource Limits
MAX_SOURCE_CODE_BYTES = 64 * 1024  # 64 KB
MAX_STDIN_BYTES = 64 * 1024        # 64 KB
MAX_STDOUT_BYTES = 64 * 1024       # 64 KB
MAX_STDERR_BYTES = 16 * 1024       # 16 KB

DEFAULT_TIME_LIMIT_MS = 2000       # 2000 ms = 2.0s
MIN_TIME_LIMIT_MS = 100            # 100 ms
MAX_TIME_LIMIT_MS = 10000          # 10000 ms = 10.0s

DEFAULT_MEMORY_LIMIT_MB = 128      # 128 MB
MIN_MEMORY_LIMIT_MB = 16           # 16 MB
MAX_MEMORY_LIMIT_MB = 512          # 512 MB

DEFAULT_PID_LIMIT = 64             # Max concurrent processes per sandbox

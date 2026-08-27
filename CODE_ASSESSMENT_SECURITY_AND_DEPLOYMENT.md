# Online Code Assessment — Sandbox Security & Production Deployment Guide

> **Scope**: Security Architecture, Kernel/Container Isolation, Threat Model, and Production Deployment  
> **Module Name**: `code_assessment`  
> **Classification**: Security-Critical Arbitrary-Code Execution Boundary

---

## 1. Executive Security Architecture

When building an online judge platform, student-submitted source code must be treated as **actively hostile**. Malicious actors may attempt:
- Extracting database credentials or Django environment variables (`os.environ`).
- Reading host files (`/etc/passwd`, `.env`, SSH keys, source code).
- Opening outbound network sockets or scanning internal VPC IPs (`127.0.0.1`, `169.254.169.254`, `10.0.0.0/8`).
- Launching fork bombs or consuming 100% CPU/RAM to cause Denial of Service.
- Mounting or hijacking the Docker daemon socket (`/var/run/docker.sock`).

To defeat these threats, the `code_assessment` system implements a **multi-layered defense-in-depth isolation boundary**:

```text
                       [ CLIENT INTERNET ]
                                |
                                v
                      [ Django REST API ]
                   (Validates payload, JWT,
                    enforces limits, creates DB record)
                                |
                                v
                     [ Celery / Redis Queue ]
                                |
                                v
               [ Dedicated Runner Microservice / Node ]
                     (Judge0 / Isolated Runner)
                                |
                                v
           +---------------------------------------------+
           |       EPHEMERAL ROOTLESS DOCKER SANDBOX     |
           |---------------------------------------------|
           |  • Network: DISABLED (--network none)       |
           |  • User: Non-Root (UID 1000:1000)           |
           |  • Root FS: Read-Only (--read-only)         |
           |  • Tmpfs: 32MB max (--tmpfs /tmp)           |
           |  • PIDs Limit: 64 (--pids-limit 64)         |
           |  • Memory: 128MB ceiling (--memory 128m)    |
           |  • CPU: 1.0 core quota (--cpus 1.0)         |
           |  • Capabilities: Dropped ALL (--cap-drop)   |
           |  • Privileges: No-New-Privileges            |
           |  • Zero Host Mounts / No Docker Socket      |
           |  • Zero Django Secrets / Clean Environment  |
           +---------------------------------------------+
                                |
                                v
                [ Output Sanitizer & Validator ]
                                |
                                v
                     [ Stored in PostgreSQL ]
```

---

## 2. Kernel & Sandbox Security Controls

### 2.1 Complete Network Isolation (`--network none`)
- All sandbox containers run with `--network none`.
- Inbound and outbound sockets are completely disabled by the Linux kernel network namespace.
- Attempts to connect to `127.0.0.1`, `localhost`, AWS metadata `169.254.169.254`, or internal PostgreSQL / Redis instances are rejected immediately at the socket layer (`Network is unreachable`).

### 2.2 Read-Only Root Filesystem (`--read-only`)
- The base container image is mounted as immutable read-only.
- Students cannot modify system binaries, install packages (`pip`, `apt`, `npm`), or leave persistent backdoor files.
- Ephemeral execution files are written only to a strictly bounded temporary directory (`/tmpfs /tmp:rw,size=32m`), which is wiped upon container termination.

### 2.3 Dropped Linux Capabilities (`--cap-drop ALL`)
- All Linux kernel capabilities (including `CAP_SYS_ADMIN`, `CAP_NET_RAW`, `CAP_SETUID`, `CAP_PTRACE`) are stripped.
- `--security-opt no-new-privileges:true` prevents setuid binaries from gaining elevated privileges.

### 2.4 Process Limit & Fork Bomb Defense (`--pids-limit 64`)
- Hard limit of 64 processes/threads per sandbox container.
- Recursive process spawning (such as `:(){ :|:& };:`) hits the kernel PID ceiling and terminates harmlessly without starving the host OS.

### 2.5 Strict Resource Ceilings
| Resource | Default | Configurable Range | Enforcement Mechanism |
| :--- | :--- | :--- | :--- |
| **CPU Time** | 2000 ms (2.0s) | 100 ms – 10000 ms | `cgroups cpu.cfs_quota_us` + process alarm timeout |
| **Memory** | 128 MB | 16 MB – 512 MB | `cgroups memory.limit_in_bytes` + memory swap disabled |
| **PIDs / Threads** | 64 | Fixed | `cgroups pids.max` |
| **Source Code Size** | 64 KB | Fixed | Django REST API Validator |
| **Input (stdin) Size**| 64 KB | Fixed | Django REST API Validator |
| **Output (stdout)** | 64 KB | Fixed | Output Truncation Sanitizer |
| **Diagnostic (stderr)**| 16 KB | Fixed | Output Truncation Sanitizer |

### 2.6 Zero Secrets & Clean Environment
- Sandboxes are launched with an empty environment dictionary (`env -i`).
- `SECRET_KEY`, `DATABASE_URL`, `DB_PASSWORD`, AWS keys, Razorpay keys, and SMTP credentials are **never injected** into the sandbox container.

---

## 3. Production Deployment Architecture

In production, the Code Execution Runner should be deployed on **isolated runner worker nodes** separated from the Django API application tier.

### 3.1 Architecture Overview

```text
[ Web Tier / API Gateway ]
       ↓
[ Django REST API ] ---- (Sends Jobs) ----> [ Celery / Redis Queue ]
                                                  ↓
                                      [ Dedicated Runner Node ]
                                      (Isolated VM with Docker/Judge0)
                                                  ↓
                                         [ Rootless Container ]
```

### 3.2 Setting up Dedicated Judge0 Runner (Recommended)

1. **Provision a Dedicated VM** (e.g. Ubuntu 22.04 LTS on AWS EC2 `c6i.xlarge` or GCP `c2-standard-4`).
2. **Install Judge0 via Docker Compose**:
   ```bash
   git clone https://github.com/judge0/judge0.git
   cd judge0
   # Configure judge0.conf with an authentication token
   echo "AUTH_TOKEN=your_secure_runner_secret_token" >> judge0.conf
   docker compose up -d
   ```
3. **Configure Django Production Settings (`Aryu/Aryu/settings.py`)**:
   ```python
   # Code Assessment Sandbox Runner Configuration
   CODE_RUNNER_BACKEND = "isolated"
   CODE_RUNNER_ENDPOINT = "http://runner-internal.aryuprojects.com:2358"
   CODE_RUNNER_AUTH_TOKEN = os.getenv("CODE_RUNNER_AUTH_TOKEN", "your_secure_runner_secret_token")
   ```

### 3.3 Celery Worker Scaling

To handle concurrent student submissions during peak examination windows:
```bash
# Start Celery worker dedicated to code assessment
celery -A Aryu worker -Q code_assessment,celery -c 8 --loglevel=INFO
```

---

## 4. Operational Monitoring & Observability

Monitor the following key metrics in production:
1. **Queue Latency**: Time spent by submissions in `queued` status before runner execution.
2. **Execution Duration**: 95th percentile sandbox execution time.
3. **Status Distribution**: Ratio of `accepted` vs `wrong_answer`, `compile_error`, `runtime_error`, `time_limit_exceeded`.
4. **Runner Availability**: Uptime of the `IsolatedRunnerClient` endpoint.
5. **System Error Rate**: Any occurrences of `STATUS_SYSTEM_ERROR` should trigger automated alerts.

---

## 5. Security Checklist Summary

- [x] Django request thread never executes arbitrary user code (`exec` / `eval` prohibited).
- [x] Ephemeral rootless containers with `--network none`.
- [x] Memory limit, CPU limit, PID limit, and wall-clock timeout enforced.
- [x] Read-only root filesystem with dropped Linux capabilities.
- [x] No application secrets or database access inside sandboxes.
- [x] No Docker socket (`/var/run/docker.sock`) mounted into student environments.
- [x] Hidden test cases strictly protected and excluded from student API responses.
- [x] IDOR defense: Students can only view their own submissions.
- [x] Payload size limits enforced at the DRF serializer boundary.

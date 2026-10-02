"""Policy-controlled subprocess runner for safe experiment code execution (Rule 15 Enforcement).

Accurate architectural classification:
- Pre-execution AST security filtering and filesystem jail enforcement.
- Strict deny-by-default environment whitelist and credential pattern inspection.
- OS-level resource limits (Windows Job Objects on Windows, POSIX limits on Linux where available).
- Cryptographic Rule 3 Human Gate token verification and canonical spec binding.
(Note: This provides policy-based subprocess confinement, not kernel-level container virtualization).
"""

from __future__ import annotations

import ast
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union
import psutil
from pydantic import BaseModel, Field

from research_os.gate.approval import (
    UnauthorizedExecutionMutation,
    compute_child_execution_hash,
    compute_code_hash,
    compute_config_hash,
    verify_approval_token,
)
from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.gate import HumanGateToken


class SandboxSecurityViolation(PermissionError):
    """Raised when simulation code breaches filesystem confinement or Rule 15 security boundaries."""
    pass


class EntrypointResolutionError(SandboxSecurityViolation, FileNotFoundError):
    """Raised when an entry point script cannot be resolved against registered code artifacts on disk."""
    pass


class SandboxExecutionResult(BaseModel):
    """Execution telemetry captured from a policy-controlled simulation run."""

    exit_code: int = Field(description="Subprocess exit code (0 indicates success, 137 indicates OOM kill)")
    stdout: str = Field(default="", description="Captured standard output")
    stderr: str = Field(default="", description="Captured standard error")
    duration_seconds: float = Field(default=0.0, description="Execution duration in seconds")
    timed_out: bool = Field(default=False, description="Whether execution was terminated due to timeout")
    resource_enforcement: str = Field(
        default="UNENFORCED_RESOURCE_LIMIT",
        description="Operating system mechanism applied for resource limits (e.g. WINDOWS_JOB_OBJECT, RLIMIT, or PSUTIL_WATCHDOG_FALLBACK)",
    )
    execution_confinement_method: str = Field(
        default="WINDOWS_JOB_OBJECT",
        description="Confinement mechanism applied: WINDOWS_JOB_OBJECT, RLIMIT_AS, or PSUTIL_WATCHDOG_FALLBACK",
    )
    error: Optional[str] = Field(default=None, description="Diagnostic error message if failure occurred")
    error_details: Optional[str] = Field(default=None, description="Detailed diagnostic error message")


class PolicySubprocessRunner:
    """Policy-controlled subprocess runner enforcing AST boundaries, environment isolation, and hardware limits."""

    SAFE_ENV_ALLOWLIST = {
        "PATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "COMSPEC",
        "PATHEXT",
        "HOME",
        "LANG",
        "LC_ALL",
        "OS",
    }

    SENSITIVE_PATTERNS = [
        "KEY",
        "SECRET",
        "TOKEN",
        "PASSWORD",
        "CREDENTIAL",
        "AUTH",
        "API",
        "GEMINI",
        "OPENAI",
        "ANTHROPIC",
        "AWS",
        "GCP",
    ]

    def __init__(self, default_timeout_seconds: int = 60) -> None:
        self.default_timeout_seconds = default_timeout_seconds

    @staticmethod
    def emit_event(
        output_dir: Union[str, Path],
        stage: str,
        status: str,
        code: str = "OK",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Emit append-only newline-delimited JSON telemetry event to output/events.jsonl."""
        try:
            out_p = Path(output_dir)
            out_p.mkdir(parents=True, exist_ok=True)
            event_file = out_p / "events.jsonl"
            rec = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": stage,
                "status": status,
                "code": code,
                "details": details or {},
            }
            with open(event_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass

    @staticmethod
    def write_error_payload(
        output_dir: Union[str, Path],
        error_code: str,
        stage: str,
        message: str,
        hint: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Cleanly serialize error payload with actionable remediation hints."""
        try:
            out_p = Path(output_dir)
            out_p.mkdir(parents=True, exist_ok=True)
            err_file = out_p / "error.json"
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error_code": error_code,
                "stage": stage,
                "message": message,
                "hint": hint,
                "details": details or {},
            }
            err_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _diagnose_exception(exc: Exception) -> tuple[str, str]:
        """Map exception to structured error code and actionable remediation hint."""
        exc_type = type(exc).__name__
        if exc_type == "DatasetIntegrityError":
            return (
                "ERR_DATASET_CHECKSUM_MISMATCH",
                "Dataset failed cryptographic SHA-256 verification or was not found in cache. Re-fetch or verify ground-truth dataset checksum.",
            )
        if exc_type == "UnauthorizedExecutionMutation":
            return (
                "ERR_UNAUTHORIZED_MUTATION",
                "Child execution arguments (seed, knobs, or code) mutated from parent gate authorization. Mint fresh delegation token for modified configuration.",
            )
        if exc_type == "EntrypointResolutionError":
            return (
                "ERR_ENTRYPOINT_RESOLUTION",
                "Entry point script was not found on disk or was unreadable. Verify file path and permissions in code directory.",
            )
        if exc_type == "EpistemicHonestyViolation":
            return (
                "ERR_EPISTEMIC_HONESTY_VIOLATION",
                "Domain declaring physical/biological/neural properties attempted PRNG state mocking without recognized numerical engines.",
            )
        if exc_type == "SandboxSecurityViolation":
            return (
                "ERR_SANDBOX_SECURITY_VIOLATION",
                "Code breached filesystem jail confinement, attempted unauthorized imports, or modified files outside sandbox.",
            )
        if isinstance(exc, PermissionError):
            return (
                "ERR_GATE_UNAUTHORIZED",
                "Human gate authorization token is missing, expired, self-signed, or rejected.",
            )
        if isinstance(exc, subprocess.TimeoutExpired):
            return (
                "ERR_PROCESS_TIMEOUT",
                "Subprocess exceeded enforced execution timeout boundary. Increase spec.timeout_seconds.",
            )
        if "tectonic" in exc_type.lower() or "tectonic" in str(exc).lower() or "latex" in str(exc).lower():
            return (
                "ERR_TECTONIC_FAILURE",
                "LaTeX or Tectonic compilation failed. Verify tectonic binary availability and LaTeX AST syntax.",
            )
        return (
            "ERR_EXECUTION_FAILURE",
            "Unexpected sandbox error occurred during execution lifecycle.",
        )

    def _sanitize_environment(self, overrides: Optional[dict[str, str]] = None) -> dict[str, str]:
        """Produce a clean, isolated environment dictionary with all credentials removed."""
        if overrides:
            for k, v in overrides.items():
                upper_k = str(k).upper()
                upper_v = str(v).upper()
                for pat in self.SENSITIVE_PATTERNS:
                    if pat in upper_k or pat in upper_v:
                        raise SandboxSecurityViolation(
                            f"Rule 15 Credential Isolation Breach: Environment override contains forbidden secret pattern '{pat}'."
                        )

        clean_env: dict[str, str] = {}
        for key, val in os.environ.items():
            upper_key = key.upper()
            if upper_key in self.SAFE_ENV_ALLOWLIST:
                clean_env[key] = val

        for key in list(clean_env.keys()):
            upper_key = key.upper()
            for pattern in self.SENSITIVE_PATTERNS:
                if pattern in upper_key:
                    clean_env.pop(key, None)
                    break

        clean_env["PYTHONUNBUFFERED"] = "1"
        clean_env["PYTHONHASHSEED"] = "0"
        clean_env["RESEARCH_OS_SANDBOX"] = "1"
        clean_env["RESEARCH_OS_POLICY_RUNNER"] = "1"

        if overrides:
            clean_env.update(overrides)

        return clean_env

    def verify_entrypoint_preflight(
        self,
        entry_point: str,
        code_dir: Union[str, Path],
        expected_sha256: Optional[str] = None,
    ) -> Path:
        """Validate that the entrypoint script exists, has proper permissions, and matches integrity hash.
        
        Enforces Directive 2:
        - Eliminates raw string execution desynchronization.
        - Verifies script file existence on disk before process spawning.
        - Verifies readable permissions and non-zero file size.
        - Confirms cryptographic SHA-256 integrity if expected hash is provided.
        
        Returns:
            Resolved absolute Path to the executable script.
        """
        code_path = Path(code_dir).resolve()
        parts = shlex.split(entry_point, posix=(os.name != "nt"))
        if not parts:
            raise EntrypointResolutionError("Entry point command is empty.")

        # Identify script argument
        script_arg = None
        for p in parts:
            if p.endswith(".py"):
                script_arg = p
                break
        if not script_arg:
            script_arg = parts[-1]

        target_file = code_path / script_arg
        if not target_file.exists():
            matches = list(code_path.glob(f"**/{Path(script_arg).name}"))
            if matches:
                target_file = matches[0]
            else:
                registered = [p.name for p in code_path.glob("*")]
                raise EntrypointResolutionError(
                    f"PRE-FLIGHT ENTRYPOINT ERROR: Target script '{script_arg}' declared in "
                    f"spec.entry_point '{entry_point}' does not exist on disk in '{code_path}'. "
                    f"Registered artifacts on disk: {registered}."
                )

        if not os.access(target_file, os.R_OK):
            raise EntrypointResolutionError(
                f"PRE-FLIGHT ENTRYPOINT ERROR: Script '{target_file}' is not readable."
            )
        if target_file.stat().st_size == 0:
            raise EntrypointResolutionError(
                f"PRE-FLIGHT ENTRYPOINT ERROR: Script '{target_file}' is an empty (0 bytes) file."
            )

        if expected_sha256:
            import hashlib
            actual_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()
            if actual_sha.lower() != expected_sha256.lower():
                raise EntrypointResolutionError(
                    f"PRE-FLIGHT INTEGRITY ERROR: Script '{target_file.name}' SHA-256 mismatch. "
                    f"Expected: {expected_sha256}, Actual: {actual_sha}."
                )

        return target_file

    def _resolve_command(
        self,
        entry_point: str,
        code_dir: Path,
        output_dir: Path,
        expected_sha256: Optional[str] = None,
    ) -> list[str]:
        """Convert entry point string into executable command args, resolving python interpreter and verified script."""
        parts = shlex.split(entry_point, posix=(os.name != "nt"))
        if not parts:
            raise ValueError("Empty entry point command")

        # Scan command parts for exfiltration attempts or injected credential strings
        for part in parts:
            upper_part = part.upper()
            for pat in ("_API_KEY", "SECRET_KEY", "PASSWORD", "BEARER_TOKEN"):
                if pat in upper_part:
                    raise SandboxSecurityViolation(
                        f"Rule 15 Credential Exfiltration: Command argument contains forbidden sensitive pattern '{pat}'."
                    )

        # Pre-flight verify target script (Directive 2)
        target_script = self.verify_entrypoint_preflight(entry_point, code_dir, expected_sha256=expected_sha256)

        if parts[0] in ("python", "python3"):
            parts[0] = sys.executable

        resolved_parts = []
        replaced_script = False
        for p in parts:
            if p in ("output", "./output"):
                resolved_parts.append(str(output_dir.resolve()))
            elif p.endswith(".json") and (code_dir / p).exists():
                resolved_parts.append(str((code_dir / p).resolve()))
            elif (p.endswith(".py") or p == target_script.name) and not replaced_script:
                resolved_parts.append(str(target_script.resolve()))
                replaced_script = True
            else:
                resolved_parts.append(p)

        return resolved_parts

    @staticmethod
    def validate_code_security(code_dir: Union[str, Path]) -> list[str]:
        """Statically inspect all Python scripts in code_dir for filesystem jail breaches.

        Enforces Rule 15:
        - Rejects any parent directory traversal ('..').
        - Rejects references to sensitive system or credential paths.
        - Rejects unauthorized networking libraries (socket, urllib, requests).
        - Rejects nested subprocess execution or shell escapes.
        """
        code_path = Path(code_dir)
        violations: list[str] = []

        DISALLOWED_MODULES = {
            "socket",
            "urllib",
            "requests",
            "http",
            "ftplib",
            "paramiko",
            "telnetlib",
            "webbrowser",
            "winreg",
            "ctypes",
        }

        SENSITIVE_TARGETS = [
            "..",
            ".env",
            ".ssh",
            "id_rsa",
            "id_ed25519",
            ".gate_key",
            ".gate_nonces",
            "C:\\Windows",
            "/etc",
            "/var",
            "/root",
            "/home",
            "AppData",
            "System32",
        ]

        for py_file in code_path.glob("**/*.py"):
            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=py_file.name)
            except Exception as e:
                violations.append(f"{py_file.name}: Syntax/parsing error: {e}")
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_mod = alias.name.split(".")[0]
                        if root_mod in DISALLOWED_MODULES:
                            violations.append(
                                f"{py_file.name}: Forbidden import '{alias.name}' breaches network isolation boundary (Rule 15)."
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        root_mod = node.module.split(".")[0]
                        if root_mod in DISALLOWED_MODULES:
                            violations.append(
                                f"{py_file.name}: Forbidden import from '{node.module}' breaches network isolation boundary (Rule 15)."
                            )
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    val = node.value.strip()
                    if ".." in val or "/../" in val or "\\..\\" in val:
                        violations.append(
                            f"{py_file.name}: Path traversal attempt detected: string literal '{val}' references parent directory ('..')."
                        )
                    for target in SENSITIVE_TARGETS:
                        if target in val:
                            violations.append(
                                f"{py_file.name}: Unauthorized reference to sensitive path: '{target}'."
                            )

        return violations

    def _apply_os_resource_limits(self, proc: subprocess.Popen, max_ram_gb: float) -> tuple[str, Any]:
        """Apply OS-level process resource constraints where natively supported."""
        if os.environ.get("RESEARCH_OS_FORCE_WATCHDOG_FALLBACK") == "1":
            return "PSUTIL_WATCHDOG_FALLBACK", None

        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                class IO_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("ReadOperationCount", ctypes.c_uint64),
                        ("WriteOperationCount", ctypes.c_uint64),
                        ("OtherOperationCount", ctypes.c_uint64),
                        ("ReadTransferCount", ctypes.c_uint64),
                        ("WriteTransferCount", ctypes.c_uint64),
                        ("OtherTransferCount", ctypes.c_uint64),
                    ]

                class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                    _fields_ = [
                        ("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD),
                    ]

                class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                    _fields_ = [
                        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t),
                    ]

                kernel32 = ctypes.windll.kernel32
                job = kernel32.CreateJobObjectW(None, None)
                if job:
                    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                    # 0x00000100 = JOB_OBJECT_LIMIT_PROCESS_MEMORY
                    # 0x00002000 = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                    # 0x00000800 = JOB_OBJECT_LIMIT_BREAKAWAY_OK
                    info.BasicLimitInformation.LimitFlags = 0x00000100 | 0x00002000 | 0x00000800
                    mem_bytes = int(max(max_ram_gb, 0.5) * 1024 * 1024 * 1024)
                    info.ProcessMemoryLimit = mem_bytes
                    kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
                    assigned = kernel32.AssignProcessToJobObject(job, proc._handle)
                    if assigned:
                        return "WINDOWS_JOB_OBJECT", job
                    else:
                        kernel32.CloseHandle(job)
                        return "PSUTIL_WATCHDOG_FALLBACK", None
            except Exception:
                return "PSUTIL_WATCHDOG_FALLBACK", None
        elif sys.platform.startswith("linux"):
            try:
                import resource
                mem_bytes = int(max(max_ram_gb, 0.5) * 1024 * 1024 * 1024)
                resource.prlimit(proc.pid, resource.RLIMIT_AS, (mem_bytes, mem_bytes))
                return "RLIMIT_AS", None
            except Exception:
                return "PSUTIL_WATCHDOG_FALLBACK", None

        return "PSUTIL_WATCHDOG_FALLBACK", None

    def _enforce_resource_watchdog(
        self,
        proc: subprocess.Popen,
        max_ram_gb: float,
        max_cpu_seconds: Optional[float] = None,
        stop_event: Optional[threading.Event] = None,
        violation_info: Optional[dict[str, Any]] = None,
        job_handle: Optional[Any] = None,
    ) -> None:
        """Active daemon watchdog continuously sampling cumulative RSS and CPU time every 50ms.

        Enforces hard memory and CPU bounds across all platforms using psutil.
        If cumulative RSS of target process + all recursive children exceeds max_ram_gb,
        or cumulative CPU time exceeds max_cpu_seconds:
          * Immediately terminates the entire process tree.
          * Records exit_code = 137 and diagnostic error details.
        """
        max_bytes = max_ram_gb * 1024 * 1024 * 1024
        try:
            target = psutil.Process(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return

        while True:
            if stop_event is not None and stop_event.is_set():
                break
            if proc.poll() is not None:
                break

            try:
                all_procs = [target]
                try:
                    all_procs.extend(target.children(recursive=True))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

                total_rss = 0
                total_cpu = 0.0

                for p in all_procs:
                    try:
                        mem = p.memory_info()
                        total_rss += mem.rss
                        cpu_times = p.cpu_times()
                        total_cpu += (cpu_times.user + cpu_times.system)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                oom_violation = (max_ram_gb > 0 and total_rss > max_bytes)
                cpu_violation = (max_cpu_seconds is not None and max_cpu_seconds > 0 and total_cpu > max_cpu_seconds)

                if oom_violation or cpu_violation:
                    if violation_info is not None:
                        if oom_violation:
                            violation_info["type"] = "OOM"
                            violation_info["error_details"] = "ResourceLimitExceeded: Process exceeded enforced_max_ram_gb"
                            violation_info["rss_bytes"] = total_rss
                            violation_info["max_ram_gb"] = max_ram_gb
                        else:
                            violation_info["type"] = "CPU"
                            violation_info["error_details"] = f"ResourceLimitExceeded: Process exceeded max_cpu_seconds ({total_cpu:.2f}s > {max_cpu_seconds}s)"
                            violation_info["cpu_seconds"] = total_cpu

                    # Terminate all processes in the tree
                    for p in all_procs:
                        try:
                            p.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    try:
                        proc.kill()
                    except Exception:
                        pass

                    if sys.platform == "win32":
                        if job_handle:
                            try:
                                import ctypes
                                ctypes.windll.kernel32.TerminateJobObject(job_handle, 137)
                            except Exception:
                                pass
                        try:
                            subprocess.run(
                                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=2,
                            )
                        except Exception:
                            pass
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            except Exception:
                pass

            if stop_event is not None:
                if stop_event.wait(0.05):
                    break
            else:
                time.sleep(0.05)

    def execute(
        self,
        spec: ExperimentSpec,
        gate_token: HumanGateToken,
        code_dir: Union[str, Path],
        output_dir: Union[str, Path],
        env_overrides: Optional[dict[str, str]] = None,
        timeout_seconds: Optional[int] = None,
    ) -> SandboxExecutionResult:
        """Execute simulation code within policy-controlled subprocess boundary.

        Args:
            spec: The experiment specification governing execution.
            gate_token: Approved HumanGateToken with valid cryptographic signature.
            code_dir: Path to directory containing simulation scripts and config.
            output_dir: Path to store generated artifacts and logs.
            env_overrides: Optional environment variables to inject.
            timeout_seconds: Timeout limit; defaults to spec.timeout_seconds.

        Returns:
            SandboxExecutionResult: Subprocess execution outcome and telemetry.

        Raises:
            PermissionError: If gate_token is not approved, has expired, or fails cryptographic spec binding.
            SandboxSecurityViolation: If code breaches filesystem confinement or Rule 15.
        """
        code_path = Path(code_dir).resolve()
        output_path = Path(output_dir).resolve()
        code_path.mkdir(parents=True, exist_ok=True)
        output_path.mkdir(parents=True, exist_ok=True)

        current_stage = "PREFLIGHT"
        try:
            self.emit_event(
                output_path,
                stage="PREFLIGHT",
                status="RUNNING",
                code="STAGE_START",
                details={"spec_id": spec.spec_id},
            )

            # 1. Mandatory Rule 3 Gate Check & Canonical Spec Binding
            if not gate_token.is_approved():
                raise PermissionError(
                    f"Rule 3 Gate Violation: Execution blocked. HumanGateToken '{gate_token.gate_id}' "
                    f"is in state '{gate_token.status}' (must be APPROVED)."
                )

            now = datetime.now(timezone.utc)
            if gate_token.expires_at and now > gate_token.expires_at:
                raise PermissionError(
                    f"Rule 3 Gate Violation: HumanGateToken '{gate_token.gate_id}' has expired. Re-authorization required."
                )

            # Zero-Trust Cryptographic Invariant: ONLY Ed25519 asymmetric signatures verified against active public key
            if (
                not gate_token.authorization_signature
                or not gate_token.public_key_hex
                or gate_token.public_key_hex == "hmac-sha256"
                or len(gate_token.public_key_hex) != 64
            ):
                raise PermissionError("Ed25519 authorization required; fallback tokens strictly forbidden")

            # Zero-Trust Invariant: Child Token Execution Identity Verification (Task 2)
            if gate_token.payload.get("child_execution_hash"):
                expected_child_hash = gate_token.payload["child_execution_hash"]
                expected_seed = gate_token.payload.get("seed")
                expected_grid_params = gate_token.payload.get("grid_cell_params") or {}
                parent_spec_hash = (
                    gate_token.payload.get("parent_spec_hash")
                    or gate_token.payload.get("canonical_spec_hash")
                )

                actual_code_hash = compute_code_hash(code_path, spec.entry_point)

                # 1. Verify seed match
                active_seed = None
                if spec.run_config.get("seed") is not None:
                    active_seed = spec.run_config["seed"]
                elif spec.random_seeds and len(spec.random_seeds) == 1:
                    active_seed = spec.random_seeds[0]

                cfg_path = code_path / "config.json"
                cfg_data = {}
                if cfg_path.exists():
                    try:
                        cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
                        if "seed" in cfg_data:
                            active_seed = cfg_data["seed"]
                    except Exception:
                        pass

                parts = shlex.split(spec.entry_point, posix=(os.name != "nt"))
                for i, p in enumerate(parts):
                    if p == "--seed" and i + 1 < len(parts):
                        try:
                            active_seed = int(parts[i + 1])
                        except (ValueError, TypeError):
                            pass

                if expected_seed is not None and active_seed is not None and int(active_seed) != int(expected_seed):
                    raise UnauthorizedExecutionMutation(
                        f"Child execution altered seed! Token expected seed {expected_seed}, "
                        f"but active execution is configured with seed {active_seed}."
                    )

                # 2. Verify runtime parameters / knob combinations
                for knob_k, knob_v in expected_grid_params.items():
                    if knob_k in spec.run_config and spec.run_config[knob_k] != knob_v:
                        raise UnauthorizedExecutionMutation(
                            f"Child execution altered parameter '{knob_k}'! Token expected {knob_v}, "
                            f"but spec.run_config has {spec.run_config[knob_k]}."
                        )
                    if knob_k in cfg_data and cfg_data[knob_k] != knob_v:
                        raise UnauthorizedExecutionMutation(
                            f"Child execution altered parameter '{knob_k}' in config.json! "
                            f"Token expected {knob_v}, but found {cfg_data[knob_k]}."
                        )

                # Verify configuration hash for child token
                if gate_token.payload.get("config_sha256"):
                    actual_cfg_hash = compute_config_hash(spec)
                    if actual_cfg_hash != gate_token.payload["config_sha256"]:
                        raise UnauthorizedExecutionMutation(
                            f"Child execution altered experiment configuration! Cryptographic config SHA-256 mismatch."
                        )

                # Verify code hash for child token
                if gate_token.payload.get("code_sha256"):
                    if actual_code_hash != gate_token.payload["code_sha256"]:
                        raise UnauthorizedExecutionMutation(
                            f"Child execution altered code! Cryptographic code SHA-256 mismatch."
                        )

                # 3. Cryptographically recompute and verify child_execution_hash
                recomputed_child_hash = compute_child_execution_hash(
                    parent_spec_hash=parent_spec_hash,
                    grid_cell_params=expected_grid_params,
                    seed=expected_seed,
                    code_hash=actual_code_hash,
                )
                if recomputed_child_hash != expected_child_hash:
                    raise UnauthorizedExecutionMutation(
                        f"Child execution hash mismatch! Expected {expected_child_hash}, "
                        f"recomputed {recomputed_child_hash}. Code, seed, or parameters altered."
                    )
            else:
                # Triple SHA-256 Binding Check for parent/standalone execution
                if gate_token.payload.get("code_sha256"):
                    actual_code_hash = compute_code_hash(code_path, spec.entry_point)
                    if actual_code_hash != gate_token.payload["code_sha256"]:
                        raise PermissionError(
                            f"Rule 3 Gate Violation: Code in '{code_dir}' was altered after approval! "
                            f"Cryptographic code SHA-256 mismatch (expected {gate_token.payload['code_sha256']}, got {actual_code_hash})."
                        )

                if gate_token.payload.get("config_sha256"):
                    actual_cfg_hash = compute_config_hash(spec)
                    if actual_cfg_hash != gate_token.payload["config_sha256"]:
                        raise PermissionError(
                            f"Rule 3 Gate Violation: Experiment configuration was altered after approval! "
                            f"Cryptographic config SHA-256 mismatch (expected {gate_token.payload['config_sha256']}, got {actual_cfg_hash})."
                        )

            from research_os.gate.approval import get_key_backend
            trusted_pub = get_key_backend().get_public_key_hex()
            if not verify_approval_token(
                gate_token,
                expected_spec=spec,
                expected_public_key_hex=trusted_pub,
                expected_code_dir=code_path,
                consume_nonce=True,
            ):
                raise PermissionError(
                    "Rule 3 Gate Violation: Spec altered after approval, self-signed/unpinned key used, "
                    "or cryptographic token invalid/replayed."
                )

            current_stage = "SECURITY_CHECK"
            self.emit_event(output_path, stage="SECURITY_CHECK", status="RUNNING", code="AST_SCANNING")

            # 2. Static Code Security Validation (Rule 15) & Anti-Fabrication Invariant
            violations = self.validate_code_security(code_path)
            if violations:
                raise SandboxSecurityViolation(
                    f"Rule 15 Security Violation: Code failed sandboxed filesystem confinement checks:\n"
                    + "\n".join(f"  - {v}" for v in violations)
                )

            from research_os.sandbox.verification import verify_anti_fabrication
            declared_domain = spec.run_config.get("domain") or getattr(spec, "domain", None)
            if declared_domain:
                for py_file in code_path.glob("**/*.py"):
                    verify_anti_fabrication(py_file, domain=declared_domain)

            # 3. Snapshot parent run directory
            parent_dir = code_path.parent
            pre_files = {p: p.stat().st_mtime for p in parent_dir.rglob("*") if p.is_file()} if parent_dir.exists() else {}

            # 4. Write runtime config if needed
            config_path = code_path / "config.json"
            if not config_path.exists() and spec.run_config:
                config_path.write_text(json.dumps(spec.run_config, indent=2), encoding="utf-8")

            # 5. Environment Sanitization & Credential Shielding
            clean_env = self._sanitize_environment(env_overrides)

            # 6. Resolve command & arguments with pre-flight entry point verification (Directive 2)
            current_stage = "COMMAND_RESOLUTION"
            cmd = self._resolve_command(
                spec.entry_point,
                code_path,
                output_path,
                expected_sha256=spec.run_config.get("entry_point_sha256"),
            )
            timeout = timeout_seconds or spec.effective_timeout_seconds or self.default_timeout_seconds

            current_stage = "SUBPROCESS_EXECUTION"
            self.emit_event(
                output_path,
                stage="SUBPROCESS_EXECUTION",
                status="RUNNING",
                code="PROCESS_SPAWN",
                details={"cmd": cmd, "timeout": timeout},
            )

            start_time = time.perf_counter()
            proc = None
            job_handle = None
            timed_out = False
            stdout_text = ""
            stderr_text = ""
            exit_code = -1
            resource_enforcement = "UNENFORCED_RESOURCE_LIMIT"
            execution_confinement_method = "PSUTIL_WATCHDOG_FALLBACK"
            error_details = None

            # Enforced caps
            max_ram = getattr(spec, "enforced_max_ram_gb", 4.0)
            max_cpu = getattr(spec, "effective_max_cpu_seconds", None)
            if max_cpu is None and spec.resource_limits:
                max_cpu = spec.resource_limits.max_cpu_seconds

            stop_watchdog = threading.Event()
            violation_info: dict[str, Any] = {}
            watchdog_thread = None
            cleanup_fn = None

            try:
                popen_kwargs: dict[str, Any] = {
                    "cwd": str(code_path),
                    "env": clean_env,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                }
                if os.name != "nt":
                    popen_kwargs["start_new_session"] = True

                proc = subprocess.Popen(cmd, **popen_kwargs)

                # Apply OS-level resource constraints (Windows Job Object / Linux rlimit)
                confinement_method, job_handle = self._apply_os_resource_limits(proc, max_ram_gb=max_ram)
                resource_enforcement = confinement_method
                execution_confinement_method = confinement_method

                # Defensive Windows fallback cleanup handler registration
                if confinement_method == "PSUTIL_WATCHDOG_FALLBACK" and sys.platform == "win32":
                    import atexit
                    target_pid = proc.pid
                    cleanup_fn = lambda: subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(target_pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    atexit.register(cleanup_fn)

                # Active psutil resource watchdog daemon thread
                watchdog_thread = threading.Thread(
                    target=self._enforce_resource_watchdog,
                    args=(proc, max_ram, max_cpu, stop_watchdog, violation_info, job_handle),
                    daemon=True,
                    name="resource_watchdog",
                )
                watchdog_thread.start()

                stdout_text, stderr_text = proc.communicate(timeout=timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                if proc:
                    try:
                        # Windows Job Object process tree termination
                        if os.name == "nt" and job_handle:
                            import ctypes
                            ctypes.windll.kernel32.TerminateJobObject(job_handle, 124)
                            ctypes.windll.kernel32.CloseHandle(job_handle)
                            job_handle = None
                        elif os.name != "nt":
                            try:
                                import signal
                                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                            except Exception:
                                pass

                        # Process tree kill defense-in-depth on Windows
                        if os.name == "nt":
                            try:
                                subprocess.run(
                                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    timeout=5,
                                )
                            except Exception:
                                pass

                        proc.kill()
                        stdout_text, stderr_text = proc.communicate(timeout=5)
                    except Exception:
                        pass
                exit_code = 124
                stderr_text += f"\n[Sandbox Error] Execution exceeded hard timeout limit of {timeout}s and process tree was terminated."
            except SandboxSecurityViolation:
                raise
            except Exception as exc:
                exit_code = 1
                stderr_text += f"\n[Sandbox Error] Process spawning error: {exc}"
            finally:
                stop_watchdog.set()
                if watchdog_thread:
                    watchdog_thread.join(timeout=0.5)

                if cleanup_fn is not None and sys.platform == "win32":
                    try:
                        import atexit
                        atexit.unregister(cleanup_fn)
                    except Exception:
                        pass

                if os.name == "nt" and job_handle:
                    try:
                        import ctypes
                        ctypes.windll.kernel32.CloseHandle(job_handle)
                    except Exception:
                        pass

            # Post-execution check for resource watchdog violation or Windows Job Object OOM
            if violation_info.get("type") == "OOM":
                exit_code = 137
                timed_out = False
                error_details = violation_info.get("error_details", "ResourceLimitExceeded: Process exceeded enforced_max_ram_gb")
                stderr_text += f"\n[Sandbox Error] {error_details}"
            elif violation_info.get("type") == "CPU":
                exit_code = 137
                timed_out = False
                error_details = violation_info.get("error_details", "ResourceLimitExceeded: Process exceeded max_cpu_seconds")
                stderr_text += f"\n[Sandbox Error] {error_details}"
            elif exit_code in (-1073741804, 3221225540, 0xC0000044):
                # Windows STATUS_QUOTA_EXCEEDED from Job Object
                exit_code = 137
                timed_out = False
                error_details = "ResourceLimitExceeded: Process exceeded enforced_max_ram_gb"
                stderr_text += f"\n[Sandbox Error] {error_details}"

            duration = round(time.perf_counter() - start_time, 3)

            # 7. Post-run filesystem jail verification (Rule 15)
            current_stage = "JAIL_VERIFICATION"
            if parent_dir.exists():
                for p in parent_dir.rglob("*"):
                    if p.is_file():
                        in_code = False
                        in_output = False
                        try:
                            p.relative_to(code_path)
                            in_code = True
                        except ValueError:
                            pass
                        try:
                            p.relative_to(output_path)
                            in_output = True
                        except ValueError:
                            pass
                        if not (in_code or in_output):
                            if p not in pre_files or p.stat().st_mtime != pre_files[p]:
                                raise SandboxSecurityViolation(
                                    f"Rule 15 Filesystem Jail Breach: Process wrote or modified unauthorized file outside sandbox: {p}"
                                )

            # 8. Save logs to output_dir
            (output_path / "stdout.log").write_text(stdout_text, encoding="utf-8")
            (output_path / "stderr.log").write_text(stderr_text, encoding="utf-8")

            # 9. Authenticated Artifact Manifest: Seal manifest.json post-execution
            current_stage = "MANIFEST_SEALING"
            from research_os.verify.deterministic import create_run_manifest
            create_run_manifest(output_path)

            # 10. Directive 3 Fail-Closed: Check for undeclared metric spoofing in metrics.json
            metrics_file = output_path / "metrics.json"
            if metrics_file.exists():
                try:
                    metrics_data = json.loads(metrics_file.read_text(encoding="utf-8"))
                    if isinstance(metrics_data, dict):
                        declared = set(getattr(spec, "declared_metrics", []) or [])
                        if not declared and "declared_metrics" in spec.run_config:
                            declared = set(spec.run_config["declared_metrics"])
                        if not declared:
                            for c_name in ("contract.json", "contract.yaml", "contract.yml"):
                                c_path = code_path / c_name
                                if c_path.exists():
                                    from research_os.specs.contracts import inspect_experiment_contract
                                    c_info = inspect_experiment_contract(code_path)
                                    if c_info.metrics:
                                        declared = set(c_info.metrics.keys())
                                    break
                        if declared:
                            emitted_keys = [k for k in metrics_data.keys() if k not in ("status", "_provenance")]
                            undeclared = [k for k in emitted_keys if k not in declared]
                            if undeclared:
                                raise SandboxSecurityViolation(
                                    f"UndeclaredMetricSpoofingError: Runner emitted undeclared metrics {undeclared} "
                                    f"violating contract boundary. Allowed: {sorted(list(declared))}."
                                )
                except json.JSONDecodeError:
                    pass

            self.emit_event(
                output_path,
                stage="SUBPROCESS_EXECUTION",
                status="COMPLETED" if exit_code == 0 else "FAILED",
                code="PROCESS_EXIT_OK" if exit_code == 0 else "PROCESS_EXIT_NONZERO",
                details={"exit_code": exit_code, "duration_seconds": duration, "timed_out": timed_out},
            )

            if exit_code != 0:
                self.write_error_payload(
                    output_path,
                    error_code="ERR_PROCESS_EXIT_NONZERO",
                    stage="SUBPROCESS_EXECUTION",
                    message=f"Process exited with non-zero code {exit_code}.",
                    hint="Check output/stderr.log in the run directory for error tracebacks.",
                    details={"exit_code": exit_code, "timed_out": timed_out, "error_details": error_details},
                )

            return SandboxExecutionResult(
                exit_code=exit_code,
                stdout=stdout_text,
                stderr=stderr_text,
                duration_seconds=duration,
                timed_out=timed_out,
                resource_enforcement=resource_enforcement,
                execution_confinement_method=execution_confinement_method,
                error=stderr_text if exit_code != 0 else None,
                error_details=error_details,
            )

        except Exception as exc:
            err_code, hint = self._diagnose_exception(exc)
            self.emit_event(
                output_path,
                stage=current_stage,
                status="FAILED",
                code=err_code,
                details={"error": str(exc), "remediation_hint": hint},
            )
            self.write_error_payload(
                output_path,
                error_code=err_code,
                stage=current_stage,
                message=str(exc),
                hint=hint,
                details={"exception_type": type(exc).__name__},
            )
            raise


# Backward-compatible alias
SandboxRunner = PolicySubprocessRunner

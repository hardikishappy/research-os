"""Comprehensive red-team adversarial test suite verifying P0 audit vulnerability closures.

Enforces the invariant: CLAIMS = IMPLEMENTATION = EVIDENCE.
Covers all 6 required attack vectors:
1. test_legacy_token_fallback_rejected: HMAC and unkeyed tokens strictly rejected.
2. test_spec_digest_placeholder_rejected: Placeholder digests (e.g. hash-{spec_id}) strictly rejected.
3. test_synthetic_trajectory_generation_refused: Missing trace raises MissingTraceError.
4. test_missing_provenance_fails_closed: Missing or incomplete provenance fails closed (FAIL).
5. test_manifest_tampering_detected: Modified, added, deleted artifacts trigger TAMPERED.
6. test_orphan_process_tree_termination: Process tree terminated cleanly on timeout (no orphaned descendants).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Optional

import pytest

from research_os.gate.approval import (
    EnvironmentKeyBackend,
    HumanApprovalGate,
    LocalFileKeyBackend,
    canonicalize_gate_payload,
    compute_canonical_spec_hash,
    generate_keyed_signature,
    get_key_backend,
    set_key_backend,
    verify_approval_token,
)
from research_os.gate.token import HumanGateTokenManager, _validate_spec_digest
from research_os.manuscript.compiler import ManuscriptCompiler
from research_os.manuscript.visualizer import (
    MissingTraceError,
    plot_scalar_bar_chart,
    plot_time_series_from_raw_logs,
    plot_time_series_with_envelope,
)
from research_os.sandbox.runner import (
    PolicySubprocessRunner,
    SandboxExecutionResult,
    SandboxSecurityViolation,
)
from research_os.schemas.evaluation import EvaluationReport, HypothesisVerdict, SeedRunSummary
from research_os.schemas.experiment import (
    ExperimentSpec,
    ExperimentType,
    HardwareRequirements,
    ResourceLimits,
)
from research_os.schemas.gate import GateDecision, GateKind, GateStatus, HumanGateToken
from research_os.schemas.verification import VerificationStatus
from research_os.verify.deterministic import (
    DeterministicVerifier,
    compute_file_sha256,
    create_run_manifest,
)


def _is_pid_alive(pid: int) -> bool:
    """Cross-platform check whether process with given PID is still active."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_process:
            return False
        try:
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(h_process, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(h_process)
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return True


def _create_test_spec(spec_id: str = "spec-redteam-01", timeout_s: int = 30) -> ExperimentSpec:
    """Helper to construct a valid minimal ExperimentSpec for red-team testing."""
    return ExperimentSpec(
        spec_id=spec_id,
        hypothesis_id="hyp-redteam-01",
        name="Red Team Security Verification Protocol",
        experiment_type=ExperimentType.BENCHMARK,
        entry_point="python run_eval.py",
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0, max_ram_gb=2.0, max_cpu_cores=2),
        timeout_seconds=max(timeout_s, 5),
        random_seeds=[42, 101],
        expected_outputs=["metrics.json", "provenance.json"],
        run_config={"mode": "red_team_audit"},
    )


# ==============================================================================
# ATTACK VECTOR 1: Legacy Token Fallback Rejected
# ==============================================================================

def test_legacy_token_fallback_rejected(tmp_path: Path):
    """Attempt execution with an HMAC or unkeyed token; assert rejection.
    
    Invariant: ONLY Ed25519 asymmetric signatures verified against the active public key are valid.
    Any fallback token format must fail closed with:
    PermissionError("Ed25519 authorization required; fallback tokens strictly forbidden")
    """
    spec = _create_test_spec("spec-fallback-01")
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    (code_dir / "run_eval.py").write_text("print('Executing')\n", encoding="utf-8")

    runner = PolicySubprocessRunner()
    now = datetime.now(timezone.utc)

    # Sub-attack 1A: Legacy unkeyed SHA-256 fallback token (public_key_hex is None)
    unkeyed_token = HumanGateToken(
        gate_id="gate-legacy-01",
        project_id="research-os",
        voyage_id=spec.spec_id,
        kind=GateKind.EXPERIMENT_LAUNCH,
        status=GateStatus.APPROVED,
        decided_by="human_lead",
        decided_at=now,
        authorization_signature="legacy_unkeyed_sha256_mock_hash",
        public_key_hex=None,
    )
    assert unkeyed_token.is_approved()

    with pytest.raises(PermissionError) as exc_info_unkeyed:
        runner.execute(spec, unkeyed_token, code_dir, output_dir)
    assert "Ed25519 authorization required; fallback tokens strictly forbidden" in str(exc_info_unkeyed.value)

    # Directly testing verify_approval_token
    with pytest.raises(PermissionError) as exc_verify_unkeyed:
        verify_approval_token(unkeyed_token, expected_spec=spec)
    assert "Ed25519 authorization required; fallback tokens strictly forbidden" in str(exc_verify_unkeyed.value)

    # Sub-attack 1B: Legacy HMAC-SHA256 authorization token
    hmac_token = HumanGateToken(
        gate_id="gate-legacy-02",
        project_id="research-os",
        voyage_id=spec.spec_id,
        kind=GateKind.EXPERIMENT_LAUNCH,
        status=GateStatus.APPROVED,
        decided_by="human_lead",
        decided_at=now,
        authorization_signature="hmac_sha256_signature_abc123",
        public_key_hex="hmac-sha256",
    )
    assert hmac_token.is_approved()

    with pytest.raises(PermissionError) as exc_info_hmac:
        runner.execute(spec, hmac_token, code_dir, output_dir)
    assert "Ed25519 authorization required; fallback tokens strictly forbidden" in str(exc_info_hmac.value)

    with pytest.raises(PermissionError) as exc_verify_hmac:
        verify_approval_token(hmac_token, expected_spec=spec)
    assert "Ed25519 authorization required; fallback tokens strictly forbidden" in str(exc_verify_hmac.value)

    # Sub-attack 1C: Truncated or invalid public key length (e.g. 16 chars instead of 64 hex chars)
    invalid_key_token = HumanGateToken(
        gate_id="gate-legacy-03",
        project_id="research-os",
        voyage_id=spec.spec_id,
        kind=GateKind.EXPERIMENT_LAUNCH,
        status=GateStatus.APPROVED,
        decided_by="human_lead",
        decided_at=now,
        authorization_signature="dummy_signature",
        public_key_hex="1234567890abcdef",  # Invalid length
    )
    assert invalid_key_token.is_approved()

    with pytest.raises(PermissionError) as exc_info_inv:
        runner.execute(spec, invalid_key_token, code_dir, output_dir)
    assert "Ed25519 authorization required; fallback tokens strictly forbidden" in str(exc_info_inv.value)


# ==============================================================================
# ATTACK VECTOR 2: Spec Digest Placeholder Rejected
# ==============================================================================

def test_spec_digest_placeholder_rejected():
    """Attempt signing or token issuance with a dummy 'hash-{spec_id}'; assert rejection.
    
    Invariant: The token generation API MUST strictly require an actual ExperimentSpec
    or its canonical 64-character SHA-256 digest (compute_canonical_spec_hash).
    """
    manager = HumanGateTokenManager()

    # Sub-attack 2A: Placeholder pattern hash-{spec_id}
    with pytest.raises(ValueError) as exc_info_ph1:
        manager.issue_token(
            spec_id="spec-target-01",
            canonical_spec_hash="hash-spec-target-01",  # Forbidden placeholder
            decision=GateStatus.APPROVED,
        )
    assert "placeholder or dummy digests" in str(exc_info_ph1.value).lower()

    # Sub-attack 2B: Non-hex or invalid-length digest string
    with pytest.raises(ValueError) as exc_info_ph2:
        manager.issue_token(
            spec_id="spec-target-02",
            canonical_spec_hash="dummy-sha256-digest-not-hex",
            decision=GateStatus.APPROVED,
        )
    assert "64 hexadecimal characters" in str(exc_info_ph2.value).lower()

    # Sub-attack 2C: Direct validation function invocation
    with pytest.raises(ValueError):
        _validate_spec_digest("hash-123456")

    # Sub-attack 2D: Neither spec nor canonical_spec_hash supplied
    with pytest.raises(ValueError) as exc_info_none:
        manager.issue_token(
            spec_id="spec-target-03",
            canonical_spec_hash=None,
            spec=None,
            decision=GateStatus.APPROVED,
        )
    assert "strictly requires an actual ExperimentSpec or its canonical SHA-256 digest" in str(exc_info_none.value)

    # Contrast with valid 64-char hex SHA-256 digest
    valid_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    token = manager.issue_token(
        spec_id="spec-target-04",
        canonical_spec_hash=valid_sha256,
        decision=GateStatus.APPROVED,
    )
    assert token.is_approved()
    assert token.payload.get("canonical_spec_hash") == valid_sha256


# ==============================================================================
# ATTACK VECTOR 3: Synthetic Trajectory Generation Refused
# ==============================================================================

def test_synthetic_trajectory_generation_refused(tmp_path: Path):
    """Attempt rendering a time-series plot without raw step logs; assert MissingTraceError is raised.
    
    Invariant: If real raw trajectory/time-series data does not exist under raw_data/
    across evaluation seeds, DO NOT generate a trajectory figure.
    Raise MissingTraceError or generate only verified scalar distribution charts.
    """
    output_png = tmp_path / "trajectory.png"

    # Sub-attack 3A: Attempt plot_time_series_with_envelope with single-point or empty trace
    with pytest.raises(MissingTraceError) as exc_env_empty:
        plot_time_series_with_envelope(
            traces_by_seed={"seed_42": []},
            output_path=output_png,
        )
    assert "Synthetic trajectory generation is forbidden" in str(exc_env_empty.value)

    with pytest.raises(MissingTraceError) as exc_env_single:
        plot_time_series_with_envelope(
            traces_by_seed={"seed_42": [0.85]},
            output_path=output_png,
        )
    assert "contains only 1 step(s)" in str(exc_env_single.value)

    # Sub-attack 3B: plot_time_series_from_raw_logs against directory without step telemetry
    empty_raw_dir = tmp_path / "raw_data"
    empty_raw_dir.mkdir(parents=True)
    with pytest.raises(MissingTraceError) as exc_raw:
        plot_time_series_from_raw_logs(
            raw_data=empty_raw_dir,
            output_path=output_png,
        )
    assert "No multi-step time-series traces found" in str(exc_raw.value)

    # Sub-attack 3C: ManuscriptCompiler figure generator without raw telemetry
    eval_report = EvaluationReport(
        evaluation_id="eval-01",
        hypothesis_id="hyp-01",
        spec_id="spec-01",
        seeds_evaluated=[42, 101],
        total_runs=2,
        successful_runs=2,
        failed_runs=0,
        verdict=HypothesisVerdict.CONFIRMED,
        target_metric="accuracy",
        seed_runs=[
            SeedRunSummary(seed=42, run_id="run-42", exit_code=0, verification_status="PASS", metrics={"accuracy": 0.92}),
            SeedRunSummary(seed=101, run_id="run-101", exit_code=0, verification_status="PASS", metrics={"accuracy": 0.95}),
        ],
        summary_rationale="Empirical multi-seed confirmation",
    )
    empty_raw_dir = tmp_path / "raw_no_traces"
    empty_raw_dir.mkdir(parents=True)

    compiler = ManuscriptCompiler(run_id="run-fig-test", output_dir=tmp_path / "manuscript")
    # Explicitly requesting trace figure generation when traces are missing must raise MissingTraceError
    with pytest.raises(MissingTraceError) as exc_compiler:
        compiler._generate_figures(eval_report, raw_data_dir=empty_raw_dir, raise_if_missing_trace=True)
    assert "Refusing to synthesize fake trajectories" in str(exc_compiler.value)

    # Default policy generates an honest scalar bar chart rather than a synthetic line curve
    fig_paths = compiler._generate_figures(eval_report, raw_data_dir=empty_raw_dir, raise_if_missing_trace=False)
    assert len(fig_paths) == 1
    pdf_path, png_path = fig_paths[0]
    assert "verified_metric_distribution.png" in png_path.name
    assert png_path.exists()
    assert pdf_path.exists()


# ==============================================================================
# ATTACK VECTOR 4: Missing Provenance Fails Closed
# ==============================================================================

def test_missing_provenance_fails_closed(tmp_path: Path):
    """Run verification without provenance.json or with missing metric entries; assert verification returns FAIL.
    
    Invariant: require_provenance=True is non-negotiable default.
    If provenance.json is missing, or if any reported scalar in metrics.json lacks
    an entry in provenance.json, verification MUST return VerificationStatus.FAIL with ProvenanceIntegrityError.
    """
    spec = _create_test_spec("spec-prov-01")
    run_dir = tmp_path / "run_prov_test"
    run_dir.mkdir(parents=True)

    # Sub-attack 4A: Missing provenance.json entirely
    (run_dir / "metrics.json").write_text(json.dumps({"f1_score": 0.88}), encoding="utf-8")

    # Default verifier has require_provenance=True
    verifier = DeterministicVerifier()
    assert verifier.require_provenance is True

    report_missing = verifier.verify_run(spec, run_dir, exit_code=0)
    assert report_missing.overall_status == VerificationStatus.FAIL
    assert report_missing.provenance_valid is False
    assert report_missing.error_details is not None
    assert "ProvenanceIntegrityError" in report_missing.error_details
    assert "provenance.json is missing" in report_missing.error_details

    # Sub-attack 4B: provenance.json exists but omits one of the reported scalar metrics
    raw_data_dir = run_dir / "raw_data"
    raw_data_dir.mkdir(parents=True)
    raw_file = raw_data_dir / "results.csv"
    raw_file.write_text("val\n10.0\n20.0\n", encoding="utf-8")
    raw_sha = compute_file_sha256(raw_file)

    # metrics.json declares two metrics: "metric_covered" and "metric_uncovered"
    (run_dir / "metrics.json").write_text(
        json.dumps({"metric_covered": 15.0, "metric_uncovered": 99.9}),
        encoding="utf-8",
    )

    prov_payload = {
        "metrics": {
            "metric_covered": {
                "reported_value": 15.0,
                "raw_artifact": {
                    "artifact_id": "art-01",
                    "relative_path": "raw_data/results.csv",
                    "sha256": raw_sha,
                },
                "derivation": {
                    "operation": "mean",
                    "target_field": "val",
                },
            }
        }
    }
    (run_dir / "provenance.json").write_text(json.dumps(prov_payload, indent=2), encoding="utf-8")

    report_incomplete = verifier.verify_run(spec, run_dir, exit_code=0)
    assert report_incomplete.overall_status == VerificationStatus.FAIL
    assert report_incomplete.provenance_valid is False
    assert report_incomplete.error_details is not None
    assert "ProvenanceIntegrityError" in report_incomplete.error_details
    assert "metric_uncovered" in report_incomplete.error_details


# ==============================================================================
# ATTACK VECTOR 5: Manifest Tampering Detected
# ==============================================================================

def test_manifest_tampering_detected(tmp_path: Path):
    """Modify manifest.json, swap raw artifact, add file, or delete file; assert status is TAMPERED.
    
    Invariant: manifest.json is cryptographically signed with the gate Ed25519 private key.
    Any post-execution alteration returns VerificationStatus.TAMPERED.
    """
    spec = _create_test_spec("spec-manifest-01")
    run_dir = tmp_path / "run_manifest_test"
    raw_dir = run_dir / "raw_data"
    raw_dir.mkdir(parents=True)

    # Create legitimate raw artifact and metric
    raw_file = raw_dir / "telemetry.csv"
    raw_file.write_text("step,speed\n1,1.5\n2,2.5\n", encoding="utf-8")
    raw_sha = compute_file_sha256(raw_file)

    (run_dir / "metrics.json").write_text(json.dumps({"avg_speed": 2.0}), encoding="utf-8")
    prov_payload = {
        "metrics": {
            "avg_speed": {
                "reported_value": 2.0,
                "raw_artifact": {
                    "artifact_id": "art-speed-01",
                    "relative_path": "raw_data/telemetry.csv",
                    "sha256": raw_sha,
                },
                "derivation": {
                    "operation": "mean",
                    "target_field": "speed",
                },
            }
        }
    }
    (run_dir / "provenance.json").write_text(json.dumps(prov_payload, indent=2), encoding="utf-8")

    # Seal and digitally sign manifest.json
    manifest_path = create_run_manifest(run_dir)
    assert manifest_path.exists()

    verifier = DeterministicVerifier(require_provenance=True)

    # Baseline: unmodified run passes verification
    baseline_report = verifier.verify_run(spec, run_dir, exit_code=0)
    assert baseline_report.overall_status == VerificationStatus.PASS

    # Sub-attack 5A: Modify raw artifact after manifest sealing
    raw_file.write_text("step,speed\n1,999.0\n2,999.0\n", encoding="utf-8")
    report_modified = verifier.verify_run(spec, run_dir, exit_code=0)
    assert report_modified.overall_status == VerificationStatus.TAMPERED
    assert report_modified.error_details is not None
    assert "Tamper detected" in report_modified.error_details
    assert "modified after manifest creation" in report_modified.error_details

    # Restore raw artifact to valid content
    raw_file.write_text("step,speed\n1,1.5\n2,2.5\n", encoding="utf-8")

    # Sub-attack 5B: Alter manifest.json file content (breaks Ed25519 signature)
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["manifest_digest"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    report_sig_break = verifier.verify_run(spec, run_dir, exit_code=0)
    assert report_sig_break.overall_status == VerificationStatus.TAMPERED
    assert report_sig_break.error_details is not None
    assert "Tamper detected" in report_sig_break.error_details

    # Re-seal manifest to test addition and deletion
    create_run_manifest(run_dir)

    # Sub-attack 5C: Inject unauthorized file into run directory
    extra_file = run_dir / "backdoor_results.txt"
    extra_file.write_text("injected payload\n", encoding="utf-8")

    report_added = verifier.verify_run(spec, run_dir, exit_code=0)
    assert report_added.overall_status == VerificationStatus.TAMPERED
    assert report_added.error_details is not None
    assert "Unauthorized post-execution file addition" in report_added.error_details

    # Clean up extra file and re-verify pass
    extra_file.unlink()
    assert verifier.verify_run(spec, run_dir, exit_code=0).overall_status == VerificationStatus.PASS

    # Sub-attack 5D: Delete an artifact that was recorded in manifest
    raw_file.unlink()
    report_deleted = verifier.verify_run(spec, run_dir, exit_code=0)
    assert report_deleted.overall_status == VerificationStatus.TAMPERED
    assert report_deleted.error_details is not None
    assert "Manifest file missing on disk" in report_deleted.error_details


# ==============================================================================
# ATTACK VECTOR 6: Orphan Process Tree Termination
# ==============================================================================

def test_orphan_process_tree_termination(tmp_path: Path):
    """Spawn a child that spawns a grandchild sleep process; assert all descendants are killed on timeout.
    
    Invariant: Timeout handling terminates the entire process tree
    (via Windows Job Object / POSIX killpg), preventing orphaned background processes.
    """
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    pid_file = code_dir / "grandchild.pid"

    # Script for grandchild: writes its own PID and sleeps indefinitely
    grandchild_script = code_dir / "grandchild.py"
    grandchild_script.write_text(
        "import sys, os, time\n"
        "pid_path = sys.argv[1]\n"
        "with open(pid_path, 'w', encoding='utf-8') as f:\n"
        "    f.write(str(os.getpid()))\n"
        "    f.flush()\n"
        "while True:\n"
        "    time.sleep(0.5)\n",
        encoding="utf-8",
    )

    # Script for child: spawns grandchild and sleeps indefinitely
    child_script = code_dir / "child.py"
    child_script.write_text(
        "import sys, os, subprocess, time\n"
        "pid_path = sys.argv[1]\n"
        "# Delay slightly to ensure Windows Job Object assignment in parent runner\n"
        "time.sleep(0.3)\n"
        "proc = subprocess.Popen([sys.executable, 'grandchild.py', pid_path])\n"
        "while True:\n"
        "    time.sleep(0.5)\n",
        encoding="utf-8",
    )

    spec = ExperimentSpec(
        spec_id="spec-tree-kill-01",
        hypothesis_id="hyp-redteam-01",
        name="Process Tree Isolation Protocol",
        experiment_type=ExperimentType.BENCHMARK,
        entry_point=f"python child.py {pid_file.name}",
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0, max_ram_gb=2.0, max_cpu_cores=2),
        timeout_seconds=5,
        random_seeds=[42],
        expected_outputs=["stdout.log"],
        run_config={},
    )

    # Request legitimate Ed25519 approval token
    gate = HumanApprovalGate()
    token = gate.request_approval(spec=spec, run_id="run-tree-kill-01", auto_approve=True)
    assert token.is_approved()

    runner = PolicySubprocessRunner()
    result = runner.execute(spec, token, code_dir, output_dir, timeout_seconds=2)

    # Execution must have timed out and terminated with code 124
    assert result.timed_out is True
    assert result.exit_code == 124

    # Grandchild must have started and written its PID before timeout
    assert pid_file.exists(), "Grandchild failed to write PID file before timeout"
    grandchild_pid = int(pid_file.read_text(encoding="utf-8").strip())
    assert grandchild_pid > 0

    # Allow brief window for OS process table update
    time.sleep(0.5)

    # Crucial assertion: Grandchild process MUST be dead (not running in background)
    assert not _is_pid_alive(grandchild_pid), (
        f"Security Failure: Orphaned grandchild process (PID {grandchild_pid}) "
        f"is still active after job object / process tree termination!"
    )


# ==============================================================================
# ATTACK VECTOR 7: Cross-Platform Memory Watchdog & Platform Fallback Hardening
# ==============================================================================

def test_watchdog_hard_memory_kill(tmp_path: Path):
    """Launch a script that allocates an array exceeding max_ram_gb; verify watchdog terminates with OOM (exit code 137).
    
    Invariant: Universal psutil watchdog continuously samples cumulative RSS and CPU time
    across target process + all recursive children every 50ms, enforcing hard caps uniformly.
    """
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    oom_script = code_dir / "oom_alloc.py"
    # Allocates ~120MB and sleeps to hold the memory
    oom_script.write_text(
        "import time\n"
        "data = bytearray(120 * 1024 * 1024)\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )

    spec = ExperimentSpec(
        spec_id="spec-oom-kill-01",
        hypothesis_id="hyp-redteam-01",
        name="Watchdog Hard Memory Enforcement Protocol",
        experiment_type=ExperimentType.BENCHMARK,
        entry_point="python oom_alloc.py",
        resource_limits=ResourceLimits(min_ram_gb=0.01, max_ram_gb=0.05, max_cpu_seconds=60),
        timeout_seconds=10,
        random_seeds=[42],
        expected_outputs=["stdout.log"],
        run_config={},
    )

    gate = HumanApprovalGate()
    token = gate.request_approval(spec=spec, run_id="run-oom-kill-01", auto_approve=True)
    assert token.is_approved()

    runner = PolicySubprocessRunner()
    start_t = time.perf_counter()
    result = runner.execute(spec, token, code_dir, output_dir, timeout_seconds=5)
    elapsed = time.perf_counter() - start_t

    # Invariant: Terminated with OOM exit code 137 and diagnostic error details
    assert result.exit_code == 137
    assert result.timed_out is False
    assert result.error_details is not None
    assert "ResourceLimitExceeded: Process exceeded enforced_max_ram_gb" in result.error_details
    assert "ResourceLimitExceeded: Process exceeded enforced_max_ram_gb" in result.stderr
    # Must have terminated swiftly via watchdog (far earlier than the 5s sleep)
    assert elapsed < 4.5


def test_windows_breakaway_fallback_telemetry(monkeypatch, tmp_path: Path):
    """Verify that when Windows Job Object is unavailable (nested CI/container), runner cleanly falls back to psutil watchdog."""
    monkeypatch.setenv("RESEARCH_OS_FORCE_WATCHDOG_FALLBACK", "1")
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    dummy_script = code_dir / "dummy.py"
    dummy_script.write_text("print('Fallback success!')\n", encoding="utf-8")

    spec = ExperimentSpec(
        spec_id="spec-fallback-01",
        hypothesis_id="hyp-redteam-01",
        name="Watchdog Fallback Confinement Telemetry Protocol",
        experiment_type=ExperimentType.BENCHMARK,
        entry_point="python dummy.py",
        timeout_seconds=5,
        random_seeds=[42],
        expected_outputs=["stdout.log"],
        run_config={},
    )

    gate = HumanApprovalGate()
    token = gate.request_approval(spec=spec, run_id="run-fallback-01", auto_approve=True)
    assert token.is_approved()

    runner = PolicySubprocessRunner()
    result = runner.execute(spec, token, code_dir, output_dir)
    assert result.exit_code == 0
    assert result.execution_confinement_method == "PSUTIL_WATCHDOG_FALLBACK"
    assert "Fallback success!" in result.stdout


def test_environment_key_backend(monkeypatch, tmp_path: Path):
    """Verify that gate signing and token verification operate completely in-memory without touching disk."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    # 1. Generate known Ed25519 seed
    raw_key = ed25519.Ed25519PrivateKey.generate()
    seed_bytes = raw_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    b64_seed = base64.b64encode(seed_bytes).decode("ascii")

    # 2. Configure environment backend
    monkeypatch.setenv("RESEARCH_OS_GATE_PRIVATE_KEY", b64_seed)
    env_backend = EnvironmentKeyBackend()
    set_key_backend(env_backend)

    assert get_key_backend().get_public_key_hex() == raw_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()

    # 3. Create gate and approve spec
    gate = HumanApprovalGate(key_backend=env_backend)
    spec = ExperimentSpec(
        spec_id="spec-env-key-01",
        hypothesis_id="hyp-redteam-01",
        name="In-Memory Key Verification Protocol",
        experiment_type=ExperimentType.BENCHMARK,
        entry_point="python dummy.py",
        timeout_seconds=5,
        random_seeds=[42],
        expected_outputs=["stdout.log"],
        run_config={},
    )
    token = gate.request_approval(spec=spec, run_id="run-env-key-01", auto_approve=True)
    assert token.is_approved()
    assert token.public_key_hex == env_backend.get_public_key_hex()

    # 4. Verify token cryptographically
    assert verify_approval_token(token, expected_spec=spec) is True

    # 5. Invariant: Disk is clean; no .gate_key file was created in tmp_path
    assert not (tmp_path / ".gate_key").exists()

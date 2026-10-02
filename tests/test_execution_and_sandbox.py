"""Unit and integration tests for Phase 3: Planning, Human Gate, Sandbox Execution, and Verification."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
import pytest

from research_os.gate.approval import (
    HumanApprovalGate,
    verify_approval_token,
)
from research_os.memory.tracker import ExperimentTracker
from research_os.models.health import check_model_health
from research_os.planning.planner import ExperimentPlanner
from research_os.sandbox.runner import SandboxRunner
from research_os.schemas.experiment import ExperimentSpec, HardwareRequirements
from research_os.schemas.gate import GateKind, GateStatus, HumanGateToken
from research_os.schemas.hypothesis import HypothesisProposal, MechanismProvenance
from research_os.schemas.verification import VerificationStatus
from research_os.verify.deterministic import DeterministicVerifier, compute_directory_checksums


@pytest.fixture
def sample_hypothesis() -> HypothesisProposal:
    """Fixture providing a sample Swarm Robotics hypothesis proposal."""
    return HypothesisProposal(
        hypothesis_id="hyp-swarm-test-01",
        title="Event-Triggered Bandwidth Throttling for Swarm Scaling",
        falsifiable_statement="Under severe communication bandwidth caps (<= 64 B/s) and 20% packet drop, event-triggered broadcast reduces overhead by >= 40%.",
        baseline_method="Continuous Fixed-Rate Periodic Broadcast (10 Hz)",
        proposed_mechanism="State-dependent event-triggered velocity delta broadcast",
        theoretical_rationale="In dense swarms, steady-state flocking creates temporal velocity correlation.",
        inspired_by_seeds=[
            MechanismProvenance(
                source_paper_id="paper-swarm-01",
                paper_title="Stigmergic Coordination for Swarm Cluster Formation",
                domain="Swarm Robotics",
                borrowed_aspect="Event-triggered velocity thresholding",
            )
        ],
        target_metric="comm_bandwidth_bytes_per_sec",
        expected_direction="decrease",
        success_threshold=64.0,
    )


def test_experiment_planner_generates_spec_and_code(sample_hypothesis: HypothesisProposal) -> None:
    """Verify ExperimentPlanner creates a valid ExperimentSpec and compilable python code."""
    planner = ExperimentPlanner()
    spec, code = planner.plan_experiment(sample_hypothesis, spec_id="spec-test-01", timeout_seconds=45)

    assert spec.spec_id == "spec-test-01"
    assert spec.hypothesis_id == sample_hypothesis.hypothesis_id
    assert "metrics.json" in spec.expected_outputs
    assert spec.timeout_seconds == 45
    assert len(spec.random_seeds) >= 1
    assert "num_robots" in spec.run_config

    # Ensure generated Python code is syntactically valid
    compiled = compile(code, "simulation.py", "exec")
    assert compiled is not None


def test_human_gate_interactive_rejection(sample_hypothesis: HypothesisProposal, tmp_path: Path) -> None:
    """Rule 3: Verify that gate rejection blocks execution and marks token REJECTED."""
    planner = ExperimentPlanner()
    spec, _ = planner.plan_experiment(sample_hypothesis)

    gate = HumanApprovalGate()
    # Non-interactive without auto-approve should reject by Rule 3
    token = gate.request_approval(
        spec=spec,
        run_id="run-reject-01",
        auto_approve=False,
        interactive=False,
        token_path=tmp_path / "approval_token.json",
    )

    assert token.status == GateStatus.REJECTED
    assert not token.is_approved()
    assert (tmp_path / "approval_token.json").exists()

    # Verify that SandboxRunner strictly refuses execution
    runner = SandboxRunner()
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    with pytest.raises(PermissionError, match="Rule 3 Gate Violation"):
        runner.execute(spec=spec, gate_token=token, code_dir=code_dir, output_dir=output_dir)


def test_human_gate_tamper_verification(sample_hypothesis: HypothesisProposal) -> None:
    """Verify cryptographic signature check catches tampering on HumanGateToken."""
    planner = ExperimentPlanner()
    spec, _ = planner.plan_experiment(sample_hypothesis)

    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id="run-tamper-01",
        user="alice@research.org",
        auto_approve=True,
    )

    assert token.is_approved()
    assert verify_approval_token(token) is True

    # Tamper with payload
    token.payload["timeout_seconds"] = 99999
    assert verify_approval_token(token) is False


def test_sandbox_environment_isolation() -> None:
    """Rule 15: Verify sensitive credentials and API keys are completely stripped."""
    runner = SandboxRunner()
    os.environ["GEMINI_API_KEY"] = "super-secret-gemini-key"
    os.environ["OPENAI_API_KEY"] = "super-secret-openai-key"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "super-secret-aws-key"

    clean_env = runner._sanitize_environment()

    assert "GEMINI_API_KEY" not in clean_env
    assert "OPENAI_API_KEY" not in clean_env
    assert "AWS_SECRET_ACCESS_KEY" not in clean_env
    assert clean_env.get("RESEARCH_OS_SANDBOX") == "1"


def test_sandbox_timeout_handling(tmp_path: Path) -> None:
    """Rule 15: Verify sandbox enforces hard timeout and terminates run."""
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    # Script that attempts to run for 10 seconds
    sleep_script = "import time\ntime.sleep(10)\n"
    (code_dir / "sleep.py").write_text(sleep_script, encoding="utf-8")

    from datetime import datetime, timezone
    spec = ExperimentSpec(
        spec_id="spec-timeout-01",
        hypothesis_id="hyp-01",
        name="Timeout Test",
        entry_point=f"python sleep.py",
        expected_outputs=["dummy.txt"],
        timeout_seconds=5,
    )

    # Valid approval token
    gate = HumanApprovalGate()
    token = gate.request_approval(spec=spec, run_id="v01", auto_approve=True)

    runner = SandboxRunner()
    result = runner.execute(
        spec=spec,
        gate_token=token,
        code_dir=code_dir,
        output_dir=output_dir,
        timeout_seconds=1,
    )

    assert result.timed_out is True
    assert result.exit_code == 124
    assert (output_dir / "stderr.log").exists()
    assert "timeout limit" in (output_dir / "stderr.log").read_text(encoding="utf-8")


def test_sandbox_successful_simulation_and_deterministic_verification(
    sample_hypothesis: HypothesisProposal,
    tmp_path: Path,
) -> None:
    """End-to-End: Plan, Approve, Sandbox Execute, and Deterministically Verify simulation."""
    tracker = ExperimentTracker(base_dir=tmp_path / "runs")
    run_id, run_dir = tracker.init_run("run-e2e-01")

    # 1. Plan
    planner = ExperimentPlanner()
    spec, code = planner.plan_experiment(sample_hypothesis, spec_id="spec-e2e-01", timeout_seconds=30)
    tracker.record_spec(run_id, spec)
    tracker.record_code(run_id, "simulation.py", code)

    # 2. Gate Approval
    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id=run_id,
        user="test-engineer",
        auto_approve=True,
        token_path=run_dir / "approval_token.json",
    )
    tracker.record_approval_token(run_id, token)
    assert token.is_approved()

    # 3. Sandbox Execute
    runner = SandboxRunner()
    result = runner.execute(
        spec=spec,
        gate_token=token,
        code_dir=run_dir / "code",
        output_dir=run_dir / "output",
        timeout_seconds=30,
    )

    assert result.exit_code == 0
    assert not result.timed_out
    assert (run_dir / "output" / "metrics.json").exists()
    assert (run_dir / "output" / "trajectory.csv").exists()
    assert (run_dir / "output" / "summary.txt").exists()

    # 4. Deterministic Verification
    verifier = DeterministicVerifier(metrics_filename="metrics.json")
    report = verifier.verify_run(
        spec=spec,
        run_dir=run_dir / "output",
        exit_code=result.exit_code,
        run_id=run_id,
        metric_targets={
            "comm_bandwidth_bytes_per_sec": ("<=", 64.0),
            "comm_overhead_reduction_pct": (">=", 40.0),
        },
    )
    tracker.record_verification(run_id, report)

    assert report.overall_status == VerificationStatus.PASS
    assert report.exit_code_passed is True
    assert len(report.missing_output_files) == 0
    assert all(m.passed for m in report.metric_evaluations)

    # 5. Manifest & Checksums
    manifest = tracker.generate_manifest(run_id, spec=spec, report=report)
    assert manifest["status"] == "PASS"
    assert "metrics.json" in str(manifest["artifacts"])
    assert (run_dir / "manifest.json").exists()


def test_model_health_check_mock() -> None:
    """Verify health check logic functions for mock provider."""
    res = check_model_health("mock")
    assert res.status == "OK"
    assert res.text_generation_ok is True
    assert res.structured_generation_ok is True

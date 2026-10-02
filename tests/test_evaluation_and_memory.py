"""Tests for Phase 4: Statistical Evaluation, Filesystem Confinement, and Research Memory Loop."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from research_os.evaluation.evaluator import StatisticalEvaluator
from research_os.memory.corpus_updater import CorpusUpdater
from research_os.memory.tracker import ExperimentTracker
from research_os.sandbox.runner import SandboxRunner, SandboxSecurityViolation
from research_os.schemas.evaluation import (
    EvaluationReport,
    HypothesisVerdict,
    SeedRunSummary,
)
from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.gate import GateKind, GateStatus, HumanGateToken
from research_os.schemas.hypothesis import HypothesisProposal


@pytest.fixture
def sample_hypothesis() -> HypothesisProposal:
    return HypothesisProposal(
        hypothesis_id="hyp-eval-01",
        title="Event-Triggered Bandwidth Throttling for Swarm Scaling",
        falsifiable_statement="Under severe communication bandwidth caps (<= 64 B/s) and 20% packet drop, event-triggered broadcast reduces overhead by >= 40%.",
        baseline_method="Continuous Fixed-Rate Periodic Broadcast (10 Hz)",
        proposed_mechanism="State-dependent event-triggered velocity delta broadcast",
        theoretical_rationale="In dense swarms, steady-state flocking creates temporal velocity correlation.",
        target_metric="comm_bandwidth_bytes_per_sec",
        expected_direction="decrease",
        success_threshold=64.0,
    )


@pytest.fixture
def sample_spec(sample_hypothesis: HypothesisProposal) -> ExperimentSpec:
    return ExperimentSpec(
        spec_id="spec-eval-01",
        hypothesis_id=sample_hypothesis.hypothesis_id,
        name="Empirical Swarm Simulation",
        entry_point="python simulation.py",
        expected_outputs=["metrics.json"],
        random_seeds=[42, 101, 2024],
        timeout_seconds=30,
    )


def test_statistical_evaluator_confirmed_and_refuted(
    sample_hypothesis: HypothesisProposal,
    sample_spec: ExperimentSpec,
) -> None:
    """Verify StatisticalEvaluator correctly computes stats and outputs CONFIRMED / REFUTED verdicts."""
    evaluator = StatisticalEvaluator()

    # 1. Successful confirmed runs (mean <= 64.0)
    confirmed_runs = [
        SeedRunSummary(
            seed=42,
            run_id="r1",
            exit_code=0,
            verification_status="PASS",
            metrics={"comm_bandwidth_bytes_per_sec": 58.0, "reduction": 65.0},
        ),
        SeedRunSummary(
            seed=101,
            run_id="r2",
            exit_code=0,
            verification_status="PASS",
            metrics={"comm_bandwidth_bytes_per_sec": 62.0, "reduction": 60.0},
        ),
        SeedRunSummary(
            seed=2024,
            run_id="r3",
            exit_code=0,
            verification_status="PASS",
            metrics={"comm_bandwidth_bytes_per_sec": 60.0, "reduction": 62.0},
        ),
    ]

    report = evaluator.evaluate_runs(sample_hypothesis, sample_spec, confirmed_runs)
    assert report.verdict == HypothesisVerdict.CONFIRMED
    assert report.successful_runs == 3
    assert report.target_metric == "comm_bandwidth_bytes_per_sec"
    m_agg = report.metric_aggregates["comm_bandwidth_bytes_per_sec"]
    assert m_agg.mean == 60.0
    assert m_agg.std_dev == 2.0
    assert m_agg.passed is True

    # 2. Refuted runs (mean > 64.0)
    refuted_runs = [
        SeedRunSummary(
            seed=42,
            run_id="r4",
            exit_code=0,
            verification_status="PASS",
            metrics={"comm_bandwidth_bytes_per_sec": 75.0},
        ),
        SeedRunSummary(
            seed=101,
            run_id="r5",
            exit_code=0,
            verification_status="PASS",
            metrics={"comm_bandwidth_bytes_per_sec": 80.0},
        ),
    ]

    refuted_report = evaluator.evaluate_runs(sample_hypothesis, sample_spec, refuted_runs)
    assert refuted_report.verdict == HypothesisVerdict.REFUTED
    assert refuted_report.metric_aggregates["comm_bandwidth_bytes_per_sec"].passed is False

    # 3. Inconclusive (only 1 valid run)
    inconclusive_runs = [
        SeedRunSummary(seed=42, run_id="r6", exit_code=0, verification_status="PASS", metrics={"comm_bandwidth_bytes_per_sec": 50.0}),
        SeedRunSummary(seed=101, run_id="r7", exit_code=1, verification_status="FAIL", metrics={}),
    ]
    inc_report = evaluator.evaluate_runs(sample_hypothesis, sample_spec, inconclusive_runs)
    assert inc_report.verdict == HypothesisVerdict.INCONCLUSIVE


def test_sandbox_security_jail_catches_traversal(tmp_path: Path) -> None:
    """Rule 15: Verify static AST checks catch parent directory traversal attempts."""
    code_dir = tmp_path / "unsafe_code"
    code_dir.mkdir()

    # Script attempting parent directory access
    unsafe_script = "import os\nwith open('../secret.txt', 'w') as f:\n    f.write('pwned')\n"
    (code_dir / "unsafe.py").write_text(unsafe_script, encoding="utf-8")

    violations = SandboxRunner.validate_code_security(code_dir)
    assert len(violations) > 0
    assert any("Path traversal" in v for v in violations)


def test_sandbox_security_jail_catches_disallowed_imports(tmp_path: Path) -> None:
    """Rule 15: Verify static AST checks catch network socket imports."""
    code_dir = tmp_path / "network_code"
    code_dir.mkdir()

    network_script = "import socket\ns = socket.socket()\n"
    (code_dir / "net.py").write_text(network_script, encoding="utf-8")

    violations = SandboxRunner.validate_code_security(code_dir)
    assert len(violations) > 0
    assert any("socket" in v for v in violations)


def test_corpus_updater_creates_valid_empirical_finding(
    sample_hypothesis: HypothesisProposal,
    sample_spec: ExperimentSpec,
    tmp_path: Path,
) -> None:
    """Rules 4 & 5: Verify CorpusUpdater converts evaluation report into a valid synthesizable finding."""
    evaluator = StatisticalEvaluator()
    runs = [
        SeedRunSummary(seed=42, run_id="r1", exit_code=0, verification_status="PASS", metrics={"comm_bandwidth_bytes_per_sec": 55.0}),
        SeedRunSummary(seed=101, run_id="r2", exit_code=0, verification_status="PASS", metrics={"comm_bandwidth_bytes_per_sec": 57.0}),
    ]
    report = evaluator.evaluate_runs(sample_hypothesis, sample_spec, runs)

    updater = CorpusUpdater(memory_dir=tmp_path / "memory")
    extraction, json_path = updater.record_empirical_finding(report, sample_hypothesis, sample_spec)

    assert json_path.exists()
    assert (tmp_path / "memory" / f"empirical-{sample_hypothesis.hypothesis_id}.md").exists()
    assert extraction.paper_id == f"empirical-{sample_hypothesis.hypothesis_id}"
    assert "Abstract" in extraction.sections
    assert len(extraction.section_provenance) > 0
    assert len(extraction.source_checksum) == 64
    assert extraction.metadata.venue == "Research OS Closed-Loop Empirical Archive"

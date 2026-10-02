"""Verification test suite for generic domain-neutral Research OS architecture.

Enforces:
1. Swarm experiment execution via SwarmRoboticsPlugin with raw data provenance.
2. NLP benchmark execution via NLPPlugin with zero swarm terminology.
3. Unsupported domain refusal (e.g. Astrophysics returns UNSUPPORTED_DOMAIN).
4. Evidence-derived, domain-neutral fallback synthesis without swarm injection.
5. Strict rejection of fabricated/unbacked scalar metrics.
6. Anti-cheating static purity: 0 matches for swarm/robot terminology in core src/research_os.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from research_os.domains.base import UnsupportedDomainError
from research_os.domains.registry import DomainRegistry, default_domain_registry
from research_os.gate.approval import HumanApprovalGate
from research_os.models.mock import MockModelAdapter
from research_os.planning.planner import ExperimentPlanner
from research_os.plugins.nlp import NLPPlugin
from research_os.plugins.swarm_robotics import SwarmRoboticsPlugin
from research_os.sandbox.runner import SandboxRunner
from research_os.schemas.experiment import ExperimentSpec, ExperimentType
from research_os.schemas.hypothesis import HypothesisProposal, MechanismProvenance
from research_os.schemas.paper import PaperExtraction, PaperMetadata, SectionProvenance
from research_os.schemas.verification import VerificationStatus
from research_os.synthesis.matrix import build_capability_matrix
from research_os.synthesis.synthesizer import LiteratureSynthesizer
from research_os.verify.deterministic import DeterministicVerifier


def test_swarm_plugin_execution(tmp_path: Path):
    """Rule 1 & 4: Swarm experiment executes via isolated plugin, generating raw data and provenance."""
    hyp = HypothesisProposal(
        hypothesis_id="hyp-swarm-pure-01",
        title="Event-Triggered Bandwidth Throttling for Swarm Scaling",
        falsifiable_statement="Event-triggered velocity broadcasts throttle communication bandwidth below 64 B/s under packet drop.",
        baseline_method="Continuous Periodic 10 Hz Broadcast",
        proposed_mechanism="State divergence threshold broadcasting",
        theoretical_rationale="Velocity correlation in dense swarms eliminates need for high frequency transmission.",
        inspired_by_seeds=[
            MechanismProvenance(
                source_paper_id="paper-swarm-01",
                paper_title="Decentralized Coordination Under Bandwidth Limits",
                domain="Swarm Robotics",
                borrowed_aspect="Velocity thresholding",
            )
        ],
        target_metric="comm_bandwidth_bytes_per_sec",
        expected_direction="decrease",
        success_threshold=64.0,
    )

    planner = ExperimentPlanner()
    spec, code = planner.plan_experiment(hyp, timeout_seconds=30)

    assert spec.experiment_type == ExperimentType.SIMULATION
    assert "num_robots" in spec.run_config

    run_dir = tmp_path / "swarm_run"
    code_dir = run_dir / "code"
    output_dir = run_dir / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    sim_file = code_dir / "simulation.py"
    sim_file.write_text(code, encoding="utf-8")

    cfg_file = code_dir / "config.json"
    cfg_file.write_text(json.dumps(spec.run_config), encoding="utf-8")

    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id="run-swarm-01",
        user="test-architect",
        auto_approve=True,
        token_path=run_dir / "token.json",
    )

    runner = SandboxRunner()
    result = runner.execute(
        spec=spec,
        gate_token=token,
        code_dir=code_dir,
        output_dir=output_dir,
        timeout_seconds=30,
    )

    assert result.exit_code == 0
    assert (output_dir / "raw_data" / "trajectory.csv").exists()
    assert (output_dir / "raw_data" / "packet_log.csv").exists()
    assert (output_dir / "metrics.json").exists()
    assert (output_dir / "provenance.json").exists()

    plugin = default_domain_registry.get_plugin("swarm_robotics")
    verifier = DeterministicVerifier(require_provenance=True)
    report = verifier.verify_run(
        spec=spec,
        run_dir=output_dir,
        exit_code=0,
        domain_plugin=plugin,
        metric_targets={
            "comm_bandwidth_bytes_per_sec": ("<=", 64.0),
        },
    )

    assert report.overall_status == VerificationStatus.PASS
    assert report.provenance_valid is True
    assert len(report.unbacked_metrics) == 0


def test_nlp_plugin_execution(tmp_path: Path):
    """Rule 1, 3 & 4: NLP benchmark executes via NLPPlugin; zero swarm terminology appears anywhere."""
    hyp = HypothesisProposal(
        hypothesis_id="hyp-nlp-rag-01",
        title="Retrieval-Augmented Generation vs Direct Generation on Hallucination Frequency",
        falsifiable_statement="Context injection via retrieval-augmented generation reduces hallucination rate by >= 50% compared to direct generation on factual QA benchmarks.",
        baseline_method="Zero-Shot Direct Generation",
        proposed_mechanism="Dynamic context injection grounding generation tokens in retrieved passages.",
        theoretical_rationale="Passage constraints restrict sampling distributions to verified source tokens.",
        inspired_by_seeds=[
            MechanismProvenance(
                source_paper_id="paper-rag-01",
                paper_title="Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
                domain="Natural Language Processing",
                borrowed_aspect="Non-parametric memory retrieval",
            )
        ],
        target_metric="hallucination_rate",
        expected_direction="decrease",
        success_threshold=0.30,
    )

    planner = ExperimentPlanner()
    spec, code = planner.plan_experiment(hyp, timeout_seconds=30)

    # Assert correct domain-specific typing
    assert spec.experiment_type == ExperimentType.BENCHMARK
    assert "benchmark_size" in spec.run_config

    # Strict purity check: Zero swarm / robotics terms in NLP spec, config, or code
    forbidden_terms = [
        "robot", "swarm", "flocking", "aggregation", "arena",
        "num_robots", "packet_drop", "communication_radius", "trajectory",
    ]
    spec_json = spec.model_dump_json().lower()
    code_lower = code.lower()

    for term in forbidden_terms:
        assert term not in spec_json, f"Swarm contamination in NLP spec: {term}"
        assert term not in code_lower, f"Swarm contamination in NLP benchmark code: {term}"

    run_dir = tmp_path / "nlp_run"
    code_dir = run_dir / "code"
    output_dir = run_dir / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    bench_file = code_dir / "run_benchmark.py"
    bench_file.write_text(code, encoding="utf-8")

    cfg_file = code_dir / "config.json"
    cfg_file.write_text(json.dumps(spec.run_config), encoding="utf-8")

    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id="run-nlp-01",
        user="test-architect",
        auto_approve=True,
        token_path=run_dir / "token.json",
    )

    runner = SandboxRunner()
    result = runner.execute(
        spec=spec,
        gate_token=token,
        code_dir=code_dir,
        output_dir=output_dir,
        timeout_seconds=30,
    )

    assert result.exit_code == 0
    assert (output_dir / "raw_data" / "predictions.jsonl").exists()
    assert (output_dir / "metrics.json").exists()
    assert (output_dir / "provenance.json").exists()

    metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    assert "hallucination_rate" in metrics
    assert "latency_ms" in metrics
    assert "token_overlap_score" in metrics

    # Deterministic verifier with provenance check
    plugin = default_domain_registry.get_plugin("nlp_benchmarking")
    verifier = DeterministicVerifier(require_provenance=True)
    report = verifier.verify_run(
        spec=spec,
        run_dir=output_dir,
        exit_code=0,
        domain_plugin=plugin,
        metric_targets={
            "hallucination_rate": ("<=", 0.30),
        },
    )

    assert report.overall_status == VerificationStatus.PASS
    assert report.provenance_valid is True
    assert len(report.unbacked_metrics) == 0


def test_unsupported_domain_refusal():
    """Rule 5: When presented with an un-registered domain, system refuses fabricated experiment code."""
    astro_hyp = HypothesisProposal(
        hypothesis_id="hyp-astro-core-01",
        title="Core-Collapse Supernova Neutrino Flux Anisotropy",
        falsifiable_statement="3D magnetorotational core collapse yields >= 15% dipolar anisotropy in neutrino flux.",
        baseline_method="Spherically Symmetric 1D Transport",
        proposed_mechanism="Magnetic field amplification via magneto-rotational instability.",
        theoretical_rationale="Convective motions break spherical symmetry during stellar collapse.",
        inspired_by_seeds=[
            MechanismProvenance(
                source_paper_id="paper-astro-01",
                paper_title="Multidimensional Core-Collapse Supernova Simulations",
                domain="Astrophysics",
                borrowed_aspect="3D Neutrino Hydrodynamics",
            )
        ],
        target_metric="neutrino_flux_anisotropy",
        expected_direction="increase",
        success_threshold=0.15,
    )

    planner = ExperimentPlanner()
    with pytest.raises(UnsupportedDomainError) as exc_info:
        planner.plan_experiment(astro_hyp)

    assert exc_info.value.status == "UNSUPPORTED_DOMAIN"
    assert "not supported" in str(exc_info.value).lower()


def test_deterministic_fallback_domain_neutral():
    """Rule 1 & Step 1: Deterministic fallback synthesis contains ZERO swarm or robotics terminology."""
    synthetic_paper = PaperExtraction(
        extraction_id="ext-generic-01",
        paper_id="paper-opt-01",
        metadata=PaperMetadata(
            paper_id="paper-opt-01",
            title="Stochastic Gradient Discretization Under Noisy Oracles",
            authors=["Alice Gomez", "Bob Vance"],
            abstract="We analyze convergence rates of discretized stochastic gradient descent under bounded variance.",
            year=2024,
        ),
        sections={
            "Introduction": "Optimization algorithms encounter convergence slowdowns under noisy gradient estimations.",
            "Limitations": "Our theoretical bounds assume i.i.d. noise; adversarial perturbation limits remain completely uncharacterized.",
        },
        section_provenance=[
            SectionProvenance(
                source_paper_id="paper-opt-01",
                section_title="Limitations",
                text_snippet="Adversarial perturbation limits remain completely uncharacterized.",
            )
        ],
        algorithms=["Noisy-SGD"],
        key_findings=["Convergence holds with probability 0.95 under sub-Gaussian noise."],
        limitations=["Adversarial perturbation limits remain completely uncharacterized."],
        source_checksum="sha256-dummy-generic-01",
    )

    cap_matrix = build_capability_matrix([synthetic_paper])
    # Force fallback by passing MockModelAdapter without pre-queued response
    mock_model = MockModelAdapter()
    synthesizer = LiteratureSynthesizer(mock_model)

    synthesis = synthesizer.synthesize_corpus(
        topic="Stochastic Gradient Optimization Dynamics",
        papers=[synthetic_paper],
        matrix=cap_matrix,
    )

    full_synthesis_text = " ".join(
        synthesis.consensus_findings +
        synthesis.contested_claims +
        [g.description for g in synthesis.identified_gaps]
    ).lower()

    forbidden = ["robot", "swarm", "packet_drop", "flocking", "arena_size", "aggregation"]
    for term in forbidden:
        assert term not in full_synthesis_text, f"Forbidden term '{term}' found in generic fallback synthesis!"


def test_fabricated_metric_rejected(tmp_path: Path):
    """Rule 4: Fabricated scalar metrics without backing raw data are rejected by DeterministicVerifier."""
    run_dir = tmp_path / "fake_experiment_output"
    run_dir.mkdir()

    # Fabricate naked metrics file without raw data or provenance
    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps({
        "accuracy": 0.99,
        "f1_score": 0.98,
        "status": "COMPLETED",
    }), encoding="utf-8")

    spec = ExperimentSpec(
        spec_id="spec-fake-01",
        hypothesis_id="hyp-fake-01",
        name="Fabricated Metric Test",
        entry_point="python dummy.py",
        expected_outputs=["metrics.json"],
    )

    verifier = DeterministicVerifier(require_provenance=True)
    report = verifier.verify_run(
        spec=spec,
        run_dir=run_dir,
        exit_code=0,
    )

    assert report.overall_status == VerificationStatus.FAIL
    assert report.provenance_valid is False
    assert "accuracy" in report.unbacked_metrics or "f1_score" in report.unbacked_metrics
    assert report.error_details is not None
    assert "provenance" in report.error_details.lower()


def test_anti_cheating_core_purity():
    """Rule 1 & Non-Negotiable Rule 6: Static AST/grep scan of src/research_os/ (excluding plugins/).

    Asserts EXACTLY 0 matches for: robot, swarm, packet_drop, flocking, arena_size, num_robots, communication_radius.
    """
    root_src = Path(__file__).resolve().parent.parent / "src" / "research_os"
    assert root_src.is_dir()

    forbidden_patterns = [
        "robot",
        "swarm",
        "packet_drop",
        "flocking",
        "arena_size",
        "num_robots",
        "communication_radius",
        "swarm_simulation_template",
    ]

    violations: list[str] = []

    for py_file in root_src.rglob("*.py"):
        # Exclude plugins directory
        if "plugins" in py_file.parts:
            continue

        rel_path = py_file.relative_to(root_src).as_posix()
        try:
            content = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        lines = content.splitlines()
        for line_idx, line in enumerate(lines, start=1):
            line_lower = line.lower()
            for pattern in forbidden_patterns:
                if pattern in line_lower:
                    violations.append(
                        f"src/research_os/{rel_path}:{line_idx} contains '{pattern}': {line.strip()}"
                    )

    assert len(violations) == 0, (
        f"Found {len(violations)} core contamination violations in src/research_os:\n" +
        "\n".join(violations[:20])
    )

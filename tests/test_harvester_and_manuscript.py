"""Tests for Academic Harvester, Telepresence Domain, Autonomous Synthesizer, and Manuscript Compiler."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from research_os.domains.registry import DomainRegistry
from research_os.domains.synthesizer import AutonomousPluginSynthesizer
from research_os.gate.approval import HumanApprovalGate
from research_os.gate.token import HumanGateTokenManager
from research_os.harvester.arxiv_client import ArxivHarvesterClient
from research_os.harvester.researcher_curator import CuratedCorpus, ResearcherCurator
from research_os.harvester.scholar import ScholarHarvesterClient
from research_os.manuscript.compiler import ManuscriptCompiler
from research_os.planning.planner import ExperimentPlanner
from research_os.plugins.telepresence import TelepresencePlugin
from research_os.plugins.telepresence.metrics import compute_telepresence_metrics_from_raw
from research_os.sandbox.runner import SandboxRunner
from research_os.schemas.evaluation import EvaluationReport, HypothesisVerdict, MetricAggregate, SeedRunSummary
from research_os.schemas.experiment import ExperimentSpec, ExperimentType, HardwareRequirements
from research_os.schemas.gate import GateDecision, GateKind
from research_os.schemas.hypothesis import HypothesisProposal, MechanismProvenance
from research_os.schemas.paper import PaperMetadata
from research_os.schemas.synthesis import CrossPaperSynthesis, ResearchGap
from research_os.schemas.verification import VerificationStatus
from research_os.verify.deterministic import DeterministicVerifier


def test_harvester_dual_horizon_and_bias_mitigation(tmp_path: Path):
    """Part 1: Verify dual-horizon paper selection (legacy vs frontier) and multi-PI bias mitigation."""
    curator = ResearcherCurator(reference_year=2026)
    out_dir = tmp_path / "corpus" / "telepresence"

    corpus = curator.harvest(
        topic="telepresence haptic jitter control",
        domain="telepresence",
        max_legacy=3,
        max_frontier=3,
        max_per_pi=1,
        output_dir=out_dir,
    )

    assert isinstance(corpus, CuratedCorpus)
    assert len(corpus.top_pis) >= 3
    assert len(corpus.legacy_foundationals) == 3
    assert len(corpus.frontier_horizon) == 3

    # Legacy: published > 5 years ago (<= 2021)
    for p in corpus.legacy_foundationals:
        assert p.metadata.year is not None
        assert p.metadata.year <= 2021
        assert p.metadata.citation_count is not None

    # Frontier: published in last 12-24 months (>= 2024)
    for p in corpus.frontier_horizon:
        assert p.metadata.year is not None
        assert p.metadata.year >= 2024

    # Verify deterministic files created under output_dir
    manifest_file = out_dir / "corpus_manifest.json"
    assert manifest_file.exists()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["total_papers"] == 6

    # Verify metadata and extractions exist
    meta_files = list((out_dir / "metadata").glob("*.json"))
    ext_files = list((out_dir / "extractions").glob("*.json"))
    assert len(meta_files) == 6
    assert len(ext_files) == 6


def test_telepresence_plugin_execution_and_provenance(tmp_path: Path):
    """Part 2: TelepresencePlugin simulation, raw network jitter telemetry, and verifier pass."""
    # Ensure telepresence plugin is registered
    plugin = DomainRegistry.get_plugin("telepresence")
    assert plugin is not None
    assert plugin.domain_id == "telepresence"
    assert ExperimentType.SIMULATION in plugin.supported_experiment_types

    hyp = HypothesisProposal(
        hypothesis_id="hyp-telepresence-jitter-01",
        title="Predictive Jitter Buffering for High Latency Telepresence",
        falsifiable_statement="Jitter buffer prediction reduces operator tracking RMSE below 0.05 under packet latency > 100ms.",
        baseline_method="Static FIFO Jitter Buffer",
        proposed_mechanism="Kalman predictive state buffering",
        theoretical_rationale="Kinematic continuity allows predicting operator trajectory during burst packet drops.",
        inspired_by_seeds=[
            MechanismProvenance(
                source_paper_id="paper-tele-01",
                paper_title="Haptic Feedback over Public IP Networks",
                domain="telepresence",
                borrowed_aspect="State extrapolation",
            )
        ],
        target_metric="tracking_rmse",
        expected_direction="decrease",
        success_threshold=0.05,
    )

    planner = ExperimentPlanner()
    spec, sim_code = planner.plan_experiment(hyp, timeout_seconds=30)
    assert "Telepresence" in spec.name or "telepresence" in spec.name.lower()
    assert "raw_data/network_jitter.csv" in spec.expected_outputs

    # Rule 3: Authorize at Human Gate
    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id="run-telepresence-test",
        auto_approve=True,
        user="test_operator",
    )
    assert token.is_approved()

    # Execute simulation in sandbox
    code_dir = tmp_path / "code"
    out_dir = tmp_path / "output"
    code_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    sim_file = code_dir / "run_telepresence.py"
    sim_file.write_text(sim_code, encoding="utf-8")

    cfg_file = code_dir / "config.json"
    cfg_file.write_text(json.dumps(spec.run_config), encoding="utf-8")

    runner = SandboxRunner(default_timeout_seconds=30)
    res = runner.execute(
        spec=spec,
        gate_token=token,
        code_dir=code_dir,
        output_dir=out_dir,
    )
    assert res.exit_code == 0, f"Simulation failed with stderr: {res.stderr}"

    # Verify raw telemetry and metrics exist
    raw_csv = out_dir / "raw_data" / "network_jitter.csv"
    metrics_json = out_dir / "metrics.json"
    prov_json = out_dir / "provenance.json"

    assert raw_csv.exists(), "Raw network_jitter.csv was not produced"
    assert metrics_json.exists(), "metrics.json was not produced"
    assert prov_json.exists(), "provenance.json was not produced"

    # Verify metrics content and provenance
    metrics = json.loads(metrics_json.read_text(encoding="utf-8"))
    assert "tracking_rmse" in metrics
    assert "packet_drop_rate" in metrics
    assert "jitter_std_ms" in metrics
    assert metrics["tracking_rmse"] < 0.05

    # Run deterministic verifier
    verifier = DeterministicVerifier(metrics_filename="metrics.json")
    report = verifier.verify_run(
        spec=spec,
        run_dir=out_dir,
        exit_code=res.exit_code,
        run_id="run-telepresence-test",
        metric_targets={"tracking_rmse": ("<=", 0.05)},
    )
    assert report.overall_status == VerificationStatus.PASS
    assert report.metric_evaluations[0].passed is True


def test_autonomous_plugin_synthesizer_and_gate(tmp_path: Path):
    """Part 2: Autonomous Plugin Synthesizer drafts and Human Gate token authorization."""
    synthesizer = AutonomousPluginSynthesizer(output_base_dir=tmp_path / "generated_plugins")
    paper_text = (
        "We propose a novel Quantum Annealing Optimization Protocol using D-Wave dimod and dwave-neal. "
        "The objective evaluates ground_state_energy and convergence_time_ms under transverse magnetic field."
    )

    draft = synthesizer.synthesize_plugin_draft(
        domain_name="quantum_annealing",
        methodology_text=paper_text,
        target_libraries=["dimod", "dwave_neal"],
    )

    assert Path(draft.plugin_code_path).exists()
    assert Path(draft.schemas_code_path).exists()
    assert Path(draft.metrics_code_path).exists()
    assert "quantum_annealing" in draft.domain_id

    # Rule 3 Gate Check: Attempting to install without approval token must raise PermissionError
    gate_mgr = HumanGateTokenManager()
    with pytest.raises(PermissionError, match="HumanGateToken"):
        synthesizer.install_approved_plugin(draft, gate_token=None)

    # Approve with valid HumanGateToken
    token = gate_mgr.issue_token(
        spec_id=f"plugin_{draft.domain_id}",
        decision=GateDecision.APPROVED,
        reason="Approved by Lead Scientist",
        approver_id="test_admin",
        gate_kind=GateKind.DOMAIN_PLUGIN_INSTALL,
    )

    installed_plugin = synthesizer.install_approved_plugin(draft, gate_token=token)
    assert installed_plugin.domain_id == "quantum_annealing"
    assert "quantum_annealing" in DomainRegistry.list_domains()


def test_manuscript_compiler(tmp_path: Path):
    """Part 3: ManuscriptCompiler generates paper.md, publication-ready paper.tex, and references.bib."""
    run_id = "test-run-manuscript-01"
    manuscript_dir = tmp_path / "experiments" / "runs" / run_id / "manuscript"

    hyp = HypothesisProposal(
        hypothesis_id="hyp-telepresence-01",
        title="Predictive Jitter Buffering",
        falsifiable_statement="Jitter buffer prediction reduces operator tracking RMSE below 0.05 under packet latency > 100ms.",
        baseline_method="Static FIFO Jitter Buffer",
        proposed_mechanism="Kalman predictive state buffering",
        theoretical_rationale="Continuous kinematics allow trajectory extrapolation under packet loss bursts.",
        target_metric="tracking_rmse",
        expected_direction="decrease",
        success_threshold=0.05,
    )

    spec = ExperimentSpec(
        spec_id="spec-telepresence-01",
        hypothesis_id=hyp.hypothesis_id,
        experiment_type=ExperimentType.SIMULATION,
        name="Telepresence Predictive Buffering Benchmark",
        entry_point="python run_simulation.py",
        run_config={"latency_ms": 120, "jitter_std": 25},
        random_seeds=[42, 101, 2024],
        expected_outputs=["metrics.json", "provenance.json", "raw_data/network_jitter.csv"],
        hardware_requirements=HardwareRequirements(min_ram_gb=2.0),
    )

    eval_report = EvaluationReport(
        evaluation_id="eval-telepresence-01",
        hypothesis_id=hyp.hypothesis_id,
        spec_id=spec.spec_id,
        seeds_evaluated=[42, 101, 2024],
        total_runs=3,
        successful_runs=3,
        failed_runs=0,
        verdict=HypothesisVerdict.CONFIRMED,
        target_metric="tracking_rmse",
        metric_aggregates={
            "tracking_rmse": MetricAggregate(
                metric_name="tracking_rmse",
                sample_values=[0.038, 0.041, 0.036],
                mean=0.0383,
                std_dev=0.0025,
                std_err=0.0014,
                target_threshold=0.05,
                operator="<=",
                passed=True,
                p_value_estimate=0.0012,
            ),
            "packet_drop_rate": MetricAggregate(
                metric_name="packet_drop_rate",
                sample_values=[0.05, 0.04, 0.06],
                mean=0.050,
                std_dev=0.010,
                std_err=0.005,
                target_threshold=0.15,
                operator="<=",
                passed=True,
            ),
        },
        seed_runs=[
            SeedRunSummary(seed=42, run_id="run_42", exit_code=0, verification_status="PASS", metrics={"tracking_rmse": 0.038}),
            SeedRunSummary(seed=101, run_id="run_101", exit_code=0, verification_status="PASS", metrics={"tracking_rmse": 0.041}),
            SeedRunSummary(seed=2024, run_id="run_2024", exit_code=0, verification_status="PASS", metrics={"tracking_rmse": 0.036}),
        ],
        summary_rationale="Multi-seed evaluation confirmed tracking error reduction below target 0.05 across all 3 seeds with p < 0.01.",
    )

    synthesis = CrossPaperSynthesis(
        synthesis_id="synth-01",
        topic="Telepresence Latency Management",
        analyzed_paper_ids=["paper_tele_01", "paper_tele_02"],
        identified_gaps=[
            ResearchGap(
                gap_id="gap-jitter-divergence",
                description="Packet arrival jitter causes significant tracking divergence in telepresence master-slave loops.",
                evidence_paper_ids=["paper_tele_01"],
                impact_potential="Essential for bilateral teleoperation over non-deterministic WANs.",
            )
        ],
    )

    sample_papers = [
        PaperMetadata(
            paper_id="paper_tele_01",
            title="Analysis of Jitter in Haptic Telepresence Over WAN",
            authors=["Alice Smith", "Bob Jones"],
            year=2020,
            venue="IEEE Transactions on Haptics",
        )
    ]

    compiler = ManuscriptCompiler(run_id=run_id, output_dir=manuscript_dir)
    bundle = compiler.compile(
        hypothesis=hyp,
        spec=spec,
        evaluation=eval_report,
        synthesis=synthesis,
        papers=sample_papers,
    )

    assert Path(bundle.markdown_path).exists()
    assert Path(bundle.latex_path).exists()
    assert Path(bundle.bibtex_path).exists()
    assert bundle.word_count > 300

    md_content = Path(bundle.markdown_path).read_text(encoding="utf-8")
    tex_content = Path(bundle.latex_path).read_text(encoding="utf-8")
    bib_content = Path(bundle.bibtex_path).read_text(encoding="utf-8")

    # Check Markdown contents
    assert "## Abstract" in md_content
    assert "CONFIRMED" in md_content
    assert "tracking_rmse" in md_content
    assert "0.0383" in md_content
    assert "No close match was identified within the examined literature corpus" in md_content
    assert "[@smith2020" in md_content

    # Check LaTeX contents
    assert "\\documentclass" in tex_content
    assert "\\begin{abstract}" in tex_content
    assert "\\cite{smith2020" in tex_content
    assert "\\begin{table}" in tex_content
    assert "\\bibliography{references}" in tex_content

    # Check BibTeX contents
    assert "@article{smith2020" in bib_content
    assert "Alice Smith and Bob Jones" in bib_content

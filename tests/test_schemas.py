"""Tests for typed domain artifacts in Research OS."""

import json
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from research_os.schemas.paper import (
    ExtractedEquation,
    PaperExtraction,
    PaperMetadata,
    SectionProvenance,
)
from research_os.schemas.synthesis import CrossPaperSynthesis, ResearchGap
from research_os.schemas.hypothesis import HypothesisProposal, MechanismProvenance
from research_os.schemas.experiment import ExperimentSpec, HardwareRequirements
from research_os.schemas.verification import (
    MetricVerification,
    VerificationReport,
    VerificationStatus,
)
from research_os.schemas.gate import GateKind, GateStatus, HumanGateToken


def test_paper_metadata_roundtrip():
    meta = PaperMetadata(
        paper_id="arxiv:2410.23166",
        title="SciPIP: Scientific Paper Idea Proposer",
        authors=["Alice Smith", "Bob Jones"],
        abstract="We propose an automated idea proposer...",
        year=2024,
        venue="EMNLP",
        arxiv_id="2410.23166",
        citation_count=12,
    )
    # JSON roundtrip
    json_str = meta.to_json()
    meta_from_json = PaperMetadata.from_json(json_str)
    assert meta_from_json == meta

    # YAML roundtrip
    yaml_str = meta.to_yaml()
    meta_from_yaml = PaperMetadata.from_yaml(yaml_str)
    assert meta_from_yaml == meta


def test_paper_extraction_with_provenance():
    prov = SectionProvenance(
        source_paper_id="p1",
        section_title="3. Methodology",
        section_index=2,
        page_start=3,
        page_end=5,
        text_snippet="We define our contrastive objective as L_c...",
    )
    eq = ExtractedEquation(
        equation_id="eq_1",
        latex=r"\mathcal{L} = -\log \frac{\exp(s)}{\sum \exp(s)}",
        description="InfoNCE loss formulation",
        provenance=prov,
    )
    meta = PaperMetadata(
        paper_id="p1",
        title="Contrastive Learning for Scientific Texts",
        authors=["Carol White"],
    )
    extraction = PaperExtraction(
        extraction_id="ext-01",
        paper_id="p1",
        metadata=meta,
        sections={"3. Methodology": "We define our contrastive objective..."},
        section_provenance=[prov],
        equations=[eq],
        algorithms=["Algorithm 1: Momentum Contrast"],
        key_findings=["Contrastive loss outperforms baseline by 4.2%"],
        limitations=["High memory requirements for large batch sizes"],
        source_checksum="a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890",
    )

    yaml_str = extraction.to_yaml()
    restored = PaperExtraction.from_yaml(yaml_str)
    assert restored.extraction_id == "ext-01"
    assert len(restored.equations) == 1
    assert restored.equations[0].provenance.section_title == "3. Methodology"


def test_cross_paper_synthesis_and_gaps():
    prov1 = SectionProvenance(
        source_paper_id="p1",
        section_title="5. Discussion",
        text_snippet="Context window scaling remains bottlenecked by quadratic memory.",
    )
    gap = ResearchGap(
        gap_id="gap-01",
        description="Quadratic self-attention complexity prevents processing whole paper suites.",
        evidence_paper_ids=["p1", "p2"],
        evidence_citations=[prov1],
        impact_potential="Enables whole-corpus in-context learning without retrieval fragmentation.",
    )
    synthesis = CrossPaperSynthesis(
        synthesis_id="synth-01",
        topic="Efficient Context Scaling in Scientific LLMs",
        analyzed_paper_ids=["p1", "p2", "p3"],
        identified_gaps=[gap],
        consensus_findings=["Standard Transformer self-attention fails past 32k tokens on commodity GPUs."],
        contested_claims=["Whether linear attention preserves mathematical reasoning fidelity."],
    )

    json_str = synthesis.to_json()
    restored = CrossPaperSynthesis.from_json(json_str)
    assert len(restored.identified_gaps) == 1
    assert restored.identified_gaps[0].gap_id == "gap-01"


def test_hypothesis_proposal():
    mech = MechanismProvenance(
        source_paper_id="seed-rl-01",
        paper_title="Proximal Policy Optimization",
        domain="RL",
        borrowed_aspect="Clipped surrogate objective to bound policy drift",
    )
    hyp = HypothesisProposal(
        hypothesis_id="hyp-01",
        title="Surrogate Bounded Attention Routing",
        falsifiable_statement="Applying clipped surrogate objectives to MoE routing reduces expert collapse by >= 15% with zero accuracy regression.",
        baseline_method="Top-2 GShard routing",
        proposed_mechanism="PPO-inspired clipped gradient routing for sparse mixture of experts",
        theoretical_rationale="Bounds gradient variance across unbalanced token batches",
        inspired_by_seeds=[mech],
        target_metric="expert_load_entropy",
        expected_direction="increase",
        success_threshold=0.85,
        addressed_gap_id="gap-01",
    )

    yaml_str = hyp.to_yaml()
    restored = HypothesisProposal.from_yaml(yaml_str)
    assert restored.hypothesis_id == "hyp-01"
    assert restored.inspired_by_seeds[0].domain == "RL"


def test_experiment_spec():
    spec = ExperimentSpec(
        spec_id="exp-01",
        hypothesis_id="hyp-01",
        name="MoE Routing Stability Benchmark",
        entry_point="python run_benchmark.py",
        run_config={"batch_size": 32, "lr": 1e-4, "num_experts": 8},
        dependencies=["torch>=2.0.0", "numpy"],
        random_seeds=[42, 1337, 2026],
        expected_outputs=["metrics.json", "checkpoint.pt"],
        timeout_seconds=300,
        hardware_requirements=HardwareRequirements(
            cuda_required=False,
            min_ram_gb=4.0,
            max_cpu_cores=4,
        ),
    )

    json_str = spec.to_json()
    restored = ExperimentSpec.from_json(json_str)
    assert restored.spec_id == "exp-01"
    assert restored.random_seeds == [42, 1337, 2026]
    assert restored.timeout_seconds == 300


def test_verification_report():
    metric = MetricVerification(
        metric_name="val_loss",
        operator="<",
        target_threshold=1.5,
        observed_value=1.35,
        passed=True,
        notes="Loss reached 1.35 which is < 1.5",
    )
    report = VerificationReport(
        report_id="vr-01",
        spec_id="exp-01",
        run_id="run-01",
        exit_code=0,
        exit_code_passed=True,
        schema_compliance=True,
        missing_output_files=[],
        checksums={"metrics.json": "abcdef1234567890"},
        metric_evaluations=[metric],
        overall_status=VerificationStatus.PASS,
    )

    yaml_str = report.to_yaml()
    restored = VerificationReport.from_yaml(yaml_str)
    assert restored.overall_status == VerificationStatus.PASS
    assert restored.exit_code_passed is True


def test_human_gate_token_lifecycle():
    token = HumanGateToken(
        gate_id="gate-01",
        project_id="proj-moe",
        voyage_id="voyage-01",
        kind=GateKind.EXPERIMENT_LAUNCH,
        payload={"estimated_gpu_hours": 1.5, "budget_usd": 3.0},
    )
    assert token.status == GateStatus.PENDING
    assert not token.is_approved()

    # Approve
    token.approve(user="lead_architect", signature="sig_sha256_mock", notes="Approved for smoke test.")
    assert token.status == GateStatus.APPROVED
    assert token.is_approved()
    assert token.decided_by == "lead_architect"
    assert token.decided_at is not None

    # Test reject
    token2 = HumanGateToken(
        gate_id="gate-02",
        project_id="proj-moe",
        voyage_id="voyage-02",
        kind=GateKind.COMPUTE_BUDGET,
    )
    token2.reject(user="finance_lead", notes="Budget exceeded.")
    assert token2.status == GateStatus.REJECTED
    assert not token2.is_approved()


def test_strict_validation_forbids_extra_fields():
    with pytest.raises(ValidationError):
        PaperMetadata(
            paper_id="p1",
            title="Valid Title",
            unauthorized_extra_field="Should Fail",  # type: ignore[call-arg]
        )

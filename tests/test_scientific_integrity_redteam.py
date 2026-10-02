"""Red-Team Adversarial Test Suite for Research OS Phase 2 Epistemic Hardening.

Proves:
1. Mechanism Execution Contract: Bernoulli simulation mock fails RAG verification.
2. Statistical Honesty: Null p-value cannot render statistical significance claims.
3. Golden Rule of Statistics: Zero variance across seeds (SD = 0.0) blocks CONFIRMED verdict.
4. Metric Contract Boundary: Dynamic metric spoofing in metrics.json fails closed.
5. Triple SHA-256 Binding: Code modification after approval token aborts execution.
6. Numerical Consistency & Evidence Binding: Unbacked numerical claims in manuscript fail compilation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from research_os.core.integrity import EpistemicHonestyViolation, ScientificIntegrityLinter
from research_os.evaluation.evaluator import MultiSeedEvaluator, StatisticalEvaluator
from research_os.evaluation.statistics import compute_statistical_inference, student_t_p_value
from research_os.gate.approval import (
    HumanApprovalGate,
    canonicalize_gate_payload,
    compute_canonical_spec_hash,
    get_key_backend,
    verify_approval_token,
    NonceLedger,
)
from research_os.schemas.gate import GateKind, GateStatus, HumanGateToken
from research_os.manuscript.compiler import ManuscriptCompiler
from research_os.manuscript.latex_ast import ClaimNode, LatexRaw, LatexStatisticalClaim, LatexText, ProseSmuggledSignificanceError
from research_os.plugins.nlp.plugin import NLPPlugin
from research_os.sandbox.runner import (
    SandboxExecutionResult,
    SandboxRunner,
    SandboxSecurityViolation,
)
from research_os.schemas.experiment import (
    ExperimentModality,
    ExperimentSpec,
    ExperimentType,
    HardwareRequirements,
)
from research_os.schemas.evaluation import (
    EvaluationReport,
    HypothesisVerdict,
    MetricAggregate,
    SeedRunSummary,
    StatisticalAnalysisResult,
)
from research_os.schemas.hypothesis import HypothesisProposal
from research_os.schemas.mechanism import MechanismContract, MechanismEventRequirement
from research_os.schemas.verification import VerificationStatus
from research_os.verify.deterministic import DeterministicVerifier


# ==============================================================================
# TEST 1: Bernoulli Mock Fails RAG Mechanism Contract
# ==============================================================================
def test_redteam_bernoulli_simulation_fails_rag_mechanism_contract(tmp_path: Path):
    """Proves that a script running random Bernoulli sampling without emitting RAG trace events fails verification."""
    # 1. Setup RAG Mechanism Contract
    rag_contract = MechanismContract(
        modality=ExperimentModality.RAG,
        required_transitions=[
            MechanismEventRequirement(
                event_type="QUERY_IN",
                required_payload_fields=["query_id", "query_text"],
            ),
            MechanismEventRequirement(
                event_type="RETRIEVAL_INVOKED",
                required_payload_fields=["query_id"],
            ),
            MechanismEventRequirement(
                event_type="CANDIDATE_DOCS_RETRIEVED",
                required_payload_fields=["query_id", "doc_ids", "scores"],
            ),
            MechanismEventRequirement(
                event_type="CONTEXT_ASSEMBLED",
                required_payload_fields=["query_id", "context_length"],
            ),
            MechanismEventRequirement(
                event_type="MODEL_INFERENCE",
                required_payload_fields=["query_id", "input_tokens", "output_tokens"],
            ),
            MechanismEventRequirement(
                event_type="FACTUALITY_EVALUATION",
                required_payload_fields=["query_id", "hallucinated", "token_overlap"],
            ),
        ],
        min_event_count=6,
        enforce_strict_ordering=True,
        enforce_hash_chain=True,
    )

    spec = ExperimentSpec(
        spec_id="spec-rag-test-01",
        hypothesis_id="hyp-rag-01",
        experiment_type=ExperimentType.BENCHMARK,
        name="Empirical RAG Benchmark Evaluation",
        entry_point="python simulation.py",
        run_config={"target_metric": "hallucination_rate"},
        declared_metrics=["hallucination_rate", "latency_ms"],
        mechanism_contract=rag_contract,
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0, max_cpu_cores=2),
        timeout_seconds=30,
        random_seeds=[42],
        expected_outputs=["metrics.json", "trace.jsonl"],
    )

    # 2. Simulate adversarial runner: writes metrics.json with Bernoulli results, but NO trace.jsonl
    run_dir = tmp_path / "run_bernoulli_mock"
    run_dir.mkdir(parents=True)
    metrics_file = run_dir / "metrics.json"
    metrics_file.write_text(
        json.dumps({
            "hallucination_rate": 0.10,
            "latency_ms": 15.0,
            "status": "COMPLETED",
        }),
        encoding="utf-8",
    )

    # 3. Deterministic verification must FAIL CLOSED with MECHANISM_VIOLATION
    verifier = DeterministicVerifier(metrics_filename="metrics.json")
    report = verifier.verify_run(
        spec=spec,
        run_dir=run_dir,
        exit_code=0,
        run_id="run-bernoulli-01",
    )

    assert report.overall_status == VerificationStatus.MECHANISM_VIOLATION
    assert report.error_details is not None
    assert "Mechanism Violation" in report.error_details
    assert "trace" in report.error_details.lower()


# ==============================================================================
# TEST 2: Null p-value Blocks Statistical Significance Claims
# ==============================================================================
def test_redteam_null_pvalue_cannot_render_significance_claim(tmp_path: Path):
    """Injects p_value = None and verifies compiler & AST raise an exception if prose claims statistical significance."""
    run_id = "test-redteam-null-pvalue"
    manuscript_dir = tmp_path / "manuscript"

    hyp = HypothesisProposal(
        hypothesis_id="hyp-test-null-pval",
        title="Context Grounding in Factuality",
        falsifiable_statement="RAG reduces hallucination rate below 0.20 across benchmark.",
        baseline_method="Direct Generation",
        proposed_mechanism="BM25 Context Retrieval",
        theoretical_rationale="Parametric memory lacks real-time verified knowledge representations.",
        target_metric="hallucination_rate",
        expected_direction="decrease",
        success_threshold=0.20,
    )

    spec = ExperimentSpec(
        spec_id="spec-test-null-pval",
        hypothesis_id=hyp.hypothesis_id,
        experiment_type=ExperimentType.BENCHMARK,
        name="NLP Grounding Evaluation",
        entry_point="python run_benchmark.py",
        run_config={"target_metric": "hallucination_rate"},
        random_seeds=[42, 101, 2024],
        expected_outputs=["metrics.json"],
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0),
    )

    # Construct EvaluationReport with explicit p_value = None and significance_claim_allowed = False
    eval_report = EvaluationReport(
        evaluation_id="eval-null-pval",
        hypothesis_id=hyp.hypothesis_id,
        spec_id=spec.spec_id,
        seeds_evaluated=[42, 101, 2024],
        total_runs=3,
        successful_runs=3,
        failed_runs=0,
        verdict=HypothesisVerdict.INCONCLUSIVE,
        target_metric="hallucination_rate",
        metric_aggregates={
            "hallucination_rate": MetricAggregate(
                metric_name="hallucination_rate",
                sample_values=[0.18, 0.19, 0.17],
                mean=0.180,
                std_dev=0.010,
                std_err=0.0058,
                target_threshold=0.20,
                operator="<=",
                passed=True,
                p_value_estimate=None,  # Explicitly None
                significance_claim_allowed=False,  # Golden Rule of Statistics
            )
        },
        seed_runs=[
            SeedRunSummary(seed=42, run_id="r1", exit_code=0, verification_status="PASS", metrics={"hallucination_rate": 0.18}),
            SeedRunSummary(seed=101, run_id="r2", exit_code=0, verification_status="PASS", metrics={"hallucination_rate": 0.19}),
            SeedRunSummary(seed=2024, run_id="r3", exit_code=0, verification_status="PASS", metrics={"hallucination_rate": 0.17}),
        ],
        # Adversarial LLM injects unverified significance claim into prose:
        summary_rationale="The evaluation demonstrates a statistically significant reduction with p < 0.05.",
    )

    compiler = ManuscriptCompiler(run_id=run_id, output_dir=manuscript_dir)

    # Manuscript compilation MUST raise EpistemicHonestyViolation
    with pytest.raises(EpistemicHonestyViolation) as exc_info:
        compiler.compile(
            hypothesis=hyp,
            spec=spec,
            evaluation=eval_report,
        )

    assert "Statistical Honesty Violation" in str(exc_info.value)
    assert "p < 0.05" in str(exc_info.value) or "statistically significant" in str(exc_info.value)

    # Also prove that typed AST node LatexStatisticalClaim rejects rendering 'significance'
    with pytest.raises(ValueError) as val_exc:
        claim_node = LatexStatisticalClaim(
            metric_name="hallucination_rate",
            evidence_ref=eval_report,
            format_spec="significance",
        )
        claim_node.render()
    assert "Cannot render statistical significance claim" in str(val_exc.value)


# ==============================================================================
# TEST 3: Zero Variance Blocks Hypothesis Confirmation
# ==============================================================================
def test_redteam_zero_variance_blocks_hypothesis_confirmation():
    """Injects identical metrics across seeds (SD = 0.0000) and proves evaluator rejects CONFIRMED."""
    hyp = HypothesisProposal(
        hypothesis_id="hyp-zero-var-01",
        title="Zero Variance Determinism Test",
        falsifiable_statement="Algorithm achieves accuracy >= 0.85.",
        baseline_method="Random Baseline",
        proposed_mechanism="Deterministic Method",
        theoretical_rationale="Deterministic algorithms have fixed variance.",
        target_metric="accuracy",
        expected_direction="increase",
        success_threshold=0.85,
    )

    spec = ExperimentSpec(
        spec_id="spec-zero-var-01",
        hypothesis_id=hyp.hypothesis_id,
        experiment_type=ExperimentType.SIMULATION,
        name="Zero Variance Simulation",
        entry_point="python run_sim.py",
        run_config={"target_metric": "accuracy"},
        random_seeds=[42, 101, 2024],
        expected_outputs=["metrics.json"],
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0),
    )

    # Seeds have IDENTICAL outputs (SD = 0.0000, e.g. outcome-engineered mock)
    run_summaries = [
        SeedRunSummary(seed=42, run_id="r1", exit_code=0, verification_status="PASS", metrics={"accuracy": 0.90}),
        SeedRunSummary(seed=101, run_id="r2", exit_code=0, verification_status="PASS", metrics={"accuracy": 0.90}),
        SeedRunSummary(seed=2024, run_id="r3", exit_code=0, verification_status="PASS", metrics={"accuracy": 0.90}),
    ]

    evaluator = MultiSeedEvaluator()
    eval_report = evaluator.evaluate_runs(
        hypothesis=hyp,
        spec=spec,
        seed_runs=run_summaries,
    )

    # Golden Rule: Even though mean 0.90 >= 0.85, zero variance forces INCONCLUSIVE
    assert eval_report.verdict != HypothesisVerdict.CONFIRMED
    assert eval_report.verdict == HypothesisVerdict.INCONCLUSIVE

    target_agg = eval_report.metric_aggregates["accuracy"]
    assert target_agg.std_dev == 0.0
    assert target_agg.significance_claim_allowed is False
    assert target_agg.statistical_analysis is not None
    assert target_agg.statistical_analysis.variance == 0.0
    assert any("zero variance" in r.lower() for r in target_agg.statistical_analysis.reasons_significance_blocked)


# ==============================================================================
# TEST 4: Dynamic Metric Spoofing Rejected Fail-Closed
# ==============================================================================
def test_redteam_dynamic_metric_spoofing_rejected(tmp_path: Path):
    """Injects an unlisted metric dynamically into metrics.json and proves runner fails closed."""
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    # Contract declares only ["accuracy", "latency_ms"]
    spec = ExperimentSpec(
        spec_id="spec-metric-boundary-01",
        hypothesis_id="hyp-boundary-01",
        experiment_type=ExperimentType.BENCHMARK,
        name="Boundary Contract Test",
        entry_point="python run_adversarial.py --output-dir output",
        run_config={"target_metric": "accuracy"},
        declared_metrics=["accuracy", "latency_ms"],
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0, max_cpu_cores=2),
        timeout_seconds=30,
        random_seeds=[42],
        expected_outputs=["metrics.json"],
    )

    # Adversarial code dynamically outputs undeclared metric 'spoofed_f1_score' to output_dir
    adv_script = code_dir / "run_adversarial.py"
    adv_script.write_text(
        "import argparse, json, sys\n"
        "from pathlib import Path\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--output-dir', default='output')\n"
        "args = parser.parse_args()\n"
        "out = Path(args.output_dir) / 'metrics.json'\n"
        "out.write_text(json.dumps({\n"
        "    'accuracy': 0.92,\n"
        "    'latency_ms': 14.5,\n"
        "    'spoofed_f1_score': 0.99,\n"  # Undeclared metric spoofing!
        "}))\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )

    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id="run-boundary-01",
        auto_approve=True,
        code_dir=code_dir,
    )

    runner = SandboxRunner(default_timeout_seconds=30)

    # Runner MUST raise SandboxSecurityViolation
    with pytest.raises(SandboxSecurityViolation) as exc_info:
        runner.execute(
            spec=spec,
            gate_token=token,
            code_dir=code_dir,
            output_dir=output_dir,
        )

    assert "UndeclaredMetricSpoofingError" in str(exc_info.value)
    assert "spoofed_f1_score" in str(exc_info.value)


# ==============================================================================
# TEST 5: Tampered Code After Approval Fails Execution
# ==============================================================================
def test_redteam_tampered_code_after_approval_fails(tmp_path: Path):
    """Modifies 1 character in simulation.py after approval token issuance and verifies execution aborts."""
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    sim_file = code_dir / "simulation.py"
    sim_file.write_text("print('Authentic experiment')\n", encoding="utf-8")

    spec = ExperimentSpec(
        spec_id="spec-crypto-bind-01",
        hypothesis_id="hyp-crypto-01",
        experiment_type=ExperimentType.SIMULATION,
        name="Cryptographic Binding Test",
        entry_point="python simulation.py",
        run_config={"seed": 42},
        declared_metrics=["accuracy"],
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0, max_cpu_cores=2),
        timeout_seconds=30,
        random_seeds=[42],
        expected_outputs=["metrics.json"],
    )

    # Request approval token binding SHA256(spec), SHA256(code), SHA256(config)
    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id="run-crypto-01",
        auto_approve=True,
        code_dir=code_dir,
    )
    assert token.is_approved()

    # Adversarial tamper: append 1 space character to simulation.py after approval token is issued
    sim_file.write_text("print('Authentic experiment') \n", encoding="utf-8")

    runner = SandboxRunner(default_timeout_seconds=30)

    # Runner MUST abort BEFORE launching subprocess due to code SHA-256 mismatch
    with pytest.raises(PermissionError) as exc_info:
        runner.execute(
            spec=spec,
            gate_token=token,
            code_dir=code_dir,
            output_dir=output_dir,
        )

    err_str = str(exc_info.value).lower()
    assert "altered after approval" in err_str or "mismatch" in err_str or "code" in err_str


# ==============================================================================
# TEST 6: Manuscript AST Blocks Unbacked Numerical Claims
# ==============================================================================
def test_redteam_manuscript_ast_blocks_unbacked_numerical_claims(tmp_path: Path):
    """Attempts to inject an unbacked number (e.g. 99.9%) into a manuscript node and verifies compiler fails."""
    run_id = "test-redteam-unbacked-claims"
    manuscript_dir = tmp_path / "manuscript"

    hyp = HypothesisProposal(
        hypothesis_id="hyp-unbacked-01",
        title="Precision Retrieval Evaluation",
        falsifiable_statement="System achieves precision above 0.80.",
        baseline_method="Vanilla Search",
        proposed_mechanism="Dense Reranking",
        theoretical_rationale="Reranking improves top-k retrieval precision.",
        target_metric="precision",
        expected_direction="increase",
        success_threshold=0.80,
    )

    spec = ExperimentSpec(
        spec_id="spec-unbacked-01",
        hypothesis_id=hyp.hypothesis_id,
        experiment_type=ExperimentType.BENCHMARK,
        name="Precision Benchmark",
        entry_point="python run_bench.py",
        run_config={"target_metric": "precision"},
        random_seeds=[42, 101, 2024],
        expected_outputs=["metrics.json"],
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0),
    )

    eval_report = EvaluationReport(
        evaluation_id="eval-unbacked-01",
        hypothesis_id=hyp.hypothesis_id,
        spec_id=spec.spec_id,
        seeds_evaluated=[42, 101, 2024],
        total_runs=3,
        successful_runs=3,
        failed_runs=0,
        verdict=HypothesisVerdict.CONFIRMED,
        target_metric="precision",
        metric_aggregates={
            "precision": MetricAggregate(
                metric_name="precision",
                sample_values=[0.84, 0.86, 0.85],
                mean=0.850,
                std_dev=0.010,
                std_err=0.0058,
                target_threshold=0.80,
                operator=">=",
                passed=True,
                p_value_estimate=0.002,
                significance_claim_allowed=True,
            )
        },
        seed_runs=[
            SeedRunSummary(seed=42, run_id="r1", exit_code=0, verification_status="PASS", metrics={"precision": 0.84}),
            SeedRunSummary(seed=101, run_id="r2", exit_code=0, verification_status="PASS", metrics={"precision": 0.86}),
            SeedRunSummary(seed=2024, run_id="r3", exit_code=0, verification_status="PASS", metrics={"precision": 0.85}),
        ],
        # Adversarial claim: Injects 99.9% which does NOT exist anywhere in evidence artifacts
        summary_rationale="Evaluation confirms outstanding accuracy reaching 99.9% across all queries.",
    )

    compiler = ManuscriptCompiler(run_id=run_id, output_dir=manuscript_dir)

    # Compiler numerical consistency scanner MUST reject unbacked number 99.9
    with pytest.raises(EpistemicHonestyViolation) as exc_info:
        compiler.compile(
            hypothesis=hyp,
            spec=spec,
            evaluation=eval_report,
        )

    assert "NumericalConsistencyError" in str(exc_info.value)
    assert "99.9" in str(exc_info.value)

    # In addition: prove that LatexRaw blocks direct injection of statistical claims
    with pytest.raises(ValueError) as raw_exc:
        LatexRaw("The intervention produced a statistically significant effect ($p < 0.05$).")
    assert "Directive 4 Violation" in str(raw_exc.value)


# ==============================================================================
# TEST 7 (POSITIVE): Genuine NLP RAG Benchmark Passes Mechanism Contract & Verifier
# ==============================================================================
def test_positive_genuine_nlp_rag_benchmark_passes_mechanism_contract(tmp_path: Path):
    """Proves that genuine NLP RAG benchmark executes BM25 retrieval, logs trace.jsonl, and passes verifier."""
    plugin = NLPPlugin()
    hyp = HypothesisProposal(
        hypothesis_id="hyp-rag-genuine-01",
        title="Grounded BM25 Retrieval Evaluation",
        falsifiable_statement="Context grounding reduces hallucination rate below 0.25 across benchmark queries.",
        baseline_method="Direct Generation",
        proposed_mechanism="BM25 Knowledge Retrieval",
        theoretical_rationale="Contextual passage injection bounds parametric entity hallucination.",
        target_metric="hallucination_rate",
        expected_direction="decrease",
        success_threshold=0.25,
    )

    spec = plugin.plan_experiment(hyp, spec_requirements={"timeout_seconds": 30, "benchmark_size": 20})
    code = plugin.generate_experiment_code(spec)

    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    sim_file = code_dir / "run_benchmark.py"
    sim_file.write_text(code, encoding="utf-8")

    cfg_file = code_dir / "config.json"
    cfg_file.write_text(json.dumps(spec.run_config), encoding="utf-8")

    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id="run-rag-genuine-01",
        auto_approve=True,
        code_dir=code_dir,
    )
    assert token.is_approved()

    runner = SandboxRunner(default_timeout_seconds=30)
    res = runner.execute(
        spec=spec,
        gate_token=token,
        code_dir=code_dir,
        output_dir=output_dir,
    )
    assert res.exit_code == 0, f"Execution failed: {res.stderr}"

    # Verify observable trace artifact exists and passed cryptographic checks
    trace_file = output_dir / "trace.jsonl"
    assert trace_file.exists()
    assert trace_file.stat().st_size > 0

    from research_os.core.trace import verify_execution_trace
    valid_trace, trace_errors = verify_execution_trace(trace_file, spec.mechanism_contract)
    assert valid_trace is True, f"Trace verification failed: {trace_errors}"

    # Deterministic verifier pass
    verifier = DeterministicVerifier(metrics_filename="metrics.json")
    report = verifier.verify_run(
        spec=spec,
        run_dir=output_dir,
        exit_code=res.exit_code,
        run_id="run-rag-genuine-01",
        metric_targets={"hallucination_rate": ("<=", 0.25)},
    )
    assert report.overall_status == VerificationStatus.PASS
    assert report.exit_code_passed is True


# ==============================================================================
# AUDIT P0/P1 REMEDIATION RED-TEAM TEST SUITE (Tests 1 - 9)
# ==============================================================================

def test_redteam_self_signed_token_rejected(tmp_path: Path):
    """1. Token signed with an unpinned attacker key is rejected fail-closed."""
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    (code_dir / "sim.py").write_text("print('hello')", encoding="utf-8")

    spec = ExperimentSpec(
        spec_id="spec-attacker-01",
        hypothesis_id="hyp-att-01",
        experiment_type=ExperimentType.SIMULATION,
        name="Attacker Key Test",
        entry_point="python sim.py",
        run_config={"seed": 42},
        declared_metrics=["accuracy"],
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0),
        timeout_seconds=30,
        random_seeds=[42],
        expected_outputs=["metrics.json"],
    )

    attacker_key = ed25519.Ed25519PrivateKey.generate()
    attacker_pub_hex = attacker_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()

    trusted_backend = get_key_backend()
    trusted_pub_hex = trusted_backend.get_public_key_hex()
    assert attacker_pub_hex != trusted_pub_hex

    payload = {
        "spec_id": spec.spec_id,
        "hypothesis_id": spec.hypothesis_id,
        "canonical_spec_hash": compute_canonical_spec_hash(spec),
        "entry_point": spec.entry_point,
        "allowed_resources": {},
        "expiration_timestamp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "kind": GateKind.EXPERIMENT_LAUNCH.value,
        "nonce": "attacker-nonce-001",
    }
    msg_bytes = canonicalize_gate_payload(
        spec_id=spec.spec_id,
        hypothesis_id=spec.hypothesis_id,
        canonical_spec_hash=payload["canonical_spec_hash"],
        entry_point=spec.entry_point,
        allowed_resources={},
        expiration_timestamp=payload["expiration_timestamp"],
        approver_identity="attacker",
        additional_payload=payload,
    )
    sig_hex = attacker_key.sign(msg_bytes).hex()

    forged_token = HumanGateToken(
        gate_id="gate-forged-01",
        project_id="research-os",
        voyage_id=spec.spec_id,
        kind=GateKind.EXPERIMENT_LAUNCH,
        status=GateStatus.APPROVED,
        decided_by="attacker",
        authorization_signature=sig_hex,
        public_key_hex=attacker_pub_hex,
        payload=payload,
        user_notes="Self-signed attacker token",
        decided_at=datetime.now(timezone.utc),
    )

    # Verification against pinned trusted key fails
    assert not verify_approval_token(forged_token, expected_public_key_hex=trusted_pub_hex)

    # Runner execution is aborted
    runner = SandboxRunner(default_timeout_seconds=30)
    with pytest.raises(PermissionError) as exc_info:
        runner.execute(
            spec=spec,
            gate_token=forged_token,
            code_dir=code_dir,
            output_dir=output_dir,
        )
    err_msg = str(exc_info.value).lower()
    assert "gate violation" in err_msg or "self-signed" in err_msg or "unpinned" in err_msg or "invalid" in err_msg


def test_redteam_code_tree_mutation_rejected(tmp_path: Path):
    """2. Adding or modifying an auxiliary file after approval aborts execution."""
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    sim_file = code_dir / "simulation.py"
    sim_file.write_text("import helper\nprint(helper.get_val())\n", encoding="utf-8")
    helper_file = code_dir / "helper.py"
    helper_file.write_text("def get_val(): return 42\n", encoding="utf-8")

    spec = ExperimentSpec(
        spec_id="spec-tree-mutate-01",
        hypothesis_id="hyp-tree-01",
        experiment_type=ExperimentType.SIMULATION,
        name="Merkle Tree Mutation Test",
        entry_point="python simulation.py",
        run_config={"seed": 42},
        declared_metrics=["accuracy"],
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0),
        timeout_seconds=30,
        random_seeds=[42],
        expected_outputs=["metrics.json"],
    )

    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id="run-tree-01",
        auto_approve=True,
        code_dir=code_dir,
    )
    assert token.is_approved()

    # Adversarial mutation: Add auxiliary file backdoor after approval token issuance
    backdoor_file = code_dir / "backdoor.py"
    backdoor_file.write_text("import os; os.system('whoami')\n", encoding="utf-8")

    runner = SandboxRunner(default_timeout_seconds=30)
    with pytest.raises(PermissionError) as exc_info:
        runner.execute(
            spec=spec,
            gate_token=token,
            code_dir=code_dir,
            output_dir=output_dir,
        )
    err = str(exc_info.value).lower()
    assert "altered after approval" in err or "code" in err or "mismatch" in err


def test_redteam_nonce_replay_rejected(tmp_path: Path):
    """3. Replaying an approved token raises a replay error."""
    ledger_path = tmp_path / "custom_nonces.json"
    ledger = NonceLedger(ledger_path)

    spec = ExperimentSpec(
        spec_id="spec-nonce-replay-01",
        hypothesis_id="hyp-nonce-01",
        experiment_type=ExperimentType.SIMULATION,
        name="Nonce Replay Test",
        entry_point="python run.py",
        run_config={"seed": 42},
        declared_metrics=["accuracy"],
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0),
        timeout_seconds=30,
        random_seeds=[42],
        expected_outputs=["metrics.json"],
    )

    code_dir = tmp_path / "code"
    code_dir.mkdir(parents=True)
    (code_dir / "run.py").write_text("print('run')", encoding="utf-8")

    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id="run-nonce-01",
        auto_approve=True,
        code_dir=code_dir,
    )
    assert token.is_approved()

    # First consumption: valid
    assert verify_approval_token(token, expected_spec=spec, expected_code_dir=code_dir, consume_nonce=True, nonce_ledger=ledger)

    # Replay consumption with same token: must fail with replay attack PermissionError
    with pytest.raises(PermissionError) as exc_info:
        verify_approval_token(token, expected_spec=spec, expected_code_dir=code_dir, consume_nonce=True, nonce_ledger=ledger)
    assert "replay attack detected" in str(exc_info.value).lower()


def test_redteam_fabricated_trace_rejected(tmp_path: Path):
    """4. Incomplete query lifecycle, truncated trace, or forged trace events are caught."""
    from research_os.core.trace import TraceLogger, verify_execution_trace

    rag_contract = MechanismContract(
        modality=ExperimentModality.RAG,
        required_transitions=[
            MechanismEventRequirement(event_type="QUERY_IN", required_payload_fields=["query_id"]),
            MechanismEventRequirement(event_type="RETRIEVAL_INVOKED", required_payload_fields=["query_id"]),
            MechanismEventRequirement(event_type="CANDIDATE_DOCS_RETRIEVED", required_payload_fields=["query_id", "doc_ids"]),
            MechanismEventRequirement(event_type="CONTEXT_ASSEMBLED", required_payload_fields=["query_id"]),
            MechanismEventRequirement(event_type="MODEL_INFERENCE", required_payload_fields=["query_id"]),
            MechanismEventRequirement(event_type="FACTUALITY_EVALUATION", required_payload_fields=["query_id"]),
        ],
        min_event_count=6,
        enforce_strict_ordering=True,
        enforce_hash_chain=True,
    )

    # Incomplete lifecycle: query stops before MODEL_INFERENCE
    trace_dir = tmp_path / "trace_incomplete"
    trace_dir.mkdir(parents=True)
    trace_path = trace_dir / "trace.jsonl"
    logger = TraceLogger(trace_path)
    logger.log("QUERY_IN", {"query_id": "q-01", "query_text": "sample query"})
    logger.log("RETRIEVAL_INVOKED", {"query_id": "q-01"})
    logger.log("CANDIDATE_DOCS_RETRIEVED", {"query_id": "q-01", "doc_ids": ["doc-1"]})
    logger.log("CONTEXT_ASSEMBLED", {"query_id": "q-01", "context_length": 50})

    valid, reasons = verify_execution_trace(trace_path, rag_contract, corpus_doc_ids={"doc-1"})
    assert not valid
    assert any("PerQueryLifecycleViolation" in r or "Mechanism transition sequence incomplete" in r for r in reasons)

    # Forged trace event with broken hash chain
    lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
    tampered_record = json.loads(lines[1])
    tampered_record["payload"]["query_id"] = "forged-id"
    lines[1] = json.dumps(tampered_record)
    tampered_path = trace_dir / "tampered_trace.jsonl"
    tampered_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    valid_t, reasons_t = verify_execution_trace(tampered_path, rag_contract)
    assert not valid_t
    assert any("Trace integrity violation" in r or "Trace chain broken" in r for r in reasons_t)

    # Query count mismatch
    valid_c, reasons_c = verify_execution_trace(trace_path, rag_contract, expected_query_count=10)
    assert not valid_c
    assert any("QueryCountMismatch" in r for r in reasons_c)


def test_redteam_zero_variance_blocks_significance():
    """5. Identical seed/item outputs cannot claim p < 0.05 or statistical significance."""
    res = compute_statistical_inference(
        sample_values=[0.12, 0.12, 0.12, 0.12],
        target_threshold=0.20,
        operator="<=",
        metric_name="hallucination_rate",
        power_threshold=2,
    )
    assert res.variance == 0.0
    assert res.standard_deviation == 0.0
    assert res.significance_claim_allowed is False
    assert any("zero variance" in r.lower() for r in res.reasons_significance_blocked)

    from research_os.evaluation.statistics import compute_paired_item_inference
    paired_res = compute_paired_item_inference(
        treatment_items=[0.10, 0.10, 0.10],
        baseline_items=[0.25, 0.25, 0.25],
        metric_name="paired_delta",
    )
    assert paired_res.variance == 0.0
    assert paired_res.significance_claim_allowed is False
    assert any("zero variance" in r.lower() for r in paired_res.reasons_significance_blocked)


def test_redteam_scipy_p_value_reference_validation():
    """6. Validates t-test p-values match SciPy reference values within 10^-6 across t in [0.5, 2.0, 2.08, 4.3, 10] and df in [2, 4, 9, 29]."""
    import scipy.stats as stats

    t_values = [0.5, 2.0, 2.08, 4.3, 10.0]
    df_values = [2, 4, 9, 29]

    for t_val in t_values:
        for df in df_values:
            scipy_ref = float(2.0 * stats.t.sf(abs(t_val), df=df))
            computed_p = student_t_p_value(t_val, df=df)
            diff = abs(computed_p - scipy_ref)
            assert diff < 1e-6, f"SciPy reference divergence at t={t_val}, df={df}: computed {computed_p} != {scipy_ref} (diff {diff})"


def test_redteam_shuffled_retrieval_control_fails(tmp_path: Path):
    """7. Equivalent metrics under shuffled context trigger INVALID_ARTIFACT."""
    run_dir = tmp_path / "run_shuffled_fail"
    run_dir.mkdir(parents=True)

    spec = ExperimentSpec(
        spec_id="spec-shuf-ctrl-01",
        hypothesis_id="hyp-shuf-01",
        experiment_type=ExperimentType.BENCHMARK,
        name="Shuffled Control Failure Test",
        entry_point="python run.py",
        run_config={"target_metric": "hallucination_rate"},
        declared_metrics=["hallucination_rate", "shuffled_hallucination_rate", "baseline_hallucination_rate"],
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0),
        timeout_seconds=30,
        random_seeds=[42],
        expected_outputs=["metrics.json"],
    )

    metrics_file = run_dir / "metrics.json"
    metrics_file.write_text(
        json.dumps({
            "hallucination_rate": 0.15,
            "baseline_hallucination_rate": 0.50,
            "shuffled_hallucination_rate": 0.15,
            "status": "COMPLETED",
        }),
        encoding="utf-8",
    )

    verifier = DeterministicVerifier(metrics_filename="metrics.json")
    report = verifier.verify_run(
        spec=spec,
        run_dir=run_dir,
        exit_code=0,
        run_id="run-shuf-01",
    )

    assert report.overall_status == VerificationStatus.INVALID_ARTIFACT
    assert report.error_details is not None
    assert "negative control" in report.error_details.lower() or "shuffled" in report.error_details.lower()


def test_redteam_prose_smuggled_significance_rejected():
    """8. AST rejects prose containing unlinked p-values or significance claims."""
    forbidden_snippets = [
        "The improvement was statistically significant across trials.",
        "We achieved p < 0.05 on the primary benchmark.",
        "Significant reduction observed with p < .05.",
        "Model yielded p \\lt 0.05 under testing.",
        "Confirmed effect with p = 0.02.",
        "Statistical significance was confirmed by experiment.",
    ]

    for snippet in forbidden_snippets:
        with pytest.raises(ProseSmuggledSignificanceError) as exc_info:
            LatexText(snippet)
        assert "Statistical Honesty Violation" in str(exc_info.value)
        assert "ProseSmuggledSignificanceError" in str(exc_info.value)


def test_redteam_reduction_pct_uses_baseline():
    """9. Asserts correct relative reduction formula against baseline arm."""
    # ((Baseline - Treatment) / Baseline) * 100
    # Baseline = 0.40, Treatment = 0.10 -> Reduction = (0.40 - 0.10) / 0.40 * 100 = 75.0%
    # Never (1 - 0.10) * 100 = 90.0%
    node1 = ClaimNode(
        metric_id="hallucination_rate",
        role="reduction_pct",
        baseline_mean=0.40,
        treatment_mean=0.10,
        format_spec=".2f",
    )
    assert node1.render() == "75.00"

    node2 = ClaimNode(
        metric_id="hallucination_rate",
        role="reduction_pct",
        baseline_mean=0.20,
        treatment_mean=0.05,
        format_spec=".1f",
    )
    assert node2.render() == "75.0"

    from research_os.schemas.verification import MetricDerivation
    from research_os.verify.deterministic import recompute_metric_from_artifact
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as tf:
        tf.write(json.dumps({"baseline_h": 1.0, "treatment_h": 0.0}) + "\n")
        tf.write(json.dumps({"baseline_h": 1.0, "treatment_h": 0.0}) + "\n")
        tf.write(json.dumps({"baseline_h": 0.0, "treatment_h": 0.0}) + "\n")
        tf.write(json.dumps({"baseline_h": 1.0, "treatment_h": 1.0}) + "\n")
        t_path = Path(tf.name)

    deriv = MetricDerivation(
        operation="reduction_pct",
        target_field="treatment_h",
        baseline_field="baseline_h",
    )
    recomputed = recompute_metric_from_artifact(t_path, deriv)
    assert abs(recomputed - 66.666667) < 1e-4
    t_path.unlink()



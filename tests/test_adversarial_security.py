"""Adversarial security, cryptographic gate, and independent verification test suite."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from research_os.gate.approval import HumanApprovalGate, compute_canonical_spec_hash
from research_os.gate.token import HumanGateTokenManager
from research_os.planning.planner import ExperimentPlanner, UnsupportedDomainError
from research_os.sandbox.runner import (
    PolicySubprocessRunner,
    SandboxExecutionResult,
    SandboxRunner,
    SandboxSecurityViolation,
)
from research_os.schemas.experiment import ExperimentSpec, ExperimentType, HardwareRequirements
from research_os.schemas.gate import GateDecision, GateKind, GateStatus, HumanGateToken
from research_os.schemas.hypothesis import HypothesisProposal, MechanismProvenance
from research_os.schemas.verification import (
    MetricDerivation,
    RawArtifactReference,
    StructuredMetricRecord,
    VerificationReport,
    VerificationStatus,
)
from research_os.verify.deterministic import (
    DeterministicVerifier,
    MetricFabricationError,
    MissingRawArtifactError,
    ProvenanceIntegrityError,
    compute_file_sha256,
    create_run_manifest,
)


def _create_minimal_spec(spec_id: str = "spec-adv-01") -> ExperimentSpec:
    """Helper to construct a valid minimal ExperimentSpec."""
    return ExperimentSpec(
        spec_id=spec_id,
        hypothesis_id="hyp-adv-01",
        name="Adversarial Security Evaluation Protocol",
        experiment_type=ExperimentType.BENCHMARK,
        entry_point="python run_eval.py",
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0, max_cpu_cores=2),
        timeout_seconds=30,
        random_seeds=[42, 101, 2024],
        expected_outputs=["metrics.json", "provenance.json"],
        run_config={"mode": "adversarial_test"},
    )


def test_spec_tamper_after_approval_fails(tmp_path: Path):
    """Stage 1 Adversarial: Any spec modification after human approval signature aborts execution."""
    spec = _create_minimal_spec("spec-tamper-01")
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    script_path = code_dir / "run_eval.py"
    script_path.write_text("print('Executing simulation')\n", encoding="utf-8")

    # Issue genuine cryptographically signed approval token bound to spec
    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id="run-tamper-01",
        user="lead-architect",
        auto_approve=True,
    )
    assert token.is_approved()
    assert token.authorization_signature is not None

    runner = PolicySubprocessRunner()

    # Baseline execution with untouched spec succeeds
    res = runner.execute(spec, token, code_dir, output_dir)
    assert res.exit_code == 0

    # Adversarial Attack 1: Alter hardware constraints
    tampered_spec_ram = spec.model_copy(deep=True)
    tampered_spec_ram.hardware_requirements.min_ram_gb = 64.0

    with pytest.raises(PermissionError) as exc_info:
        runner.execute(tampered_spec_ram, token, code_dir, output_dir)
    assert "Spec altered after approval" in str(exc_info.value)

    # Adversarial Attack 2: Alter entry point
    tampered_spec_cmd = spec.model_copy(deep=True)
    tampered_spec_cmd.entry_point = "python malicious_entry.py"

    with pytest.raises(PermissionError) as exc_info:
        runner.execute(tampered_spec_cmd, token, code_dir, output_dir)
    assert "Spec altered after approval" in str(exc_info.value)


def test_fabricated_metric_discrepancy_rejected(tmp_path: Path):
    """Stage 3 Adversarial: Reported scalar metric is rejected when raw data recomputes differently."""
    run_dir = tmp_path / "run_fabrication"
    raw_data_dir = run_dir / "raw_data"
    raw_data_dir.mkdir(parents=True)

    # Write authentic raw records: 3 out of 4 items have is_hallucination=True (True rate = 0.75)
    raw_file = raw_data_dir / "predictions.jsonl"
    records = [
        {"id": 1, "is_hallucination": True},
        {"id": 2, "is_hallucination": True},
        {"id": 3, "is_hallucination": True},
        {"id": 4, "is_hallucination": False},
    ]
    raw_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    raw_sha = compute_file_sha256(raw_file)

    # Fabricate reported metric (declare 0.10 instead of 0.75)
    metrics_file = run_dir / "metrics.json"
    metrics_file.write_text(json.dumps({"hallucination_rate": 0.10, "status": "completed"}), encoding="utf-8")

    # Declare provenance linking to the raw file and mathematical derivation
    prov_file = run_dir / "provenance.json"
    prov_payload = {
        "metrics": {
            "hallucination_rate": {
                "reported_value": 0.10,
                "raw_artifact": {
                    "artifact_id": "art-pred-01",
                    "relative_path": "raw_data/predictions.jsonl",
                    "sha256": raw_sha,
                },
                "derivation": {
                    "operation": "fraction_where",
                    "target_field": "is_hallucination",
                    "condition": "==",
                    "target_value": True,
                },
            }
        }
    }
    prov_file.write_text(json.dumps(prov_payload, indent=2), encoding="utf-8")

    spec = _create_minimal_spec("spec-fab-01")
    verifier = DeterministicVerifier(require_provenance=True)
    report = verifier.verify_run(spec, run_dir, exit_code=0)

    # Verification must fail due to fabrication discrepancy
    assert report.overall_status == VerificationStatus.FAIL
    assert report.provenance_valid is False
    assert "MetricFabricationError" in str(report.error_details)
    assert "0.1" in str(report.error_details)
    assert "0.75" in str(report.error_details)


def test_missing_raw_artifact_fails(tmp_path: Path):
    """Stage 3 Adversarial: Provenance record pointing to non-existent raw artifact fails closed."""
    run_dir = tmp_path / "run_missing_raw"
    run_dir.mkdir(parents=True)

    metrics_file = run_dir / "metrics.json"
    metrics_file.write_text(json.dumps({"error_rate": 0.05}), encoding="utf-8")

    prov_file = run_dir / "provenance.json"
    prov_payload = {
        "metrics": {
            "error_rate": {
                "reported_value": 0.05,
                "raw_artifact": {
                    "artifact_id": "art-missing-01",
                    "relative_path": "raw_data/does_not_exist.csv",
                    "sha256": "abcdef123456",
                },
                "derivation": {
                    "operation": "mean",
                    "target_field": "error",
                },
            }
        }
    }
    prov_file.write_text(json.dumps(prov_payload, indent=2), encoding="utf-8")

    spec = _create_minimal_spec("spec-miss-01")
    verifier = DeterministicVerifier(require_provenance=True)
    report = verifier.verify_run(spec, run_dir, exit_code=0)

    assert report.overall_status == VerificationStatus.FAIL
    assert report.provenance_valid is False
    assert "MissingRawArtifactError" in str(report.error_details)


def test_post_run_artifact_tamper_detected(tmp_path: Path):
    """Stage 3 Adversarial: Modifying raw data after manifest creation is flagged as TAMPERED."""
    run_dir = tmp_path / "run_tamper_manifest"
    raw_data_dir = run_dir / "raw_data"
    raw_data_dir.mkdir(parents=True)

    # Create legitimate output
    raw_file = raw_data_dir / "telemetry.csv"
    raw_file.write_text("step,val\n1,10.0\n2,20.0\n", encoding="utf-8")
    raw_sha = compute_file_sha256(raw_file)

    metrics_file = run_dir / "metrics.json"
    metrics_file.write_text(json.dumps({"val_mean": 15.0}), encoding="utf-8")

    prov_file = run_dir / "provenance.json"
    prov_payload = {
        "metrics": {
            "val_mean": {
                "reported_value": 15.0,
                "raw_artifact": {
                    "artifact_id": "art-tele-01",
                    "relative_path": "raw_data/telemetry.csv",
                    "sha256": raw_sha,
                },
                "derivation": {
                    "operation": "mean",
                    "target_field": "val",
                },
            }
        }
    }
    prov_file.write_text(json.dumps(prov_payload, indent=2), encoding="utf-8")

    # Seal manifest immediately
    create_run_manifest(run_dir)

    spec = _create_minimal_spec("spec-tamper-manifest-01")
    verifier = DeterministicVerifier(require_provenance=True)

    # Baseline: initial verification passes
    initial_report = verifier.verify_run(spec, run_dir, exit_code=0)
    assert initial_report.overall_status == VerificationStatus.PASS

    # Adversarial Attack: Tamper with telemetry.csv post-run
    raw_file.write_text("step,val\n1,999.0\n2,999.0\n", encoding="utf-8")

    # Re-verify: must catch hash discrepancy and mark TAMPERED
    tampered_report = verifier.verify_run(spec, run_dir, exit_code=0)
    assert tampered_report.overall_status == VerificationStatus.TAMPERED
    assert "Tamper detected" in str(tampered_report.error_details)


def test_credential_exfiltration_blocked(tmp_path: Path):
    """Stage 2 Adversarial: Injected API keys, secret credentials, or banned tokens are rejected."""
    spec = _create_minimal_spec("spec-cred-01")
    code_dir = tmp_path / "code"
    output_dir = tmp_path / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    (code_dir / "run_eval.py").write_text("print('Safe script')\n", encoding="utf-8")

    gate = HumanApprovalGate()
    token = gate.request_approval(spec=spec, run_id="run-cred-01", auto_approve=True)

    runner = PolicySubprocessRunner()

    # Attack 1: Attempt to inject secret in environment overrides
    with pytest.raises(SandboxSecurityViolation) as exc_info:
        runner.execute(
            spec,
            token,
            code_dir,
            output_dir,
            env_overrides={"OPENAI_API_KEY": "sk-1234567890abcdef"},
        )
    assert "Credential Isolation Breach" in str(exc_info.value)

    # Attack 2: Attempt to pass secret via command argument
    spec_leaky = spec.model_copy(deep=True)
    spec_leaky.entry_point = "python run_eval.py --auth_token=BEARER_TOKEN_EXFIL"
    leaky_token = gate.request_approval(spec=spec_leaky, run_id="run-cred-02", auto_approve=True)

    with pytest.raises(SandboxSecurityViolation) as exc_info:
        runner.execute(spec_leaky, leaky_token, code_dir, output_dir)
    assert "Credential Exfiltration" in str(exc_info.value)


def test_unsupported_domain_refusal():
    """Stage 5 Adversarial: Non-registered domains fail closed with UNSUPPORTED_DOMAIN."""
    unsupported_hyp = HypothesisProposal(
        hypothesis_id="hyp-quantum-chem-01",
        title="VQE Ground State Energy of Beryllium Hydride",
        falsifiable_statement="Unitary Coupled Cluster ansatz converges to within 1 milli-Hartree of FCI energy.",
        baseline_method="Hartree-Fock Mean Field",
        proposed_mechanism="Variational Quantum Eigensolver with UCCSD parameterization.",
        theoretical_rationale="Quantum entanglement models electron correlation more accurately than classical approximations.",
        inspired_by_seeds=[
            MechanismProvenance(
                source_paper_id="paper-chem-01",
                paper_title="Quantum Chemistry in the Age of Quantum Computing",
                domain="Quantum Chemistry",
                borrowed_aspect="UCCSD Ansatz",
            )
        ],
        target_metric="energy_error_hartree",
        expected_direction="decrease",
        success_threshold=0.001,
    )

    planner = ExperimentPlanner()
    with pytest.raises(UnsupportedDomainError) as exc_info:
        planner.plan_experiment(unsupported_hyp)

    assert exc_info.value.status == "UNSUPPORTED_DOMAIN"
    assert "not supported" in str(exc_info.value).lower()

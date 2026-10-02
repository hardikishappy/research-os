"""Adversarial Red-Team Test Suite for Just-in-Time (JIT) Domain Plugins.

Enforces:
1. test_unapproved_staged_plugin_rejected: Staged plugin without signature fails admission.
2. test_tampered_staged_plugin_rejected: Modify generator.py after Ed25519 signing; assert admission fails closed.
3. test_unsupported_verification_primitive_fails: Attempt synthesizing a plugin with a custom Python function or
   unsupported op ("operation": "arbitrary_eval"); assert UNSUPPORTED_VERIFICATION_PRIMITIVE.
4. test_plugin_cannot_tamper_core_verification: A synthesized plugin writes an experiment script attempting to overwrite
   provenance.json or alter manifest signature; assert DeterministicVerifier detects and fails with VerificationStatus.TAMPERED.
5. test_self_referential_fabrication_prevented: A synthesized plugin attempts to report false metrics; assert core
   verifier recomputes from raw logs and fails with MetricFabricationError.
6. Additional security boundary tests: staging inside src/ prevented, malicious AST injection rejected.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from research_os.domains.declarative import (
    DeclarativeMetricDef,
    DeclarativePluginSpec,
    UnsupportedVerificationPrimitiveError,
    recompute_declarative_metric,
)
from research_os.domains.registry import (
    DeclarativeDomainPluginAdapter,
    DomainRegistry,
    SecurityViolationError,
)
from research_os.gate.plugin_approval import (
    create_plugin_approval_token,
    verify_plugin_approval_token,
)
from research_os.plugins.staging import (
    build_default_generator_code,
    synthesize_staged_plugin,
    validate_staging_path,
)
from research_os.schemas.experiment import ExperimentSpec, ExperimentType
from research_os.schemas.hypothesis import HypothesisProposal
from research_os.schemas.verification import VerificationStatus
from research_os.verify.deterministic import (
    DeterministicVerifier,
    MetricFabricationError,
    create_run_manifest,
)


def _generate_test_keypair() -> tuple[ed25519.Ed25519PrivateKey, str]:
    """Generate fresh Ed25519 keypair for test signing."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, pub_bytes.hex()


def test_unapproved_staged_plugin_rejected(tmp_path: Path):
    """Test 1: Staged plugin without cryptographic approval token fails admission."""
    staged_base = tmp_path / "staged_plugins"
    domain_dir = synthesize_staged_plugin(
        domain_id="optics_photonics",
        staging_base_dir=staged_base,
        supported_metrics=["beam_quality_factor"],
    )

    registry = DomainRegistry()
    _, pub_hex = _generate_test_keypair()

    # Attempt to load plugin before human gate has signed it
    with pytest.raises(PermissionError) as exc_info:
        registry.load_staged_plugin(domain_dir, expected_public_key=pub_hex)

    assert "Missing plugin approval token" in str(exc_info.value) or "unapproved" in str(exc_info.value).lower()
    assert "optics_photonics" not in registry.list_domains()


def test_tampered_staged_plugin_rejected(tmp_path: Path):
    """Test 2: Modifying generator.py or plugin.json after Ed25519 signing fails closed with PermissionError."""
    staged_base = tmp_path / "staged_plugins"
    domain_dir = synthesize_staged_plugin(
        domain_id="plasma_kinetics",
        staging_base_dir=staged_base,
        supported_metrics=["electron_temperature"],
    )

    priv_key, pub_hex = _generate_test_keypair()

    # Legitimate signing at gate
    token = create_plugin_approval_token(
        staged_dir=domain_dir,
        approver_identity="Chief Scientist",
        private_key=priv_key,
    )
    assert token.public_key_hex == pub_hex
    assert (domain_dir / "plugin_approval.token").exists()

    # Prior to tampering, verification succeeds
    assert verify_plugin_approval_token(domain_dir, expected_public_key=pub_hex) is True

    # Tamper 2A: Alter generator.py post-approval
    generator_file = domain_dir / "generator.py"
    original_code = generator_file.read_text(encoding="utf-8")
    tampered_code = original_code + "\n# MALICIOUS INJECTION COMMENT\n"
    generator_file.write_text(tampered_code, encoding="utf-8")

    registry = DomainRegistry()
    with pytest.raises(PermissionError) as exc_info:
        registry.load_staged_plugin(domain_dir, expected_public_key=pub_hex)

    assert "Plugin tampered post-approval" in str(exc_info.value)
    assert "plasma_kinetics" not in registry.list_domains()

    # Restore generator.py
    generator_file.write_text(original_code, encoding="utf-8")
    assert verify_plugin_approval_token(domain_dir, expected_public_key=pub_hex) is True

    # Tamper 2B: Alter plugin.json post-approval (e.g. relaxing verification primitives)
    plugin_file = domain_dir / "plugin.json"
    spec_data = json.loads(plugin_file.read_text(encoding="utf-8"))
    spec_data["supported_metrics"].append("unauthorized_metric")
    plugin_file.write_text(json.dumps(spec_data, indent=2), encoding="utf-8")

    with pytest.raises(PermissionError) as exc_info_json:
        registry.load_staged_plugin(domain_dir, expected_public_key=pub_hex)

    assert "Plugin tampered post-approval" in str(exc_info_json.value)


def test_unsupported_verification_primitive_fails(tmp_path: Path):
    """Test 3: Attempting to define or synthesize a plugin with custom Python code or unsupported ops fails closed."""
    # Sub-case 3A: Unsupported operation string in DeclarativeMetricDef
    with pytest.raises(UnsupportedVerificationPrimitiveError) as exc_info_op:
        DeclarativeMetricDef(
            metric_id="bad_metric",
            raw_artifact_file="raw_data/telemetry.json",
            operation="arbitrary_eval",  # type: ignore
            target_field="val",
            unit="unitless",
        )
    assert "UNSUPPORTED_VERIFICATION_PRIMITIVE: Op not in trusted core" in str(exc_info_op.value)

    # Sub-case 3B: Executable Python snippet or eval-like operation
    with pytest.raises(UnsupportedVerificationPrimitiveError) as exc_info_py:
        DeclarativeMetricDef(
            metric_id="exec_metric",
            raw_artifact_file="raw_data/telemetry.json",
            operation="eval_lambda",  # type: ignore
            target_field="val",
            unit="unitless",
        )
    assert "UNSUPPORTED_VERIFICATION_PRIMITIVE: Op not in trusted core" in str(exc_info_py.value)

    # Sub-case 3C: Synthesis with invalid operation in verification primitives raises immediately
    staged_base = tmp_path / "staged_plugins"
    with pytest.raises(UnsupportedVerificationPrimitiveError):
        synthesize_staged_plugin(
            domain_id="unsupported_op_domain",
            staging_base_dir=staged_base,
            verification_primitives={
                "custom_op": DeclarativeMetricDef(
                    metric_id="custom_op",
                    raw_artifact_file="raw.json",
                    operation="arbitrary_code_exec",  # type: ignore
                    target_field="x",
                )
            },
        )


def test_plugin_cannot_tamper_core_verification(tmp_path: Path):
    """Test 4: Experiment script attempting to overwrite provenance.json or alter manifest signature is flagged TAMPERED."""
    run_dir = tmp_path / "run_tamper_experiment"
    raw_dir = run_dir / "raw_data"
    raw_dir.mkdir(parents=True)

    # Legitimate simulation outputs
    raw_file = raw_dir / "sensor_log.json"
    raw_data = [{"step": 1, "reading": 10.0}, {"step": 2, "reading": 20.0}]
    raw_file.write_text(json.dumps(raw_data), encoding="utf-8")

    (run_dir / "metrics.json").write_text(json.dumps({"mean_reading": 15.0}), encoding="utf-8")

    prov_payload = {
        "metrics": {
            "mean_reading": {
                "reported_value": 15.0,
                "raw_artifact": {
                    "artifact_id": "art-sensor-01",
                    "relative_path": "raw_data/sensor_log.json",
                },
                "derivation": {
                    "operation": "mean",
                    "target_field": "reading",
                },
            }
        }
    }
    (run_dir / "provenance.json").write_text(json.dumps(prov_payload, indent=2), encoding="utf-8")

    # Seal manifest with Ed25519 signature
    manifest_path = create_run_manifest(run_dir)
    assert manifest_path.exists()

    spec = ExperimentSpec(
        spec_id="spec-tamper-check",
        hypothesis_id="hyp-tamper-check",
        experiment_type=ExperimentType.SIMULATION,
        name="Tamper Verification Check",
        description="Verify that post-manifest file overwrites are caught",
        entry_point="python run.py",
        expected_outputs=["metrics.json", "provenance.json", "raw_data/sensor_log.json"],
    )

    verifier = DeterministicVerifier(require_provenance=True)

    # 4A: Baseline check passes
    baseline_report = verifier.verify_run(spec, run_dir, exit_code=0)
    assert baseline_report.overall_status == VerificationStatus.PASS

    # 4B: Malicious script attempts to overwrite provenance.json after manifest was sealed
    tampered_prov = {
        "metrics": {
            "mean_reading": {
                "reported_value": 999.0,
                "raw_artifact": {
                    "artifact_id": "art-sensor-01",
                    "relative_path": "raw_data/sensor_log.json",
                },
                "derivation": {
                    "operation": "mean",
                    "target_field": "reading",
                },
            }
        }
    }
    (run_dir / "provenance.json").write_text(json.dumps(tampered_prov, indent=2), encoding="utf-8")

    report_tampered_prov = verifier.verify_run(spec, run_dir, exit_code=0)
    assert report_tampered_prov.overall_status == VerificationStatus.TAMPERED
    assert "Tamper detected" in str(report_tampered_prov.error_details)
    assert "provenance.json" in str(report_tampered_prov.error_details)

    # 4C: Malicious script attempts to alter manifest.json signature
    create_run_manifest(run_dir)
    manifest_content = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_content["signature"] = "0" * 128
    manifest_path.write_text(json.dumps(manifest_content, indent=2), encoding="utf-8")

    report_tampered_manifest = verifier.verify_run(spec, run_dir, exit_code=0)
    assert report_tampered_manifest.overall_status == VerificationStatus.TAMPERED
    assert "Tamper detected" in str(report_tampered_manifest.error_details)


def test_self_referential_fabrication_prevented(tmp_path: Path):
    """Test 5: Synthesized plugin reporting false metrics is caught when verifier recomputes from raw logs."""
    staged_base = tmp_path / "staged_plugins"
    metric_id = "consensus_ratio"
    raw_rel_file = "raw_data/consensus_log.jsonl"
    target_field = "ratio"

    domain_dir = synthesize_staged_plugin(
        domain_id="consensus_theory",
        staging_base_dir=staged_base,
        supported_metrics=[metric_id],
        verification_primitives={
            metric_id: DeclarativeMetricDef(
                metric_id=metric_id,
                raw_artifact_file=raw_rel_file,
                operation="mean",
                target_field=target_field,
                unit="scalar",
                tolerance=1e-6,
            )
        },
    )

    priv_key, pub_hex = _generate_test_keypair()
    create_plugin_approval_token(staged_dir=domain_dir, approver_identity="Reviewer", private_key=priv_key)

    registry = DomainRegistry()
    plugin = registry.load_staged_plugin(domain_dir, expected_public_key=pub_hex)
    assert isinstance(plugin, DeclarativeDomainPluginAdapter)

    # Setup experiment run directory with fabricated metric
    run_dir = tmp_path / "run_fabricated_metric"
    raw_dir = run_dir / "raw_data"
    raw_dir.mkdir(parents=True)

    # Actual telemetry logs: mean = 0.40
    raw_file = run_dir / raw_rel_file
    raw_records = [
        {"id": 1, "ratio": 0.35},
        {"id": 2, "ratio": 0.45},
        {"id": 3, "ratio": 0.40},
    ]
    with open(raw_file, "w", encoding="utf-8") as f:
        for r in raw_records:
            f.write(json.dumps(r) + "\n")

    # True independent recomputation produces 0.40
    true_computed = recompute_declarative_metric(
        run_dir,
        plugin.spec.verification_primitives[metric_id],
    )
    assert abs(true_computed - 0.40) < 1e-6

    # Malicious/fabricated metric claimed by plugin execution
    fabricated_metrics = {
        metric_id: 0.95,  # Claimed 0.95 vs authentic 0.40
    }
    (run_dir / "metrics.json").write_text(json.dumps(fabricated_metrics), encoding="utf-8")

    # 5A: DeclarativeDomainPluginAdapter validation catches discrepancy
    prov_report = plugin.validate_metric_provenance(run_dir, fabricated_metrics)
    assert prov_report.is_valid is False
    assert len(prov_report.errors) > 0
    fabrication_errors = [e for e in prov_report.errors if "MetricFabricationError" in e]
    assert len(fabrication_errors) == 1
    assert "0.95" in fabrication_errors[0]
    assert "0.400000" in fabrication_errors[0]

    # 5B: DeterministicVerifier recomputes from raw provenance and fails with MetricFabricationError
    prov_payload = {
        "metrics": {
            metric_id: {
                "reported_value": 0.95,
                "raw_artifact": {
                    "artifact_id": f"art-{metric_id}",
                    "relative_path": raw_rel_file,
                },
                "derivation": {
                    "operation": "mean",
                    "target_field": target_field,
                },
            }
        }
    }
    (run_dir / "provenance.json").write_text(json.dumps(prov_payload, indent=2), encoding="utf-8")
    create_run_manifest(run_dir)

    spec = ExperimentSpec(
        spec_id="spec-fab-consensus",
        hypothesis_id="hyp-fab-consensus",
        experiment_type=ExperimentType.SIMULATION,
        name="Consensus Ratio Protocol",
        description="Verify that fabricated consensus ratio is rejected",
        entry_point="python sim.py",
        expected_outputs=["metrics.json", "provenance.json", raw_rel_file],
    )

    verifier = DeterministicVerifier(require_provenance=True)
    report = verifier.verify_run(spec, run_dir, exit_code=0)

    assert report.overall_status == VerificationStatus.FAIL
    assert report.provenance_valid is False
    assert "MetricFabricationError" in str(report.error_details)
    assert "0.95" in str(report.error_details)


def test_staging_isolation_breach_prevented():
    """Security Boundary: Synthesizing a plugin directly into src/ is strictly forbidden."""
    with pytest.raises(ValueError) as exc_info:
        validate_staging_path("src/research_os/plugins/malicious_domain")
    assert "Staging Isolation Breach" in str(exc_info.value)


def test_malicious_generator_ast_rejected(tmp_path: Path):
    """Security Boundary: Generator script containing unsafe imports/calls is rejected by AST scanner."""
    staged_base = tmp_path / "staged_plugins"
    domain_dir = synthesize_staged_plugin(
        domain_id="unsafe_domain",
        staging_base_dir=staged_base,
        generator_code="""\"\"\"Unsafe generator.\"\"\"
import os
import subprocess

def generate_code(spec):
    os.system("rm -rf /")
    return "print('pwned')"
""",
    )

    priv_key, pub_hex = _generate_test_keypair()
    create_plugin_approval_token(staged_dir=domain_dir, approver_identity="Admin", private_key=priv_key)

    registry = DomainRegistry()
    with pytest.raises(SecurityViolationError) as exc_info:
        registry.load_staged_plugin(domain_dir, expected_public_key=pub_hex)

    assert "Forbidden module import: 'subprocess'" in str(exc_info.value)

"""Tests for the deterministic verification engine in Research OS."""

import json
from pathlib import Path
import pytest
from pydantic import BaseModel, Field

from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.verification import VerificationStatus
from research_os.verify.deterministic import (
    DeterministicVerifier,
    compute_directory_checksums,
    compute_file_sha256,
    evaluate_metric_condition,
)


def test_compute_file_sha256(tmp_path: Path):
    test_file = tmp_path / "sample.txt"
    test_file.write_text("Hello Research OS Deterministic World!", encoding="utf-8")

    digest1 = compute_file_sha256(test_file)
    assert len(digest1) == 64
    assert isinstance(digest1, str)

    # Identical content yields identical hash
    test_file2 = tmp_path / "sample_copy.txt"
    test_file2.write_text("Hello Research OS Deterministic World!", encoding="utf-8")
    assert compute_file_sha256(test_file2) == digest1

    # Modified content yields different hash
    test_file3 = tmp_path / "sample_diff.txt"
    test_file3.write_text("Different content", encoding="utf-8")
    assert compute_file_sha256(test_file3) != digest1


def test_compute_directory_checksums(tmp_path: Path):
    sub = tmp_path / "artifacts"
    sub.mkdir()
    (sub / "a.txt").write_text("File A", encoding="utf-8")
    (sub / "b.json").write_text('{"key": "value"}', encoding="utf-8")

    checksums = compute_directory_checksums(sub)
    assert "a.txt" in checksums
    assert "b.json" in checksums
    assert len(checksums["a.txt"]) == 64


def test_evaluate_metric_condition():
    assert evaluate_metric_condition(0.95, 0.90, ">") is True
    assert evaluate_metric_condition(0.85, 0.90, ">") is False

    assert evaluate_metric_condition(1.2, 1.5, "<") is True
    assert evaluate_metric_condition(1.6, 1.5, "<") is False

    assert evaluate_metric_condition(0.90, 0.90, ">=") is True
    assert evaluate_metric_condition(0.91, 0.90, ">=") is True
    assert evaluate_metric_condition(0.89, 0.90, ">=") is False

    assert evaluate_metric_condition(0.50, 0.50, "<=") is True
    assert evaluate_metric_condition(0.49, 0.50, "<=") is True
    assert evaluate_metric_condition(0.51, 0.50, "<=") is False

    assert evaluate_metric_condition(0.5000001, 0.5000000, "==") is True
    assert evaluate_metric_condition(0.51, 0.50, "==") is False

    with pytest.raises(ValueError):
        evaluate_metric_condition(1.0, 1.0, "!=")


def test_verifier_pass_scenario(tmp_path: Path):
    run_dir = tmp_path / "run_success"
    run_dir.mkdir()

    raw_dir = run_dir / "raw_data"
    raw_dir.mkdir()
    raw_file = raw_dir / "eval_log.csv"
    raw_file.write_text("loss,acc,throughput\n0.42,0.94,120.5\n", encoding="utf-8")
    raw_sha = compute_file_sha256(raw_file)

    metrics_file = run_dir / "metrics.json"
    metrics_file.write_text(json.dumps({
        "eval_loss": 0.42,
        "accuracy": 0.94,
        "throughput": 120.5
    }), encoding="utf-8")

    prov_file = run_dir / "provenance.json"
    prov_file.write_text(json.dumps({
        "metrics": {
            "eval_loss": {
                "reported_value": 0.42,
                "raw_artifact": {"relative_path": "raw_data/eval_log.csv", "sha256": raw_sha},
                "derivation": {"operation": "mean", "target_field": "loss"},
            },
            "accuracy": {
                "reported_value": 0.94,
                "raw_artifact": {"relative_path": "raw_data/eval_log.csv", "sha256": raw_sha},
                "derivation": {"operation": "mean", "target_field": "acc"},
            },
            "throughput": {
                "reported_value": 120.5,
                "raw_artifact": {"relative_path": "raw_data/eval_log.csv", "sha256": raw_sha},
                "derivation": {"operation": "mean", "target_field": "throughput"},
            },
        }
    }, indent=2), encoding="utf-8")

    model_file = run_dir / "checkpoint.pt"
    model_file.write_bytes(b"DUMMY_MODEL_WEIGHTS")

    spec = ExperimentSpec(
        spec_id="exp-01",
        hypothesis_id="hyp-01",
        name="Successful Run Test",
        entry_point="python main.py",
        expected_outputs=["metrics.json", "checkpoint.pt", "provenance.json"],
    )

    verifier = DeterministicVerifier(metrics_filename="metrics.json")
    report = verifier.verify_run(
        spec=spec,
        run_dir=run_dir,
        exit_code=0,
        metric_targets={
            "eval_loss": ("<", 0.50),
            "accuracy": (">=", 0.90),
        },
    )

    assert report.overall_status == VerificationStatus.PASS
    assert report.exit_code_passed is True
    assert len(report.missing_output_files) == 0
    assert report.schema_compliance is True
    assert len(report.metric_evaluations) == 2
    assert all(m.passed for m in report.metric_evaluations)
    assert "metrics.json" in report.checksums
    assert "checkpoint.pt" in report.checksums
    assert report.error_details is None


def test_verifier_exit_code_failure(tmp_path: Path):
    run_dir = tmp_path / "run_fail"
    run_dir.mkdir()
    (run_dir / "metrics.json").write_text("{}", encoding="utf-8")

    spec = ExperimentSpec(
        spec_id="exp-02",
        hypothesis_id="hyp-01",
        name="Exit Code Failure",
        entry_point="python main.py",
        expected_outputs=["metrics.json"],
    )

    verifier = DeterministicVerifier()
    report = verifier.verify_run(spec=spec, run_dir=run_dir, exit_code=137)

    assert report.overall_status == VerificationStatus.FAIL
    assert report.exit_code_passed is False
    assert "non-zero exit code: 137" in report.error_details  # type: ignore[operator]


def test_verifier_missing_outputs_failure(tmp_path: Path):
    run_dir = tmp_path / "run_missing"
    run_dir.mkdir()

    spec = ExperimentSpec(
        spec_id="exp-03",
        hypothesis_id="hyp-01",
        name="Missing Outputs",
        entry_point="python main.py",
        expected_outputs=["metrics.json", "weights.bin"],
    )

    verifier = DeterministicVerifier()
    report = verifier.verify_run(spec=spec, run_dir=run_dir, exit_code=0)

    assert report.overall_status == VerificationStatus.FAIL
    assert "metrics.json" in report.missing_output_files
    assert "weights.bin" in report.missing_output_files


def test_verifier_metric_threshold_failure(tmp_path: Path):
    run_dir = tmp_path / "run_bad_metric"
    run_dir.mkdir()

    (run_dir / "metrics.json").write_text(json.dumps({
        "accuracy": 0.82
    }), encoding="utf-8")

    spec = ExperimentSpec(
        spec_id="exp-04",
        hypothesis_id="hyp-01",
        name="Bad Metric Value",
        entry_point="python main.py",
        expected_outputs=["metrics.json"],
    )

    verifier = DeterministicVerifier()
    report = verifier.verify_run(
        spec=spec,
        run_dir=run_dir,
        exit_code=0,
        metric_targets={"accuracy": (">=", 0.90)},
    )

    assert report.overall_status == VerificationStatus.FAIL
    assert len(report.metric_evaluations) == 1
    assert report.metric_evaluations[0].passed is False
    assert report.metric_evaluations[0].observed_value == 0.82


def test_verifier_schema_validation(tmp_path: Path):
    run_dir = tmp_path / "run_schema_test"
    run_dir.mkdir()

    class ExpectedMetrics(BaseModel):
        loss: float
        epochs: int
        model_name: str

    # Valid schema run
    (run_dir / "metrics.json").write_text(json.dumps({
        "loss": 0.25,
        "epochs": 10,
        "model_name": "transformer-small"
    }), encoding="utf-8")

    spec = ExperimentSpec(
        spec_id="exp-05",
        hypothesis_id="hyp-01",
        name="Schema Test",
        entry_point="python main.py",
        expected_outputs=["metrics.json"],
    )

    verifier = DeterministicVerifier(require_provenance=False)
    report_valid = verifier.verify_run(
        spec=spec,
        run_dir=run_dir,
        exit_code=0,
        metric_schema=ExpectedMetrics,
        require_provenance=False,
    )
    assert report_valid.overall_status == VerificationStatus.PASS
    assert report_valid.schema_compliance is True

    # Invalid schema run (missing field and bad type)
    (run_dir / "metrics.json").write_text(json.dumps({
        "loss": "not-a-number",
    }), encoding="utf-8")

    report_invalid = verifier.verify_run(
        spec=spec,
        run_dir=run_dir,
        exit_code=0,
        metric_schema=ExpectedMetrics,
        require_provenance=False,
    )
    assert report_invalid.overall_status == VerificationStatus.FAIL
    assert report_invalid.schema_compliance is False

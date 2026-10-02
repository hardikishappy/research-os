"""Verification report schemas for Research OS."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from pydantic import Field
from .base import ArtifactBaseModel


class VerificationStatus(str, Enum):
    """Overall outcome of a deterministic verification evaluation."""

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    TAMPERED = "TAMPERED"
    MECHANISM_VIOLATION = "MECHANISM_VIOLATION"
    INVALID_ARTIFACT = "INVALID_ARTIFACT"
    SEED_NOT_APPLIED = "SEED_NOT_APPLIED"


class RawArtifactReference(ArtifactBaseModel):
    """Content-addressed reference to a raw telemetry data artifact."""

    artifact_id: str = Field(description="Unique identifier for the raw artifact")
    relative_path: str = Field(description="Relative POSIX path from run directory (e.g. 'raw_data/network_log.csv')")
    sha256: str = Field(description="Cryptographic SHA-256 hash of the artifact on disk")


class MetricDerivation(ArtifactBaseModel):
    """Specification of the mathematical operation used to independently recompute a metric."""

    operation: Literal["fraction_where", "mean", "sum", "count", "rmse", "min", "max", "std", "delta_relative", "reduction_pct", "custom"] = Field(
        description="Mathematical reduction operation performed on raw records"
    )
    target_field: Optional[str] = Field(default=None, description="Field name in raw records to reduce")
    condition: Optional[str] = Field(default=None, description="Condition comparator (e.g. '==', '!=', '>', '<')")
    target_value: Optional[Any] = Field(default=None, description="Target value for conditional filtering")
    target_column: Optional[str] = Field(default=None, description="Primary column for paired metrics (e.g. RMSE)")
    reference_column: Optional[str] = Field(default=None, description="Reference baseline column for paired metrics")
    baseline_field: Optional[str] = Field(default=None, description="Baseline reference field for delta_relative calculations")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Arbitrary domain/custom reduction parameters")


class StructuredMetricRecord(ArtifactBaseModel):
    """Structured metric record pairing reported value with independent derivation procedure."""

    metric_id: str = Field(description="Unique metric name or identifier")
    reported_value: float = Field(description="Scalar metric value reported by simulation script")
    raw_artifact: RawArtifactReference = Field(description="Content-addressed raw artifact reference")
    derivation: MetricDerivation = Field(description="Mathematical derivation rule")
    recomputed_value: Optional[float] = Field(default=None, description="Independently verified scalar value")
    discrepancy: Optional[float] = Field(default=None, description="Absolute difference between reported and recomputed")
    verified: bool = Field(default=False, description="Whether recomputed value matched reported value within tolerance")


class MetricVerification(ArtifactBaseModel):
    """Deterministic evaluation of an observed metric against an expected threshold."""

    metric_name: str = Field(description="Name of the metric evaluated (e.g. 'val_loss', 'accuracy')")
    operator: Literal[">", "<", ">=", "<=", "=="] = Field(
        description="Comparison operator applied: observed <operator> target_threshold"
    )
    target_threshold: float = Field(description="Expected target threshold")
    observed_value: float = Field(description="Actual value extracted from run output")
    passed: bool = Field(description="Whether the condition evaluated to True")
    notes: Optional[str] = Field(default=None, description="Diagnostic commentary on metric outcome")


class VerificationReport(ArtifactBaseModel):
    """Deterministic, auditable verification report for an experiment execution run."""

    report_id: str = Field(description="Unique verification report ID")
    spec_id: str = Field(description="ExperimentSpec identifier being verified")
    run_id: str = Field(description="Unique ID of the specific execution run")
    exit_code: int = Field(description="Process return code from container/subprocess")
    exit_code_passed: bool = Field(
        description="Deterministic assertion that exit_code == 0"
    )
    schema_compliance: bool = Field(
        description="Whether produced output data validly conforms to the expected metric schema"
    )
    missing_output_files: list[str] = Field(
        default_factory=list,
        description="Any expected output files that were not found in the output bundle"
    )
    checksums: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of relative file path to SHA-256 integrity checksum"
    )
    metric_evaluations: list[MetricVerification] = Field(
        default_factory=list,
        description="Detailed evaluations of all tracked metrics"
    )
    structured_metrics: list[StructuredMetricRecord] = Field(
        default_factory=list,
        description="Detailed independent recomputations of structured metrics"
    )
    provenance_valid: bool = Field(
        default=True,
        description="Whether all metrics are backed by authentic raw data and valid computation records"
    )
    unbacked_metrics: list[str] = Field(
        default_factory=list,
        description="List of declared metrics lacking raw data derivation"
    )
    overall_status: VerificationStatus = Field(
        description="Final deterministic verdict: PASS if all checks succeeded, otherwise FAIL/ERROR/TAMPERED"
    )
    error_details: Optional[str] = Field(
        default=None,
        description="Consolidated stack trace or failure explanation if verification failed"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of report generation"
    )

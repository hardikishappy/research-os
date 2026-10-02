"""Declarative Metric and Verification Specification for Research OS Domains.

Enforces the core scientific integrity invariant:
"AI-generated plugins expand experimental capability; the trusted core alone holds authority over scientific verification."
Untrusted generated plugins must NEVER define arbitrary executable Python verification logic.
Metric derivations must be strictly declarative and recomputed solely by the trusted DeterministicVerifier.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional, Union
from pydantic import Field, field_validator

from research_os.schemas.base import ArtifactBaseModel
from research_os.schemas.verification import MetricDerivation


class UnsupportedVerificationPrimitiveError(ValueError):
    """Raised when an untrusted plugin declares an unapproved verification operation."""
    pass


ALLOWED_OPERATIONS = {
    "mean",
    "sum",
    "fraction_where",
    "count",
    "rmse",
    "std",
    "min",
    "max",
    "delta_relative",
}

OperationType = Literal[
    "mean",
    "sum",
    "fraction_where",
    "count",
    "rmse",
    "std",
    "min",
    "max",
    "delta_relative",
]


class DeclarativeMetricDef(ArtifactBaseModel):
    """Declarative specification for a single metric derivation."""

    metric_id: str = Field(description="Unique metric identifier (e.g. 'objective_score')")
    raw_artifact_file: str = Field(description="Relative path to raw telemetry artifact (e.g. 'raw_data/eval_log.jsonl')")
    operation: OperationType = Field(description="Mathematical reduction operation from approved core set")
    target_field: str = Field(description="Field in raw records to reduce")
    condition: Optional[str] = Field(default=None, description="Conditional comparison operator (e.g. '==', '!=', '>')")
    target_value: Optional[Union[float, int, bool, str]] = Field(default=None, description="Target value for condition")
    baseline_field: Optional[str] = Field(default=None, description="Baseline reference field for relative comparisons")
    unit: str = Field(default="", description="Scientific or engineering unit of measurement")
    tolerance: float = Field(default=1e-6, ge=0.0, description="Permissible numeric discrepancy during recomputation")

    def __init__(self, **data: Any) -> None:
        op = data.get("operation")
        if op is not None:
            op_str = str(op).strip()
            if op_str not in ALLOWED_OPERATIONS:
                raise UnsupportedVerificationPrimitiveError(
                    f"UNSUPPORTED_VERIFICATION_PRIMITIVE: Op not in trusted core: '{op_str}'. "
                    f"Approved core primitives are: {sorted(ALLOWED_OPERATIONS)}"
                )
        super().__init__(**data)

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> DeclarativeMetricDef:
        if isinstance(obj, dict):
            op = obj.get("operation")
            if op is not None and str(op).strip() not in ALLOWED_OPERATIONS:
                raise UnsupportedVerificationPrimitiveError(
                    f"UNSUPPORTED_VERIFICATION_PRIMITIVE: Op not in trusted core: '{op}'. "
                    f"Approved core primitives are: {sorted(ALLOWED_OPERATIONS)}"
                )
        try:
            return super().model_validate(obj, strict=strict, from_attributes=from_attributes, context=context)
        except Exception as e:
            if "UNSUPPORTED_VERIFICATION_PRIMITIVE" in str(e):
                raise UnsupportedVerificationPrimitiveError(str(e)) from e
            raise

    @field_validator("operation", mode="before")
    @classmethod
    def validate_operation(cls, v: Any) -> str:
        op_str = str(v).strip()
        if op_str not in ALLOWED_OPERATIONS:
            raise UnsupportedVerificationPrimitiveError(
                f"UNSUPPORTED_VERIFICATION_PRIMITIVE: Op not in trusted core: '{op_str}'. "
                f"Approved core primitives are: {sorted(ALLOWED_OPERATIONS)}"
            )
        return op_str

    def to_metric_derivation(self) -> MetricDerivation:
        """Convert into a core MetricDerivation model."""
        return MetricDerivation(
            operation=self.operation,
            target_field=self.target_field,
            condition=self.condition,
            target_value=self.target_value,
            baseline_field=self.baseline_field,
        )


class DeclarativePluginSpec(ArtifactBaseModel):
    """Strictly declarative domain plugin specification."""

    domain_id: str = Field(description="Unique domain slug (e.g. 'astrophysics')")
    interface_version: str = Field(default="1.0.0", description="Plugin interface contract version")
    display_name: str = Field(default="", description="Human-readable domain name")
    description: str = Field(default="", description="Domain scope and experimental capability description")
    supported_metrics: list[str] = Field(default_factory=list, description="List of recognized metric identifiers")
    verification_primitives: dict[str, DeclarativeMetricDef] = Field(
        default_factory=dict,
        description="Declarative derivation mapping: metric_id -> DeclarativeMetricDef",
    )
    allowed_dependencies: list[str] = Field(
        default_factory=lambda: ["numpy", "pydantic"],
        description="Permitted third-party library dependencies",
    )

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> DeclarativePluginSpec:
        try:
            return super().model_validate(obj, strict=strict, from_attributes=from_attributes, context=context)
        except Exception as e:
            if "UNSUPPORTED_VERIFICATION_PRIMITIVE" in str(e):
                raise UnsupportedVerificationPrimitiveError(str(e)) from e
            raise


def recompute_declarative_metric(run_dir: Union[str, Path], metric_def: DeclarativeMetricDef) -> float:
    """Independently calculate the scalar metric value directly from raw file records using trusted core verifier."""
    from research_os.verify.deterministic import recompute_metric_from_artifact

    base_path = Path(run_dir)
    raw_path = base_path / metric_def.raw_artifact_file
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing declared raw data artifact on disk: {raw_path}")

    derivation = metric_def.to_metric_derivation()
    return recompute_metric_from_artifact(raw_path, derivation)

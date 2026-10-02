"""Unified Metric Catalog and Canonical Definitions for Research OS.

Provides standard definitions, canonical units, and value constraints for metrics
across domains to prevent metric confusion (e.g. recall_at_k vs hallucination_rate).
"""

from __future__ import annotations

from typing import Optional
from pydantic import Field

from research_os.schemas.base import ArtifactBaseModel
from research_os.specs.units import UnitType, ValueWithUnit


class MetricDefinition(ArtifactBaseModel):
    """Specification of an expected scientific or evaluation metric."""

    metric_name: str = Field(description="Canonical metric identifier")
    canonical_unit: UnitType = Field(description="Standardized unit of measurement")
    description: str = Field(default="", description="Scientific or operational definition")
    min_value: Optional[float] = Field(default=None, description="Lower physical or mathematical bound")
    max_value: Optional[float] = Field(default=None, description="Upper physical or mathematical bound")
    acceptable_units: list[UnitType] = Field(
        default_factory=list,
        description="List of units that can be automatically converted to canonical_unit",
    )

    @property
    def name(self) -> str:
        return self.metric_name

    @property
    def unit(self) -> UnitType:
        return self.canonical_unit

    def validate_and_normalize(self, raw_value: float, raw_unit: Optional[str] = None) -> ValueWithUnit:
        """Validate an incoming measurement against this definition and return canonical ValueWithUnit."""
        unit_str = raw_unit or str(self.canonical_unit.value)
        val_unit = ValueWithUnit(value=raw_value, unit=unit_str)

        # Convert to canonical
        if self.canonical_unit == UnitType.FRACTION and val_unit.unit in (UnitType.PERCENTAGE, UnitType.FRACTION, UnitType.SCALAR):
            canonical = ValueWithUnit(value=val_unit.as_fraction(), unit=UnitType.FRACTION)
        else:
            canonical = val_unit.to_canonical()

        # Check bounds
        if self.min_value is not None and canonical.value < self.min_value:
            raise ValueError(
                f"Metric '{self.metric_name}' value {canonical.value} is below minimum bound {self.min_value}."
            )
        if self.max_value is not None and canonical.value > self.max_value:
            raise ValueError(
                f"Metric '{self.metric_name}' value {canonical.value} exceeds maximum bound {self.max_value}."
            )

        return canonical


class MetricCatalog:
    """Registry of known standardized research metrics across supported domains."""

    _catalog: dict[str, MetricDefinition] = {}

    @classmethod
    def register(cls, definition: MetricDefinition) -> None:
        cls._catalog[definition.metric_name.lower()] = definition

    @classmethod
    def get(cls, metric_name: str) -> Optional[MetricDefinition]:
        return cls._catalog.get(metric_name.strip().lower())

    @classmethod
    def require(cls, metric_name: str) -> MetricDefinition:
        entry = cls.get(metric_name)
        if entry is None:
            raise KeyError(f"Metric '{metric_name}' is not registered in the MetricCatalog. Strict registration required (U1).")
        return entry

    @classmethod
    def list_metrics(cls) -> list[str]:
        return sorted(list(cls._catalog.keys()))


# Register standard foundation metrics
_STANDARD_METRICS: list[MetricDefinition] = [
    MetricDefinition(
        metric_name="recall_at_k",
        canonical_unit=UnitType.FRACTION,
        description="Fraction of relevant items retrieved in top-k results",
        min_value=0.0,
        max_value=1.0,
        acceptable_units=[UnitType.FRACTION, UnitType.PERCENTAGE],
    ),
    MetricDefinition(
        metric_name="precision_at_k",
        canonical_unit=UnitType.FRACTION,
        description="Fraction of top-k retrieved items that are relevant",
        min_value=0.0,
        max_value=1.0,
        acceptable_units=[UnitType.FRACTION, UnitType.PERCENTAGE],
    ),
    MetricDefinition(
        metric_name="hallucination_rate",
        canonical_unit=UnitType.FRACTION,
        description="Fraction of generated claims unsupported by evidence",
        min_value=0.0,
        max_value=1.0,
        acceptable_units=[UnitType.FRACTION, UnitType.PERCENTAGE],
    ),
    MetricDefinition(
        metric_name="baseline_hallucination_rate",
        canonical_unit=UnitType.FRACTION,
        description="Baseline hallucination rate without retrieved context",
        min_value=0.0,
        max_value=1.0,
        acceptable_units=[UnitType.FRACTION, UnitType.PERCENTAGE],
    ),
    MetricDefinition(
        metric_name="shuffled_hallucination_rate",
        canonical_unit=UnitType.FRACTION,
        description="Negative control hallucination rate with shuffled distractor context",
        min_value=0.0,
        max_value=1.0,
        acceptable_units=[UnitType.FRACTION, UnitType.PERCENTAGE],
    ),
    MetricDefinition(
        metric_name="hallucination_reduction_pct",
        canonical_unit=UnitType.PERCENTAGE,
        description="Relative percentage reduction in hallucination rate against baseline",
        min_value=-1000.0,
        max_value=100.0,
        acceptable_units=[UnitType.PERCENTAGE, UnitType.FRACTION],
    ),
    MetricDefinition(
        metric_name="token_overlap_score",
        canonical_unit=UnitType.FRACTION,
        description="Token overlap fraction between generated text and ground truth",
        min_value=0.0,
        max_value=1.0,
        acceptable_units=[UnitType.FRACTION, UnitType.PERCENTAGE],
    ),
    MetricDefinition(
        metric_name="latency_ms",
        canonical_unit=UnitType.MILLISECONDS,
        description="Execution latency in milliseconds",
        min_value=0.0,
        acceptable_units=[UnitType.MILLISECONDS, UnitType.SECONDS],
    ),
    MetricDefinition(
        metric_name="total_evaluated_queries",
        canonical_unit=UnitType.COUNT,
        description="Total number of evaluated queries in benchmark",
        min_value=0.0,
        acceptable_units=[UnitType.COUNT, UnitType.SCALAR],
    ),
    MetricDefinition(
        metric_name="accuracy",
        canonical_unit=UnitType.FRACTION,
        description="Classification accuracy fraction",
        min_value=0.0,
        max_value=1.0,
        acceptable_units=[UnitType.FRACTION, UnitType.PERCENTAGE],
    ),
    MetricDefinition(
        metric_name="f1_score",
        canonical_unit=UnitType.FRACTION,
        description="Harmonic mean of precision and recall",
        min_value=0.0,
        max_value=1.0,
        acceptable_units=[UnitType.FRACTION, UnitType.PERCENTAGE],
    ),
    MetricDefinition(
        metric_name="latency_seconds",
        canonical_unit=UnitType.SECONDS,
        description="End-to-end execution latency in seconds",
        min_value=0.0,
        acceptable_units=[UnitType.SECONDS, UnitType.MILLISECONDS, UnitType.MICROSECONDS],
    ),
    MetricDefinition(
        metric_name="throughput_qps",
        canonical_unit=UnitType.RATE_PER_SECOND,
        description="Queries or tasks processed per second",
        min_value=0.0,
        acceptable_units=[UnitType.RATE_PER_SECOND],
    ),
    MetricDefinition(
        metric_name="verification_score",
        canonical_unit=UnitType.FRACTION,
        description="Deterministic verification score",
        min_value=0.0,
        max_value=1.0,
        acceptable_units=[UnitType.FRACTION, UnitType.PERCENTAGE],
    ),
    MetricDefinition(
        metric_name="tracking_rmse",
        canonical_unit=UnitType.SCALAR,
        description="Root mean square tracking error",
        min_value=0.0,
        acceptable_units=[UnitType.SCALAR],
    ),
    MetricDefinition(
        metric_name="aggregation_time_steps",
        canonical_unit=UnitType.COUNT,
        description="Time steps required for multi-agent aggregation",
        min_value=0.0,
        acceptable_units=[UnitType.COUNT, UnitType.SCALAR],
    ),
    MetricDefinition(
        metric_name="final_cluster_diameter",
        canonical_unit=UnitType.SCALAR,
        description="Final spatial diameter of aggregated agent cluster",
        min_value=0.0,
        acceptable_units=[UnitType.SCALAR],
    ),
    MetricDefinition(
        metric_name="collision_count",
        canonical_unit=UnitType.COUNT,
        description="Total agent collisions during simulation",
        min_value=0.0,
        acceptable_units=[UnitType.COUNT],
    ),
    MetricDefinition(
        metric_name="position_error_m",
        canonical_unit=UnitType.SCALAR,
        description="Position tracking error in meters",
        min_value=0.0,
        acceptable_units=[UnitType.SCALAR],
    ),
    MetricDefinition(
        metric_name="jitter_ms",
        canonical_unit=UnitType.MILLISECONDS,
        description="Network transmission jitter in milliseconds",
        min_value=0.0,
        acceptable_units=[UnitType.MILLISECONDS, UnitType.SECONDS],
    ),
    MetricDefinition(
        metric_name="packet_loss_rate",
        canonical_unit=UnitType.FRACTION,
        description="Packet drop fraction",
        min_value=0.0,
        max_value=1.0,
        acceptable_units=[UnitType.FRACTION, UnitType.PERCENTAGE],
    ),
]

for m in _STANDARD_METRICS:
    MetricCatalog.register(m)

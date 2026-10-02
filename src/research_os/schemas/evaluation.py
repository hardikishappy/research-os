"""Multi-seed statistical evaluation schemas for Research OS (Rules 4 & 16)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from pydantic import field_validator, Field, model_validator

from .base import ArtifactBaseModel


class StatisticalAnalysisResult(ArtifactBaseModel):
    """Rigorous inferential statistics derived from independent observational units (Directive 2)."""

    metric_name: str = Field(description="Name of the analyzed metric")
    sample_size: int = Field(ge=0, description="Number of independent observational units (N)")
    mean: float = Field(description="Sample mean (M)")
    variance: float = Field(ge=0.0, description="Sample variance (s^2)")
    standard_deviation: float = Field(ge=0.0, description="Sample standard deviation (SD)")
    standard_error: float = Field(ge=0.0, description="Standard error of the mean (SE)")
    degrees_of_freedom: int = Field(ge=0, description="Degrees of freedom (df = N - 1)")
    test_statistic: Optional[float] = Field(default=None, description="Calculated t-statistic (or z-statistic)")
    p_value: Optional[float] = Field(default=None, description="Calculated two-tailed p-value (or None if uninformative)")
    confidence_interval: Optional[tuple[float, float]] = Field(
        default=None,
        description="95% two-sided confidence interval (lower, upper)",
    )
    assumptions_met: bool = Field(default=True, description="Whether statistical assumptions (e.g. non-zero variance) are satisfied")
    significance_claim_allowed: bool = Field(
        default=False,
        description="Whether manuscript or evaluator is permitted to claim statistical significance (Rule 1 & Directive 2)",
    )
    reasons_significance_blocked: list[str] = Field(
        default_factory=list,
        description="Audit reasons why significance claims are blocked",
    )


class HypothesisVerdict(str, Enum):
    """Categorical scientific conclusion derived from multi-seed empirical evaluation."""

    CONFIRMED = "CONFIRMED"
    REFUTED = "REFUTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class ThresholdStatus(str, Enum):
    """Status indicating whether the empirical mean satisfied the registered target threshold."""

    PASS = "PASS"
    FAIL = "FAIL"


class StatisticalSupport(str, Enum):
    """Inferential status conditioned on statistical significance and sample power (p-value, N >= 3)."""

    SIGNIFICANT = "SIGNIFICANT"
    INSUFFICIENT = "INSUFFICIENT"
    INFORMATIVE_NON_SIGNIFICANT = "INFORMATIVE_NON_SIGNIFICANT"


class ReplicationStatus(str, Enum):
    """Cross-seed replication and dispersion stability classification."""

    REPRODUCIBLE = "REPRODUCIBLE"
    HIGH_VARIANCE = "HIGH_VARIANCE"
    SINGLE_POINT = "SINGLE_POINT"


class MetricAggregate(ArtifactBaseModel):
    """Statistical summary across multiple seed executions."""

    metric_name: str = Field(description="Name of the evaluated metric")
    sample_values: list[float] = Field(description="Observed numeric values across seeds")
    mean: float = Field(description="Sample mean across valid seed runs")
    std_dev: float = Field(description="Sample standard deviation across runs")
    std_err: float = Field(description="Standard error of the mean")
    target_threshold: float = Field(description="Target quantitative threshold from hypothesis")
    operator: Literal[">", "<", ">=", "<=", "=="] = Field(
        description="Comparison operator applied: mean <operator> target_threshold"
    )
    passed: bool = Field(description="Whether the mean satisfies the condition")
    p_value_estimate: Optional[float] = Field(
        default=None,
        description="Estimated confidence / t-statistic p-value if applicable"
    )
    statistical_analysis: Optional[StatisticalAnalysisResult] = Field(
        default=None,
        description="Rigorous inferential statistics object (Directive 2)",
    )
    significance_claim_allowed: bool = Field(
        default=False,
        description="Whether statistical significance claims are allowed (Golden Rule of Statistics)",
    )

    @model_validator(mode="before")
    @classmethod
    def validate_golden_rule(cls, data: Any) -> Any:
        if isinstance(data, dict):
            stat_analysis = data.get("statistical_analysis")
            if stat_analysis is not None:
                sig = (
                    getattr(stat_analysis, "significance_claim_allowed", False)
                    if not isinstance(stat_analysis, dict)
                    else stat_analysis.get("significance_claim_allowed", False)
                )
                data["significance_claim_allowed"] = sig
            elif (
                data.get("p_value_estimate") is not None
                and data.get("p_value_estimate") < 0.05
                and data.get("std_dev", 0.0) > 0.0
                and len(data.get("sample_values", [])) >= 2
            ):
                data["significance_claim_allowed"] = True
            else:
                data["significance_claim_allowed"] = False
        return data


class SeedRunSummary(ArtifactBaseModel):
    """Summary of an individual seed experiment run."""

    seed: int = Field(description="Random seed evaluated")
    run_id: str = Field(description="Execution run ID")
    exit_code: int = Field(description="Subprocess return code")
    verification_status: str = Field(description="'PASS', 'FAIL', or 'ERROR'")
    metrics: dict[str, float] = Field(default_factory=dict, description="Raw metrics extracted from output")
    @field_validator('metrics', mode='before')
    @classmethod
    def filter_numeric_metrics(cls, v):
        if isinstance(v, dict):
            clean = {}
            for k, val in v.items():
                if k in ('status', '_provenance', 'run_id'):
                    continue
                try:
                    clean[k] = float(val)
                except (ValueError, TypeError):
                    continue
            return clean
        return v



class EvaluationReport(ArtifactBaseModel):
    """Consolidated statistical evaluation across random seeds (Rules 4 & 16)."""

    evaluation_id: str = Field(description="Unique evaluation report ID")
    hypothesis_id: str = Field(description="Falsifiable hypothesis under test")
    spec_id: str = Field(description="Experiment specification evaluated")
    seeds_evaluated: list[int] = Field(description="List of random seeds executed")
    total_runs: int = Field(description="Total seed runs dispatched")
    successful_runs: int = Field(description="Number of runs with exit code 0 and valid metrics")
    failed_runs: int = Field(description="Number of aborted or failed runs")
    verdict: HypothesisVerdict = Field(description="Final empirical verdict: CONFIRMED, REFUTED, or INCONCLUSIVE")
    threshold_status: Optional[ThresholdStatus] = Field(
        default=None,
        description="Whether empirical mean met the registered numeric threshold (PASS | FAIL)",
    )
    statistical_support: Optional[StatisticalSupport] = Field(
        default=None,
        description="Statistical support conditioned on p-value and N >= 3 (SIGNIFICANT | INSUFFICIENT | INFORMATIVE_NON_SIGNIFICANT)",
    )
    replication_status: Optional[ReplicationStatus] = Field(
        default=None,
        description="Cross-seed replication and variance stability (REPRODUCIBLE | HIGH_VARIANCE | SINGLE_POINT)",
    )
    target_metric: str = Field(description="Primary metric tested")
    metric_aggregates: dict[str, MetricAggregate] = Field(
        default_factory=dict,
        description="Aggregated statistics per evaluated metric"
    )
    seed_runs: list[SeedRunSummary] = Field(
        default_factory=list,
        description="Per-seed run results"
    )
    summary_rationale: str = Field(description="Scientific rationale and explanation of the verdict")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC evaluation timestamp"
    )


class GridCombinationSummary(ArtifactBaseModel):
    """Result of a single parameter combination sweep across seeds."""

    combination_id: str = Field(description="Unique combination identifier (e.g. combo-0)")
    parameters: dict[str, Any] = Field(description="Parameter settings for this combination")
    seeds_evaluated: list[int] = Field(description="Seeds evaluated under this combination")
    successful_runs: int = Field(description="Number of successful runs")
    verdict: HypothesisVerdict = Field(description="Verdict for this combination")
    threshold_status: Optional[ThresholdStatus] = Field(default=None, description="PASS or FAIL threshold status")
    statistical_support: Optional[StatisticalSupport] = Field(default=None, description="Statistical support classification")
    replication_status: Optional[ReplicationStatus] = Field(default=None, description="Replication stability classification")
    mean_target_metric: float = Field(description="Mean observed value for target metric")
    std_dev_target_metric: float = Field(default=0.0, description="Standard deviation for target metric")
    std_err_target_metric: float = Field(default=0.0, description="Standard error for target metric")
    metric_means: dict[str, float] = Field(default_factory=dict, description="Mean values for all metrics")
    evaluation_report: Optional[EvaluationReport] = Field(default=None, description="Detailed evaluation report")


class GridEvaluationReport(ArtifactBaseModel):
    """Aggregated evaluation across a parametric grid / ablation sweep."""

    grid_id: str = Field(description="Unique grid evaluation run identifier")
    hypothesis_id: str = Field(description="Hypothesis under parametric stress test")
    spec_id: str = Field(description="Base experiment spec ID")
    knobs: dict[str, list[Any]] = Field(description="Parameter knobs expanded in the sweep")
    seeds: list[int] = Field(description="Random seeds evaluated per parameter combination")
    total_combinations: int = Field(description="Total parameter combinations in Cartesian grid")
    total_runs: int = Field(description="Total runs across combinations and seeds")
    target_metric: str = Field(description="Target metric evaluated across grid")
    combinations: list[GridCombinationSummary] = Field(description="Results per parameter combination")
    best_combination_id: str = Field(description="Combination ID that yielded optimal target metric")
    best_parameters: dict[str, Any] = Field(description="Optimal parameter dictionary")
    best_target_metric_mean: float = Field(description="Optimal target metric mean")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC grid evaluation timestamp"
    )


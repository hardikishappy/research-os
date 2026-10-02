"""Telepresence and Haptic Control Domain Plugin implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from research_os.domains.base import (
    MetricProvenanceReport,
    ValidationResult,
)
from research_os.plugins.base import BaseDomainAdapter
from research_os.models.base import BaseModelAdapter
from research_os.plugins.telepresence.experiments.telepresence_generator import (
    get_telepresence_simulation_code,
)
from research_os.plugins.telepresence.metrics import compute_telepresence_metrics_from_raw
from research_os.plugins.telepresence.schemas import TelepresenceConfig
from research_os.schemas.experiment import (
    ExperimentSpec,
    ExperimentType,
    HardwareRequirements,
)
from research_os.schemas.hypothesis import HypothesisProposal


class TelepresencePlugin(BaseDomainAdapter):
    """Domain plugin evaluating telepresence tracking, jitter buffers, and latency compensation."""

    domain_id: str = "telepresence"
    display_name: str = "Telepresence & Haptic Control Under Network Jitter"
    supported_experiment_types: list[ExperimentType] = [
        ExperimentType.SIMULATION,
        ExperimentType.BENCHMARK,
    ]

    def matches_domain(self, hypothesis: HypothesisProposal) -> bool:
        """Check if hypothesis belongs to telepresence / haptic control domain."""
        search_space = " ".join([
            hypothesis.title,
            hypothesis.falsifiable_statement,
            hypothesis.proposed_mechanism,
            hypothesis.theoretical_rationale,
        ]).lower()

        for seed in hypothesis.inspired_by_seeds:
            seed_domain = seed.domain.lower()
            if any(term in seed_domain for term in ["telepresence", "haptic", "telerobotics", "network jitter"]):
                return True

        keywords = [
            "telepresence",
            "haptic",
            "jitter buffer",
            "tracking rmse",
            "network jitter",
            "packet latency",
            "telerobotic",
        ]
        return any(kw in search_space for kw in keywords)

    def validate_hypothesis(self, hypothesis: HypothesisProposal) -> ValidationResult:
        """Validate whether the hypothesis can be verified in telepresence tracking simulation."""
        if not self.matches_domain(hypothesis):
            return ValidationResult(
                is_valid=False,
                domain_id=self.domain_id,
                reasons=["Hypothesis does not target telepresence, jitter compensation, or tracking accuracy."],
            )

        valid = bool(hypothesis.target_metric and hypothesis.success_threshold is not None)
        reasons = [] if valid else ["Missing quantitative target_metric or success_threshold."]
        return ValidationResult(
            is_valid=valid,
            domain_id=self.domain_id,
            reasons=reasons,
        )

    def plan_experiment(
        self,
        hypothesis: HypothesisProposal,
        spec_requirements: Optional[dict[str, Any]] = None,
    ) -> ExperimentSpec:
        """Compile a telepresence hypothesis into an ExperimentSpec."""
        actual_spec_id = f"spec-{hypothesis.hypothesis_id[:12]}"
        default_cfg = TelepresenceConfig(
            success_threshold=hypothesis.success_threshold or 0.05,
        )
        run_config = default_cfg.model_dump()
        run_config.update({
            "target_metric": hypothesis.target_metric,
            "expected_direction": hypothesis.expected_direction,
            "success_threshold": hypothesis.success_threshold,
        })
        if spec_requirements:
            run_config.update(spec_requirements)

        timeout = int(spec_requirements.get("timeout_seconds", 30)) if spec_requirements else 30

        return ExperimentSpec(
            spec_id=actual_spec_id,
            hypothesis_id=hypothesis.hypothesis_id,
            experiment_type=ExperimentType.SIMULATION,
            name=f"Empirical Simulation: {hypothesis.title}",
            description=f"Telepresence jitter evaluation of: {hypothesis.falsifiable_statement}",
            entry_point="python run_telepresence.py --config config.json --output-dir output",
            run_config=run_config,
            dependencies=["pydantic>=2.0.0"],
            random_seeds=[42, 101, 2024],
            expected_outputs=["metrics.json", "provenance.json", "raw_data/network_jitter.csv", "summary.txt"],
            timeout_seconds=timeout,
            hardware_requirements=HardwareRequirements(
                cuda_required=False,
                min_ram_gb=1.0,
                max_cpu_cores=2,
            ),
        )

    def generate_experiment_code(
        self,
        spec: ExperimentSpec,
        model_adapter: Optional[BaseModelAdapter] = None,
    ) -> str:
        """Return the complete telepresence tracking simulation script."""
        return get_telepresence_simulation_code()

    def validate_metric_provenance(
        self,
        raw_data_dir: Path,
        metrics: dict[str, Any],
    ) -> MetricProvenanceReport:
        """Verify metrics.json against raw network_jitter.csv."""
        errors: list[str] = []
        unbacked: list[str] = []

        if not raw_data_dir.exists():
            return MetricProvenanceReport(
                is_valid=False,
                unbacked_metrics=list(metrics.keys()),
                errors=[f"Raw data directory does not exist: {raw_data_dir}"],
            )

        try:
            recomputed_metrics, provenance_records = compute_telepresence_metrics_from_raw(
                raw_data_dir=raw_data_dir,
            )
        except Exception as e:
            return MetricProvenanceReport(
                is_valid=False,
                unbacked_metrics=list(metrics.keys()),
                errors=[f"Failed to recompute telepresence metrics from raw jitter log: {e}"],
            )

        tracked_keys = [
            "tracking_rmse",
            "tracking_error_reduction_pct",
            "packet_drop_rate",
        ]
        for k in tracked_keys:
            if k in metrics:
                obs = metrics[k]
                expected = recomputed_metrics.get(k)
                if expected is None:
                    unbacked.append(k)
                elif abs(obs - expected) > 1e-2:
                    errors.append(f"Metric '{k}' mismatch: reported {obs} != recomputed {expected}")
            else:
                unbacked.append(k)

        is_valid = len(errors) == 0 and len(unbacked) == 0
        return MetricProvenanceReport(
            is_valid=is_valid,
            provenance_records=provenance_records,
            unbacked_metrics=unbacked,
            errors=errors,
        )

    def validate_environment(self) -> dict[str, bool]:
        """Validates that telepresence and control simulation libraries are available."""
        import importlib.util
        packages = ["numpy", "scipy", "matplotlib"]
        return {pkg: importlib.util.find_spec(pkg) is not None for pkg in packages}

    def generate_execution_plan(self, spec: ExperimentSpec) -> dict[str, Any]:
        """Binds experiment specifications to verified domain solvers."""
        return {
            "domain_id": self.domain_id,
            "solver": "JitterCompensatedKinematicTracker",
            "mechanism": "Adaptive Jitter Buffer with Forward Prediction",
            "modality": "SIMULATION",
        }

"""Swarm Robotics Domain Plugin implementation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from research_os.domains.base import (
    MetricProvenanceReport,
    ValidationResult,
)
from research_os.plugins.base import BaseDomainAdapter
from research_os.models.base import BaseModelAdapter
from research_os.plugins.swarm_robotics.experiments.simulation_generator import (
    get_swarm_simulation_code,
)
from research_os.plugins.swarm_robotics.metrics import compute_swarm_metrics_from_raw
from research_os.plugins.swarm_robotics.schemas import SwarmConfig
from research_os.schemas.experiment import (
    ExperimentSpec,
    ExperimentType,
    HardwareRequirements,
)
from research_os.schemas.hypothesis import HypothesisProposal


class SwarmRoboticsPlugin(BaseDomainAdapter):
    """Domain plugin for multi-robot swarm aggregation and communication kinematics."""

    domain_id: str = "swarm_robotics"
    display_name: str = "Swarm Robotics: Decentralized Multi-Agent Systems"
    supported_experiment_types: list[ExperimentType] = [ExperimentType.SIMULATION]

    def matches_domain(self, hypothesis: HypothesisProposal) -> bool:
        """Check if hypothesis belongs to swarm robotics domain."""
        search_space = " ".join([
            hypothesis.title,
            hypothesis.falsifiable_statement,
            hypothesis.proposed_mechanism,
            hypothesis.theoretical_rationale,
        ]).lower()

        # Check seeds domain
        for seed in hypothesis.inspired_by_seeds:
            if "swarm" in seed.domain.lower() or "robot" in seed.domain.lower():
                return True

        keywords = ["swarm", "robot", "flocking", "aggregation", "inter-robot", "arena"]
        return any(kw in search_space for kw in keywords)

    def validate_hypothesis(self, hypothesis: HypothesisProposal) -> ValidationResult:
        """Validate whether the hypothesis can be experimentally verified in simulation."""
        if not self.matches_domain(hypothesis):
            return ValidationResult(
                is_valid=False,
                domain_id=self.domain_id,
                reasons=["Hypothesis does not target multi-agent swarm coordination or kinematics."],
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
        """Compile a swarm hypothesis into an ExperimentSpec."""
        actual_spec_id = f"spec-{hypothesis.hypothesis_id[:12]}"
        default_cfg = SwarmConfig(
            bandwidth_cap_bytes=hypothesis.success_threshold or 64.0,
        )
        run_config = default_cfg.model_dump()
        run_config.update({
            "target_metric": hypothesis.target_metric,
            "expected_direction": hypothesis.expected_direction,
            "success_threshold": hypothesis.success_threshold,
        })
        if spec_requirements:
            run_config.update(spec_requirements)

        timeout = int(spec_requirements.get("timeout_seconds", 60)) if spec_requirements else 60

        return ExperimentSpec(
            spec_id=actual_spec_id,
            hypothesis_id=hypothesis.hypothesis_id,
            experiment_type=ExperimentType.SIMULATION,
            name=f"Empirical Simulation: {hypothesis.title}",
            description=f"Kinematic simulation evaluating: {hypothesis.falsifiable_statement}",
            entry_point="python simulation.py --config config.json --output-dir output",
            run_config=run_config,
            dependencies=["pydantic>=2.0.0"],
            random_seeds=[42, 101, 2024],
            expected_outputs=["metrics.json", "trajectory.csv", "summary.txt", "provenance.json"],
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
        """Return the complete simulation script."""
        return get_swarm_simulation_code()

    def validate_metric_provenance(
        self,
        raw_data_dir: Path,
        metrics: dict[str, Any],
    ) -> MetricProvenanceReport:
        """Verify metrics.json against raw trajectory and packet logs."""
        errors: list[str] = []
        unbacked: list[str] = []

        if not raw_data_dir.exists():
            return MetricProvenanceReport(
                is_valid=False,
                unbacked_metrics=list(metrics.keys()),
                errors=[f"Raw data directory does not exist: {raw_data_dir}"],
            )

        try:
            recomputed_metrics, provenance_records = compute_swarm_metrics_from_raw(
                raw_data_dir=raw_data_dir,
                num_robots=int(metrics.get("num_robots", 50)),
            )
        except Exception as e:
            return MetricProvenanceReport(
                is_valid=False,
                unbacked_metrics=list(metrics.keys()),
                errors=[f"Failed to recompute metrics from raw logs: {e}"],
            )

        # Check key tracked metrics
        tracked_keys = [
            "comm_bandwidth_bytes_per_sec",
            "comm_overhead_reduction_pct",
            "aggregation_time_steps",
            "order_parameter",
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
        """Validates that robotics / kinematics simulation libraries are available."""
        import importlib.util
        packages = ["numpy", "scipy", "matplotlib"]
        return {pkg: importlib.util.find_spec(pkg) is not None for pkg in packages}

    def generate_execution_plan(self, spec: ExperimentSpec) -> dict[str, Any]:
        """Binds experiment specifications to verified domain solvers."""
        return {
            "domain_id": self.domain_id,
            "solver": "DecentralizedKinematicsSimulator",
            "num_robots": spec.run_config.get("num_robots", 50),
            "arena_size": spec.run_config.get("arena_size", [10.0, 10.0]),
            "mechanism": "State divergence threshold broadcasting",
            "modality": "SIMULATION",
        }

"""Experiment planner compiling falsifiable hypotheses into reproducible specs via domain plugins."""

from __future__ import annotations

from typing import Any, Optional

from research_os.domains.base import UnsupportedDomainError
from research_os.domains.registry import DomainRegistry, default_domain_registry
from research_os.models.base import BaseModelAdapter
from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.hypothesis import HypothesisProposal


class ExperimentPlanner:
    """Plans experiments and compiles falsifiable hypotheses into executable specs via domain plugins."""

    def __init__(
        self,
        domain_registry: Optional[DomainRegistry] = None,
        model_adapter: Optional[BaseModelAdapter] = None,
    ) -> None:
        self.registry = domain_registry or default_domain_registry
        self.model_adapter = model_adapter

    def plan_experiment(
        self,
        hypothesis: HypothesisProposal,
        spec_id: Optional[str] = None,
        run_config_overrides: Optional[dict[str, Any]] = None,
        timeout_seconds: int = 60,
    ) -> tuple[ExperimentSpec, str]:
        """Convert a HypothesisProposal into an ExperimentSpec and executable code via domain plugins.

        Args:
            hypothesis: The scientific hypothesis to be tested.
            spec_id: Optional unique spec ID.
            run_config_overrides: Optional parameter overrides.
            timeout_seconds: Hard execution boundary limit.

        Returns:
            tuple[ExperimentSpec, str]: The specification artifact and code string.

        Raises:
            UnsupportedDomainError: When no registered domain plugin supports the hypothesis domain.
        """
        plugin = self.registry.detect_domain(hypothesis)
        if not plugin:
            raise UnsupportedDomainError(
                f"Domain for hypothesis '{hypothesis.hypothesis_id}' is not supported by any registered domain plugin.",
                status="UNSUPPORTED_DOMAIN",
                hypothesis_id=hypothesis.hypothesis_id,
            )

        spec_reqs: dict[str, Any] = {"timeout_seconds": timeout_seconds}
        if run_config_overrides:
            spec_reqs.update(run_config_overrides)

        spec = plugin.plan_experiment(hypothesis, spec_reqs)
        if spec_id:
            spec.spec_id = spec_id

        code = plugin.generate_experiment_code(spec, self.model_adapter)
        return spec, code

    def generate_simulation_script(
        self,
        hypothesis: HypothesisProposal,
        spec: ExperimentSpec,
    ) -> str:
        """Generate executable experiment script via domain plugin."""
        plugin = self.registry.detect_domain(hypothesis)
        if not plugin:
            raise UnsupportedDomainError(
                f"Cannot generate experiment code: Domain for hypothesis '{hypothesis.hypothesis_id}' is unsupported.",
                status="UNSUPPORTED_DOMAIN",
                hypothesis_id=hypothesis.hypothesis_id,
            )
        return plugin.generate_experiment_code(spec, self.model_adapter)

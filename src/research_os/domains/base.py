"""Domain plugin abstraction and provenance models for Research OS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional
from pydantic import Field

from research_os.models.base import BaseModelAdapter
from research_os.schemas.base import ArtifactBaseModel
from research_os.schemas.experiment import ExperimentSpec, ExperimentType
from research_os.schemas.hypothesis import HypothesisProposal


class ValidationResult(ArtifactBaseModel):
    """Result of domain hypothesis validation."""

    is_valid: bool = Field(description="Whether the hypothesis is scientifically valid in this domain")
    domain_id: str = Field(description="Domain plugin ID that performed validation")
    reasons: list[str] = Field(default_factory=list, description="Validation rationale or rejection reasons")


class MetricProvenanceItem(ArtifactBaseModel):
    """Traceable origin record connecting a metric to its raw measurement."""

    metric_name: str = Field(description="Name of the evaluated metric")
    raw_source_file: str = Field(description="Relative path to the raw data file backing this metric")
    derivation_procedure: str = Field(description="Explicit calculation formula or procedure applied")
    computed_value: float = Field(description="Numerical value calculated from raw data")
    verified: bool = Field(default=True, description="Whether recalculation against raw data matches")
    notes: Optional[str] = Field(default=None, description="Diagnostic commentary or warnings")


class MetricProvenanceReport(ArtifactBaseModel):
    """Auditable proof that metrics are backed by raw experimental outputs."""

    is_valid: bool = Field(description="Whether all metrics possess valid traceable provenance")
    provenance_records: list[MetricProvenanceItem] = Field(
        default_factory=list,
        description="Individual provenance derivations for each metric"
    )
    unbacked_metrics: list[str] = Field(
        default_factory=list,
        description="List of declared metrics lacking raw data derivation"
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Integrity or calculation discrepancies discovered"
    )


class UnsupportedDomainError(Exception):
    """Raised when an experiment is requested for an un-registered research domain."""

    def __init__(
        self,
        message: str,
        status: str = "UNSUPPORTED_DOMAIN",
        hypothesis_id: Optional[str] = None,
        domain_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.hypothesis_id = hypothesis_id
        self.domain_id = domain_id


class DomainNotFoundError(UnsupportedDomainError):
    """Raised when an experiment domain is not registered."""
    pass


class DomainPlugin(ABC):
    """Abstract base class for all domain-specific Research OS plugins."""

    domain_id: str
    display_name: str
    supported_experiment_types: list[ExperimentType]

    @abstractmethod
    def validate_hypothesis(self, hypothesis: HypothesisProposal) -> ValidationResult:
        """Validate whether a hypothesis proposal can be operationalized in this domain."""
        pass

    @abstractmethod
    def plan_experiment(
        self,
        hypothesis: HypothesisProposal,
        spec_requirements: Optional[dict[str, Any]] = None,
    ) -> ExperimentSpec:
        """Compile a hypothesis into a typed, reproducible ExperimentSpec."""
        pass

    @abstractmethod
    def generate_experiment_code(
        self,
        spec: ExperimentSpec,
        model_adapter: Optional[BaseModelAdapter] = None,
    ) -> str:
        """Generate the complete executable script for the experiment."""
        pass

    @abstractmethod
    def validate_metric_provenance(
        self,
        raw_data_dir: Path,
        metrics: dict[str, Any],
    ) -> MetricProvenanceReport:
        """Verify that metrics reported in metrics.json are authentically derived from raw outputs."""
        pass

    def matches_domain(self, hypothesis: HypothesisProposal) -> bool:
        """Check if this plugin can handle the given hypothesis based on domain/mechanisms."""
        return False

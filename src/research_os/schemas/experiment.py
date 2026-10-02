"""Experiment specification schemas for Research OS."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import Field, field_validator, model_validator
from .base import ArtifactBaseModel
from .mechanism import MechanismContract


class ExperimentClass(str, Enum):
    """Rigorous epistemic classification of research experiment execution."""

    EMPIRICAL = "EMPIRICAL"                         # Real-world physical or observational measurements
    SIMULATION = "SIMULATION"                       # Computational modeling or in-silico physics
    SYNTHETIC_BENCHMARK = "SYNTHETIC_BENCHMARK"     # Programmatic or algorithmic synthetic workloads
    REPRODUCTION = "REPRODUCTION"                   # Exact recreation of previously published protocols


class ExperimentModality(str, Enum):
    """Specific technical modality of experimental execution."""

    RAG = "RAG"
    MULTI_AGENT = "MULTI_AGENT"
    PHYSICS_SIMULATION = "PHYSICS_SIMULATION"
    TABULAR_EVALUATION = "TABULAR_EVALUATION"
    GENERIC = "GENERIC"


class ExperimentType(str, Enum):
    """Extensible classification of experimental protocols."""

    SIMULATION = "SIMULATION"
    BENCHMARK = "BENCHMARK"
    DATASET_ANALYSIS = "DATASET_ANALYSIS"
    NUMERICAL_EXPERIMENT = "NUMERICAL_EXPERIMENT"


class ResourceLimits(ArtifactBaseModel):
    """Explicitly separated execution resource boundaries and enforced operating system limits.
    
    Disambiguates host requirements (min_ram_gb) from enforced process limits (max_ram_gb).
    """

    min_ram_gb: float = Field(default=2.0, ge=0.01, description="Host system RAM requirement in GB")
    max_ram_gb: float = Field(default=4.0, ge=0.01, description="Enforced memory cap in GB via Windows Job Object / Linux prlimit / psutil watchdog")
    max_cpu_seconds: int = Field(default=300, ge=1, description="Enforced CPU time limit in seconds")
    timeout_seconds: int = Field(default=600, ge=5, le=86400, description="Hard wall-clock timeout limit in seconds")
    max_cpu_cores: Optional[int] = Field(default=None, ge=1, description="CPU core cap")


class HardwareRequirements(ArtifactBaseModel):
    """Execution environment resource boundaries."""

    cuda_required: bool = Field(default=False, description="Whether GPU/CUDA compute is required")
    min_gpu_vram_gb: Optional[float] = Field(default=None, ge=0.0, description="Minimum GPU VRAM in GB")
    min_ram_gb: float = Field(default=2.0, ge=0.01, description="Minimum system RAM requirement in GB (Host requirement)")
    max_ram_gb: Optional[float] = Field(default=None, ge=0.01, description="Enforced memory cap in GB via Windows Job Object / Linux prlimit / psutil watchdog")
    max_cpu_cores: Optional[int] = Field(default=None, ge=1, description="CPU core cap")
    max_cpu_seconds: Optional[int] = Field(default=None, ge=1, description="Enforced CPU time limit in seconds")
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=86400, description="Timeout limit in seconds")


class ExperimentSpec(ArtifactBaseModel):
    """Deterministic recipe for compiling and running an empirical experiment."""

    spec_id: str = Field(description="Unique experiment specification ID (e.g. 'exp-moe-01')")
    hypothesis_id: str = Field(description="Foreign key to HypothesisProposal.hypothesis_id")
    experiment_type: ExperimentType = Field(
        default=ExperimentType.SIMULATION,
        description="Categorical type of experiment being performed"
    )
    experiment_class: ExperimentClass = Field(
        default=ExperimentClass.SIMULATION,
        description="Epistemic modality of the experiment (Directive 3)"
    )

    @model_validator(mode="before")
    @classmethod
    def infer_experiment_class(cls, data: Any) -> Any:
        if isinstance(data, dict) and "experiment_class" not in data:
            exp_type = data.get("experiment_type", ExperimentType.SIMULATION)
            if isinstance(exp_type, str):
                try:
                    exp_type = ExperimentType(exp_type)
                except ValueError:
                    pass
            if exp_type == ExperimentType.SIMULATION:
                data["experiment_class"] = ExperimentClass.SIMULATION
            elif exp_type == ExperimentType.BENCHMARK:
                data["experiment_class"] = ExperimentClass.SYNTHETIC_BENCHMARK
            elif exp_type == ExperimentType.DATASET_ANALYSIS:
                data["experiment_class"] = ExperimentClass.EMPIRICAL
            elif exp_type == ExperimentType.NUMERICAL_EXPERIMENT:
                data["experiment_class"] = ExperimentClass.SIMULATION
        return data
    name: str = Field(min_length=1, description="Short human-readable experiment name")
    description: str = Field(default="", description="Detailed narrative of experimental protocol")
    entry_point: str = Field(
        min_length=1,
        description="Command or script entry point (e.g. 'python run_experiment.py')"
    )
    run_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Deterministic hyperparameters and arguments passed to the entry point"
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Python packages required for execution (e.g. ['torch>=2.0.0', 'numpy'])"
    )
    random_seeds: list[int] = Field(
        default_factory=lambda: [42],
        min_length=1,
        description="List of random seeds to evaluate for statistical confidence"
    )
    expected_outputs: list[str] = Field(
        min_length=1,
        description="Relative file paths that must be produced upon successful run (e.g. ['metrics.json'])"
    )
    timeout_seconds: int = Field(
        default=600,
        ge=5,
        le=86400,
        description="Hard timeout limit in seconds after which execution is aborted"
    )
    hardware_requirements: HardwareRequirements = Field(
        default_factory=HardwareRequirements,
        description="Resource quotas and hardware requirements"
    )
    resource_limits: Optional[ResourceLimits] = Field(
        default=None,
        description="Explicit resource limits separating host requirements from enforced OS caps"
    )
    mechanism_contract: Optional[MechanismContract] = Field(
        default=None,
        description="Mandatory structural execution transitions and trace event requirements (Directive 1)"
    )
    declared_metrics: list[str] = Field(
        default_factory=list,
        description="Explicit list of permitted/declared metric names (Directive 3)",
    )

    @property
    def enforced_max_ram_gb(self) -> float:
        """Return the enforced memory cap (strictly distinguished from min_ram_gb host requirement)."""
        if self.resource_limits is not None and self.resource_limits.max_ram_gb is not None:
            return self.resource_limits.max_ram_gb
        if self.hardware_requirements.max_ram_gb is not None:
            return self.hardware_requirements.max_ram_gb
        return max(self.hardware_requirements.min_ram_gb * 2.0, 4.0)

    @property
    def effective_timeout_seconds(self) -> int:
        if self.resource_limits is not None and self.resource_limits.timeout_seconds:
            return self.resource_limits.timeout_seconds
        return self.timeout_seconds

    @property
    def effective_max_cpu_seconds(self) -> Optional[int]:
        if self.resource_limits is not None and self.resource_limits.max_cpu_seconds is not None:
            return self.resource_limits.max_cpu_seconds
        if self.hardware_requirements.max_cpu_seconds is not None:
            return self.hardware_requirements.max_cpu_seconds
        return None

    @field_validator("expected_outputs")
    @classmethod
    def validate_expected_outputs(cls, outputs: list[str]) -> list[str]:
        cleaned = [o.strip() for o in outputs if o.strip()]
        if not cleaned:
            raise ValueError("ExperimentSpec must specify at least one expected output file.")
        return cleaned

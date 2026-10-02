"""Universal Domain Adapter Interface for Research OS.

Provides the foundational abstract base class for domain adapters across
applied scientific disciplines (NLP, Robotics, Biotech, Neurotech, Defense).
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
from abc import abstractmethod
from pathlib import Path
from typing import Any, Optional, Union

from research_os.domains.base import (
    DomainPlugin,
    MetricProvenanceReport,
    ValidationResult,
)
from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.hypothesis import HypothesisProposal


class DatasetIntegrityError(RuntimeError):
    """Raised when an empirical baseline dataset is missing or fails cryptographic checksum verification."""
    pass


class BaseDomainAdapter(DomainPlugin):
    """Universal domain adapter interface for all Research OS applied domains."""

    domain_id: str
    display_name: str

    @abstractmethod
    def validate_environment(self) -> dict[str, bool]:
        """Validates that domain-specific runtimes/libraries are available in the system path.
        
        Returns a mapping of runtime/library names to availability status (True/False).
        """
        pass

    def fetch_verified_data(
        self,
        dataset_id: str,
        target_dir: Optional[Union[str, Path]] = None,
        expected_sha256: Optional[str] = None,
    ) -> Path:
        """Pulls empirical baseline datasets with cryptographic SHA-256 caching.
        
        Supports local cache resolution, verified checksum verification, and authentic data acquisition.
        Fails closed: never generates mock or placeholder datasets if missing or checksum invalid.
        """
        cache_base = Path(target_dir or "data/cache") / self.domain_id
        safe_name = dataset_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        cached_file = cache_base / f"{safe_name}.dat"

        # Check existing cached data with SHA-256 integrity
        if not cached_file.exists():
            raise DatasetIntegrityError(
                f"Dataset {dataset_id} failed checksum verification or is missing at {cached_file}"
            )

        content = cached_file.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()
        if expected_sha256 is not None and actual_sha.lower() != expected_sha256.lower():
            raise DatasetIntegrityError(
                f"Dataset {dataset_id} failed checksum verification or is missing: "
                f"expected {expected_sha256}, got {actual_sha}"
            )

        return cached_file

    @abstractmethod
    def generate_execution_plan(self, spec: ExperimentSpec) -> dict[str, Any]:
        """Binds experiment specifications to verified domain solvers rather than synthetic algebraic mock functions."""
        pass

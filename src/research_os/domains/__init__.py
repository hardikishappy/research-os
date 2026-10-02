"""Domain plugin abstractions, registries, and provenance contracts for Research OS."""

from .base import (
    DomainNotFoundError,
    DomainPlugin,
    MetricProvenanceItem,
    MetricProvenanceReport,
    UnsupportedDomainError,
    ValidationResult,
)
from .declarative import (
    DeclarativeMetricDef,
    DeclarativePluginSpec,
    UnsupportedVerificationPrimitiveError,
    recompute_declarative_metric,
)
from .registry import DomainRegistry, default_domain_registry

__all__ = [
    "DomainPlugin",
    "ValidationResult",
    "MetricProvenanceItem",
    "MetricProvenanceReport",
    "UnsupportedDomainError",
    "DomainNotFoundError",
    "DomainRegistry",
    "default_domain_registry",
    "DeclarativeMetricDef",
    "DeclarativePluginSpec",
    "UnsupportedVerificationPrimitiveError",
    "recompute_declarative_metric",
]

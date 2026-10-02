"""Deterministic verification module for Research OS."""

from .deterministic import (
    DeterministicVerifier,
    MetricFabricationError,
    MissingRawArtifactError,
    ProvenanceIntegrityError,
    compute_directory_checksums,
    compute_file_sha256,
    create_run_manifest,
    evaluate_metric_condition,
    recompute_metric_from_artifact,
)

__all__ = [
    "DeterministicVerifier",
    "MetricFabricationError",
    "MissingRawArtifactError",
    "ProvenanceIntegrityError",
    "compute_file_sha256",
    "compute_directory_checksums",
    "create_run_manifest",
    "evaluate_metric_condition",
    "recompute_metric_from_artifact",
]

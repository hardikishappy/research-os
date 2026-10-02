"""Experiment classification schemas for Research OS (Directive 3).

Enforces:
- Explicit ontological separation between real-world empirical data, in-silico simulations,
  synthetic benchmarks, and literature reproductions.
- Scientific integrity constraints derived from experimental modality.
"""

from __future__ import annotations

from research_os.schemas.experiment import ExperimentClass

__all__ = ["ExperimentClass"]

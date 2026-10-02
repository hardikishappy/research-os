"""Core architectural invariants and scientific integrity foundations for Research OS."""

from .classification import ExperimentClass
from .integrity import (
    EpistemicHonestyViolation,
    ScientificIntegrityError,
    ScientificIntegrityLinter,
)
from .trace import ExecutionTraceRecord, TraceLogger, verify_execution_trace

__all__ = [
    "ExperimentClass",
    "ScientificIntegrityError",
    "EpistemicHonestyViolation",
    "ScientificIntegrityLinter",
    "ExecutionTraceRecord",
    "TraceLogger",
    "verify_execution_trace",
]

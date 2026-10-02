"""Policy-controlled execution engine for Research OS (Rule 15 Enforcement)."""

from __future__ import annotations

from .runner import (
    EntrypointResolutionError,
    PolicySubprocessRunner,
    SandboxExecutionResult,
    SandboxRunner,
    SandboxSecurityViolation,
    UnauthorizedExecutionMutation,
)
from .verification import verify_anti_fabrication

__all__ = [
    "EntrypointResolutionError",
    "PolicySubprocessRunner",
    "SandboxRunner",
    "SandboxExecutionResult",
    "SandboxSecurityViolation",
    "UnauthorizedExecutionMutation",
    "verify_anti_fabrication",
]

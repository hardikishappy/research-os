"""Mechanism Execution Contracts for Research OS (Directive 1).

Defines mandatory structural execution transitions and observable trace event requirements.
Enforces that experiments must demonstrate authentic causal mechanics rather than
mocked outcome-engineered sampling.
"""

from __future__ import annotations

from research_os.schemas.mechanism import MechanismContract, MechanismEventRequirement

__all__ = [
    "MechanismContract",
    "MechanismEventRequirement",
]

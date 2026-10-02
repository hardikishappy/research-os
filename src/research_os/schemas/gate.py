"""Human-in-the-loop approval gate schemas for Research OS."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import Field
from .base import ArtifactBaseModel


class GateKind(str, Enum):
    """Categorical types of approval gates requiring human sign-off."""

    IDEA_PROMOTION = "idea_promotion"
    COMPUTE_BUDGET = "compute_budget"
    EXPERIMENT_LAUNCH = "experiment_launch"
    PAPER_SUBMISSION = "paper_submission"
    DIRECTION_PIVOT = "direction_pivot"
    DOMAIN_PLUGIN_INSTALL = "domain_plugin_install"


class GateStatus(str, Enum):
    """Lifecycle state of a human gate."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# Semantic alias
GateDecision = GateStatus


class HumanGateToken(ArtifactBaseModel):
    """Tamper-evident token representing human authorization for high-stakes transitions."""

    gate_id: str = Field(description="Unique gate identifier (e.g. 'gate-proj-01-launch')")
    project_id: str = Field(description="Associated project identifier")
    voyage_id: str = Field(description="Associated execution voyage or workflow run ID")
    kind: GateKind = Field(description="Type of gate being authorized")
    status: GateStatus = Field(
        default=GateStatus.PENDING,
        description="Current authorization status"
    )
    authorization_signature: Optional[str] = Field(
        default=None,
        description="Cryptographic signature, HMAC, or user credential verifying identity"
    )
    decided_by: Optional[str] = Field(
        default=None,
        description="Username, email, or UUID of human decision maker"
    )
    user_notes: Optional[str] = Field(
        default=None,
        description="Explanatory rationale, conditions, or review comments provided by reviewer"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Contextual snapshot payload submitted for human review (e.g. proposed budget, idea spec)"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when gate was opened"
    )
    decided_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when human decision was recorded"
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Expiration timestamp after which token is invalid"
    )
    public_key_hex: Optional[str] = Field(
        default=None,
        description="Public verification key in hex for asymmetric authorization"
    )

    def is_approved(self) -> bool:
        """Check if gate has been formally approved with valid decision metadata."""
        return (
            self.status == GateStatus.APPROVED
            and self.decided_by is not None
            and self.decided_at is not None
        )

    def approve(self, user: str, signature: str, notes: Optional[str] = None) -> None:
        """Record an explicit human approval."""
        self.status = GateStatus.APPROVED
        self.decided_by = user
        self.authorization_signature = signature
        self.user_notes = notes
        self.decided_at = datetime.now(timezone.utc)

    def reject(self, user: str, notes: Optional[str] = None) -> None:
        """Record an explicit human rejection."""
        self.status = GateStatus.REJECTED
        self.decided_by = user
        self.user_notes = notes
        self.decided_at = datetime.now(timezone.utc)

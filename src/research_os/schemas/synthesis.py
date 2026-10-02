"""Cross-paper literature synthesis and research gap schemas for Research OS."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pydantic import Field
from .base import ArtifactBaseModel
from .paper import SectionProvenance


class ResearchGap(ArtifactBaseModel):
    """An identified empirical or theoretical gap supported by cited paper evidence."""

    gap_id: str = Field(description="Unique gap identifier (e.g. 'gap-context-length-01')")
    description: str = Field(min_length=10, description="Detailed explanation of the unresolved scientific challenge")
    evidence_paper_ids: list[str] = Field(
        min_length=1,
        description="List of source paper IDs that substantiate this limitation or gap"
    )
    evidence_citations: list[SectionProvenance] = Field(
        default_factory=list,
        description="Exact cited snippets and section locations evidencing the gap"
    )
    impact_potential: str = Field(
        description="Assessment of potential research significance if this gap is solved"
    )


class CrossPaperSynthesis(ArtifactBaseModel):
    """Structured synthesis of multiple research papers across a shared topic."""

    synthesis_id: str = Field(description="Unique synthesis artifact ID")
    topic: str = Field(min_length=1, description="Research theme or query under investigation")
    analyzed_paper_ids: list[str] = Field(
        min_length=1,
        description="IDs of all literature sources ingested in this synthesis"
    )
    identified_gaps: list[ResearchGap] = Field(
        default_factory=list,
        description="Identified research gaps grounded in cited literature evidence"
    )
    consensus_findings: list[str] = Field(
        default_factory=list,
        description="Findings broadly corroborated across multiple papers"
    )
    contested_claims: list[str] = Field(
        default_factory=list,
        description="Conflicting experimental results or theoretical disputes among authors"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of synthesis generation"
    )

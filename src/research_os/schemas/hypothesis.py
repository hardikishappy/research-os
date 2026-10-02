"""Hypothesis proposal schemas for Research OS."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import Field
from .base import ArtifactBaseModel


class MechanismProvenance(ArtifactBaseModel):
    """Credit attribution for a borrowed algorithmic or architectural mechanism."""

    source_paper_id: str = Field(description="Paper ID from which the mechanism was borrowed")
    paper_title: str = Field(description="Title of the source paper")
    domain: str = Field(description="Subfield or domain of the source paper (e.g. 'RL', 'NLP')")
    borrowed_aspect: str = Field(description="Exact algorithmic technique or insight adopted")


class HypothesisProposal(ArtifactBaseModel):
    """Falsifiable scientific hypothesis ready for experimental operationalization."""

    hypothesis_id: str = Field(description="Unique hypothesis identifier (e.g. 'hyp-moe-routing-01')")
    title: str = Field(min_length=1, description="Concise hypothesis summary title")
    falsifiable_statement: str = Field(
        min_length=10,
        description="Empirically falsifiable prediction (e.g. 'Method X achieves lower latency than Y with <= 1% accuracy drop')"
    )
    baseline_method: str = Field(
        description="Standard baseline against which the hypothesis will be tested"
    )
    proposed_mechanism: str = Field(
        description="Novel technical mechanism or variation to be introduced"
    )
    theoretical_rationale: str = Field(
        description="Scientific principles or prior literature backing why this mechanism should work"
    )
    inspired_by_seeds: list[MechanismProvenance] = Field(
        default_factory=list,
        description="Explicit provenance tracking borrowed cross-domain or literature mechanisms"
    )
    target_metric: str = Field(
        description="Primary quantitative metric to measure (e.g. 'perplexity', 'top1_accuracy')"
    )
    expected_direction: Literal["increase", "decrease"] = Field(
        description="Expected direction of metric improvement"
    )
    success_threshold: float = Field(
        description="Minimum quantitative delta or absolute metric value required to confirm hypothesis"
    )
    addressed_gap_id: Optional[str] = Field(
        default=None,
        description="Associated ResearchGap identifier if derived from literature synthesis"
    )

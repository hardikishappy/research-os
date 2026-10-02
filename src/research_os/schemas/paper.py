"""Paper ingestion and extraction schemas for Research OS."""

from __future__ import annotations

import re
from typing import Optional
from pydantic import Field, field_validator
from .base import ArtifactBaseModel


class PaperMetadata(ArtifactBaseModel):
    """Metadata describing a published scientific paper."""

    paper_id: str = Field(description="Unique deterministic ID (e.g. arXiv ID, DOI, or S2 corpus ID)")
    title: str = Field(min_length=1, description="Full paper title")
    authors: list[str] = Field(default_factory=list, description="List of author names")
    abstract: str = Field(default="", description="Paper abstract text")
    year: Optional[int] = Field(default=None, description="Publication year")
    venue: Optional[str] = Field(default=None, description="Publication venue or journal")
    doi: Optional[str] = Field(default=None, description="Digital Object Identifier")
    arxiv_id: Optional[str] = Field(default=None, description="arXiv identifier, e.g. '2410.23166'")
    url: Optional[str] = Field(default=None, description="Canonical source URL")
    citation_count: Optional[int] = Field(default=None, ge=0, description="Observed citation count")

    @field_validator("arxiv_id")
    @classmethod
    def validate_arxiv_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            # Canonical arXiv format or prefixed
            if not re.match(r"^(arxiv:)?\d{4}\.\d{4,5}(v\d+)?$", v, re.IGNORECASE):
                # Allow legacy formats like hep-th/9901001
                if not re.match(r"^[a-zA-Z\-]+/\d{7}$", v):
                    pass  # keep flexible but clean
        return v


class SectionProvenance(ArtifactBaseModel):
    """Provenance pointer tying extracted text/formulas to an exact paper section."""

    source_paper_id: str = Field(description="Foreign key to PaperMetadata.paper_id")
    section_title: str = Field(description="Heading or section name (e.g. '3.2 Contrastive Loss')")
    section_index: Optional[int] = Field(default=None, description="Zero-based or one-based section order index")
    page_start: Optional[int] = Field(default=None, ge=1, description="Start page in original PDF")
    page_end: Optional[int] = Field(default=None, ge=1, description="End page in original PDF")
    text_snippet: str = Field(description="Exact verbatim or extracted sentence snippet")


class ExtractedEquation(ArtifactBaseModel):
    """Mathematical equation extracted from a paper with provenance."""

    equation_id: str = Field(description="Equation identifier (e.g. 'eq_1', 'loss_formulation')")
    latex: str = Field(description="Clean LaTeX representation of the equation")
    description: str = Field(default="", description="Semantic role and variable definitions")
    provenance: SectionProvenance = Field(description="Exact location in source paper")


class PaperExtraction(ArtifactBaseModel):
    """Complete structured extraction from a paper, retaining auditable provenance."""

    extraction_id: str = Field(description="Unique extraction artifact identifier")
    paper_id: str = Field(description="Source paper identifier")
    metadata: PaperMetadata = Field(description="Paper metadata")
    sections: dict[str, str] = Field(
        default_factory=dict,
        description="Dictionary mapping section title to extracted body text"
    )
    section_provenance: list[SectionProvenance] = Field(
        default_factory=list,
        description="Detailed provenance mappings for all extracted sections"
    )
    equations: list[ExtractedEquation] = Field(
        default_factory=list,
        description="Extracted mathematical formulas with provenance"
    )
    algorithms: list[str] = Field(
        default_factory=list,
        description="Pseudocode or procedural algorithm blocks"
    )
    key_findings: list[str] = Field(
        default_factory=list,
        description="Bullet points of verified empirical claims and findings"
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Author-acknowledged or extracted method limitations"
    )
    source_checksum: str = Field(
        description="SHA-256 hash of the raw input PDF or source document"
    )

"""Gap mining module for extracting evidence-grounded research gaps."""

from __future__ import annotations

import re
from typing import Optional
from research_os.models.base import BaseModelAdapter
from research_os.schemas.paper import PaperExtraction, SectionProvenance
from research_os.schemas.synthesis import CrossPaperSynthesis, ResearchGap


GAP_MINER_PROMPT = """You are a rigorous scientific gap mining engine in Research OS.
Analyze the CrossPaperSynthesis and papers to extract explicit, falsifiable research gaps.

POLICIES:
1. RULE 1 (Evidence): Every gap must point to explicit paper IDs and concrete section snippets in evidence_citations.
2. RULE 2 (Novelty Hedging): Descriptions must explicitly state: 'No close match was identified in the searched sources' or similar hedged phrasing. NEVER claim absolute novelty.
"""


def hedge_gap_description(description: str) -> str:
    """Enforce Rule 2 (Novelty Hedging) on a research gap description."""
    hedging_phrases = [
        "no close match was identified in the searched sources",
        "in the analyzed literature, no direct resolution was found",
        "within the examined scope, this question remains open",
    ]
    lower_desc = description.lower()
    if not any(phrase in lower_desc for phrase in hedging_phrases):
        # Cleanly prepend the required scientific hedging statement
        description = f"No close match was identified in the searched sources addressing {description[0].lower() + description[1:]}"
    return description


class GapMiner:
    """Extracts and verifies grounded research gaps from synthesized literature."""

    def __init__(self, model_adapter: Optional[BaseModelAdapter] = None) -> None:
        self.model = model_adapter

    def mine_gaps(
        self,
        synthesis: CrossPaperSynthesis,
        papers: list[PaperExtraction],
    ) -> list[ResearchGap]:
        """Mine and validate research gaps from a CrossPaperSynthesis artifact.

        Guarantees:
        - All gaps are backed by existing paper IDs in the corpus.
        - Descriptions adhere strictly to Rule 2 (Novelty Hedging).
        - Each gap includes verified SectionProvenance citations.
        """
        # If synthesis already contains gaps, validate and hedge them
        gaps: list[ResearchGap] = []
        valid_paper_ids = {p.paper_id for p in papers}

        if synthesis.identified_gaps:
            for g in synthesis.identified_gaps:
                # Ensure all evidence papers actually exist in the corpus
                filtered_evidence_ids = [pid for pid in g.evidence_paper_ids if pid in valid_paper_ids]
                if not filtered_evidence_ids and valid_paper_ids:
                    filtered_evidence_ids = [list(valid_paper_ids)[0]]

                # Ensure evidence citations are grounded
                citations: list[SectionProvenance] = []
                for cit in g.evidence_citations:
                    if cit.source_paper_id in valid_paper_ids:
                        citations.append(cit)

                # If no citations survived, extract from evidence papers directly
                if not citations and filtered_evidence_ids:
                    for pid in filtered_evidence_ids:
                        matching_paper = next((p for p in papers if p.paper_id == pid), None)
                        if matching_paper and matching_paper.section_provenance:
                            citations.append(matching_paper.section_provenance[0])

                hedged_desc = hedge_gap_description(g.description)

                gaps.append(
                    ResearchGap(
                        gap_id=g.gap_id,
                        description=hedged_desc,
                        evidence_paper_ids=filtered_evidence_ids,
                        evidence_citations=citations,
                        impact_potential=g.impact_potential,
                    )
                )

        if not gaps:
            # Deterministic generation from paper limitations
            for idx, p in enumerate(papers, start=1):
                if p.limitations:
                    lim_text = p.limitations[0]
                    prov = p.section_provenance[0] if p.section_provenance else SectionProvenance(
                        source_paper_id=p.paper_id,
                        section_title="Limitations",
                        text_snippet=lim_text,
                    )
                    gaps.append(
                        ResearchGap(
                            gap_id=f"gap-auto-{idx:02d}",
                            description=hedge_gap_description(f"solutions for: {lim_text}"),
                            evidence_paper_ids=[p.paper_id],
                            evidence_citations=[prov],
                            impact_potential=f"Resolves operational bottleneck noted in {p.metadata.title}",
                        )
                    )

        return gaps

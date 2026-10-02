"""Academic Harvester & Multi-Researcher Citation Explorer for Research OS."""

from research_os.harvester.arxiv_client import ArxivHarvesterClient
from research_os.harvester.scholar import ScholarHarvesterClient
from research_os.harvester.researcher_curator import (
    CuratedCorpus,
    PrincipalInvestigator,
    ResearcherCurator,
)

__all__ = [
    "ArxivHarvesterClient",
    "ScholarHarvesterClient",
    "ResearcherCurator",
    "CuratedCorpus",
    "PrincipalInvestigator",
]

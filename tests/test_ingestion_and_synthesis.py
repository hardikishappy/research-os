"""Integration and unit tests for Literature Ingestion, Synthesis, and Gap Mining."""

import json
from pathlib import Path
import pytest

from research_os.cli import run_ingest_and_mine
from research_os.ideation.gap_miner import GapMiner, hedge_gap_description
from research_os.ideation.hypothesis_generator import HypothesisGenerator
from research_os.ingestion.parser import (
    deduplicate_papers,
    load_paper_fixtures,
    normalize_title,
    parse_paper_file,
)
from research_os.models.mock import MockModelAdapter
from research_os.schemas.hypothesis import HypothesisProposal
from research_os.schemas.paper import PaperExtraction
from research_os.schemas.synthesis import CrossPaperSynthesis, ResearchGap
from research_os.synthesis.matrix import CapabilityMatrix, build_capability_matrix
from research_os.synthesis.synthesizer import LiteratureSynthesizer

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "swarm_robotics"


def test_fixture_papers_exist():
    assert FIXTURES_DIR.is_dir()
    files = list(FIXTURES_DIR.glob("*.md"))
    assert len(files) >= 4


def test_parse_single_markdown_paper():
    p1_path = FIXTURES_DIR / "paper_01_reynolds_bandwidth.md"
    extraction = parse_paper_file(p1_path)

    assert isinstance(extraction, PaperExtraction)
    assert extraction.metadata.title == "Scalable Decentralized Flocking under Strict Bandwidth Limits"
    assert "Marcus Vance" in extraction.metadata.authors
    assert extraction.metadata.year == 2023
    assert extraction.metadata.doi == "10.1109/TRO.2023.1092831"
    assert extraction.metadata.arxiv_id == "2304.09182"
    assert len(extraction.sections) >= 5
    assert len(extraction.equations) >= 1
    assert "F_{ij}" in extraction.equations[0].latex
    assert len(extraction.key_findings) >= 2
    assert len(extraction.limitations) >= 2
    assert len(extraction.source_checksum) == 64

    # Verify provenance
    for prov in extraction.section_provenance:
        assert prov.source_paper_id == extraction.paper_id
        assert len(prov.text_snippet) > 0


def test_deduplication_logic():
    p1_path = FIXTURES_DIR / "paper_01_reynolds_bandwidth.md"
    ext1 = parse_paper_file(p1_path)

    # Identical copy
    ext2 = parse_paper_file(p1_path)

    deduped = deduplicate_papers([ext1, ext2])
    assert len(deduped) == 1

    # Modified title copy with same DOI
    ext3 = ext1.model_copy(deep=True)
    ext3.metadata.title = "Completely Different Title But Identical DOI"
    deduped2 = deduplicate_papers([ext1, ext3])
    assert len(deduped2) == 1

    # Same title with different DOI
    ext4 = ext1.model_copy(deep=True)
    ext4.metadata.doi = "10.1000/different.doi"
    deduped3 = deduplicate_papers([ext1, ext4])
    assert len(deduped3) == 1  # Deduplicated on normalized title


def test_load_all_fixtures():
    papers = load_paper_fixtures(FIXTURES_DIR)
    assert len(papers) == 4
    # All unique paper IDs
    ids = [p.paper_id for p in papers]
    assert len(set(ids)) == 4


def test_capability_matrix_building():
    papers = load_paper_fixtures(FIXTURES_DIR)
    matrix = build_capability_matrix(papers)

    assert isinstance(matrix, CapabilityMatrix)
    assert len(matrix.rows) == 4

    md_table = matrix.to_markdown_table()
    assert "| Paper ID |" in md_table
    assert "ARGoS Simulator" in md_table
    assert "Stage Simulator" in md_table


def test_literature_synthesizer_rules():
    papers = load_paper_fixtures(FIXTURES_DIR)
    matrix = build_capability_matrix(papers)
    mock_model = MockModelAdapter()
    synthesizer = LiteratureSynthesizer(mock_model)

    synthesis = synthesizer.synthesize_corpus(
        topic="Swarm Robotics Bandwidth Bottlenecks",
        papers=papers,
        matrix=matrix,
    )

    assert isinstance(synthesis, CrossPaperSynthesis)
    assert len(synthesis.analyzed_paper_ids) == 4
    assert len(synthesis.consensus_findings) >= 2
    assert len(synthesis.contested_claims) >= 2
    assert len(synthesis.identified_gaps) >= 1

    # Check Rule 1 (Evidence)
    gap = synthesis.identified_gaps[0]
    assert len(gap.evidence_paper_ids) > 0
    assert all(pid in synthesis.analyzed_paper_ids for pid in gap.evidence_paper_ids)
    assert len(gap.evidence_citations) > 0
    for cit in gap.evidence_citations:
        assert cit.source_paper_id in synthesis.analyzed_paper_ids

    # Check Rule 2 (Novelty Hedging)
    hedging_token = "no close match was identified in the searched sources"
    assert hedging_token in gap.description.lower()


def test_gap_miner_and_hedging():
    # Test standalone hedging helper
    raw_gap = "scaling flocking to 500 agents under packet loss"
    hedged = hedge_gap_description(raw_gap)
    assert "no close match was identified in the searched sources" in hedged.lower()

    # Pre-hedged gap is preserved
    already_hedged = "No close match was identified in the searched sources for X"
    assert hedge_gap_description(already_hedged) == already_hedged


def test_hypothesis_generator():
    papers = load_paper_fixtures(FIXTURES_DIR)
    matrix = build_capability_matrix(papers)
    synthesizer = LiteratureSynthesizer(MockModelAdapter())
    synthesis = synthesizer.synthesize_corpus(
        topic="Swarm Bandwidth Limits",
        papers=papers,
        matrix=matrix,
    )

    miner = GapMiner()
    gaps = miner.mine_gaps(synthesis, papers)
    assert len(gaps) >= 1

    hyp_gen = HypothesisGenerator()
    hypotheses = hyp_gen.generate_hypotheses(gaps=gaps, papers=papers, matrix=matrix)

    assert len(hypotheses) == len(gaps)
    for hyp in hypotheses:
        assert isinstance(hyp, HypothesisProposal)
        assert hyp.addressed_gap_id is not None
        assert len(hyp.falsifiable_statement) > 20
        assert hyp.baseline_method
        assert hyp.proposed_mechanism
        assert hyp.target_metric
        assert hyp.expected_direction in ("increase", "decrease")
        assert hyp.success_threshold > 0.0
        assert len(hyp.inspired_by_seeds) > 0


def test_end_to_end_cli_pipeline(tmp_path: Path):
    artifacts_dir = run_ingest_and_mine(
        corpus_dir=FIXTURES_DIR,
        topic="Swarm Robotics: Scaling Under Bandwidth Limits",
        provider="mock",
        output_base=tmp_path / "experiments" / "runs",
        run_id="integration-test-run",
    )

    assert artifacts_dir.is_dir()

    # Verify all expected artifacts exist
    expected_files = [
        "capability_matrix.json",
        "capability_matrix.md",
        "synthesis.json",
        "gaps.json",
        "hypotheses.json",
        "manifest.json",
    ]
    for fname in expected_files:
        p = artifacts_dir / fname
        assert p.is_file(), f"Expected artifact {fname} not found"

    # Schema validation of saved JSON files
    matrix_data = json.loads((artifacts_dir / "capability_matrix.json").read_text(encoding="utf-8"))
    CapabilityMatrix.model_validate(matrix_data)

    synthesis_data = json.loads((artifacts_dir / "synthesis.json").read_text(encoding="utf-8"))
    synthesis = CrossPaperSynthesis.model_validate(synthesis_data)

    gaps_data = json.loads((artifacts_dir / "gaps.json").read_text(encoding="utf-8"))
    for g in gaps_data:
        gap_obj = ResearchGap.model_validate(g)
        assert "no close match was identified in the searched sources" in gap_obj.description.lower()

    hyp_data = json.loads((artifacts_dir / "hypotheses.json").read_text(encoding="utf-8"))
    for h in hyp_data:
        HypothesisProposal.model_validate(h)

    manifest_data = json.loads((artifacts_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_data["run_id"] == "integration-test-run"
    assert manifest_data["status"] == "COMPLETED"
    assert manifest_data["paper_count"] == 4

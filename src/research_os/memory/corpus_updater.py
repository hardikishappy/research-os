"""Research memory feedback loop converting empirical evaluations into synthesizable literature artifacts (Rules 4 & 5)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from research_os.schemas.evaluation import EvaluationReport
from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.hypothesis import HypothesisProposal
from research_os.schemas.paper import PaperExtraction, PaperMetadata, SectionProvenance


class CorpusUpdater:
    """Stores verified empirical outcomes as synthesizable research memory artifacts."""

    def __init__(self, memory_dir: Union[str, Path] = "data/research_memory") -> None:
        self.memory_dir = Path(memory_dir).resolve()
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def record_empirical_finding(
        self,
        evaluation: EvaluationReport,
        hypothesis: HypothesisProposal,
        spec: Optional[ExperimentSpec] = None,
    ) -> tuple[PaperExtraction, Path]:
        """Convert an EvaluationReport into a synthetic PaperExtraction artifact.

        Enables closed-loop cumulative learning where subsequent synthesis cycles
        cite the system's own verified experiments.
        """
        finding_id = f"empirical-{evaluation.hypothesis_id}"
        extraction_id = f"ext-{evaluation.evaluation_id}"

        # 1. Format sections
        metrics_summary_lines = []
        for name, agg in evaluation.metric_aggregates.items():
            metrics_summary_lines.append(
                f"- **{name}**: mean = {agg.mean:.2f} (std_dev = {agg.std_dev:.2f}, std_err = {agg.std_err:.2f}), "
                f"target {agg.operator} {agg.target_threshold} -> {'PASS' if agg.passed else 'FAIL'}"
            )
        metrics_section = (
            "Empirical Multi-Seed Observations:\n"
            + ("\n".join(metrics_summary_lines) if metrics_summary_lines else "No metrics recorded.")
        )

        sections = {
            "Abstract": (
                f"Empirical testing of hypothesis '{hypothesis.title}' across {evaluation.total_runs} random seeds. "
                f"Outcome: {evaluation.verdict.value}. Rationale: {evaluation.summary_rationale}"
            ),
            "Hypothesis & Proposed Mechanism": (
                f"Statement: {hypothesis.falsifiable_statement}\n"
                f"Proposed Mechanism: {hypothesis.proposed_mechanism}\n"
                f"Theoretical Rationale: {hypothesis.theoretical_rationale}\n"
                f"Baseline Method: {hypothesis.baseline_method}"
            ),
            "Experimental Protocol": (
                f"Spec ID: {evaluation.spec_id}\n"
                f"Seeds Evaluated: {evaluation.seeds_evaluated}\n"
                f"Valid Completed Runs: {evaluation.successful_runs}/{evaluation.total_runs}"
            ),
            "Results & Statistical Evaluation": metrics_section,
            "Conclusion & Empirical Status": (
                f"Hypothesis Status: {evaluation.verdict.value}\n"
                f"Scientific Verdict: {evaluation.summary_rationale}"
            ),
        }

        # 2. Format section provenance
        provenance_list: list[SectionProvenance] = []
        for idx, (sec_title, sec_text) in enumerate(sections.items()):
            provenance_list.append(
                SectionProvenance(
                    source_paper_id=finding_id,
                    section_title=sec_title,
                    section_index=idx,
                    page_start=1,
                    page_end=1,
                    text_snippet=sec_text[:200],
                )
            )

        metadata = PaperMetadata(
            paper_id=finding_id,
            title=f"Empirical Finding: {hypothesis.title} [{evaluation.verdict.value}]",
            authors=["Research OS Execution Sandbox", "Human Gate Reviewer"],
            abstract=sections["Abstract"],
            year=datetime.now(timezone.utc).year,
            venue="Research OS Closed-Loop Empirical Archive",
            url=f"research-os://evaluations/{evaluation.evaluation_id}",
            citation_count=1,
        )

        eval_checksum = hashlib.sha256(evaluation.to_json().encode("utf-8")).hexdigest()
        extraction = PaperExtraction(
            extraction_id=extraction_id,
            paper_id=finding_id,
            metadata=metadata,
            sections=sections,
            section_provenance=provenance_list,
            equations=[],
            algorithms=[f"Algorithm entry point: {spec.entry_point if spec else 'simulation.py'}"],
            key_findings=[evaluation.summary_rationale],
            limitations=[f"Evaluated across {evaluation.total_runs} random simulation seeds."],
            source_checksum=eval_checksum,
        )

        # 3. Write to disk
        json_path = self.memory_dir / f"{finding_id}.json"
        json_path.write_text(extraction.to_json(), encoding="utf-8")

        # Also write human-readable markdown
        md_path = self.memory_dir / f"{finding_id}.md"
        md_content = (
            f"# {metadata.title}\n\n"
            f"**Evaluation ID:** `{evaluation.evaluation_id}` | **Verdict:** `{evaluation.verdict.value}`\n\n"
            f"## Abstract\n{sections['Abstract']}\n\n"
            f"## Hypothesis & Mechanism\n{sections['Hypothesis & Proposed Mechanism']}\n\n"
            f"## Results\n{sections['Results & Statistical Evaluation']}\n\n"
            f"## Conclusion\n{sections['Conclusion & Empirical Status']}\n"
        )
        md_path.write_text(md_content, encoding="utf-8")

        return extraction, json_path

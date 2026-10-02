"""Deterministic capability and attribute matrix builder across ingested literature."""

from __future__ import annotations

import re
from typing import Optional
from pydantic import Field

from research_os.schemas.base import ArtifactBaseModel
from research_os.schemas.paper import PaperExtraction


class PaperAttributes(ArtifactBaseModel):
    """Extracted dimensional attributes for an analyzed paper."""

    paper_id: str = Field(description="Unique paper ID")
    title: str = Field(description="Paper title")
    year: Optional[int] = Field(default=None, description="Publication year")
    primary_method: str = Field(description="Coordination or modeling algorithm category")
    evaluation_scale: str = Field(description="Scale of evaluation or sample size")
    operational_constraints: str = Field(description="Environmental or channel constraints")
    noise_modeled: str = Field(description="Sensor or measurement noise modeling")
    evaluation_platform: str = Field(description="Simulator or benchmark environment used")
    primary_metrics: list[str] = Field(default_factory=list, description="Primary evaluation metrics")
    baseline_methods: list[str] = Field(default_factory=list, description="Baselines compared against")


class CapabilityMatrix(ArtifactBaseModel):
    """Cross-paper comparative matrix across ingested literature."""

    matrix_id: str = Field(description="Unique capability matrix identifier")
    domain: str = Field(default="Empirical Research", description="Research domain analyzed")
    rows: list[PaperAttributes] = Field(default_factory=list, description="Extracted rows per paper")

    def to_markdown_table(self) -> str:
        """Render matrix as a GitHub-flavored Markdown comparison table."""
        headers = [
            "Paper ID",
            "Title",
            "Year",
            "Method",
            "Scale",
            "Constraints",
            "Noise",
            "Platform",
            "Primary Metric",
        ]
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for r in self.rows:
            metric_str = ", ".join(r.primary_metrics[:2]) if r.primary_metrics else "N/A"
            title_trunc = (r.title[:28] + "..") if len(r.title) > 30 else r.title
            lines.append(
                f"| `{r.paper_id}` | {title_trunc} | {r.year or 'N/A'} | {r.primary_method} | "
                f"{r.evaluation_scale} | {r.operational_constraints} | {r.noise_modeled} | "
                f"{r.evaluation_platform} | {metric_str} |"
            )
        return "\n".join(lines)


def extract_paper_attributes(paper: PaperExtraction) -> PaperAttributes:
    """Deterministically extract dimensional attributes from a PaperExtraction."""
    full_text = " ".join([paper.metadata.abstract] + list(paper.sections.values())).lower()

    # 1. Primary Method
    if paper.algorithms:
        method = paper.algorithms[0]
    elif re.search(r"consensus|laplacian|distributed averaging", full_text):
        method = "Distributed Consensus / Laplacian"
    elif re.search(r"virtual (spring|physics|force)|artificial physics", full_text):
        method = "Virtual Physics / Artificial Forces"
    elif re.search(r"potential field|gradient descent", full_text):
        method = "Potential Field Optimization"
    elif re.search(r"reinforcement learning|marl|policy gradient", full_text):
        method = "Multi-Agent Reinforcement Learning"
    elif re.search(r"retrieval-augmented|rag|context injection", full_text):
        method = "Retrieval-Augmented Generation"
    elif re.search(r"event-triggered|threshold broadcast", full_text):
        method = "Adaptive Event-Triggered Communication"
    else:
        method = "Empirical Computational Model"

    # 2. Evaluation Scale
    scale_match = re.search(
        r"(?:scale|sample\s+size|agents?|units?|n\s*=)\s*(?:of\s+)?(\d{1,4}(?:\s*(?:to|-)\s*\d{1,4})?)",
        full_text,
    )
    if scale_match:
        scale = f"N={scale_match.group(1).replace(' ', '')}"
    elif re.search(r"large-scale|hundreds", full_text):
        scale = "N=100+"
    elif re.search(r"small-scale|few agents", full_text):
        scale = "N<=10"
    else:
        scale = "N=Standard Evaluation Set"

    # 3. Operational Constraints
    if re.search(r"bandwidth limit|latency|lossy wireless|packet loss", full_text):
        constraints = "Bandwidth-Constrained / Lossy Network"
    elif re.search(r"limited range|local graph|bounded radius", full_text):
        constraints = "Locally Bounded Graph"
    elif re.search(r"context window|token limit", full_text):
        constraints = "Context-Window Constrained"
    elif re.search(r"stigmerg|indirect environmental", full_text):
        constraints = "Indirect Environmental Signaling"
    else:
        constraints = "Nominal Channel Baseline"

    # 4. Noise Modeled
    if re.search(r"gaussian bearing noise|sensor noise|measurement noise", full_text):
        noise = "Gaussian Measurement Noise"
    elif re.search(r"hallucination|adversarial|distractor", full_text):
        noise = "Adversarial Noise / Distractors"
    else:
        noise = "Ideal Sensing (Zero Noise)"

    # 5. Evaluation Platform
    if re.search(r"\bargos\b", full_text):
        platform = "ARGoS Simulator"
    elif re.search(r"\bstage\b", full_text):
        platform = "Stage Simulator"
    elif re.search(r"\bwebots\b", full_text):
        platform = "Webots Environment"
    elif re.search(r"\bbenchmark\b", full_text):
        platform = "Standardized Benchmark"
    else:
        platform = "Custom Python Testbed"

    # 6. Primary Metrics
    metrics: list[str] = []
    if re.search(r"overhead|bandwidth|bytes transferred|packets sent", full_text):
        metrics.append("comm_overhead_bytes_per_sec")
    if re.search(r"convergence time|execution latency", full_text):
        metrics.append("convergence_time_seconds")
    if re.search(r"hallucination|exact match|accuracy|recall", full_text):
        metrics.append("accuracy_metric")
    if not metrics:
        metrics = ["task_completion_rate", "runtime_overhead"]

    # 7. Baselines
    baselines: list[str] = []
    if "boids" in full_text or "vicsek" in full_text:
        baselines.append("Classical Local Interaction Baseline")
    elif "direct generation" in full_text:
        baselines.append("Zero-Shot Direct Generation Baseline")
    else:
        baselines.append("Standard Static Baseline")

    return PaperAttributes(
        paper_id=paper.paper_id,
        title=paper.metadata.title,
        year=paper.metadata.year,
        primary_method=method,
        evaluation_scale=scale,
        operational_constraints=constraints,
        noise_modeled=noise,
        evaluation_platform=platform,
        primary_metrics=metrics,
        baseline_methods=baselines,
    )


def build_capability_matrix(
    papers: list[PaperExtraction],
    domain: str = "Empirical Research",
) -> CapabilityMatrix:
    """Build a deterministic comparison matrix across all ingested papers."""
    rows = [extract_paper_attributes(p) for p in papers]
    rows.sort(key=lambda r: r.paper_id)
    return CapabilityMatrix(
        matrix_id="matrix-empirical-01",
        domain=domain,
        rows=rows,
    )

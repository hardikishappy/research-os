"""Metric calculation and provenance derivations for NLP benchmarks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_os.domains.base import MetricProvenanceItem


def compute_nlp_metrics_from_raw(
    raw_data_dir: Path,
) -> tuple[dict[str, Any], list[MetricProvenanceItem]]:
    """Compute verified NLP metrics from raw predictions.jsonl log."""
    pred_path = raw_data_dir / "predictions.jsonl"
    if not pred_path.exists():
        raise FileNotFoundError(f"Missing raw predictions log: {pred_path}")

    total_items = 0
    rag_hallucinations = 0
    baseline_hallucinations = 0
    shuffled_hallucinations = 0
    total_token_overlap = 0.0
    total_latency_ms = 0.0

    with pred_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            total_items += 1
            if item.get("rag_hallucinated", False):
                rag_hallucinations += 1
            if item.get("baseline_hallucinated", False):
                baseline_hallucinations += 1
            if item.get("shuffled_hallucinated", False):
                shuffled_hallucinations += 1
            total_token_overlap += float(item.get("token_overlap", 0.0))
            total_latency_ms += float(item.get("latency_ms", 0.0))

    if total_items == 0:
        raise ValueError("Raw predictions log is empty")

    hallucination_rate = rag_hallucinations / total_items
    baseline_hallucination_rate = baseline_hallucinations / total_items
    shuffled_hallucination_rate = shuffled_hallucinations / total_items
    avg_token_overlap = total_token_overlap / total_items
    avg_latency_ms = total_latency_ms / total_items

    reduction_pct = (
        ((baseline_hallucination_rate - hallucination_rate) / baseline_hallucination_rate) * 100.0
        if baseline_hallucination_rate > 0
        else 0.0
    )

    metrics = {
        "hallucination_rate": round(hallucination_rate, 4),
        "baseline_hallucination_rate": round(baseline_hallucination_rate, 4),
        "shuffled_hallucination_rate": round(shuffled_hallucination_rate, 4),
        "hallucination_reduction_pct": round(reduction_pct, 2),
        "token_overlap_score": round(avg_token_overlap, 4),
        "latency_ms": round(avg_latency_ms, 2),
        "total_evaluated_queries": total_items,
        "status": "COMPLETED",
    }

    provenance_records = [
        MetricProvenanceItem(
            metric_name="hallucination_rate",
            raw_source_file="raw_data/predictions.jsonl",
            derivation_procedure="count(rag_hallucinated == True) / total_evaluated_queries",
            computed_value=round(hallucination_rate, 4),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="baseline_hallucination_rate",
            raw_source_file="raw_data/predictions.jsonl",
            derivation_procedure="count(baseline_hallucinated == True) / total_evaluated_queries",
            computed_value=round(baseline_hallucination_rate, 4),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="shuffled_hallucination_rate",
            raw_source_file="raw_data/predictions.jsonl",
            derivation_procedure="count(shuffled_hallucinated == True) / total_evaluated_queries",
            computed_value=round(shuffled_hallucination_rate, 4),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="hallucination_reduction_pct",
            raw_source_file="raw_data/predictions.jsonl",
            derivation_procedure="((baseline_rate - rag_rate) / baseline_rate) * 100",
            computed_value=round(reduction_pct, 2),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="token_overlap_score",
            raw_source_file="raw_data/predictions.jsonl",
            derivation_procedure="mean(token_overlap against reference gold answer)",
            computed_value=round(avg_token_overlap, 4),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="latency_ms",
            raw_source_file="raw_data/predictions.jsonl",
            derivation_procedure="mean(query execution latency in milliseconds)",
            computed_value=round(avg_latency_ms, 2),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="total_evaluated_queries",
            raw_source_file="raw_data/predictions.jsonl",
            derivation_procedure="count(queries evaluated in benchmark)",
            computed_value=float(total_items),
            verified=True,
        ),
    ]

    return metrics, provenance_records

"""Metric calculation and provenance derivations for Telepresence simulations."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from research_os.domains.base import MetricProvenanceItem


def compute_telepresence_metrics_from_raw(
    raw_data_dir: Path,
) -> tuple[dict[str, Any], list[MetricProvenanceItem]]:
    """Compute verified telepresence metrics from raw network_jitter.csv."""
    jitter_path = raw_data_dir / "network_jitter.csv"
    if not jitter_path.exists():
        raise FileNotFoundError(f"Missing raw network jitter data: {jitter_path}")

    total_samples = 0
    sq_err_predicted = 0.0
    sq_err_baseline = 0.0
    total_latency_ms = 0.0
    latencies = []
    dropped_packets = 0

    with jitter_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_samples += 1
            sx = float(row.get("sent_x", 0.0))
            sy = float(row.get("sent_y", 0.0))
            rx = float(row.get("received_x", 0.0))
            ry = float(row.get("received_y", 0.0))
            px = float(row.get("predicted_x", 0.0))
            py = float(row.get("predicted_y", 0.0))
            lat = float(row.get("latency_ms", 0.0))
            dropped = int(float(row.get("dropped", 0)))

            if dropped == 1:
                dropped_packets += 1

            sq_err_predicted += (sx - px) ** 2 + (sy - py) ** 2
            sq_err_baseline += (sx - rx) ** 2 + (sy - ry) ** 2
            total_latency_ms += lat
            latencies.append(lat)

    if total_samples == 0:
        raise ValueError("network_jitter.csv is empty")

    rmse_predicted = math.sqrt(sq_err_predicted / total_samples)
    rmse_baseline = math.sqrt(sq_err_baseline / total_samples)
    reduction_pct = (
        ((rmse_baseline - rmse_predicted) / rmse_baseline) * 100.0 if rmse_baseline > 0 else 0.0
    )
    mean_latency = total_latency_ms / total_samples
    packet_drop_rate = dropped_packets / total_samples

    mean_lat_sq_diff = sum((x - mean_latency) ** 2 for x in latencies) / total_samples
    jitter_std = math.sqrt(mean_lat_sq_diff)

    metrics = {
        "tracking_rmse": round(rmse_predicted, 4),
        "baseline_tracking_rmse": round(rmse_baseline, 4),
        "tracking_error_reduction_pct": round(reduction_pct, 2),
        "packet_drop_rate": round(packet_drop_rate, 4),
        "mean_latency_ms": round(mean_latency, 2),
        "jitter_std_ms": round(jitter_std, 2),
        "total_packets_evaluated": total_samples,
        "status": "COMPLETED",
    }

    provenance_records = [
        MetricProvenanceItem(
            metric_name="tracking_rmse",
            raw_source_file="raw_data/network_jitter.csv",
            derivation_procedure="sqrt(mean((sent_pos - predicted_pos)^2))",
            computed_value=round(rmse_predicted, 4),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="baseline_tracking_rmse",
            raw_source_file="raw_data/network_jitter.csv",
            derivation_procedure="sqrt(mean((sent_pos - delayed_received_pos)^2))",
            computed_value=round(rmse_baseline, 4),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="tracking_error_reduction_pct",
            raw_source_file="raw_data/network_jitter.csv",
            derivation_procedure="((baseline_rmse - predicted_rmse) / baseline_rmse) * 100",
            computed_value=round(reduction_pct, 2),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="packet_drop_rate",
            raw_source_file="raw_data/network_jitter.csv",
            derivation_procedure="sum(dropped) / total_packets",
            computed_value=round(packet_drop_rate, 4),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="mean_latency_ms",
            raw_source_file="raw_data/network_jitter.csv",
            derivation_procedure="mean(latency_ms)",
            computed_value=round(mean_latency, 2),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="jitter_std_ms",
            raw_source_file="raw_data/network_jitter.csv",
            derivation_procedure="std(latency_ms)",
            computed_value=round(jitter_std, 2),
            verified=True,
        ),
        MetricProvenanceItem(
            metric_name="total_packets_evaluated",
            raw_source_file="raw_data/network_jitter.csv",
            derivation_procedure="count(packet_events)",
            computed_value=float(total_samples),
            verified=True,
        ),
    ]

    return metrics, provenance_records

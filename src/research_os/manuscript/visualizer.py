"""Publication-Grade Scientific Visualization Engine for Research OS (matplotlib & seaborn).

Generates:
- High-resolution (300 DPI) raster (.png) and publication vector graphics (.pdf).
- Empirical time-series and multi-seed convergence curves with shaded error envelopes (+-1 SD / 95% CI).
- Strict scientific formatting: physical units, monochrome-safe colorblind palettes, LaTeX typography integration.
- BANS synthetic trajectories and fabricated intermediate points: only verified raw log rows are visualized.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Optional, Union
import numpy as np

import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt


class MissingTraceError(ValueError):
    """Raised when real empirical trajectory time-series log rows are missing or synthetic data is attempted."""
    pass


class PublicationVisualizer:
    """Generates publication-ready figures for scientific manuscripts."""

    # Colorblind-friendly, monochrome-safe palette (Tol / Okabe-Ito inspired)
    PALETTE = {
        "primary": "#1f77b4",       # Slate blue
        "secondary": "#ff7f0e",     # Safety amber/orange
        "accent": "#2ca02c",        # Telemetry green
        "contrast": "#d62728",      # Crimson boundary
        "neutral_dark": "#161b22",  # Dark slate
        "neutral_light": "#f0f6fc", # Paper white
        "grid": "#d0d7de",          # Light gridline
    }

    def __init__(self, run_id: str, output_dir: Optional[Path | str] = None) -> None:
        self.run_id = run_id
        if output_dir:
            self.figures_dir = Path(output_dir)
        else:
            self.figures_dir = Path("experiments/runs") / run_id / "manuscript" / "figures"
        self.figures_dir.mkdir(parents=True, exist_ok=True)
        self._setup_style()

    def _setup_style(self) -> None:
        """Configure matplotlib rcParams for IEEEtran / Nature journal formatting."""
        try:
            plt.style.use("seaborn-v0_8-paper")
        except Exception:
            pass

        matplotlib.rcParams.update({
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Helvetica", "Arial"],
            "font.size": 9.0,
            "axes.labelsize": 9.5,
            "axes.titlesize": 10.0,
            "xtick.labelsize": 8.0,
            "ytick.labelsize": 8.0,
            "legend.fontsize": 8.5,
            "figure.titlesize": 11.0,
            "lines.linewidth": 1.5,
            "lines.markersize": 4.0,
            "grid.alpha": 0.4,
            "grid.linestyle": ":",
            "axes.grid": True,
            "figure.dpi": 300,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        })

    def plot_time_series_with_envelope(
        self,
        traces_by_seed: dict[int, list[float]],
        x_label: str = "Execution Steps (t)",
        y_label: str = "Target Metric Value",
        title: str = "Multi-Seed Empirical Convergence Under Parameter Regime",
        filename_prefix: str = "empirical_convergence",
        time_points: Optional[list[float]] = None,
        confidence_band: str = "std",
    ) -> tuple[Path, Path]:
        """Generate time-series curve with shaded +-1 SD error envelope across seeds.

        Invariant: Multi-step time-series figures strictly require authentic raw trace
        observations with >= 2 steps per seed. Synthesizing or interpolating intermediate points is forbidden.
        """
        if not traces_by_seed:
            raise MissingTraceError(
                "No seed traces provided for visualization. Multi-step trajectory figures strictly require real raw time-series logs."
            )

        lengths = [len(v) for v in traces_by_seed.values()]
        min_len = min(lengths) if lengths else 0
        if min_len < 2:
            raise MissingTraceError(
                f"Seed trace contains only {min_len} step(s). Multi-step trajectory figures strictly require real raw "
                "time-series log rows with >= 2 steps per seed. Synthetic trajectory generation is forbidden."
            )

        matrix = np.array([v[:min_len] for v in traces_by_seed.values()], dtype=float)
        mean_curve = np.mean(matrix, axis=0)
        std_curve = np.std(matrix, axis=0, ddof=1) if len(traces_by_seed) > 1 else np.zeros_like(mean_curve)

        x_vals = np.array(time_points[:min_len]) if time_points else np.arange(1, min_len + 1)

        fig, ax = plt.subplots(figsize=(4.8, 3.2), dpi=300)

        # Plot individual seed trajectories faintly
        for seed_idx, (seed_val, trace) in enumerate(traces_by_seed.items()):
            ax.plot(
                x_vals,
                trace[:min_len],
                color=self.PALETTE["primary"],
                alpha=0.25,
                linewidth=0.8,
                label=f"Seed {seed_val}" if seed_idx == 0 else "_nolegend_",
            )

        # Plot ensemble mean
        ax.plot(
            x_vals,
            mean_curve,
            color=self.PALETTE["primary"],
            linewidth=2.0,
            label="Ensemble Mean ($M$)",
            zorder=4,
        )

        # Plot shaded error envelope
        if confidence_band == "ci95" and len(traces_by_seed) > 1:
            n = len(traces_by_seed)
            margin = 1.96 * (std_curve / np.sqrt(n))
            lower = mean_curve - margin
            upper = mean_curve + margin
            band_label = "95% Confidence Interval"
        else:
            lower = mean_curve - std_curve
            upper = mean_curve + std_curve
            band_label = r"Empirical Dispersion ($\pm 1\sigma$)"

        ax.fill_between(
            x_vals,
            lower,
            upper,
            color=self.PALETTE["primary"],
            alpha=0.18,
            label=band_label,
            zorder=3,
        )

        ax.set_xlabel(x_label, fontweight="medium")
        ax.set_ylabel(y_label, fontweight="medium")
        ax.set_title(title, fontweight="bold", pad=8)
        ax.legend(frameon=True, framealpha=0.9, loc="best", facecolor="white")
        ax.grid(True, linestyle=":", alpha=0.5)

        pdf_path = self.figures_dir / f"{filename_prefix}.pdf"
        png_path = self.figures_dir / f"{filename_prefix}.png"

        fig.tight_layout()
        fig.savefig(pdf_path, format="pdf")
        fig.savefig(png_path, format="png", dpi=300)
        plt.close(fig)

        return pdf_path, png_path

    def plot_time_series_from_raw_logs(
        self,
        raw_log_files_by_seed: dict[int, Path | str],
        metric_column: str,
        step_column: str = "step",
        x_label: str = "Execution Steps (t)",
        y_label: Optional[str] = None,
        title: str = "Empirical Trajectory Convergence",
        filename_prefix: str = "empirical_convergence",
    ) -> tuple[Path, Path]:
        """Generate time-series curve strictly linked to verified raw log rows."""
        traces: dict[int, list[float]] = {}
        for seed, log_path in raw_log_files_by_seed.items():
            p = Path(log_path)
            if not p.is_file():
                raise MissingTraceError(f"Raw step log file does not exist: {p}")

            rows: list[float] = []
            suffix = p.suffix.lower()
            if suffix == ".csv":
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        if metric_column in r:
                            try:
                                rows.append(float(r[metric_column]))
                            except (ValueError, TypeError):
                                pass
            elif suffix in (".jsonl", ".ndjson"):
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.strip():
                            obj = json.loads(line)
                            if metric_column in obj:
                                try:
                                    rows.append(float(obj[metric_column]))
                                except (ValueError, TypeError):
                                    pass

            if len(rows) < 2:
                raise MissingTraceError(
                    f"Raw log {p} for seed {seed} contains only {len(rows)} step(s) for metric '{metric_column}'. "
                    "At least 2 authentic step observations are required."
                )
            traces[seed] = rows

        return self.plot_time_series_with_envelope(
            traces_by_seed=traces,
            x_label=x_label,
            y_label=y_label or metric_column,
            title=title,
            filename_prefix=filename_prefix,
        )

    def plot_scalar_bar_chart(
        self,
        scalar_values_by_seed: dict[int, float],
        metric_name: str,
        target_threshold: Optional[float] = None,
        unit: str = "",
        title: str = "Verified Scalar Metric Across Evaluation Seeds",
        filename_prefix: str = "metric_scalar_summary",
    ) -> tuple[Path, Path]:
        """Generate publication-ready bar chart representing verified scalar metrics across seeds."""
        fig, ax = plt.subplots(figsize=(4.8, 3.2), dpi=300)
        seeds = [f"Seed {s}" for s in scalar_values_by_seed.keys()]
        values = list(scalar_values_by_seed.values())

        bars = ax.bar(seeds, values, color=self.PALETTE["primary"], alpha=0.8, width=0.45, edgecolor=self.PALETTE["neutral_dark"])
        ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=8)

        if len(values) > 1:
            mean_val = float(np.mean(values))
            std_dev = float(np.std(values, ddof=1))
            std_err = float(std_dev / np.sqrt(len(values)))
            ax.axhline(mean_val, color=self.PALETTE["contrast"], linestyle="--", linewidth=1.5, label=f"Mean: {mean_val:.4f} $\\pm$ {std_err:.4f}")
            ax.axhspan(mean_val - std_err, mean_val + std_err, color=self.PALETTE["contrast"], alpha=0.15, label=r"Ensemble Mean $\pm$ 1 SE")

        if target_threshold is not None:
            ax.axhline(target_threshold, color="#8b0000", linestyle=":", linewidth=1.5, label=f"Target ({target_threshold})")

        ax.legend(frameon=True, facecolor="white", fontsize=8, loc="upper right")

        max_val = max(values) if values else 1.0
        if target_threshold is not None:
            max_val = max(max_val, target_threshold)
        ax.set_ylim(0, max_val * 1.35 if max_val > 0 else 1.0)

        y_label_str = f"{metric_name} ({unit})" if unit else metric_name
        ax.set_ylabel(y_label_str, fontweight="medium")
        ax.set_title(title, fontweight="bold", pad=8)
        ax.grid(True, linestyle=":", alpha=0.5, axis="y")

        pdf_path = self.figures_dir / f"{filename_prefix}.pdf"
        png_path = self.figures_dir / f"{filename_prefix}.png"

        fig.tight_layout()
        fig.savefig(pdf_path, format="pdf")
        fig.savefig(png_path, format="png", dpi=300)
        plt.close(fig)

        return pdf_path, png_path

    def plot_metric_distributions(
        self,
        metric_values_by_condition: dict[str, list[float]],
        metric_name: str,
        unit: str = "",
        title: str = "Empirical Metric Distribution by Condition",
        filename_prefix: str = "metric_distributions",
    ) -> tuple[Path, Path]:
        """Generate publication-ready box/violin summary across conditions."""
        fig, ax = plt.subplots(figsize=(4.5, 3.2), dpi=300)

        labels = list(metric_values_by_condition.keys())
        data = [metric_values_by_condition[k] for k in labels]

        ax.boxplot(
            data,
            patch_artist=True,
            tick_labels=labels,
            medianprops=dict(color=self.PALETTE["contrast"], linewidth=1.8),
            boxprops=dict(facecolor=self.PALETTE["primary"], alpha=0.3, color=self.PALETTE["primary"]),
            whiskerprops=dict(color="#30363d", linewidth=1.2),
            capprops=dict(color="#30363d", linewidth=1.2),
            flierprops=dict(marker="o", markerfacecolor=self.PALETTE["secondary"], alpha=0.6, markersize=3.5),
        )

        y_label_str = f"{metric_name} ({unit})" if unit else metric_name
        ax.set_ylabel(y_label_str, fontweight="medium")
        ax.set_title(title, fontweight="bold", pad=8)
        ax.grid(True, linestyle=":", alpha=0.5, axis="y")

        pdf_path = self.figures_dir / f"{filename_prefix}.pdf"
        png_path = self.figures_dir / f"{filename_prefix}.png"

        fig.tight_layout()
        fig.savefig(pdf_path, format="pdf")
        fig.savefig(png_path, format="png", dpi=300)
        plt.close(fig)

        return pdf_path, png_path

    def plot_ablation_grid(
        self,
        grid_report: Union[dict, Any],
        metric_name: Optional[str] = None,
        title: Optional[str] = None,
        filename_prefix: str = "parametric_ablation_grid",
    ) -> tuple[Path, Path]:
        """Generate publication-ready ablation heatmap or response curves for multi-variable sweeps."""
        if hasattr(grid_report, "model_dump"):
            data = grid_report.model_dump()
        elif hasattr(grid_report, "dict"):
            data = grid_report.dict()
        else:
            data = dict(grid_report)

        knobs = data.get("knobs", {})
        combinations = data.get("combinations", [])
        m_name = metric_name or data.get("target_metric", "Metric")
        t_str = title or f"Parametric Ablation Grid: {m_name}"

        pdf_path = self.figures_dir / f"{filename_prefix}.pdf"
        png_path = self.figures_dir / f"{filename_prefix}.png"

        knob_keys = list(knobs.keys())
        if len(knob_keys) >= 2:
            # 2D Heatmap: Knob 0 vs Knob 1
            k0 = knob_keys[0]
            k1 = knob_keys[1]
            k0_vals = knobs[k0]
            k1_vals = knobs[k1]

            matrix = np.full((len(k0_vals), len(k1_vals)), np.nan)
            for c in combinations:
                p = c.get("parameters", {})
                v0 = p.get(k0)
                v1 = p.get(k1)
                if v0 in k0_vals and v1 in k1_vals:
                    r = k0_vals.index(v0)
                    col = k1_vals.index(v1)
                    val = c.get("mean_target_metric")
                    if val is not None:
                        matrix[r, col] = float(val)

            fig, ax = plt.subplots(figsize=(5.2, 3.8), dpi=300)
            cax = ax.imshow(matrix, cmap="viridis", aspect="auto", origin="lower")
            cbar = fig.colorbar(cax, ax=ax)
            cbar.set_label(f"Mean {m_name}", fontsize=8)

            ax.set_xticks(range(len(k1_vals)))
            ax.set_xticklabels([str(v) for v in k1_vals], fontsize=8)
            ax.set_yticks(range(len(k0_vals)))
            ax.set_yticklabels([str(v) for v in k0_vals], fontsize=8)

            ax.set_xlabel(f"Parameter: {k1}", fontweight="medium", fontsize=9)
            ax.set_ylabel(f"Parameter: {k0}", fontweight="medium", fontsize=9)
            ax.set_title(t_str, fontweight="bold", pad=8, fontsize=10)

            # Add numeric text inside cells
            mean_mat = np.nanmean(matrix) if not np.isnan(np.nanmean(matrix)) else 0.0
            for r in range(len(k0_vals)):
                for col in range(len(k1_vals)):
                    val = matrix[r, col]
                    if not np.isnan(val):
                        text_color = "white" if val < mean_mat else "black"
                        ax.text(col, r, f"{val:.3f}", ha="center", va="center", color=text_color, fontsize=8, fontweight="bold")

            fig.tight_layout()
            fig.savefig(pdf_path, format="pdf")
            fig.savefig(png_path, format="png", dpi=300)
            plt.close(fig)
            return pdf_path, png_path
        else:
            # 1D Response Curve
            k0 = knob_keys[0] if knob_keys else "Parameter"
            x_vals = []
            y_vals = []
            y_errs = []
            for c in combinations:
                p = c.get("parameters", {})
                if k0 in p:
                    x_vals.append(p[k0])
                    y_vals.append(float(c.get("mean_target_metric", 0.0)))
                    y_errs.append(float(c.get("std_err_target_metric", 0.0)))

            fig, ax = plt.subplots(figsize=(4.8, 3.4), dpi=300)
            try:
                sorted_indices = sorted(range(len(x_vals)), key=lambda i: float(x_vals[i]))
                x_plot = [x_vals[i] for i in sorted_indices]
                y_plot = [y_vals[i] for i in sorted_indices]
                err_plot = [y_errs[i] for i in sorted_indices]
            except (ValueError, TypeError):
                x_plot, y_plot, err_plot = x_vals, y_vals, y_errs

            ax.errorbar(
                range(len(x_plot)),
                y_plot,
                yerr=err_plot,
                fmt="o-",
                color=self.PALETTE["primary"],
                ecolor=self.PALETTE["contrast"],
                capsize=4,
                capthick=1.2,
                linewidth=1.8,
                markersize=6,
                label=f"Mean {m_name} $\\pm$ 1 SE",
            )
            ax.set_xticks(range(len(x_plot)))
            ax.set_xticklabels([str(x) for x in x_plot])
            ax.set_xlabel(f"Ablation Knob: {k0}", fontweight="medium")
            ax.set_ylabel(f"Observed {m_name}", fontweight="medium")
            ax.set_title(t_str, fontweight="bold", pad=8)
            ax.grid(True, linestyle=":", alpha=0.5)
            ax.legend(frameon=True, fontsize=8)

            fig.tight_layout()
            fig.savefig(pdf_path, format="pdf")
            fig.savefig(png_path, format="png", dpi=300)
            plt.close(fig)
            return pdf_path, png_path


def plot_time_series_with_envelope(
    traces_by_seed: dict[Any, list[float]],
    output_path: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    x_label: str = "Execution Steps (t)",
    y_label: str = "Target Metric Value",
    title: str = "Multi-Seed Empirical Convergence Under Parameter Regime",
    filename_prefix: str = "empirical_convergence",
) -> tuple[Path, Path]:
    """Module-level function for plot_time_series_with_envelope."""
    out_dir = Path(output_dir or (Path(output_path).parent if output_path else "."))
    prefix = Path(output_path).stem if output_path else filename_prefix
    viz = PublicationVisualizer(run_id="default_run", output_dir=out_dir)
    return viz.plot_time_series_with_envelope(
        traces_by_seed=traces_by_seed,
        x_label=x_label,
        y_label=y_label,
        title=title,
        filename_prefix=prefix,
    )


def plot_time_series_from_raw_logs(
    raw_data: Union[dict[int, Path | str], Path, str],
    metric_column: str = "val",
    output_path: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    x_label: str = "Execution Steps (t)",
    y_label: Optional[str] = None,
    title: str = "Multi-Seed Empirical Convergence From Raw Logs",
    filename_prefix: str = "empirical_convergence_raw",
) -> tuple[Path, Path]:
    """Module-level function for plot_time_series_from_raw_logs."""
    out_dir = Path(output_dir or (Path(output_path).parent if output_path else "."))
    prefix = Path(output_path).stem if output_path else filename_prefix
    viz = PublicationVisualizer(run_id="default_run", output_dir=out_dir)

    if isinstance(raw_data, (str, Path)):
        p = Path(raw_data)
        if not p.exists():
            raise MissingTraceError(f"Raw data path does not exist: {p}")
        if p.is_dir():
            files = sorted(list(p.glob("*.csv")) + list(p.glob("*.jsonl")))
            if not files:
                raise MissingTraceError(
                    f"No multi-step time-series traces found in {p}. "
                    "Synthetic interpolation is strictly forbidden."
                )
            raw_log_files_by_seed = {i: f for i, f in enumerate(files)}
        else:
            raw_log_files_by_seed = {0: p}
    else:
        raw_log_files_by_seed = raw_data

    return viz.plot_time_series_from_raw_logs(
        raw_log_files_by_seed=raw_log_files_by_seed,
        metric_column=metric_column,
        x_label=x_label,
        y_label=y_label,
        title=title,
        filename_prefix=prefix,
    )


def plot_scalar_bar_chart(
    scalar_values_by_seed: dict[int, float],
    metric_name: str,
    output_path: Optional[Path | str] = None,
    output_dir: Optional[Path | str] = None,
    target_threshold: Optional[float] = None,
    unit: str = "",
    title: str = "Verified Scalar Metric Across Evaluation Seeds",
    filename_prefix: str = "metric_scalar_summary",
) -> tuple[Path, Path]:
    """Module-level function for plot_scalar_bar_chart."""
    out_dir = Path(output_dir or (Path(output_path).parent if output_path else "."))
    prefix = Path(output_path).stem if output_path else filename_prefix
    viz = PublicationVisualizer(run_id="default_run", output_dir=out_dir)
    return viz.plot_scalar_bar_chart(
        scalar_values_by_seed=scalar_values_by_seed,
        metric_name=metric_name,
        target_threshold=target_threshold,
        unit=unit,
        title=title,
        filename_prefix=prefix,
    )

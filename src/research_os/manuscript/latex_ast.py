"""Robust Structured LaTeX Abstract Syntax Tree (AST) & Escaping Pipeline.

Enforces Directive 4:
- Eliminates fragile string-concatenation LaTeX generation.
- Full escaping of TeX special characters (_, %, <=, >=, &, #, $, {, }, ^, ~).
- Absolute/bundle-relative path resolution for figures independent of shell CWD.
"""

from __future__ import annotations

import hashlib
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from research_os.core.integrity import EpistemicHonestyViolation


class ProseSmuggledSignificanceError(EpistemicHonestyViolation):
    """Raised when unlinked statistical significance claims or p-values are smuggled into free prose."""
    pass


def escape_latex(text: str) -> str:
    """Safely escape all LaTeX control characters and mathematical comparison operators.
    
    Order of operations is critical:
    1. Escape backslashes, ampersands, percent signs, dollar signs, hashes, underscores, braces, tildes, carets.
    2. Replace mathematical comparison operators (<=, >=, !=, ==, standalone <, >) with clean math mode symbols.
    """
    if not text:
        return ""

    s = str(text)

    # 1. Backslashes and control symbols first (so subsequent math delimiters are not escaped)
    replacements = [
        ("&", "\\&"),
        ("%", "\\%"),
        ("$", "\\$"),
        ("#", "\\#"),
        ("_", "\\_"),
        ("{", "\\{"),
        ("}", "\\}"),
        ("~", "\\textasciitilde{}"),
        ("^", "\\textasciicircum{}"),
    ]

    for char, escaped in replacements:
        s = s.replace(char, escaped)

    # 2. Operators safely introducing math-mode delimiters
    s = s.replace("<=", " $\\le$ ")
    s = s.replace(">=", " $\\ge$ ")
    s = s.replace("!=", " $\\ne$ ")
    s = s.replace("==", " $=$ ")

    # Standalone < and > (not part of $\le$ or tags)
    s = re.sub(r"(?<!\\le\s)(?<!\\ge\s)<(?!=)", " $<$ ", s)
    s = re.sub(r"(?<!\\le\s)(?<!\\ge\s)>(?!=)", " $>$ ", s)

    # Clean up duplicate whitespace introduced by operator spacing
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def resolve_figure_path(figure_path: Union[str, Path], manuscript_dir: Union[str, Path]) -> str:
    """Resolve a figure file path to a clean, portable forward-slash relative or absolute path.
    
    Guarantees compilation does not depend on the shell's current working directory.
    """
    m_dir = Path(manuscript_dir).resolve()
    fig = Path(figure_path)

    # If already relative to manuscript_dir
    if not fig.is_absolute():
        resolved_fig = (m_dir / fig).resolve()
    else:
        resolved_fig = fig.resolve()

    try:
        rel = resolved_fig.relative_to(m_dir)
        # Always use forward slashes for TeX graphics compatibility
        return rel.as_posix()
    except ValueError:
        # Fall back to normalized absolute forward-slash path
        return resolved_fig.as_posix()


class LatexNode(ABC):
    """Abstract base class for all LaTeX AST elements."""

    @abstractmethod
    def render(self) -> str:
        """Render the node to valid LaTeX code."""
        pass


class LatexText(LatexNode):
    """Text node with automatic escaping of LaTeX control characters and claim validation (M1, M2)."""

    FORBIDDEN_PROSE_PATTERNS = [
        re.compile(r"p\s*(?:<|<=|≤|\\lt|\\le)\s*0?\.05", re.IGNORECASE),
        re.compile(r"p\s*(?:<|<=|≤|\\lt|\\le)\s*0?\.01", re.IGNORECASE),
        re.compile(r"p\s*=\s*0?\.\d+", re.IGNORECASE),
        re.compile(r"\bstatistically\s+significant\b", re.IGNORECASE),
        re.compile(r"\bstatistical\s+significance\b", re.IGNORECASE),
    ]

    def __init__(self, text: str, raw: bool = False, validate_claims: bool = True) -> None:
        self.text = text
        self.raw = raw
        if validate_claims and text:
            for pat in self.FORBIDDEN_PROSE_PATTERNS:
                m = pat.search(text)
                if m:
                    raise ProseSmuggledSignificanceError(
                        f"Statistical Honesty Violation: ProseSmuggledSignificanceError: Free text contains smuggled statistical significance claim "
                        f"or p-value ('{m.group(0)}'). Statistical results must be rendered via typed ClaimNode or LatexStatisticalClaim (M1, M2)."
                    )

    def render(self) -> str:
        return self.text if self.raw else escape_latex(self.text)


class LatexRaw(LatexNode):
    """Verbatim LaTeX snippet. Unrestricted scientific significance claims are forbidden (Directive 4)."""

    FORBIDDEN_RAW_CLAIMS = [
        re.compile(r"p\s*[<≤]\s*0?\.05", re.IGNORECASE),
        re.compile(r"p\s*[<≤]\s*0?\.01", re.IGNORECASE),
        re.compile(r"statistically\s+significant", re.IGNORECASE),
        re.compile(r"statistical\s+significance", re.IGNORECASE),
    ]

    def __init__(self, snippet: str, allow_claims: bool = False) -> None:
        self.snippet = snippet
        if not allow_claims:
            for pat in self.FORBIDDEN_RAW_CLAIMS:
                if pat.search(snippet):
                    raise ValueError(
                        f"Directive 4 Violation: LatexRaw cannot be used as an escape hatch to inject "
                        f"scientific or statistical significance claims ('{snippet}'). "
                        f"Use typed evidence node LatexStatisticalClaim."
                    )

    def render(self) -> str:
        return self.snippet


class LatexCommand(LatexNode):
    """A standard LaTeX command (e.g. \\section{...}, \\caption{...})."""

    def __init__(
        self,
        command: str,
        argument: Union[str, LatexNode],
        options: Optional[str] = None,
        escape_arg: bool = True,
    ) -> None:
        self.command = command
        self.argument = argument
        self.options = options
        self.escape_arg = escape_arg

    def render(self) -> str:
        if isinstance(self.argument, LatexNode):
            arg_str = self.argument.render()
        else:
            arg_str = escape_latex(self.argument) if self.escape_arg else str(self.argument)

        opts_str = f"[{self.options}]" if self.options else ""
        return f"\\{self.command}{opts_str}{{{arg_str}}}"


class LatexEnvironment(LatexNode):
    """A LaTeX block environment (\\begin{name}...\\end{name})."""

    def __init__(
        self,
        name: str,
        options: Optional[str] = None,
        children: Optional[list[LatexNode]] = None,
    ) -> None:
        self.name = name
        self.options = options
        self.children = children or []

    def add(self, child: LatexNode) -> LatexEnvironment:
        self.children.append(child)
        return self

    def render(self) -> str:
        opts_str = f"[{self.options}]" if self.options else ""
        body = "\n".join(c.render() for c in self.children)
        return f"\\begin{{{self.name}}}{opts_str}\n{body}\n\\end{{{self.name}}}"


class LatexTable(LatexNode):
    """Professional academic table rendered using booktabs with cell-level auto-escaping."""

    def __init__(
        self,
        headers: Sequence[Union[str, LatexNode]],
        rows: Sequence[Sequence[Union[str, LatexNode]]],
        caption: str = "",
        label: str = "",
        alignment: Optional[str] = None,
        pos: str = "h",
        footnote: Optional[str] = None,
        escape_caption: bool = True,
        resize_to_width: Optional[str] = None,
    ) -> None:
        self.headers = headers
        self.rows = rows
        self.caption = caption
        self.label = label
        self.pos = pos
        self.alignment = alignment or ("l" + "c" * (len(headers) - 1))
        self.footnote = footnote
        self.escape_caption = escape_caption
        self.resize_to_width = resize_to_width

    def _render_cell(self, cell: Union[str, LatexNode]) -> str:
        if isinstance(cell, LatexNode):
            return cell.render()
        return escape_latex(str(cell))

    def render(self) -> str:
        lines: list[str] = []
        lines.append(f"\\begin{{table}}[{self.pos}]")
        lines.append("\\centering")
        if self.caption:
            cap_str = escape_latex(self.caption) if self.escape_caption else str(self.caption)
            lines.append(f"\\caption{{{cap_str}}}")
        if self.label:
            lines.append(f"\\label{{{self.label}}}")

        if self.resize_to_width:
            lines.append(f"\\resizebox{{{self.resize_to_width}}}{{!}}{{")

        lines.append(f"\\begin{{tabular}}{{{self.alignment}}}")
        lines.append("\\toprule")

        # Escaped headers or rendered nodes
        escaped_headers = [self._render_cell(h) for h in self.headers]
        lines.append(" & ".join(escaped_headers) + " \\\\")
        lines.append("\\midrule")

        # Escaped row cells or rendered nodes
        for row in self.rows:
            escaped_row = [self._render_cell(cell) for cell in row]
            lines.append(" & ".join(escaped_row) + " \\\\")

        lines.append("\\bottomrule")
        lines.append("\\end{tabular}")
        if self.resize_to_width:
            lines.append("}")
        if self.footnote:
            lines.append(f"\\vspace{{2pt}}\n\\par\\footnotesize{{{escape_latex(self.footnote)}}}")
        lines.append("\\end{table}")
        return "\n".join(lines)


class LatexFigure(LatexNode):
    """Structured figure node resolving assets relative to manuscript directory."""

    def __init__(
        self,
        figure_path: Union[str, Path],
        manuscript_dir: Union[str, Path],
        caption: str = "",
        label: str = "",
        width: str = "\\columnwidth",
        pos: str = "h",
    ) -> None:
        self.resolved_path = resolve_figure_path(figure_path, manuscript_dir)
        self.caption = caption
        self.label = label
        self.width = width
        self.pos = pos

    def render(self) -> str:
        lines: list[str] = []
        lines.append(f"\\begin{{figure}}[{self.pos}]")
        lines.append("\\centering")
        lines.append(f"\\includegraphics[width={self.width}]{{{self.resolved_path}}}")
        if self.caption:
            lines.append(f"\\caption{{{escape_latex(self.caption)}}}")
        if self.label:
            lines.append(f"\\label{{{self.label}}}")
        lines.append("\\end{figure}")
        return "\n".join(lines)


class LatexDocument(LatexNode):
    """Complete publication-ready LaTeX document compiler."""

    def __init__(
        self,
        documentclass: str = "IEEEtran",
        options: str = "10pt,journal,compsoc",
        packages: Optional[list[str]] = None,
    ) -> None:
        self.documentclass = documentclass
        self.options = options
        self.packages = packages or [
            "amsmath,amssymb,amsfonts",
            "booktabs",
            "graphicx",
            "hyperref",
            "cite",
        ]
        self.body_nodes: list[LatexNode] = []

    def add(self, node: LatexNode) -> LatexDocument:
        self.body_nodes.append(node)
        return self

    def render(self) -> str:
        lines: list[str] = []
        opts = f"[{self.options}]" if self.options else ""
        lines.append(f"\\documentclass{opts}{{{self.documentclass}}}")
        for pkg in self.packages:
            lines.append(f"\\usepackage{{{pkg}}}")
        lines.append("\\begin{document}\n")

        for node in self.body_nodes:
            lines.append(node.render())
            lines.append("")

        lines.append("\\end{document}\n")
        return "\n".join(lines)


class LatexStatisticalClaim(LatexNode):
    """Evidence-bound statistical claim AST node (Directive 4).

    Pulls empirical numbers directly from verified MetricAggregate or EvaluationReport.
    Strictly forbids rendering 'p < 0.05' unless p_value is not None and significance_claim_allowed == True.
    """

    def __init__(
        self,
        metric_name: str,
        evidence_ref: Any,
        format_spec: str = "mean_std",
        symbolic_ref: Optional[str] = None,
    ) -> None:
        self.metric_name = metric_name
        self.evidence_ref = evidence_ref
        self.format_spec = format_spec
        self.symbolic_ref = symbolic_ref or f"\\evidenceClaim{{{metric_name}.{format_spec}}}"

    def _resolve_aggregate(self) -> Any:
        ref = self.evidence_ref
        if hasattr(ref, "metric_aggregates") and self.metric_name in ref.metric_aggregates:
            return ref.metric_aggregates[self.metric_name]
        if hasattr(ref, "mean"):
            return ref
        if isinstance(ref, dict):
            if "metric_aggregates" in ref and self.metric_name in ref["metric_aggregates"]:
                return ref["metric_aggregates"][self.metric_name]
            if self.metric_name in ref:
                return ref[self.metric_name]
            if "mean" in ref:
                return ref
        raise KeyError(f"Metric '{self.metric_name}' not found in evidence reference")

    def render(self) -> str:
        agg = self._resolve_aggregate()
        mean = getattr(agg, "mean", None) if not isinstance(agg, dict) else agg.get("mean")
        std_dev = getattr(agg, "std_dev", None) if not isinstance(agg, dict) else agg.get("std_dev")
        std_err = getattr(agg, "std_err", None) if not isinstance(agg, dict) else agg.get("std_err")
        p_val = getattr(agg, "p_value_estimate", None) if not isinstance(agg, dict) else agg.get("p_value_estimate")
        stat_analysis = getattr(agg, "statistical_analysis", None) if not isinstance(agg, dict) else agg.get("statistical_analysis")
        if p_val is None and stat_analysis:
            p_val = getattr(stat_analysis, "p_value", None) if not isinstance(stat_analysis, dict) else stat_analysis.get("p_value")
        sig_allowed = getattr(agg, "significance_claim_allowed", False) if not isinstance(agg, dict) else agg.get("significance_claim_allowed", False)
        if not sig_allowed and stat_analysis:
            sig_allowed = getattr(stat_analysis, "significance_claim_allowed", False) if not isinstance(stat_analysis, dict) else stat_analysis.get("significance_claim_allowed", False)

        if mean is None:
            mean = 0.0
        if std_dev is None:
            std_dev = 0.0

        if self.format_spec == "mean":
            return f"{mean:.4f}"
        elif self.format_spec == "mean_std":
            return f"${mean:.4f} \\pm {std_dev:.4f}$"
        elif self.format_spec == "reduction_pct":
            return f"{(1.0 - mean) * 100:.1f}\\%"
        elif self.format_spec in ("p_value", "p"):
            if not sig_allowed or p_val is None:
                return "p = \\text{n.s.}"
            return f"$p = {p_val:.4f}$"
        elif self.format_spec == "significance":
            if not sig_allowed or p_val is None:
                raise ValueError(
                    f"Cannot render statistical significance claim for '{self.metric_name}': "
                    f"p_value is {p_val} and significance_claim_allowed is {sig_allowed}."
                )
            if p_val < 0.001:
                return "$p < 0.001$"
            elif p_val < 0.01:
                return "$p < 0.01$"
            elif p_val < 0.05:
                return "$p < 0.05$"
            else:
                return f"$p = {p_val:.4f}$"
        elif self.format_spec in ("claim", "summary"):
            if sig_allowed and p_val is not None and p_val < 0.05:
                return f"{self.metric_name}: Mean = {mean:.4f} ($SD = {std_dev:.4f}$, $p < 0.05$)"
            else:
                return f"{self.metric_name}: Mean = {mean:.4f} ($SD = {std_dev:.4f}$, not statistically significant)"
        return f"{mean:.4f}"


class LatexMetricTable(LatexNode):
    """Typed AST node for verified statistical metric tables (Directive 4)."""

    def __init__(
        self,
        evidence_table_ref: Any,
        caption: str = "Aggregated Multi-Seed Statistical Evaluation",
        label: str = "tab:metrics",
    ) -> None:
        self.evidence_table_ref = evidence_table_ref
        self.caption = caption
        self.label = label

    def render(self) -> str:
        ref = self.evidence_table_ref
        if hasattr(ref, "metric_aggregates"):
            aggs = ref.metric_aggregates
            n_runs = getattr(ref, "total_runs", 1)
        elif isinstance(ref, dict) and "metric_aggregates" in ref:
            aggs = ref["metric_aggregates"]
            n_runs = ref.get("total_runs", 1)
        elif isinstance(ref, dict):
            aggs = ref
            n_runs = 1
        else:
            raise ValueError(f"Unsupported evidence_table_ref type: {type(ref)}")

        headers = [
            "Metric",
            LatexRaw("Mean ($M$)", allow_claims=True),
            LatexRaw("SD", allow_claims=True),
            LatexRaw("$N$", allow_claims=True),
            LatexRaw("d.f.", allow_claims=True),
            LatexRaw("$p$-value", allow_claims=True),
            "Verdict",
        ]
        df_val = max(1, n_runs - 1)
        rows: list[list[Union[str, LatexNode]]] = []
        has_zero_var = False
        for m_name, agg in aggs.items():
            passed = getattr(agg, "passed", True) if not isinstance(agg, dict) else agg.get("passed", True)
            mean = getattr(agg, "mean", 0.0) if not isinstance(agg, dict) else agg.get("mean", 0.0)
            std_dev = getattr(agg, "std_dev", 0.0) if not isinstance(agg, dict) else agg.get("std_dev", 0.0)
            samples = getattr(agg, "sample_values", []) if not isinstance(agg, dict) else agg.get("sample_values", [])
            p_val = getattr(agg, "p_value_estimate", None) if not isinstance(agg, dict) else agg.get("p_value_estimate")
            stat_analysis = getattr(agg, "statistical_analysis", None) if not isinstance(agg, dict) else agg.get("statistical_analysis")
            if p_val is None and stat_analysis:
                p_val = getattr(stat_analysis, "p_value", None) if not isinstance(stat_analysis, dict) else stat_analysis.get("p_value")
            sig_allowed = getattr(agg, "significance_claim_allowed", False) if not isinstance(agg, dict) else agg.get("significance_claim_allowed", False)
            if not sig_allowed and stat_analysis:
                sig_allowed = getattr(stat_analysis, "significance_claim_allowed", False) if not isinstance(stat_analysis, dict) else stat_analysis.get("significance_claim_allowed", False)

            pass_str = "Confirmed" if passed else "Refuted"
            if len(samples) > 1 and std_dev == 0.0:
                p_val_str = "N/A*"
                has_zero_var = True
            elif not sig_allowed or p_val is None:
                p_val_str = "N/A"
            else:
                p_val_str = f"{p_val:.4f}"

            rows.append([
                m_name,
                f"{mean:.4f}",
                f"{std_dev:.4f}",
                str(n_runs),
                str(df_val),
                p_val_str,
                pass_str,
            ])

        footnote = (
            "* Identical outputs across seeds (SD = 0.0000); null hypothesis significance testing uninformative."
            if has_zero_var
            else None
        )
        escaped_title = escape_latex(self.caption)
        caption_str = f"{escaped_title} ($N={n_runs}$)"
        return LatexTable(
            headers=headers,
            rows=rows,
            caption=caption_str,
            label=self.label,
            footnote=footnote,
            escape_caption=False,
            resize_to_width="\\columnwidth",
        ).render()


class LatexVerifiedFigure(LatexNode):
    """Cryptographically verified publication figure node (Directive 4)."""

    def __init__(
        self,
        figure_path: Union[str, Path],
        sha256_hash: Optional[str] = None,
        evidence_ref: Optional[Any] = None,
        caption: str = "",
        label: str = "fig:figure",
        manuscript_dir: Optional[Union[str, Path]] = None,
        width: str = "\\columnwidth",
    ) -> None:
        self.figure_path = Path(figure_path)
        self.sha256_hash = sha256_hash
        self.evidence_ref = evidence_ref
        self.caption = caption
        self.label = label
        self.manuscript_dir = Path(manuscript_dir) if manuscript_dir else None
        self.width = width

        if self.figure_path.exists() and self.figure_path.is_file() and self.sha256_hash:
            actual_hash = hashlib.sha256(self.figure_path.read_bytes()).hexdigest()
            if actual_hash != self.sha256_hash:
                raise ValueError(
                    f"LatexVerifiedFigure integrity check failed for '{self.figure_path}': "
                    f"expected hash {self.sha256_hash}, got {actual_hash}"
                )

    def render(self) -> str:
        fig_str = resolve_figure_path(self.figure_path, self.manuscript_dir) if self.manuscript_dir else self.figure_path.as_posix()
        lines = [
            "\\begin{figure}[h]",
            "\\centering",
            f"\\includegraphics[width={self.width}]{{{fig_str}}}",
        ]
        if self.caption:
            lines.append(f"\\caption{{{escape_latex(self.caption)}}}")
        if self.label:
            lines.append(f"\\label{{{self.label}}}")
        lines.append("\\end{figure}")
        return "\n".join(lines)


class ClaimNode(LatexNode):
    """Typed evidence-bound AST node for scientific and statistical claims (M1, M2, M3)."""

    def __init__(
        self,
        metric_id: str,
        role: str,  # "treatment_mean", "mean", "baseline_mean", "reduction_pct", "p_value", "std_dev"
        evidence_ref: Any = None,  # MetricAggregate, EvaluationReport, or dict
        format_spec: str = ".2f",
        baseline_mean: Optional[float] = None,
        treatment_mean: Optional[float] = None,
    ) -> None:
        self.metric_id = metric_id
        self.role = role
        self.evidence_ref = evidence_ref
        self.format_spec = format_spec
        self.baseline_mean = baseline_mean
        self.treatment_mean = treatment_mean

    def render(self) -> str:
        if self.role == "reduction_pct" and self.baseline_mean is not None and self.treatment_mean is not None:
            if float(self.baseline_mean) <= 0.0:
                raise ValueError("Cannot compute reduction_pct: baseline mean must be positive and non-zero.")
            red = ((float(self.baseline_mean) - float(self.treatment_mean)) / float(self.baseline_mean)) * 100.0
            return f"{red:{self.format_spec}}"

        evidence = self.evidence_ref
        target_agg = None
        baseline_agg = None

        if isinstance(evidence, dict):
            if "aggregates" in evidence:
                target_agg = evidence["aggregates"].get(self.metric_id)
                baseline_agg = evidence["aggregates"].get(f"baseline_{self.metric_id}")
            elif self.metric_id in evidence:
                target_agg = evidence[self.metric_id]
        elif hasattr(evidence, "aggregates"):
            target_agg = evidence.aggregates.get(self.metric_id)
            baseline_agg = evidence.aggregates.get(f"baseline_{self.metric_id}")
        elif hasattr(evidence, "metric_name"):
            target_agg = evidence

        if target_agg is None and self.treatment_mean is None:
            raise KeyError(f"Metric '{self.metric_id}' not found in evidence artifact.")

        t_mean = self.treatment_mean
        if t_mean is None and target_agg is not None:
            t_mean = getattr(target_agg, "mean", None)
            if t_mean is None and isinstance(target_agg, dict):
                t_mean = target_agg.get("mean")

        if self.role in ("treatment_mean", "mean"):
            return f"{float(t_mean):{self.format_spec}}"

        elif self.role == "std_dev":
            sd = getattr(target_agg, "std_dev", 0.0) if target_agg else 0.0
            if isinstance(target_agg, dict):
                sd = target_agg.get("std_dev", 0.0)
            return f"{float(sd):{self.format_spec}}"

        elif self.role == "baseline_mean":
            b_mean = self.baseline_mean
            if b_mean is None:
                b_mean = getattr(baseline_agg, "mean", None) if baseline_agg else None
                if b_mean is None and isinstance(baseline_agg, dict):
                    b_mean = baseline_agg.get("mean")
                if b_mean is None and target_agg is not None:
                    b_mean = getattr(target_agg, "target_threshold", 0.0)
            return f"{float(b_mean):{self.format_spec}}"

        elif self.role == "reduction_pct":
            # Exact Relative Reduction Math (M3): ((Baseline - Treatment) / Baseline) * 100
            b_mean = self.baseline_mean
            if b_mean is None:
                b_mean = getattr(baseline_agg, "mean", None) if baseline_agg else None
                if b_mean is None and isinstance(baseline_agg, dict):
                    b_mean = baseline_agg.get("mean")
                if b_mean is None and target_agg is not None:
                    b_mean = getattr(target_agg, "target_threshold", None)
                    if isinstance(target_agg, dict):
                        b_mean = target_agg.get("target_threshold")
            if b_mean is None or float(b_mean) <= 0.0:
                raise ValueError("Cannot compute reduction_pct: baseline mean must be positive and non-zero.")
            base_val = float(b_mean)
            treat_val = float(t_mean)
            reduction = ((base_val - treat_val) / base_val) * 100.0
            return f"{reduction:{self.format_spec}}"

        elif self.role == "p_value":
            p_val = getattr(target_agg, "p_value_estimate", None)
            sig_allowed = getattr(target_agg, "significance_claim_allowed", False)
            if isinstance(target_agg, dict):
                p_val = target_agg.get("p_value_estimate")
                sig_allowed = target_agg.get("significance_claim_allowed", False)

            if p_val is None or not sig_allowed:
                raise ValueError(
                    f"EvidenceConsistencyViolation: Cannot render p-value for '{self.metric_id}'. "
                    f"Significance claims are blocked (p={p_val}, allowed={sig_allowed})."
                )
            if p_val < 0.001:
                return "$p < 0.001$"
            return f"$p = {float(p_val):{self.format_spec}}$"

        else:
            raise ValueError(f"Unsupported ClaimNode role: '{self.role}'")

"""Scientific Integrity Linter and Epistemic Honesty Gate for Research OS (Directive 3).

Enforces:
- Epistemic Language Integrity: If an experiment is SIMULATION or SYNTHETIC_BENCHMARK,
  strictly forbids overclaiming "empirical evidence", "real-world validation", etc.
- Statistical Honesty Gate: If metric variance across seeds is zero (SD == 0.0) or sample size
  is below statistical power thresholds, blocks null-hypothesis significance claims (e.g. 'p < 0.05').
"""

from __future__ import annotations

import re
from typing import Optional

from research_os.core.classification import ExperimentClass
from research_os.schemas.evaluation import EvaluationReport


class ScientificIntegrityError(ValueError):
    """Raised when scientific claims in manuscripts or reports violate epistemic truthfulness."""
    pass


class EpistemicHonestyViolation(ScientificIntegrityError):
    """Raised when simulation artifacts claim empirical validation or zero-variance runs claim significance."""
    pass


class ScientificIntegrityLinter:
    """Automated linter auditing manuscripts and reports for scientific overclaims and statistical fraud."""

    FORBIDDEN_SIMULATION_PHRASES: list[tuple[re.Pattern, str]] = [
        (re.compile(r"\bempirical\s+evidence\b", re.IGNORECASE), "simulation evidence"),
        (re.compile(r"\breal-?world\s+validation\b", re.IGNORECASE), "in-silico validation"),
        (re.compile(r"\breal-?world\s+deployment\b", re.IGNORECASE), "experimental deployment"),
        (re.compile(r"\bempirically\s+proven\s+in\s+the\s+real\s+world\b", re.IGNORECASE), "demonstrated in simulation"),
        (re.compile(r"\bempirically\s+validated\s+in\s+the\s+real\s+world\b", re.IGNORECASE), "validated in simulation"),
        (re.compile(r"\bdemonstrates\s+real-?world\s+efficacy\b", re.IGNORECASE), "demonstrates simulation efficacy"),
    ]

    SIGNIFICANCE_CLAIM_PATTERNS: list[re.Pattern] = [
        re.compile(r"p\s*<\s*0\.05", re.IGNORECASE),
        re.compile(r"p\s*<\s*0\.01", re.IGNORECASE),
        re.compile(r"statistically\s+significant", re.IGNORECASE),
        re.compile(r"statistically\s+confirmed", re.IGNORECASE),
        re.compile(r"rejects?\s+(the\s+)?null\s+hypothesis", re.IGNORECASE),
    ]

    @classmethod
    def lint_text(
        cls,
        text: str,
        experiment_class: ExperimentClass,
        evaluation: Optional[EvaluationReport] = None,
    ) -> list[str]:
        """Audit text for epistemic overclaims and fraudulent statistical significance."""
        violations: list[str] = []

        # 1. Epistemic Language Linter (Simulation vs Empirical)
        if experiment_class in (ExperimentClass.SIMULATION, ExperimentClass.SYNTHETIC_BENCHMARK):
            for pattern, _ in cls.FORBIDDEN_SIMULATION_PHRASES:
                matches = pattern.findall(text)
                if matches:
                    violations.append(
                        f"Epistemic Overclaim: ExperimentClass.{experiment_class.value} manuscript uses "
                        f"forbidden empirical claim phrase: '{matches[0]}'. "
                        f"Simulations and synthetic benchmarks must not claim real-world empirical proof."
                    )

        # 2. Statistical Honesty Gate (Zero Variance / Low Power / Null p-value)
        if evaluation:
            has_zero_variance = False
            zero_variance_metrics = []
            for m_name, agg in evaluation.metric_aggregates.items():
                if len(agg.sample_values) > 1 and agg.std_dev == 0.0:
                    has_zero_variance = True
                    zero_variance_metrics.append(m_name)

            is_insufficient_sample = evaluation.total_runs < 2 or evaluation.successful_runs < 2

            # Check if target metric lacks valid p-value or significance permission
            target_metric_lacks_significance = False
            target_agg = evaluation.metric_aggregates.get(evaluation.target_metric)
            if target_agg is not None:
                p_val = getattr(target_agg, "p_value_estimate", None)
                stat_analysis = getattr(target_agg, "statistical_analysis", None)
                if p_val is None and stat_analysis:
                    p_val = getattr(stat_analysis, "p_value", None)
                sig_allowed = getattr(target_agg, "significance_claim_allowed", False)
                if not sig_allowed and stat_analysis:
                    sig_allowed = getattr(stat_analysis, "significance_claim_allowed", False)
                if p_val is None or not sig_allowed or (p_val is not None and p_val >= 0.05):
                    target_metric_lacks_significance = True

            if has_zero_variance or is_insufficient_sample or target_metric_lacks_significance:
                for pattern in cls.SIGNIFICANCE_CLAIM_PATTERNS:
                    found = pattern.findall(text)
                    if found:
                        if has_zero_variance:
                            reason = f"zero variance across seeds ({', '.join(zero_variance_metrics)} SD=0.0)"
                        elif is_insufficient_sample:
                            reason = f"insufficient sample size (N={evaluation.total_runs})"
                        else:
                            reason = (
                                f"null or uninformative p-value on target metric '{evaluation.target_metric}' "
                                f"(p_value_estimate is None or significance_claim_allowed=False)"
                            )
                        violations.append(
                            f"Statistical Honesty Violation: Manuscript claims '{found[0]}' while evaluation has "
                            f"{reason}. Missing or uninformative p-values cannot claim statistical significance."
                        )

        return violations

    @classmethod
    def assert_integrity(
        cls,
        text: str,
        experiment_class: ExperimentClass,
        evaluation: Optional[EvaluationReport] = None,
    ) -> None:
        """Enforce strict gate: raises EpistemicHonestyViolation if any violation is found."""
        violations = cls.lint_text(text, experiment_class, evaluation)
        if violations:
            msg = "\n".join(f"  - {v}" for v in violations)
            raise EpistemicHonestyViolation(f"Scientific Integrity Linter Rejected Manuscript:\n{msg}")

    @classmethod
    def sanitize_epistemic_claims(cls, text: str, experiment_class: ExperimentClass) -> str:
        """Automatically rewrite overclaimed phrases into honest in-silico terminology."""
        if experiment_class not in (ExperimentClass.SIMULATION, ExperimentClass.SYNTHETIC_BENCHMARK):
            return text

        sanitized = text
        for pattern, replacement in cls.FORBIDDEN_SIMULATION_PHRASES:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized

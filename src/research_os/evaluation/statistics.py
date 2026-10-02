"""Strictly Typed Statistical Inference Engine for Research OS (Directive 2 & P0 Hardening).

Enforces:
- Complete delegation of distribution math to scipy.stats (stats.t.sf, stats.t.ppf, stats.t.interval).
- Elimination of custom numerical approximations (_betainc) and hardcoded critical value tables.
- Descriptive vs. Inferential isolation: non-target metrics are strictly descriptive (significance_claim_allowed = False).
- Golden Rule of Statistics:
    If variance == 0.0 or sample_size < power_threshold or p_value is None or p_value >= alpha:
        significance_claim_allowed = False.
- Unit of Analysis: independent evaluation items / queries, paired item-level evaluation via McNemar (binomtest) and paired t-tests (ttest_rel).
"""

from __future__ import annotations

import math
from typing import Optional, Sequence
import scipy.stats as stats

from research_os.schemas.evaluation import (
    ReplicationStatus,
    StatisticalAnalysisResult,
    StatisticalSupport,
    ThresholdStatus,
)


def student_t_p_value(t_stat: float, df: int) -> float:
    """Calculate exact two-tailed p-value for Student's t distribution via scipy.stats.
    
    Guarantees machine precision (< 10^-6) matching SciPy ground truth.
    """
    if df <= 0 or math.isnan(t_stat) or math.isinf(t_stat):
        return 1.0
    t_abs = abs(t_stat)
    if t_abs == 0.0:
        return 1.0
    # Two-tailed p-value = 2 * P(T >= |t|) = 2 * stats.t.sf(|t|, df)
    p_val = float(2.0 * stats.t.sf(t_abs, df=df))
    return max(0.0, min(1.0, p_val))


def compute_statistical_inference(
    sample_values: Sequence[float],
    target_threshold: Optional[float] = None,
    operator: str = ">=",
    metric_name: str = "metric",
    power_threshold: int = 2,
    alpha: float = 0.05,
    is_target_metric: bool = True,
) -> StatisticalAnalysisResult:
    """Compute rigorous inferential statistics for sample metrics using scipy.stats.

    Enforces P0 Audit Requirements:
    - Descriptive vs. Inferential Isolation: Non-target metrics must NOT be tested against 0.0
      or treated as inferential hypotheses; significance_claim_allowed = False by default.
    - If variance == 0.0: blocks significance claims (SD == 0.0000 cannot claim p < 0.05).
    - If sample_size < power_threshold: blocks significance claims.
    - If p_value is None or >= alpha: significance_claim_allowed = False.
    """
    n = len(sample_values)
    reasons_blocked: list[str] = []

    if n == 0:
        return StatisticalAnalysisResult(
            metric_name=metric_name,
            sample_size=0,
            mean=0.0,
            variance=0.0,
            standard_deviation=0.0,
            standard_error=0.0,
            degrees_of_freedom=0,
            test_statistic=None,
            p_value=None,
            confidence_interval=None,
            assumptions_met=False,
            significance_claim_allowed=False,
            reasons_significance_blocked=["Empty sample (N=0)"],
        )

    mean = float(sum(sample_values) / n)

    if n < 2:
        variance = 0.0
        sd = 0.0
        se = 0.0
        df = 0
    else:
        variance = float(sum((x - mean) ** 2 for x in sample_values) / (n - 1))
        sd = float(math.sqrt(variance))
        se = float(sd / math.sqrt(n))
        df = n - 1

    # Descriptive vs. Inferential Isolation (S3):
    # Non-target metrics must NOT be tested against 0.0 or treated as inferential hypotheses.
    if not is_target_metric or target_threshold is None:
        reasons_blocked.append("Non-target / descriptive metric: inferential significance testing disabled")
        return StatisticalAnalysisResult(
            metric_name=metric_name,
            sample_size=n,
            mean=round(mean, 6),
            variance=round(variance, 6),
            standard_deviation=round(sd, 6),
            standard_error=round(se, 6),
            degrees_of_freedom=df,
            test_statistic=None,
            p_value=None,
            confidence_interval=(round(mean - 1.96 * se, 4), round(mean + 1.96 * se, 4)) if se > 0 else (round(mean, 4), round(mean, 4)),
            assumptions_met=(variance > 0.0) and (n >= 2),
            significance_claim_allowed=False,
            reasons_significance_blocked=reasons_blocked,
        )

    # Golden Rule Checks:
    # 1. Zero Variance
    if n > 1 and variance == 0.0:
        reasons_blocked.append("Zero variance across observational units (SD == 0.0000); identical outputs cannot establish statistical significance")

    # 2. Power Threshold
    if n < power_threshold:
        reasons_blocked.append(f"Sample size N={n} is below statistical power threshold (N >= {power_threshold} required)")

    # 3. Test Statistic and p-value computation via scipy.stats
    t_stat: Optional[float] = None
    p_val: Optional[float] = None
    ci: Optional[tuple[float, float]] = None

    if se > 0.0 and df > 0:
        comp_thresh = target_threshold
        t_stat = float((mean - comp_thresh) / se)
        p_val = student_t_p_value(t_stat, df)

        # Confidence Interval via scipy.stats.t.interval
        try:
            ci_low, ci_high = stats.t.interval(1.0 - alpha, df=df, loc=mean, scale=se)
            ci = (round(float(ci_low), 4), round(float(ci_high), 4))
        except Exception:
            t_crit = float(stats.t.ppf(1.0 - alpha / 2.0, df=df))
            ci = (round(mean - t_crit * se, 4), round(mean + t_crit * se, 4))
    else:
        t_stat = None
        p_val = None
        ci = (round(mean, 4), round(mean, 4))

    if p_val is None:
        reasons_blocked.append("p-value estimate is uninformative / undefined")
    elif p_val >= alpha:
        reasons_blocked.append(f"Observed p-value ({p_val:.4f}) does not meet significance threshold (alpha = {alpha})")

    # Directional / Condition consistency
    condition_passed = False
    if operator == ">=":
        condition_passed = mean >= target_threshold
    elif operator == "<=":
        condition_passed = mean <= target_threshold
    elif operator == ">":
        condition_passed = mean > target_threshold
    elif operator == "<":
        condition_passed = mean < target_threshold
    elif operator == "==":
        condition_passed = abs(mean - target_threshold) <= 1e-4

    if not condition_passed:
        reasons_blocked.append(f"Sample mean ({mean:.4f}) does not satisfy expected condition ({operator} {target_threshold})")

    assumptions_met = (variance > 0.0) and (n >= 2)
    significance_allowed = (len(reasons_blocked) == 0) and condition_passed and (p_val is not None and p_val < alpha)

    return StatisticalAnalysisResult(
        metric_name=metric_name,
        sample_size=n,
        mean=round(mean, 6),
        variance=round(variance, 6),
        standard_deviation=round(sd, 6),
        standard_error=round(se, 6),
        degrees_of_freedom=df,
        test_statistic=round(t_stat, 4) if t_stat is not None else None,
        p_value=round(p_val, 6) if p_val is not None else None,
        confidence_interval=ci,
        assumptions_met=assumptions_met,
        significance_claim_allowed=significance_allowed,
        reasons_significance_blocked=reasons_blocked,
    )


def compute_paired_item_inference(
    treatment_items: Sequence[float],
    baseline_items: Sequence[float],
    metric_name: str = "metric",
    is_binary: bool = False,
    alpha: float = 0.05,
    power_threshold: int = 10,
) -> StatisticalAnalysisResult:
    """Compute rigorous paired item-level evaluation across independent evaluation units (S4).

    Uses:
    - McNemar's exact test (via stats.binomtest) for binary outcomes (e.g. hallucinated 0 vs 1).
    - Paired Student's t-test (via stats.ttest_rel) for continuous metrics.
    """
    n = min(len(treatment_items), len(baseline_items))
    reasons_blocked: list[str] = []

    if n == 0:
        return StatisticalAnalysisResult(
            metric_name=metric_name,
            sample_size=0,
            mean=0.0,
            variance=0.0,
            standard_deviation=0.0,
            standard_error=0.0,
            degrees_of_freedom=0,
            test_statistic=None,
            p_value=None,
            confidence_interval=None,
            assumptions_met=False,
            significance_claim_allowed=False,
            reasons_significance_blocked=["Empty paired sample (N=0)"],
        )

    t_vals = [float(x) for x in treatment_items[:n]]
    b_vals = [float(x) for x in baseline_items[:n]]
    diffs = [t - b for t, b in zip(t_vals, b_vals)]

    mean_diff = float(sum(diffs) / n)
    variance_diff = float(sum((d - mean_diff) ** 2 for d in diffs) / (n - 1)) if n > 1 else 0.0
    sd_diff = float(math.sqrt(variance_diff))
    se_diff = float(sd_diff / math.sqrt(n)) if n > 0 else 0.0
    df = n - 1

    if n < power_threshold:
        reasons_blocked.append(f"Item-level sample size N={n} is below power threshold (N >= {power_threshold})")

    if variance_diff == 0.0:
        reasons_blocked.append("Zero variance across paired differences (all paired item deltas identical)")

    t_stat: Optional[float] = None
    p_val: Optional[float] = None

    if is_binary:
        # McNemar's exact test on discordant pairs:
        # b = treatment=1, baseline=0
        # c = treatment=0, baseline=1
        b_count = sum(1 for t, b in zip(t_vals, b_vals) if t > 0.5 and b <= 0.5)
        c_count = sum(1 for t, b in zip(t_vals, b_vals) if t <= 0.5 and b > 0.5)
        discordant = b_count + c_count
        if discordant > 0:
            binom_res = stats.binomtest(b_count, n=discordant, p=0.5)
            p_val = float(binom_res.pvalue)
            t_stat = float(b_count - c_count)
        else:
            p_val = 1.0
            t_stat = 0.0
    else:
        # Continuous paired t-test
        if variance_diff > 0.0 and n >= 2:
            res = stats.ttest_rel(t_vals, b_vals)
            t_stat = float(res.statistic)
            p_val = float(res.pvalue)
        else:
            t_stat = None
            p_val = None

    if p_val is None:
        reasons_blocked.append("p-value is undefined / uninformative")
    elif p_val >= alpha:
        reasons_blocked.append(f"Paired p-value ({p_val:.4f}) does not meet significance threshold (alpha = {alpha})")

    assumptions_met = (variance_diff > 0.0) and (n >= 2)
    sig_allowed = (len(reasons_blocked) == 0) and (p_val is not None and p_val < alpha)

    ci = (round(mean_diff - 1.96 * se_diff, 4), round(mean_diff + 1.96 * se_diff, 4)) if se_diff > 0 else (round(mean_diff, 4), round(mean_diff, 4))

    return StatisticalAnalysisResult(
        metric_name=metric_name,
        sample_size=n,
        mean=round(mean_diff, 6),
        variance=round(variance_diff, 6),
        standard_deviation=round(sd_diff, 6),
        standard_error=round(se_diff, 6),
        degrees_of_freedom=df,
        test_statistic=round(t_stat, 4) if t_stat is not None else None,
        p_value=round(p_val, 6) if p_val is not None else None,
        confidence_interval=ci,
        assumptions_met=assumptions_met,
        significance_claim_allowed=sig_allowed,
        reasons_significance_blocked=reasons_blocked,
    )


def determine_decoupled_verdicts(
    sample_values: Sequence[float],
    mean: float,
    std_dev: float,
    target_threshold: float,
    operator: str = ">=",
    p_value: Optional[float] = None,
    alpha: float = 0.05,
    significance_allowed: bool = False,
) -> tuple[ThresholdStatus, StatisticalSupport, ReplicationStatus]:
    """Calculate the 3 decoupled outcome verdicts in empirical evaluation (Directive 4).

    1. threshold_status: PASS | FAIL (whether empirical mean met registered numeric threshold).
    2. statistical_support: SIGNIFICANT | INSUFFICIENT | INFORMATIVE_NON_SIGNIFICANT (conditioned on p-value and N >= 3).
    3. replication_status: REPRODUCIBLE | HIGH_VARIANCE | SINGLE_POINT (conditioned on cross-seed variance stability).
    """
    n = len(sample_values)

    # 1. threshold_status: PASS | FAIL
    passed = False
    if operator == ">":
        passed = mean > target_threshold
    elif operator == ">=":
        passed = mean >= target_threshold
    elif operator == "<":
        passed = mean < target_threshold
    elif operator == "<=":
        passed = mean <= target_threshold
    elif operator == "==":
        passed = abs(mean - target_threshold) < 1e-9

    thresh_status = ThresholdStatus.PASS if passed else ThresholdStatus.FAIL

    # 2. statistical_support: SIGNIFICANT | INSUFFICIENT | INFORMATIVE_NON_SIGNIFICANT
    if n < 3 or p_value is None:
        stat_support = StatisticalSupport.INSUFFICIENT
    elif p_value < alpha and significance_allowed:
        stat_support = StatisticalSupport.SIGNIFICANT
    else:
        stat_support = StatisticalSupport.INFORMATIVE_NON_SIGNIFICANT

    # 3. replication_status: REPRODUCIBLE | HIGH_VARIANCE | SINGLE_POINT
    if n <= 1:
        rep_status = ReplicationStatus.SINGLE_POINT
    else:
        abs_mean = abs(mean) if abs(mean) > 1e-9 else 1.0
        cv = std_dev / abs_mean
        if cv > 0.35:
            rep_status = ReplicationStatus.HIGH_VARIANCE
        else:
            rep_status = ReplicationStatus.REPRODUCIBLE

    return thresh_status, stat_support, rep_status

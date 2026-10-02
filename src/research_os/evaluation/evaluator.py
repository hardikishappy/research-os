"""Statistical evaluation of multi-seed experiment runs (Rules 4 & 16).

Aggregates empirical results across multiple random seeds, computing sample mean,
standard deviation, and standard error, and determining whether hypotheses are
CONFIRMED, REFUTED, or INCONCLUSIVE via deterministic threshold checks.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from research_os.gate.approval import (
    canonicalize_gate_payload,
    compute_canonical_spec_hash,
    generate_keyed_signature,
    mint_child_delegation_token,
)
from research_os.memory.tracker import ExperimentTracker
from research_os.sandbox.runner import SandboxRunner
from research_os.evaluation.statistics import determine_decoupled_verdicts
from research_os.schemas.evaluation import (
    EvaluationReport,
    GridCombinationSummary,
    GridEvaluationReport,
    HypothesisVerdict,
    MetricAggregate,
    ReplicationStatus,
    SeedRunSummary,
    StatisticalSupport,
    ThresholdStatus,
)
from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.gate import GateKind, GateStatus, HumanGateToken
from research_os.schemas.hypothesis import HypothesisProposal
from research_os.schemas.verification import VerificationStatus
from research_os.verify.deterministic import (
    DeterministicVerifier,
    evaluate_metric_condition,
)
from research_os.evaluation.statistics import compute_statistical_inference


class StatisticalEvaluator:
    """Evaluates hypothesis validity across multiple random seeds deterministically."""

    def __init__(self, metrics_filename: str = "metrics.json") -> None:
        self.metrics_filename = metrics_filename

    def aggregate_metrics(
        self,
        hypothesis: HypothesisProposal,
        seed_runs: list[SeedRunSummary],
    ) -> dict[str, MetricAggregate]:
        """Compute mean, std_dev, and std_err across valid seed runs."""
        # Collect numeric values per metric
        metric_samples: dict[str, list[float]] = {}
        for run in seed_runs:
            if run.exit_code == 0:
                for k, v in run.metrics.items():
                    if isinstance(v, (int, float)) and not math.isnan(v):
                        metric_samples.setdefault(k, []).append(float(v))

        aggregates: dict[str, MetricAggregate] = {}
        target_op = "<=" if hypothesis.expected_direction == "decrease" else ">="

        for metric_name, values in metric_samples.items():
            if not values:
                continue

            n = len(values)
            mean = sum(values) / n
            if n > 1:
                variance = sum((x - mean) ** 2 for x in values) / (n - 1)
                std_dev = math.sqrt(variance)
                std_err = std_dev / math.sqrt(n)
            else:
                std_dev = 0.0
                std_err = 0.0

            # Determine threshold check
            if metric_name == hypothesis.target_metric:
                threshold = hypothesis.success_threshold
                op = target_op
                passed = evaluate_metric_condition(mean, threshold, op)
            else:
                threshold = 0.0
                op = ">="
                passed = True

            is_target = (metric_name == hypothesis.target_metric)
            # Compute formal inferential statistics (Directive 2 & P0 Hardening)
            stat_res = compute_statistical_inference(
                sample_values=values,
                target_threshold=threshold if is_target else None,
                operator=op,
                metric_name=metric_name,
                power_threshold=2,
                is_target_metric=is_target,
            )

            aggregates[metric_name] = MetricAggregate(
                metric_name=metric_name,
                sample_values=[round(v, 4) for v in values],
                mean=round(mean, 4),
                std_dev=round(std_dev, 4),
                std_err=round(std_err, 4),
                target_threshold=threshold,
                operator=op,  # type: ignore[arg-type]
                passed=passed,
                p_value_estimate=stat_res.p_value,
                statistical_analysis=stat_res,
                significance_claim_allowed=stat_res.significance_claim_allowed,
            )

        return aggregates

    def evaluate_runs(
        self,
        hypothesis: HypothesisProposal,
        spec: ExperimentSpec,
        seed_runs: list[SeedRunSummary],
        evaluation_id: Optional[str] = None,
    ) -> EvaluationReport:
        """Evaluate aggregated seed runs against hypothesis and produce an EvaluationReport."""
        eval_id = evaluation_id or f"eval-{uuid.uuid4().hex[:8]}"
        seeds = [r.seed for r in seed_runs]
        successful = [r for r in seed_runs if r.exit_code == 0 and r.verification_status == "PASS"]
        failed = [r for r in seed_runs if r not in successful]

        aggregates = self.aggregate_metrics(hypothesis, seed_runs)

        target_agg = aggregates.get(hypothesis.target_metric)
        if len(successful) < 2 or target_agg is None:
            verdict = HypothesisVerdict.INCONCLUSIVE
            rationale = (
                f"Insufficient successful seed runs ({len(successful)}/{len(seed_runs)}) "
                f"to establish statistical confidence for hypothesis '{hypothesis.hypothesis_id}'."
            )
        elif target_agg.passed:
            # Check if hypothesis confirmation is statistically justified (Directive 2 & Golden Rule)
            # Fail closed: if statistical_analysis is missing, assumptions not met, or significance not allowed
            stat_obj = target_agg.statistical_analysis
            if stat_obj is None or not stat_obj.assumptions_met:
                verdict = HypothesisVerdict.INCONCLUSIVE
                reasons = "; ".join(stat_obj.reasons_significance_blocked) if stat_obj else "Missing statistical analysis object"
                rationale = (
                    f"Hypothesis INCONCLUSIVE across {len(successful)} seeds: "
                    f"Statistical assumptions not met for target metric '{hypothesis.target_metric}' "
                    f"(SD={target_agg.std_dev:.4f}, variance={stat_obj.variance if stat_obj else 0.0:.4f}, "
                    f"N={stat_obj.sample_size if stat_obj else 0}). "
                    f"Reasons: {reasons}."
                )
            else:
                verdict = HypothesisVerdict.CONFIRMED
                rationale = (
                    f"Hypothesis CONFIRMED across {len(successful)} seeds: "
                    f"Mean observed {hypothesis.target_metric} = {target_agg.mean} "
                    f"(std_err={target_agg.std_err}) satisfied threshold {target_agg.operator} {target_agg.target_threshold}."
                )
        else:
            verdict = HypothesisVerdict.REFUTED
            rationale = (
                f"Hypothesis REFUTED across {len(successful)} seeds: "
                f"Mean observed {hypothesis.target_metric} = {target_agg.mean} "
                f"(std_err={target_agg.std_err}) failed threshold {target_agg.operator} {target_agg.target_threshold}."
            )

        if target_agg:
            t_status, s_support, r_status = determine_decoupled_verdicts(
                sample_values=target_agg.sample_values,
                mean=target_agg.mean,
                std_dev=target_agg.std_dev,
                target_threshold=target_agg.target_threshold,
                operator=target_agg.operator,
                p_value=target_agg.p_value_estimate,
                significance_allowed=target_agg.significance_claim_allowed,
            )
        else:
            t_status = ThresholdStatus.FAIL
            s_support = StatisticalSupport.INSUFFICIENT
            r_status = ReplicationStatus.SINGLE_POINT

        return EvaluationReport(
            evaluation_id=eval_id,
            hypothesis_id=hypothesis.hypothesis_id,
            spec_id=spec.spec_id,
            seeds_evaluated=seeds,
            total_runs=len(seed_runs),
            successful_runs=len(successful),
            failed_runs=len(failed),
            verdict=verdict,
            threshold_status=t_status,
            statistical_support=s_support,
            replication_status=r_status,
            target_metric=hypothesis.target_metric,
            metric_aggregates=aggregates,
            seed_runs=seed_runs,
            summary_rationale=rationale,
        )

    def execute_multi_seed_evaluation(
        self,
        hypothesis: HypothesisProposal,
        spec: ExperimentSpec,
        simulation_code: str,
        gate_token: HumanGateToken,
        tracker: ExperimentTracker,
        runner: SandboxRunner,
        verifier: DeterministicVerifier,
        seeds: Optional[list[int]] = None,
        base_run_id: Optional[str] = None,
        timeout: int = 60,
    ) -> tuple[EvaluationReport, list[Path]]:
        """Run complete multi-seed simulation battery and produce an EvaluationReport."""
        run_seeds = seeds or spec.random_seeds or [42, 101, 2024]
        actual_base_id = base_run_id or f"multirun-{uuid.uuid4().hex[:8]}"

        seed_run_summaries: list[SeedRunSummary] = []
        run_dirs: list[Path] = []

        print(f"\n=======================================================")
        print(f" Multi-Seed Evaluation Battery (Rules 4 & 16)")
        print(f" Hypothesis: {hypothesis.hypothesis_id} ({hypothesis.title})")
        print(f" Random Seeds: {run_seeds}")
        print(f"=======================================================\n")

        # Pre-flight contract validation (Directive 1)
        from research_os.specs.contracts import verify_spec_contract
        verify_spec_contract(spec=spec, hypothesis=hypothesis)

        # Resolve script filename dynamically from entry_point to prevent desynchronization (Directive 2)
        import shlex
        parts = shlex.split(spec.entry_point, posix=(os.name != "nt"))
        script_filename = "simulation.py"
        for p in parts:
            if p.endswith(".py"):
                script_filename = Path(p).name
                break

        for seed in run_seeds:
            seed_run_id = f"{actual_base_id}-s{seed}"
            actual_seed_id, seed_dir = tracker.init_run(seed_run_id)
            run_dirs.append(seed_dir)

            print(f"[Seed {seed}] Preparing run bundle at {seed_dir.name}...")

            # Prepare seed-specific spec copy
            seed_spec = spec.model_copy(deep=True)
            seed_spec.run_config["seed"] = seed
            tracker.record_spec(actual_seed_id, seed_spec)
            tracker.record_code(actual_seed_id, script_filename, simulation_code)

            # Mint parent-delegated child execution token (Requirement A)
            seed_token = mint_child_delegation_token(
                parent_token=gate_token,
                seed=seed,
                seed_spec=seed_spec,
                seed_code_dir=seed_dir / "code",
                actual_seed_id=actual_seed_id,
                grid_cell_params={},
            )
            tracker.record_approval_token(actual_seed_id, seed_token)

            # Execute
            print(f"[Seed {seed}] Running sandboxed simulation...")
            result = runner.execute(
                spec=seed_spec,
                gate_token=seed_token,
                code_dir=seed_dir / "code",
                output_dir=seed_dir / "output",
                timeout_seconds=timeout,
            )

            # Deterministic Verification
            op = "<=" if hypothesis.expected_direction == "decrease" else ">="
            metric_targets = {
                hypothesis.target_metric: (op, hypothesis.success_threshold)
            }
            v_report = verifier.verify_run(
                spec=seed_spec,
                run_dir=seed_dir / "output",
                exit_code=result.exit_code,
                run_id=actual_seed_id,
                metric_targets=metric_targets,
            )
            tracker.record_verification(actual_seed_id, v_report)
            tracker.generate_manifest(actual_seed_id, spec=seed_spec, report=v_report)

            # Extract metrics
            metrics: dict[str, float] = {}
            metrics_file = seed_dir / "output" / self.metrics_filename
            if metrics_file.exists():
                try:
                    with open(metrics_file, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    metrics = {k: float(v) for k, v in raw.items() if isinstance(v, (int, float))}
                except Exception:
                    pass

            seed_run_summaries.append(
                SeedRunSummary(
                    seed=seed,
                    run_id=actual_seed_id,
                    exit_code=result.exit_code,
                    verification_status=v_report.overall_status.value,
                    metrics=metrics,
                )
            )
            print(f"[Seed {seed}] Completed: exit_code={result.exit_code}, status={v_report.overall_status.value}")

        # Compute aggregate evaluation report
        eval_report = self.evaluate_runs(hypothesis, spec, seed_run_summaries)
        print("\n" + "=" * 68)
        print(f" MULTI-SEED EVALUATION SUMMARY")
        print("=" * 68)
        print(f" Hypothesis ID: {eval_report.hypothesis_id}")
        print(f" Verdict:       {eval_report.verdict.value}")
        print(f" Valid Runs:    {eval_report.successful_runs}/{eval_report.total_runs}")
        if hypothesis.target_metric in eval_report.metric_aggregates:
            m = eval_report.metric_aggregates[hypothesis.target_metric]
            print(f" Target Metric: {m.metric_name} = {m.mean:.2f} ± {m.std_err:.2f} {m.operator} {m.target_threshold}")
        print(f" Rationale:     {eval_report.summary_rationale}")
        print("=" * 68 + "\n")

        return eval_report, run_dirs

    def execute_grid_evaluation(
        self,
        hypothesis: HypothesisProposal,
        spec: ExperimentSpec,
        simulation_code: str,
        gate_token: HumanGateToken,
        tracker: ExperimentTracker,
        runner: SandboxRunner,
        verifier: DeterministicVerifier,
        grid_config: Union[dict[str, Any], Path, str],
        base_run_id: Optional[str] = None,
        timeout: int = 60,
    ) -> tuple[GridEvaluationReport, EvaluationReport, list[Path]]:
        """Run declarative parameter grid ablation sweep and produce a unified GridEvaluationReport."""
        import itertools

        actual_base_id = base_run_id or f"grid-{uuid.uuid4().hex[:8]}"

        # 1. Parse grid configuration
        if isinstance(grid_config, (str, Path)):
            p = Path(grid_config)
            if not p.exists():
                raise FileNotFoundError(f"Grid configuration file not found: {p}")
            text = p.read_text(encoding="utf-8")
            if p.suffix in (".yaml", ".yml"):
                try:
                    import yaml
                    cfg_dict = yaml.safe_load(text) or {}
                except Exception as exc:
                    raise ValueError(f"Failed to parse YAML grid config '{p}': {exc}") from exc
            else:
                cfg_dict = json.loads(text)
        elif isinstance(grid_config, dict):
            cfg_dict = dict(grid_config)
        else:
            raise TypeError(f"Expected dict, str, or Path for grid_config, got {type(grid_config)}")

        # Extract knobs and seeds
        seeds: list[int] = cfg_dict.get("seeds") or spec.random_seeds or [42, 101, 2024]
        if "knobs" in cfg_dict and isinstance(cfg_dict["knobs"], dict):
            knobs = cfg_dict["knobs"]
        else:
            knobs = {k: v for k, v in cfg_dict.items() if k != "seeds" and isinstance(v, list)}

        if not knobs:
            raise ValueError("Grid configuration must define at least one parameter knob with a list of values.")

        knob_names = list(knobs.keys())
        knob_value_lists = [knobs[k] for k in knob_names]
        combos = [
            dict(zip(knob_names, combo_vals))
            for combo_vals in itertools.product(*knob_value_lists)
        ]

        print(f"\n=======================================================")
        print(f" Parametric Stress-Testing Grid Harness (Ablation Sweep)")
        print(f" Hypothesis:     {hypothesis.hypothesis_id} ({hypothesis.title})")
        print(f" Knobs:          {list(knobs.keys())}")
        print(f" Combinations:   {len(combos)} total parameter configurations")
        print(f" Seeds per Combo:{seeds}")
        print(f" Total Runs:     {len(combos) * len(seeds)}")
        print(f"=======================================================\n")

        # Resolve script filename
        import shlex
        parts = shlex.split(spec.entry_point, posix=(os.name != "nt"))
        script_filename = "simulation.py"
        for p_elem in parts:
            if p_elem.endswith(".py"):
                script_filename = Path(p_elem).name
                break

        from research_os.specs.contracts import verify_spec_contract
        verify_spec_contract(spec=spec, hypothesis=hypothesis)

        combination_summaries: list[GridCombinationSummary] = []
        combination_eval_reports: list[EvaluationReport] = []
        all_run_dirs: list[Path] = []

        for combo_idx, params in enumerate(combos):
            combo_id = f"combo-{combo_idx}"
            combo_spec = spec.model_copy(deep=True)
            combo_spec.run_config.update(params)

            combo_summaries: list[SeedRunSummary] = []

            for seed in seeds:
                run_id = f"{actual_base_id}-c{combo_idx}-s{seed}"
                actual_seed_id, seed_dir = tracker.init_run(run_id)
                all_run_dirs.append(seed_dir)

                seed_spec = combo_spec.model_copy(deep=True)
                seed_spec.run_config["seed"] = seed
                tracker.record_spec(actual_seed_id, seed_spec)
                tracker.record_code(actual_seed_id, script_filename, simulation_code)

                # Mint child token bound to combination parameters & seed
                seed_token = mint_child_delegation_token(
                    parent_token=gate_token,
                    seed=seed,
                    seed_spec=seed_spec,
                    seed_code_dir=seed_dir / "code",
                    actual_seed_id=actual_seed_id,
                    grid_cell_params=params,
                )
                tracker.record_approval_token(actual_seed_id, seed_token)

                result = runner.execute(
                    spec=seed_spec,
                    gate_token=seed_token,
                    code_dir=seed_dir / "code",
                    output_dir=seed_dir / "output",
                    timeout_seconds=timeout,
                )

                op = "<=" if hypothesis.expected_direction == "decrease" else ">="
                metric_targets = {
                    hypothesis.target_metric: (op, hypothesis.success_threshold)
                }
                v_report = verifier.verify_run(
                    spec=seed_spec,
                    run_dir=seed_dir / "output",
                    exit_code=result.exit_code,
                    run_id=actual_seed_id,
                    metric_targets=metric_targets,
                )
                tracker.record_verification(actual_seed_id, v_report)
                tracker.generate_manifest(actual_seed_id, spec=seed_spec, report=v_report)

                m_data: dict[str, float] = {}
                m_file = seed_dir / "output" / self.metrics_filename
                if m_file.exists():
                    try:
                        with open(m_file, "r", encoding="utf-8") as f:
                            raw = json.load(f)
                        m_data = {k: float(v) for k, v in raw.items() if isinstance(v, (int, float))}
                    except Exception:
                        pass

                combo_summaries.append(
                    SeedRunSummary(
                        seed=seed,
                        run_id=actual_seed_id,
                        exit_code=result.exit_code,
                        verification_status=v_report.overall_status.value,
                        metrics=m_data,
                    )
                )

            combo_eval = self.evaluate_runs(
                hypothesis=hypothesis,
                spec=combo_spec,
                seed_runs=combo_summaries,
                evaluation_id=f"eval-{actual_base_id}-c{combo_idx}",
            )
            combination_eval_reports.append(combo_eval)

            t_agg = combo_eval.metric_aggregates.get(hypothesis.target_metric)
            mean_target = t_agg.mean if t_agg else 0.0
            sd_target = t_agg.std_dev if t_agg else 0.0
            se_target = t_agg.std_err if t_agg else 0.0
            all_means = {k: agg.mean for k, agg in combo_eval.metric_aggregates.items()}

            combo_summary = GridCombinationSummary(
                combination_id=combo_id,
                parameters=params,
                seeds_evaluated=seeds,
                successful_runs=combo_eval.successful_runs,
                verdict=combo_eval.verdict,
                threshold_status=combo_eval.threshold_status,
                statistical_support=combo_eval.statistical_support,
                replication_status=combo_eval.replication_status,
                mean_target_metric=mean_target,
                std_dev_target_metric=sd_target,
                std_err_target_metric=se_target,
                metric_means=all_means,
                evaluation_report=combo_eval,
            )
            combination_summaries.append(combo_summary)

            print(
                f"[Grid Combo {combo_idx + 1}/{len(combos)}] {params} -> "
                f"{hypothesis.target_metric}={mean_target:.4f} (SE={se_target:.4f}, Verdict={combo_eval.verdict.value})"
            )

        # 4. Determine best configuration
        is_decrease = hypothesis.expected_direction == "decrease"
        if is_decrease:
            best_idx = min(
                range(len(combination_summaries)),
                key=lambda i: combination_summaries[i].mean_target_metric,
            )
        else:
            best_idx = max(
                range(len(combination_summaries)),
                key=lambda i: combination_summaries[i].mean_target_metric,
            )

        best_combo = combination_summaries[best_idx]
        best_eval_report = combination_eval_reports[best_idx]

        grid_report = GridEvaluationReport(
            grid_id=actual_base_id,
            hypothesis_id=hypothesis.hypothesis_id,
            spec_id=spec.spec_id,
            knobs=knobs,
            seeds=seeds,
            total_combinations=len(combos),
            total_runs=len(combos) * len(seeds),
            target_metric=hypothesis.target_metric,
            combinations=combination_summaries,
            best_combination_id=best_combo.combination_id,
            best_parameters=best_combo.parameters,
            best_target_metric_mean=best_combo.mean_target_metric,
        )

        print("\n" + "=" * 68)
        print(f" PARAMETRIC GRID EVALUATION COMPLETE")
        print("=" * 68)
        print(f" Grid ID:         {grid_report.grid_id}")
        print(f" Best Parameters: {grid_report.best_parameters}")
        print(f" Optimal Mean:    {grid_report.best_target_metric_mean:.4f}")
        print("=" * 68 + "\n")

        return grid_report, best_eval_report, all_run_dirs


MultiSeedEvaluator = StatisticalEvaluator

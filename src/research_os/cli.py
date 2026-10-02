"""Command Line Interface for Research OS."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import re
import subprocess
from research_os.domains.base import DomainNotFoundError, UnsupportedDomainError
from research_os.evaluation.evaluator import StatisticalEvaluator
from research_os.gate.approval import HumanApprovalGate
from research_os.harvester.researcher_curator import ResearcherCurator
from research_os.ideation.gap_miner import GapMiner
from research_os.ideation.hypothesis_generator import HypothesisGenerator
from research_os.ingestion.parser import load_paper_fixtures
from research_os.manuscript.compiler import ManuscriptCompiler
from research_os.memory.corpus_updater import CorpusUpdater
from research_os.memory.tracker import ExperimentTracker
from research_os.models import get_model_adapter
from research_os.models.health import check_model_health
from research_os.planning.planner import ExperimentPlanner
from research_os.sandbox.runner import PolicySubprocessRunner, SandboxRunner
from research_os.schemas.evaluation import EvaluationReport, HypothesisVerdict, MetricAggregate, SeedRunSummary
from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.hypothesis import HypothesisProposal
from research_os.schemas.synthesis import CrossPaperSynthesis
from research_os.synthesis.matrix import build_capability_matrix
from research_os.synthesis.synthesizer import LiteratureSynthesizer
from research_os.verify.deterministic import (
    DeterministicVerifier,
    compute_directory_checksums,
)


def run_ingest_and_mine(
    corpus_dir: Union[str, Path],
    topic: str = "Decentralized Coordination & Scaling Under Communication Constraints",
    provider: str = "mock",
    output_base: Union[str, Path] = "experiments/runs",
    run_id: Optional[str] = None,
) -> Path:
    """Execute the end-to-end literature ingestion, synthesis, and hypothesis mining pipeline."""
    actual_run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
    artifacts_dir = Path(output_base) / actual_run_id / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=======================================================")
    print(f" Research OS: Ingest & Mine Pipeline")
    print(f" Run ID:    {actual_run_id}")
    print(f" Corpus:    {corpus_dir}")
    print(f" Provider:  {provider}")
    print(f" Topic:     {topic}")
    print(f"=======================================================\n")

    # Step 1: Ingest & Deduplicate
    print(f"[1/4] Ingesting and deduplicating papers from {corpus_dir}...")
    papers = load_paper_fixtures(corpus_dir)
    if not papers:
        raise ValueError(f"No valid paper documents found in {corpus_dir}")
    print(f"      Ingested {len(papers)} unique papers with section provenance.")

    # Step 2: Capability Matrix
    print(f"[2/4] Building deterministic capability matrix...")
    matrix = build_capability_matrix(papers)
    (artifacts_dir / "capability_matrix.json").write_text(matrix.to_json(), encoding="utf-8")
    (artifacts_dir / "capability_matrix.md").write_text(matrix.to_markdown_table(), encoding="utf-8")
    print(f"      Matrix computed with {len(matrix.rows)} entries.")

    # Step 3: Synthesis
    print(f"[3/4] Synthesizing literature with provider '{provider}'...")
    model = get_model_adapter(provider)
    synthesizer = LiteratureSynthesizer(model)
    synthesis = synthesizer.synthesize_corpus(topic=topic, papers=papers, matrix=matrix)
    (artifacts_dir / "synthesis.json").write_text(synthesis.to_json(), encoding="utf-8")
    print(f"      Synthesis generated: {len(synthesis.consensus_findings)} consensus findings, {len(synthesis.contested_claims)} contested claims.")

    # Step 4: Gap & Hypothesis Mining
    print(f"[4/4] Mining research gaps and formulating falsifiable hypotheses...")
    miner = GapMiner(model)
    gaps = miner.mine_gaps(synthesis, papers)
    (artifacts_dir / "gaps.json").write_text(
        json.dumps([json.loads(g.to_json()) for g in gaps], indent=2), encoding="utf-8"
    )

    hyp_gen = HypothesisGenerator(model)
    hypotheses = hyp_gen.generate_hypotheses(gaps=gaps, papers=papers, matrix=matrix)
    (artifacts_dir / "hypotheses.json").write_text(
        json.dumps([json.loads(h.to_json()) for h in hypotheses], indent=2), encoding="utf-8"
    )
    print(f"      Mined {len(gaps)} research gaps and {len(hypotheses)} falsifiable hypotheses.")

    # Step 5: Manifest with Checksums
    checksums = compute_directory_checksums(artifacts_dir)
    manifest = {
        "run_id": actual_run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "provider": provider,
        "corpus_dir": str(corpus_dir),
        "paper_count": len(papers),
        "gap_count": len(gaps),
        "hypothesis_count": len(hypotheses),
        "artifacts": checksums,
        "status": "COMPLETED",
    }
    (artifacts_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\nPipeline successfully completed! Artifacts written to:")
    print(f" -> {artifacts_dir.resolve().as_posix()}\n")

    return artifacts_dir


def run_check_models(provider: str = "gemini", model_name: Optional[str] = None) -> int:
    """Run model health check smoke test and display formatted status."""
    print(f"\n=======================================================")
    print(f" Research OS: Model Connectivity Health Check")
    print(f" Target Provider: {provider}")
    print(f" Specific Model:  {model_name or 'Default'}")
    print(f"=======================================================\n")

    providers = [provider] if provider != "all" else ["gemini", "mock", "openai", "anthropic", "local"]
    all_ok = True

    for p in providers:
        print(f"Testing connectivity for '{p}'...")
        res = check_model_health(provider=p, model_name=model_name)
        status_symbol = "[OK]" if res.status == "OK" else ("[WARN]" if res.status == "DEGRADED" else "[FAIL]")
        print(f"  Status:       {status_symbol} {res.status}")
        print(f"  Model:        {res.model_name}")
        print(f"  Latency:      {res.latency_ms:.1f} ms")
        print(f"  Text Gen:     {res.text_generation_ok}")
        print(f"  Structured:   {res.structured_generation_ok}")
        print(f"  Details:      {res.message}")
        if res.error:
            print(f"  Diagnostics:  {res.error}")
        print("-" * 55)
        if res.status == "FAILED":
            all_ok = False

    return 0 if all_ok else 1


def run_experiment(
    hypothesis_file: Union[str, Path] = "experiments/runs/test-run-01/artifacts/hypotheses.json",
    hypothesis_id: Optional[str] = None,
    output_base: Union[str, Path] = "experiments/runs",
    run_id: Optional[str] = None,
    approve: bool = False,
    user: Optional[str] = None,
    timeout: int = 60,
    interactive: bool = True,
    seeds: Optional[list[int]] = None,
    evaluate: bool = False,
    update_corpus: bool = True,
    auto_scaffold_plugin: bool = False,
    grid_config: Optional[Union[str, Path]] = None,
) -> Path:
    """Execute end-to-end experiment pipeline: planning, human gate, sandbox execution, and deterministic verification."""
    hyp_path = Path(hypothesis_file)
    if not hyp_path.exists():
        raise FileNotFoundError(f"Hypothesis file not found: {hypothesis_file}")

    with hyp_path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    if isinstance(raw_data, list):
        if not raw_data:
            raise ValueError(f"No hypotheses found in {hypothesis_file}")
        if hypothesis_id:
            matching = [h for h in raw_data if h.get("hypothesis_id") == hypothesis_id]
            if not matching:
                raise ValueError(f"Hypothesis '{hypothesis_id}' not found in {hypothesis_file}")
            target_raw = matching[0]
        else:
            target_raw = raw_data[0]
    elif isinstance(raw_data, dict):
        target_raw = raw_data
    else:
        raise ValueError(f"Invalid format in {hypothesis_file}")

    hypothesis = HypothesisProposal.model_validate(target_raw)

    print(f"\n=======================================================")
    print(f" Research OS: Experiment Execution Pipeline")
    print(f" Hypothesis ID: {hypothesis.hypothesis_id}")
    print(f" Title:         {hypothesis.title}")
    print(f" Output Base:   {output_base}")
    if evaluate or seeds:
        print(f" Mode:          Multi-Seed Statistical Evaluation (Rules 4 & 16)")
    print(f"=======================================================\n")

    # Step 1: Memory & Tracker Initialization
    tracker = ExperimentTracker(base_dir=output_base)
    actual_run_id, run_dir = tracker.init_run(run_id)
    print(f"[1/5] Initialized run directory: {run_dir.resolve().as_posix()}")

    # Step 2: Planning & Code Generation
    print(f"[2/5] Compiling experiment specification and simulation code...")
    planner = ExperimentPlanner()
    try:
        spec, simulation_code = planner.plan_experiment(hypothesis, timeout_seconds=timeout)
    except (UnsupportedDomainError, DomainNotFoundError) as exc:
        domain_name = getattr(hypothesis, "domain", None) or getattr(exc, "domain_id", None)
        if not domain_name:
            for seed in hypothesis.inspired_by_seeds:
                if getattr(seed, "domain", None):
                    domain_name = seed.domain
                    break
        domain_name = domain_name or "unsupported_domain"
        print(f"\n[!] Domain '{domain_name}' is not registered.")

        should_scaffold = auto_scaffold_plugin
        if not should_scaffold and interactive:
            try:
                ans = input("[*] Synthesize a candidate declarative DomainPlugin for this hypothesis? (y/N): ").strip().lower()
                should_scaffold = (ans == "y")
            except (EOFError, KeyboardInterrupt):
                should_scaffold = False

        if should_scaffold:
            from research_os.plugins.staging import synthesize_staged_plugin
            staged_path = synthesize_staged_plugin(domain_id=domain_name, hypothesis=hypothesis)
            print(f"[+] Staged declarative plugin synthesized at: {staged_path.as_posix()}")
            print("\nPlease review the declarative metrics and sign the plugin before re-running:")
            approver_name = user or "Hardik"
            print(f'  research-os gate approve-plugin --staged-dir {staged_path.as_posix()} --approver "{approver_name}"\n')
            return run_dir
        else:
            raise

    if seeds:
        spec.random_seeds = seeds
    tracker.record_spec(actual_run_id, spec)
    (run_dir / "hypothesis.json").write_text(hypothesis.to_json(), encoding="utf-8")

    # Dynamically derive script filename from entry_point (Directive 2)
    import shlex
    parts = shlex.split(spec.entry_point, posix=(sys.platform != "win32"))
    script_fn = "simulation.py"
    for p in parts:
        if p.endswith(".py"):
            script_fn = Path(p).name
            break
    tracker.record_code(actual_run_id, script_fn, simulation_code)
    print(f"      Spec: {spec.spec_id} ({spec.name})")
    print(f"      Code generated: code/{script_fn} ({len(simulation_code.splitlines())} lines)")

    # Pre-Flight Contract Verification (Directive 1)
    from research_os.specs.contracts import verify_spec_contract
    verify_spec_contract(spec=spec, hypothesis=hypothesis, code_dir=run_dir / "code")

    # Step 3: Human Approval Gate (Rule 3)
    print(f"[3/5] Requesting human authorization at approval gate (Rule 3)...")
    gate = HumanApprovalGate()
    token = gate.request_approval(
        spec=spec,
        run_id=actual_run_id,
        user=user,
        auto_approve=approve,
        interactive=interactive,
        token_path=run_dir / "approval_token.json",
        code_dir=run_dir / "code",
    )
    tracker.record_approval_token(actual_run_id, token)

    if not token.is_approved():
        print(f"\n[Gate Error] Execution halted: Gate status is '{token.status}'.")
        print(f"Run state preserved at: {run_dir.resolve().as_posix()}")
        tracker.generate_manifest(
            actual_run_id,
            spec=spec,
            extra_metadata={"status": "ABORTED_AT_GATE", "reason": token.user_notes},
        )
        return run_dir

    # Step 4: Multi-Seed Evaluation or Single Execution
    runner = SandboxRunner(default_timeout_seconds=timeout)
    verifier = DeterministicVerifier(metrics_filename="metrics.json")

    if grid_config:
        print(f"\n[4/5] Running parametric grid ablation sweep via {grid_config}...")
        evaluator = StatisticalEvaluator(metrics_filename="metrics.json")
        grid_report, eval_report, grid_dirs = evaluator.execute_grid_evaluation(
            hypothesis=hypothesis,
            spec=spec,
            simulation_code=simulation_code,
            gate_token=token,
            tracker=tracker,
            runner=runner,
            verifier=verifier,
            grid_config=grid_config,
            base_run_id=actual_run_id,
            timeout=timeout,
        )

        grid_file = run_dir / "grid_evaluation.json"
        grid_file.write_text(grid_report.to_json(), encoding="utf-8")
        eval_file = run_dir / "evaluation.json"
        eval_file.write_text(eval_report.to_json(), encoding="utf-8")

        # Step 5: Research Memory Closed-Loop Feedback
        if update_corpus:
            print(f"[5/5] Updating closed-loop research memory with empirical finding...")
            corpus_updater = CorpusUpdater()
            extraction, memory_file = corpus_updater.record_empirical_finding(
                evaluation=eval_report,
                hypothesis=hypothesis,
                spec=spec,
            )
            print(f"      Empirical finding archived at: {memory_file.resolve().as_posix()}")

        tracker.generate_manifest(
            actual_run_id,
            spec=spec,
            extra_metadata={
                "verdict": eval_report.verdict.value,
                "threshold_status": eval_report.threshold_status.value if eval_report.threshold_status else None,
                "statistical_support": eval_report.statistical_support.value if eval_report.statistical_support else None,
                "replication_status": eval_report.replication_status.value if eval_report.replication_status else None,
                "requested_seeds": spec.random_seeds,
                "successful_seeds": [s.seed for s in eval_report.seed_runs if s.exit_code == 0],
                "grid_id": grid_report.grid_id,
                "best_parameters": grid_report.best_parameters,
                "total_combinations": grid_report.total_combinations,
            },
        )

        # Step 5: Automatically compile publication manuscript (Markdown, LaTeX AST, BibTeX, PDF)
        print(f"[5/5] Compiling publication manuscript with parametric grid ablation analysis...")
        manuscript_pdf_str = "N/A"
        try:
            compiler = ManuscriptCompiler(run_id=actual_run_id, output_dir=run_dir / "manuscript")
            bundle = compiler.compile(
                hypothesis=hypothesis,
                spec=spec,
                evaluation=eval_report,
                grid_evaluation=grid_file,
            )
            print(f"      Manuscript Markdown: {bundle.markdown_path}")
            print(f"      Manuscript LaTeX:    {bundle.latex_path}")
            print(f"      Manuscript BibTeX:   {bundle.bibtex_path}")
            if bundle.pdf_path:
                manuscript_pdf_str = bundle.pdf_path
                print(f"      Manuscript PDF:      {bundle.pdf_path}")
        except Exception as exc:
            print(f"      [!] Warning: Manuscript compilation skipped: {exc}")

        print("\n" + "=" * 68)
        print(f" PARAMETRIC GRID ABLATION RUN COMPLETE")
        print("=" * 68)
        print(f" Run ID:          {actual_run_id}")
        print(f" Verdict:         {eval_report.verdict.value}")
        print(f" Best Parameters: {grid_report.best_parameters}")
        print(f" Grid Evaluation: {grid_file.resolve().as_posix()}")
        print(f" Evaluation Doc:  {eval_file.resolve().as_posix()}")
        if manuscript_pdf_str != "N/A":
            print(f" Manuscript PDF:  {Path(manuscript_pdf_str).resolve().as_posix()}")
        print(f" Run Location:    {run_dir.resolve().as_posix()}")
        print("=" * 68 + "\n")

    elif evaluate or seeds:
        print(f"\n[4/5] Running multi-seed statistical battery across seeds: {spec.random_seeds}...")
        evaluator = StatisticalEvaluator(metrics_filename="metrics.json")
        eval_report, seed_dirs = evaluator.execute_multi_seed_evaluation(
            hypothesis=hypothesis,
            spec=spec,
            simulation_code=simulation_code,
            gate_token=token,
            tracker=tracker,
            runner=runner,
            verifier=verifier,
            seeds=spec.random_seeds,
            base_run_id=actual_run_id,
            timeout=timeout,
        )

        # Record evaluation report in parent run dir
        eval_file = run_dir / "evaluation.json"
        eval_file.write_text(eval_report.to_json(), encoding="utf-8")

        # Step 5: Research Memory Closed-Loop Feedback
        if update_corpus:
            print(f"[5/5] Updating closed-loop research memory with empirical finding...")
            corpus_updater = CorpusUpdater()
            extraction, memory_file = corpus_updater.record_empirical_finding(
                evaluation=eval_report,
                hypothesis=hypothesis,
                spec=spec,
            )
            print(f"      Empirical finding archived at: {memory_file.resolve().as_posix()}")

        tracker.generate_manifest(
            actual_run_id,
            spec=spec,
            extra_metadata={
                "verdict": eval_report.verdict.value,
                "threshold_status": eval_report.threshold_status.value if eval_report.threshold_status else None,
                "statistical_support": eval_report.statistical_support.value if eval_report.statistical_support else None,
                "replication_status": eval_report.replication_status.value if eval_report.replication_status else None,
                "requested_seeds": spec.random_seeds,
                "successful_seeds": [s.seed for s in eval_report.seed_runs if s.exit_code == 0],
                "seeds_evaluated": eval_report.seeds_evaluated,
                "successful_runs": eval_report.successful_runs,
            },
        )

        # Step 5: Automatically compile publication manuscript (Markdown, LaTeX AST, BibTeX, PDF)
        print(f"[5/5] Compiling publication manuscript (Markdown, LaTeX AST, BibTeX, PDF)...")
        manuscript_pdf_str = "N/A"
        try:
            compiler = ManuscriptCompiler(run_id=actual_run_id, output_dir=run_dir / "manuscript")
            bundle = compiler.compile(
                hypothesis=hypothesis,
                spec=spec,
                evaluation=eval_report,
            )
            print(f"      Manuscript Markdown: {bundle.markdown_path}")
            print(f"      Manuscript LaTeX:    {bundle.latex_path}")
            print(f"      Manuscript BibTeX:   {bundle.bibtex_path}")
            if bundle.pdf_path:
                manuscript_pdf_str = bundle.pdf_path
                print(f"      Manuscript PDF:      {bundle.pdf_path}")
        except Exception as exc:
            print(f"      [!] Warning: Manuscript compilation skipped: {exc}")

        print("\n" + "=" * 68)
        print(f" MULTI-SEED EVALUATION RUN COMPLETE")
        print("=" * 68)
        print(f" Run ID:          {actual_run_id}")
        print(f" Verdict:         {eval_report.verdict.value}")
        print(f" Seeds:           {eval_report.seeds_evaluated}")
        print(f" Evaluation Doc:  {eval_file.resolve().as_posix()}")
        if manuscript_pdf_str != "N/A":
            print(f" Manuscript PDF:  {Path(manuscript_pdf_str).resolve().as_posix()}")
        print(f" Run Location:    {run_dir.resolve().as_posix()}")
        print("=" * 68 + "\n")

    else:
        print(f"\n[4/5] Executing simulation in restricted sandbox (timeout={timeout}s)...")
        exec_result = runner.execute(
            spec=spec,
            gate_token=token,
            code_dir=run_dir / "code",
            output_dir=run_dir / "output",
            timeout_seconds=timeout,
        )
        print(f"      Process Exit Code: {exec_result.exit_code}")
        print(f"      Execution Duration: {exec_result.duration_seconds}s")
        if exec_result.timed_out:
            print(f"      [WARNING] Subprocess timed out!")

        # Step 5: Deterministic Verification & Bookkeeping (Rule 6, 4, 5)
        print(f"[5/5] Running deterministic verification checks (Rule 6)...")
        op = "<=" if hypothesis.expected_direction == "decrease" else ">="
        metric_targets = {
            hypothesis.target_metric: (op, hypothesis.success_threshold)
        }

        report = verifier.verify_run(
            spec=spec,
            run_dir=run_dir / "output",
            exit_code=exec_result.exit_code,
            run_id=actual_run_id,
            metric_targets=metric_targets,
        )
        tracker.record_verification(actual_run_id, report)

        manifest = tracker.generate_manifest(
            actual_run_id,
            spec=spec,
            report=report,
            extra_metadata={
                "duration_seconds": exec_result.duration_seconds,
                "timed_out": exec_result.timed_out,
            },
        )

        print("\n" + "=" * 68)
        print(f" EXPERIMENT RUN VERIFICATION SUMMARY")
        print("=" * 68)
        print(f" Run ID:              {actual_run_id}")
        print(f" Verification Status: {report.overall_status.value}")
        print(f" Exit Code Check:     {'PASS' if report.exit_code_passed else 'FAIL'}")
        print(f" Schema Compliance:   {'PASS' if report.schema_compliance else 'FAIL'}")
        for mev in report.metric_evaluations:
            m_status = "PASS" if mev.passed else "FAIL"
            print(f" Metric [{mev.metric_name}]: {m_status} (Observed {mev.observed_value} {mev.operator} {mev.target_threshold})")
        print(f" Artifact Count:      {len(manifest.get('artifacts', {}))} files verified")
        print(f" Location:            {run_dir.resolve().as_posix()}")
        print("=" * 68 + "\n")

    return run_dir


def run_harvest(
    topic: str,
    domain: Optional[str] = None,
    include_legacy: bool = True,
    include_frontier: bool = True,
    max_papers: int = 20,
    output_dir: Optional[str] = None,
) -> None:
    """Execute dual-horizon academic harvesting with bias mitigation."""
    clean_domain = domain or re.sub(r"[^a-zA-Z0-9_]", "_", topic.lower())[:24].strip("_")
    curator = ResearcherCurator()
    half = max(1, max_papers // 2)
    max_legacy = half if include_legacy else 0
    max_frontier = (max_papers - max_legacy) if include_frontier else 0

    print(f"\n=======================================================")
    print(f" Research OS: Academic Literature Harvester")
    print(f" Topic:            {topic}")
    print(f" Domain:           {clean_domain}")
    print(f" Legacy Target:    {max_legacy}")
    print(f" Frontier Target:  {max_frontier}")
    print(f"=======================================================\n")

    corpus = curator.harvest(
        topic=topic,
        domain=clean_domain,
        max_legacy=max_legacy,
        max_frontier=max_frontier,
        output_dir=output_dir,
    )

    print(f"Harvest completed successfully!")
    print(f"Total Papers Ingested: {corpus.total_papers}")
    print(f"Corpus Manifest:       {corpus.manifest_path}")
    print("\nTop Principal Investigators Identified (Bias Mitigation):")
    for pi in corpus.top_pis:
        print(f" - {pi.name} (h-index: {pi.h_index}, velocity: {pi.citation_velocity}, score: {pi.composite_score})")
    print(f"\nLegacy Foundationals: {len(corpus.legacy_foundationals)}")
    for p in corpus.legacy_foundationals:
        print(f" - [{p.metadata.year}] {p.metadata.title} (citations: {p.metadata.citation_count})")
    print(f"\nFrontier Horizon: {len(corpus.frontier_horizon)}")
    for p in corpus.frontier_horizon:
        print(f" - [{p.metadata.year}] {p.metadata.title} (arXiv: {p.metadata.arxiv_id or 'N/A'})")


def run_compile_manuscript(
    run_id: str,
    output_dir: Optional[str] = None,
    base_runs_dir: Union[str, Path] = "experiments/runs",
) -> Path:
    """Compile paper.md, paper.tex, and references.bib from an experiment run."""
    run_path = Path(base_runs_dir) / run_id
    if not run_path.exists():
        raise FileNotFoundError(f"Run directory not found: {run_path}")

    # Load spec
    spec_path = run_path / "spec.json"
    if not spec_path.exists():
        spec_path = run_path / "artifacts" / "spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"ExperimentSpec artifact not found in {run_path}")
    spec = ExperimentSpec.from_json(spec_path.read_text(encoding="utf-8"))

    # Load hypothesis
    hyp_path = run_path / "hypothesis.json"
    if hyp_path.exists():
        hyp = HypothesisProposal.from_json(hyp_path.read_text(encoding="utf-8"))
    else:
        hyp = HypothesisProposal(
            hypothesis_id=spec.hypothesis_id,
            title=spec.name,
            falsifiable_statement=f"Operationalizing {spec.name} improves target metrics within verified bounds.",
            baseline_method="Standard Default Baseline",
            proposed_mechanism=spec.name,
            theoretical_rationale="Empirical operationalization protocol grounded in domain principles.",
            target_metric="verification_score",
            expected_direction="increase",
            success_threshold=0.8,
        )

    # Load evaluation report
    eval_path = run_path / "evaluation.json"
    if eval_path.exists():
        evaluation = EvaluationReport.from_json(eval_path.read_text(encoding="utf-8"))
    else:
        # Check if child seed runs exist under parent directory
        child_dirs = sorted([d for d in run_path.parent.glob(f"{run_id}-s*") if d.is_dir()])
        child_runs: list[SeedRunSummary] = []
        for cdir in child_dirs:
            seed_val_str = cdir.name.split("-s")[-1]
            try:
                s_int = int(seed_val_str)
            except ValueError:
                continue
            m_path = cdir / "output" / "metrics.json"
            c_metrics = {}
            if m_path.exists():
                try:
                    c_metrics = json.loads(m_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            child_runs.append(
                SeedRunSummary(
                    seed=s_int,
                    run_id=cdir.name,
                    exit_code=0,
                    verification_status="PASS",
                    metrics=c_metrics,
                )
            )

        if child_runs and len(child_runs) >= 2:
            evaluator = StatisticalEvaluator(metrics_filename="metrics.json")
            evaluation = evaluator.evaluate_runs(hyp, spec, child_runs, evaluation_id=f"eval_{run_id}")
            eval_path.write_text(evaluation.to_json(), encoding="utf-8")
        else:
            metrics_path = run_path / "output" / "metrics.json"
            if not metrics_path.exists():
                metrics_path = run_path / "metrics.json"
            metrics_dict = {}
            if metrics_path.exists():
                metrics_dict = json.loads(metrics_path.read_text(encoding="utf-8"))
            
            single_seed = spec.run_config.get("seed", 42)
            aggregates = {}
            for k, v in metrics_dict.items():
                if isinstance(v, (int, float)):
                    aggregates[k] = MetricAggregate(
                        metric_name=k,
                        sample_values=[float(v)],
                        mean=float(v),
                        std_dev=0.0,
                        std_err=0.0,
                        target_threshold=0.0,
                        operator=">=",
                        passed=True,
                    )
            evaluation = EvaluationReport(
                evaluation_id=f"eval_{run_id}",
                hypothesis_id=hyp.hypothesis_id,
                spec_id=spec.spec_id,
                seeds_evaluated=[single_seed],
                total_runs=1,
                successful_runs=1,
                failed_runs=0,
                verdict=HypothesisVerdict.INCONCLUSIVE,
                target_metric=list(metrics_dict.keys())[0] if metrics_dict else "primary_metric",
                metric_aggregates=aggregates,
                seed_runs=[
                    SeedRunSummary(seed=single_seed, run_id=run_id, exit_code=0, verification_status="PASS", metrics=metrics_dict)
                ],
                summary_rationale="Single execution run evaluated (N=1); multi-seed inferential hypothesis testing inconclusive.",
            )

    # Load synthesis if available
    synthesis = None
    synth_path = run_path / "artifacts" / "synthesis.json"
    if synth_path.exists():
        synthesis = CrossPaperSynthesis.from_json(synth_path.read_text(encoding="utf-8"))

    manifest_data = None
    manifest_candidates = [
        run_path / "verified_execution_manifest.json",
        run_path / "artifacts" / "verified_execution_manifest.json",
        run_path / "manifest.json",
    ]
    for m_cand in manifest_candidates:
        if m_cand.exists():
            try:
                manifest_data = json.loads(m_cand.read_text(encoding="utf-8"))
                break
            except Exception:
                pass

    compiler = ManuscriptCompiler(run_id=run_id, output_dir=output_dir)
    try:
        bundle = compiler.compile(
            hypothesis=hyp,
            spec=spec,
            evaluation=evaluation,
            synthesis=synthesis,
            execution_manifest=manifest_data,
        )
    except Exception as exc:
        err_code, hint = PolicySubprocessRunner._diagnose_exception(exc)
        PolicySubprocessRunner.write_error_payload(
            run_path / "output",
            error_code=err_code,
            stage="MANUSCRIPT_COMPILATION",
            message=str(exc),
            hint=hint,
            details={"run_id": run_id, "exception_type": type(exc).__name__},
        )
        PolicySubprocessRunner.emit_event(
            run_path / "output",
            stage="MANUSCRIPT_COMPILATION",
            status="FAILED",
            code=err_code,
            details={"error": str(exc), "remediation_hint": hint},
        )
        raise

    print(f"\n=======================================================")
    print(f" Research OS: Manuscript Compilation Complete")
    print(f" Run ID:        {run_id}")
    print(f" Title:         {bundle.title}")
    print(f" Markdown:      {bundle.markdown_path}")
    print(f" LaTeX:         {bundle.latex_path}")
    print(f" BibTeX:        {bundle.bibtex_path}")
    if bundle.pdf_path:
        print(f" PDF:           {bundle.pdf_path}")
    print(f" Word Count:    ~{bundle.word_count} words")
    print(f"=======================================================\n")
    return Path(bundle.markdown_path)


def run_dashboard(port: int = 8501, host: str = "localhost") -> None:
    """Launch interactive Streamlit Control Dashboard."""
    app_path = Path(__file__).parent / "dashboard" / "app.py"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(port),
        "--server.address",
        host,
    ]
    print(f"Starting Research OS Control Dashboard on http://{host}:{port}...")
    subprocess.run(cmd)


def run_gate_generate_keys(env_export: bool = False, file_path: Optional[str] = None) -> None:
    """Generate Ed25519 keypair and output as environment exports or file."""
    from research_os.gate.approval import generate_ed25519_keypair

    b64_seed, pub_hex = generate_ed25519_keypair()

    if env_export:
        print(f"export RESEARCH_OS_GATE_PRIVATE_KEY={b64_seed}")
        print(f"export RESEARCH_OS_GATE_PUBLIC_KEY={pub_hex}")
    elif file_path:
        out_p = Path(file_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        import base64
        out_p.write_bytes(base64.b64decode(b64_seed))
        try:
            if sys.platform != "win32":
                os.chmod(out_p, 0o600)
        except Exception:
            pass
        print(f"Private key saved to {out_p}")
    else:
        print("Generated Ed25519 Keypair:")
        print(f"RESEARCH_OS_GATE_PRIVATE_KEY={b64_seed}")
        print(f"RESEARCH_OS_GATE_PUBLIC_KEY={pub_hex}")


def run_gate_approve_plugin(
    staged_dir: str,
    approver: str = "Operator",
    key_path: Optional[str] = None,
) -> None:
    """Cryptographically sign a staged domain plugin with Ed25519 signature."""
    from research_os.gate.plugin_approval import create_plugin_approval_token
    from research_os.gate.approval import LocalFileKeyBackend

    priv_key = None
    if key_path:
        priv_key = LocalFileKeyBackend(key_path).get_private_key()

    token = create_plugin_approval_token(
        staged_dir=staged_dir,
        approver_identity=approver,
        private_key=priv_key,
    )
    print(f"\n=======================================================")
    print(f" Research OS: Domain Plugin Cryptographically Approved")
    print(f" Domain ID:        {token.domain_id}")
    print(f" Approver:         {token.approver_identity}")
    print(f" Canonical Hash:   {token.canonical_plugin_hash}")
    print(f" Public Key:       {token.public_key_hex}")
    print(f" Token Path:       {Path(staged_dir) / 'plugin_approval.token'}")
    print(f"=======================================================\n")



def main() -> None:
    """CLI entry point for research-os."""
    parser = argparse.ArgumentParser(
        prog="research-os",
        description="Research OS: Turn scientific literature into verified research experiments.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: ingest-and-mine
    mine_parser = subparsers.add_parser(
        "ingest-and-mine",
        help="Ingest papers, build capability matrix, synthesize literature, and mine falsifiable hypotheses.",
    )
    mine_parser.add_argument(
        "--corpus-dir",
        required=True,
        type=str,
        help="Path to directory containing paper files (.json, .md, .txt, .pdf)",
    )
    mine_parser.add_argument(
        "--topic",
        default="Decentralized Coordination & Scaling Under Communication Constraints",
        type=str,
        help="Research domain or thematic query",
    )
    mine_parser.add_argument(
        "--provider",
        default="mock",
        type=str,
        choices=["mock", "openai", "anthropic", "gemini", "local"],
        help="Model provider to use (default: mock)",
    )
    mine_parser.add_argument(
        "--output-dir",
        default="experiments/runs",
        type=str,
        help="Base directory for storing run outputs (default: experiments/runs)",
    )
    mine_parser.add_argument(
        "--run-id",
        default=None,
        type=str,
        help="Optional custom run ID",
    )

    # Subcommand: check-models
    check_parser = subparsers.add_parser(
        "check-models",
        help="Check connectivity and authentication health against model providers.",
    )
    check_parser.add_argument(
        "--provider",
        default="gemini",
        type=str,
        help="Model provider to test ('gemini', 'mock', 'openai', 'anthropic', 'local', or 'all')",
    )
    check_parser.add_argument(
        "--model-name",
        default=None,
        type=str,
        help="Specific model name to test (e.g. 'gemini-3.5-flash', 'gemini-3.5-flash-lite')",
    )

    # Subcommand: run-experiment
    exp_parser = subparsers.add_parser(
        "run-experiment",
        help="Plan, gate, execute, and verify an empirical simulation experiment from a hypothesis.",
    )
    exp_parser.add_argument(
        "--hypothesis-file",
        default="experiments/runs/test-run-01/artifacts/hypotheses.json",
        type=str,
        help="Path to JSON file containing hypotheses",
    )
    exp_parser.add_argument(
        "--hypothesis-id",
        default=None,
        type=str,
        help="Hypothesis ID to execute (defaults to first hypothesis)",
    )
    exp_parser.add_argument(
        "--output-dir",
        default="experiments/runs",
        type=str,
        help="Base directory for storing experiment runs",
    )
    exp_parser.add_argument(
        "--run-id",
        default=None,
        type=str,
        help="Custom run ID for the experiment run",
    )
    exp_parser.add_argument(
        "--approve",
        action="store_true",
        help="Explicitly pre-authorize execution at human approval gate (Rule 3)",
    )
    exp_parser.add_argument(
        "--user",
        default=None,
        type=str,
        help="Human operator identity for approval token signature",
    )
    exp_parser.add_argument(
        "--timeout",
        default=60,
        type=int,
        help="Hard timeout limit in seconds for sandboxed execution",
    )
    exp_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run without interactive prompts (requires --approve or existing token)",
    )
    exp_parser.add_argument(
        "--seeds",
        default=None,
        type=str,
        help="Comma-separated random seeds (e.g. '42,101,2024') for multi-seed statistical evaluation",
    )
    exp_parser.add_argument(
        "--evaluate",
        action="store_true",
        help="Run multi-seed statistical evaluation battery (Rules 4 & 16)",
    )
    exp_parser.add_argument(
        "--no-corpus-update",
        action="store_true",
        help="Skip recording empirical finding into research memory corpus",
    )
    exp_parser.add_argument(
        "--auto-scaffold-plugin",
        action="store_true",
        help="Automatically synthesize a candidate declarative DomainPlugin if domain is unregistered",
    )
    exp_parser.add_argument(
        "--grid-config",
        default=None,
        type=str,
        help="Path to YAML or JSON parameter grid configuration for ablation sweep",
    )

    # Subcommand: harvest
    harvest_parser = subparsers.add_parser(
        "harvest",
        help="Harvest academic literature using arXiv, Google Scholar, and OpenAlex with bias mitigation.",
    )
    harvest_parser.add_argument(
        "--topic",
        required=True,
        type=str,
        help="Research topic or query string to harvest",
    )
    harvest_parser.add_argument(
        "--domain",
        default=None,
        type=str,
        help="Target domain identifier (defaults to sanitized topic name)",
    )
    harvest_parser.add_argument(
        "--include-legacy",
        action="store_true",
        default=True,
        help="Include foundational landmark papers (>5 years old)",
    )
    harvest_parser.add_argument(
        "--include-frontier",
        action="store_true",
        default=True,
        help="Include recent preprints and frontier papers (12-24 months old)",
    )
    harvest_parser.add_argument(
        "--max-papers",
        default=20,
        type=int,
        help="Maximum total papers to harvest across horizons",
    )
    harvest_parser.add_argument(
        "--output-dir",
        default=None,
        type=str,
        help="Custom destination directory (defaults to data/corpus/<domain>)",
    )

    # Subcommand: compile-manuscript
    compile_parser = subparsers.add_parser(
        "compile-manuscript",
        help="Compile paper.md, publication-ready paper.tex, and references.bib from an experiment run.",
    )
    compile_parser.add_argument(
        "--run-id",
        required=True,
        type=str,
        help="Experiment run ID to compile manuscript for",
    )
    compile_parser.add_argument(
        "--output-dir",
        default=None,
        type=str,
        help="Output directory for compiled paper (defaults to experiments/runs/<run_id>/manuscript)",
    )

    # Subcommand: dashboard
    dash_parser = subparsers.add_parser(
        "dashboard",
        help="Launch the interactive Research OS Control Dashboard.",
    )
    dash_parser.add_argument(
        "--port",
        default=8501,
        type=int,
        help="Dashboard web server port (default 8501)",
    )
    dash_parser.add_argument(
        "--host",
        default="localhost",
        type=str,
        help="Dashboard web server host (default localhost)",
    )

    # Subcommand: gate
    gate_parser = subparsers.add_parser(
        "gate",
        help="Manage Human Approval Gate cryptographic keys and tokens.",
    )
    gate_subparsers = gate_parser.add_subparsers(dest="gate_action", required=True)
    gen_keys_parser = gate_subparsers.add_parser(
        "generate-keys",
        help="Generate Ed25519 signing and verification keypairs.",
    )
    gen_keys_parser.add_argument(
        "--env-export",
        action="store_true",
        help="Output keys formatted as environment variable export commands for CI/CD pipelines.",
    )
    gen_keys_parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Optional file path to persist the private key (defaults to standard .gate_key if not --env-export).",
    )
    approve_plugin_parser = gate_subparsers.add_parser(
        "approve-plugin",
        help="Cryptographically approve and sign a staged declarative domain plugin.",
    )
    approve_plugin_parser.add_argument(
        "--staged-dir",
        required=True,
        type=str,
        help="Path to staged plugin directory containing plugin.json, generator.py, and manifest.json",
    )
    approve_plugin_parser.add_argument(
        "--approver",
        default="Operator",
        type=str,
        help="Human approver identifier",
    )
    approve_plugin_parser.add_argument(
        "--key",
        default=None,
        type=str,
        help="Optional path to private key file",
    )

    args = parser.parse_args()

    if args.command == "ingest-and-mine":
        try:
            run_ingest_and_mine(
                corpus_dir=args.corpus_dir,
                topic=args.topic,
                provider=args.provider,
                output_base=args.output_dir,
                run_id=args.run_id,
            )
        except Exception as e:
            print(f"Error during execution: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "check-models":
        code = run_check_models(provider=args.provider, model_name=args.model_name)
        sys.exit(code)

    elif args.command == "run-experiment":
        seeds_list = None
        if args.seeds:
            try:
                seeds_list = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
            except ValueError:
                print(f"Invalid seeds format '{args.seeds}'. Must be comma-separated integers.", file=sys.stderr)
                sys.exit(1)

        try:
            run_experiment(
                hypothesis_file=args.hypothesis_file,
                hypothesis_id=args.hypothesis_id,
                output_base=args.output_dir,
                run_id=args.run_id,
                approve=args.approve,
                user=args.user,
                timeout=args.timeout,
                interactive=not args.non_interactive,
                seeds=seeds_list,
                evaluate=args.evaluate or (seeds_list is not None and len(seeds_list) > 1),
                update_corpus=not args.no_corpus_update,
                auto_scaffold_plugin=args.auto_scaffold_plugin,
                grid_config=args.grid_config,
            )
        except Exception as e:
            err_code, hint = PolicySubprocessRunner._diagnose_exception(e)
            print(f"\n[FATAL ERROR] {err_code}: {e}", file=sys.stderr)
            print(f"[REMEDIATION HINT] {hint}\n", file=sys.stderr)
            sys.exit(1)

    elif args.command == "harvest":
        try:
            run_harvest(
                topic=args.topic,
                domain=args.domain,
                include_legacy=args.include_legacy,
                include_frontier=args.include_frontier,
                max_papers=args.max_papers,
                output_dir=args.output_dir,
            )
        except Exception as e:
            print(f"Error during literature harvest: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "compile-manuscript":
        try:
            run_compile_manuscript(
                run_id=args.run_id,
                output_dir=args.output_dir,
            )
        except Exception as e:
            err_code, hint = PolicySubprocessRunner._diagnose_exception(e)
            print(f"\n[FATAL ERROR] {err_code}: {e}", file=sys.stderr)
            print(f"[REMEDIATION HINT] {hint}\n", file=sys.stderr)
            sys.exit(1)

    elif args.command == "dashboard":
        try:
            run_dashboard(
                port=args.port,
                host=args.host,
            )
        except Exception as e:
            print(f"Error starting dashboard: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "gate":
        try:
            if args.gate_action == "generate-keys":
                run_gate_generate_keys(env_export=args.env_export, file_path=args.file)
            elif args.gate_action == "approve-plugin":
                run_gate_approve_plugin(
                    staged_dir=args.staged_dir,
                    approver=args.approver,
                    key_path=args.key,
                )
        except Exception as e:
            print(f"Error in gate command: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()

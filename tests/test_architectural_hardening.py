"""Comprehensive Test Suite for Core Architectural Hardening & Scientific Integrity (Directives 1-4).

Validates:
- Directive 1: Strong-Typed Metric & Spec Contracts (Catalog, ValueWithUnit, SpecContractValidationError).
- Directive 2: Artifact-Driven Pre-Flight Entry-Point Verification (EntrypointResolutionError, SHA-256, disk integrity).
- Directive 3: Experiment Classification & Epistemic Honesty Gate (ExperimentClass, ScientificIntegrityLinter, SD == 0.0 significance blocks).
- Directive 4: Robust Manuscript AST & Asset Path Resolver (LatexDocument AST, escaping <=, >=, _, %, figure path resolution).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from research_os.core.classification import ExperimentClass
from research_os.core.integrity import (
    EpistemicHonestyViolation,
    ScientificIntegrityLinter,
)
from research_os.evaluation.evaluator import StatisticalEvaluator
from research_os.manuscript.compiler import ManuscriptCompiler
from research_os.manuscript.latex_ast import (
    LatexCommand,
    LatexDocument,
    LatexEnvironment,
    LatexFigure,
    LatexRaw,
    LatexTable,
    LatexText,
    escape_latex,
    resolve_figure_path,
)
from research_os.sandbox.runner import (
    EntrypointResolutionError,
    PolicySubprocessRunner,
)
from research_os.schemas.evaluation import (
    EvaluationReport,
    HypothesisVerdict,
    MetricAggregate,
    SeedRunSummary,
)
from research_os.schemas.experiment import (
    ExperimentSpec,
    ExperimentType,
    HardwareRequirements,
)
from research_os.schemas.hypothesis import HypothesisProposal
from research_os.specs.catalog import MetricCatalog, MetricDefinition
from research_os.specs.contracts import (
    RunnerIntrospection,
    SpecContractValidationError,
    introspect_runner_contract,
    verify_spec_contract,
)
from research_os.specs.units import UnitType, ValueWithUnit


# ==============================================================================
# DIRECTIVE 1: STRONG-TYPED METRIC & SPEC CONTRACTS
# ==============================================================================


def test_metric_catalog_and_definition():
    """Directive 1: MetricCatalog validates standard metrics and directionality."""
    metric = MetricCatalog.get("recall_at_k")
    assert metric.name == "recall_at_k"
    assert metric.unit == UnitType.FRACTION
    assert metric.min_value == 0.0
    assert metric.max_value == 1.0

    # Test custom registered metric
    custom = MetricDefinition(
        metric_name="custom_latency",
        canonical_unit=UnitType.MILLISECONDS,
        min_value=0.0,
    )
    MetricCatalog.register(custom)
    assert MetricCatalog.get("custom_latency").unit == UnitType.MILLISECONDS
    assert MetricCatalog.get("custom_latency").name == "custom_latency"


def test_unit_conversion_percentage_to_fraction():
    """Directive 1: ValueWithUnit auto-normalizes Percentage [0, 100] to Fraction [0, 1]."""
    # Case study bug: passing 50.0 as percentage into a validator expecting 0.50 fraction
    val = ValueWithUnit(raw_value=50.0, unit=UnitType.PERCENTAGE)
    assert val.raw_value == 50.0
    assert val.canonical_value == 0.50
    assert val.canonical_unit == UnitType.FRACTION
    assert val.as_fraction() == 0.50

    # Standard fraction stays identical
    frac = ValueWithUnit(raw_value=0.75, unit=UnitType.FRACTION)
    assert frac.canonical_value == 0.75
    assert frac.as_fraction() == 0.75

    # Milliseconds to seconds
    ms = ValueWithUnit(raw_value=250.0, unit=UnitType.MILLISECONDS)
    assert ms.canonical_value == 0.25
    assert ms.canonical_unit == UnitType.SECONDS

    # Megabytes to bytes
    mb = ValueWithUnit(raw_value=10.0, unit=UnitType.MEGABYTES)
    assert mb.canonical_value == 10.0 * 1024 * 1024
    assert mb.canonical_unit == UnitType.BYTES

    # Negative percentage rejected
    with pytest.raises(ValueError):
        ValueWithUnit(raw_value=-5.0, unit=UnitType.PERCENTAGE)


def test_spec_contract_validation_positive(tmp_path: Path):
    """Directive 1 Positive: Spec matching runner declared outputs succeeds contract validation."""
    runner_script = tmp_path / "run_benchmark.py"
    code = """
import sys, json

if "--describe" in sys.argv:
    print(json.dumps({
        "supported_metrics": ["hallucination_rate", "accuracy"],
        "declared_outputs": ["metrics.json", "provenance.json"]
    }))
    sys.exit(0)

# Main execution
metrics = {"hallucination_rate": 0.15, "accuracy": 0.85}
with open("metrics.json", "w") as f:
    json.dump(metrics, f)
"""
    runner_script.write_text(code.strip(), encoding="utf-8")

    spec = ExperimentSpec(
        spec_id="spec-contract-01",
        hypothesis_id="hyp-01",
        experiment_type=ExperimentType.BENCHMARK,
        name="Contract Validation Test",
        description="Testing contract match",
        entry_point="python run_benchmark.py",
        run_config={"target_metric": "hallucination_rate"},
        dependencies=[],
        random_seeds=[42],
        expected_outputs=["metrics.json"],
        timeout_seconds=30,
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0, max_cpu_cores=1),
    )

    intro = introspect_runner_contract(code_dir=tmp_path, entry_point=spec.entry_point)
    assert "hallucination_rate" in intro.supported_metrics

    # Validates cleanly without raising
    verify_spec_contract(spec=spec, code_dir=tmp_path)


def test_spec_contract_validation_negative_mismatch(tmp_path: Path):
    """Directive 1 Negative: Spec declaring target_metric 'recall_at_k' rejected if runner emits 'hallucination_rate'."""
    runner_script = tmp_path / "simulation.py"
    code = """
import sys, json

if "--describe" in sys.argv:
    print(json.dumps({
        "supported_metrics": ["hallucination_rate"],
        "declared_outputs": ["metrics.json"]
    }))
    sys.exit(0)
"""
    runner_script.write_text(code.strip(), encoding="utf-8")

    # Spec expects 'recall_at_k'
    spec = ExperimentSpec(
        spec_id="spec-contract-mismatch",
        hypothesis_id="hyp-01",
        experiment_type=ExperimentType.BENCHMARK,
        name="Contract Mismatch Test",
        description="Mismatched metric spec",
        entry_point="python simulation.py",
        run_config={"target_metric": "recall_at_k"},
        dependencies=[],
        random_seeds=[42],
        expected_outputs=["metrics.json"],
        timeout_seconds=30,
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0, max_cpu_cores=1),
    )

    with pytest.raises(SpecContractValidationError) as exc_info:
        verify_spec_contract(spec=spec, code_dir=tmp_path)

    assert "recall_at_k" in str(exc_info.value)
    assert "hallucination_rate" in str(exc_info.value)


# ==============================================================================
# DIRECTIVE 2: ARTIFACT-DRIVEN PRE-FLIGHT ENTRY-POINT VERIFICATION
# ==============================================================================


def test_preflight_entrypoint_missing_file_rejected(tmp_path: Path):
    """Directive 2 Negative: Missing entrypoint file (desynchronization) is rejected prior to subprocess spawn."""
    runner = PolicySubprocessRunner()
    code_dir = tmp_path / "code"
    code_dir.mkdir()

    # File on disk is 'actual_script.py', but spec demands 'run_benchmark.py'
    (code_dir / "actual_script.py").write_text("print('hello')", encoding="utf-8")

    with pytest.raises(EntrypointResolutionError) as exc_info:
        runner.verify_entrypoint_preflight(
            entry_point="python run_benchmark.py --config config.json",
            code_dir=code_dir,
        )

    assert "run_benchmark.py" in str(exc_info.value)
    assert "does not exist on disk" in str(exc_info.value)


def test_preflight_entrypoint_sha256_integrity_positive_and_negative(tmp_path: Path):
    """Directive 2: Confirms SHA-256 pre-flight integrity verification."""
    runner = PolicySubprocessRunner()
    code_dir = tmp_path / "code"
    code_dir.mkdir()

    script = code_dir / "verified_benchmark.py"
    script.write_text("import sys\nprint('verified')", encoding="utf-8")

    import hashlib
    correct_hash = hashlib.sha256(script.read_bytes()).hexdigest()
    wrong_hash = "0" * 64

    # Positive test: correct hash passes
    resolved = runner.verify_entrypoint_preflight(
        entry_point="python verified_benchmark.py",
        code_dir=code_dir,
        expected_sha256=correct_hash,
    )
    assert resolved == script.resolve()

    # Negative test: corrupted hash rejected before execution
    with pytest.raises(EntrypointResolutionError) as exc_info:
        runner.verify_entrypoint_preflight(
            entry_point="python verified_benchmark.py",
            code_dir=code_dir,
            expected_sha256=wrong_hash,
        )
    assert "SHA-256 mismatch" in str(exc_info.value)


# ==============================================================================
# DIRECTIVE 3: EXPERIMENT CLASSIFICATION & EPISTEMIC HONESTY GATE
# ==============================================================================


def test_experiment_classification_enum_and_auto_inference():
    """Directive 3: ExperimentClass enum exists and auto-infers from experiment_type."""
    spec_sim = ExperimentSpec(
        spec_id="spec-sim-01",
        hypothesis_id="hyp-01",
        experiment_type=ExperimentType.SIMULATION,
        name="Simulation Test",
        description="Testing simulation class",
        entry_point="python simulation.py",
        run_config={},
        dependencies=[],
        random_seeds=[42],
        expected_outputs=["metrics.json"],
        timeout_seconds=30,
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0, max_cpu_cores=1),
    )
    assert spec_sim.experiment_class == ExperimentClass.SIMULATION

    spec_emp = ExperimentSpec(
        spec_id="spec-emp-01",
        hypothesis_id="hyp-01",
        experiment_type=ExperimentType.DATASET_ANALYSIS,
        name="Empirical Test",
        description="Testing empirical dataset analysis class",
        entry_point="python run.py",
        run_config={},
        dependencies=[],
        random_seeds=[42],
        expected_outputs=["metrics.json"],
        timeout_seconds=30,
        hardware_requirements=HardwareRequirements(min_ram_gb=1.0, max_cpu_cores=1),
    )
    assert spec_emp.experiment_class == ExperimentClass.EMPIRICAL


def test_scientific_integrity_linter_simulation_rejects_empirical_claims():
    """Directive 3 Negative: Simulation manuscript using forbidden empirical claims is blocked."""
    manuscript = (
        "In this study, we provide rigorous empirical evidence and real-world validation "
        "demonstrating that our mechanism solves the decentralized coordination problem."
    )

    violations = ScientificIntegrityLinter.lint_text(
        text=manuscript,
        experiment_class=ExperimentClass.SIMULATION,
    )
    assert len(violations) >= 2
    assert any("empirical evidence" in v for v in violations)
    assert any("real-world validation" in v for v in violations)

    with pytest.raises(EpistemicHonestyViolation) as exc_info:
        ScientificIntegrityLinter.assert_integrity(
            text=manuscript,
            experiment_class=ExperimentClass.SIMULATION,
        )
    assert "Epistemic Overclaim" in str(exc_info.value)


def test_scientific_integrity_linter_zero_variance_blocks_p_value_claims():
    """Directive 3 Negative: Identical seed outputs (SD == 0.0) cannot claim statistical significance (p < 0.05)."""
    # Create evaluation report with SD == 0.0 across 3 seeds (case study mock failure)
    eval_report = EvaluationReport(
        evaluation_id="eval-zero-var-01",
        hypothesis_id="hyp-01",
        spec_id="spec-01",
        seeds_evaluated=[42, 101, 2024],
        verdict=HypothesisVerdict.CONFIRMED,
        target_metric="accuracy",
        metric_aggregates={
            "accuracy": MetricAggregate(
                metric_name="accuracy",
                mean=0.95,
                std_dev=0.0000,
                std_err=0.0000,
                sample_values=[0.95, 0.95, 0.95],
                target_threshold=0.90,
                operator=">=",
                passed=True,
                p_value_estimate=None,
            )
        },
        seed_runs=[
            SeedRunSummary(seed=42, run_id="r1", exit_code=0, metrics={"accuracy": 0.95}, verification_status="VERIFIED"),
            SeedRunSummary(seed=101, run_id="r2", exit_code=0, metrics={"accuracy": 0.95}, verification_status="VERIFIED"),
            SeedRunSummary(seed=2024, run_id="r3", exit_code=0, metrics={"accuracy": 0.95}, verification_status="VERIFIED"),
        ],
        total_runs=3,
        successful_runs=3,
        failed_runs=0,
        summary_rationale="Identical mock outputs.",
    )

    fraudulent_text = "The experimental results confirmed our hypothesis with p < 0.05 and statistically significant gains."

    with pytest.raises(EpistemicHonestyViolation) as exc_info:
        ScientificIntegrityLinter.assert_integrity(
            text=fraudulent_text,
            experiment_class=ExperimentClass.SIMULATION,
            evaluation=eval_report,
        )

    assert "Statistical Honesty Violation" in str(exc_info.value)
    assert "zero variance" in str(exc_info.value)


# ==============================================================================
# DIRECTIVE 4: ROBUST MANUSCRIPT AST & ASSET PATH RESOLVER
# ==============================================================================


def test_latex_escaping_special_characters_and_operators():
    """Directive 4: escape_latex safely escapes special characters and comparison operators."""
    raw = "Metric accuracy_rate <= 0.85 & threshold >= 50% for target #1: cost $100 {test} ^2 ~ approx"
    escaped = escape_latex(raw)

    assert "\\le" in escaped
    assert "\\ge" in escaped
    assert "\\&" in escaped
    assert "\\%" in escaped
    assert "\\#" in escaped
    assert "\\$" in escaped
    assert "\\_" in escaped
    assert "\\{" in escaped
    assert "\\}" in escaped
    assert "\\textasciicircum" in escaped
    assert "\\textasciitilde" in escaped


def test_latex_ast_document_and_table_rendering():
    """Directive 4: Structured AST builds valid publication-grade LaTeX without string concatenation."""
    doc = LatexDocument()
    doc.add(LatexCommand("title", "Test Paper on Robust AST"))
    doc.add(LatexCommand("author", "Autonomous Discovery Engine"))

    env = LatexEnvironment("abstract")
    env.add(LatexText("This is an abstract with metric <= 50%."))
    doc.add(env)

    headers = ["Metric", LatexRaw("Mean ($M$)"), "SD", "Verdict"]
    rows = [
        ["accuracy_score", "0.9200", "0.0150", "Confirmed"],
        ["error_rate", "0.0800", "0.0050", "Confirmed"],
    ]
    table = LatexTable(
        headers=headers,
        rows=rows,
        caption="Summary of Performance (threshold <= 0.10)",
        label="tab:perf",
    )
    doc.add(table)

    rendered = doc.render()

    assert "\\documentclass" in rendered
    assert "\\begin{table}[h]" in rendered
    assert "\\toprule" in rendered
    assert "\\bottomrule" in rendered
    assert "accuracy\\_score" in rendered
    assert "Mean ($M$)" in rendered
    assert "$\\le$" in rendered


def test_latex_figure_path_resolution(tmp_path: Path):
    """Directive 4: Figures resolve bundle-relative or absolute paths independent of shell CWD."""
    manuscript_dir = tmp_path / "manuscript"
    figures_dir = manuscript_dir / "figures"
    figures_dir.mkdir(parents=True)

    fig_file = figures_dir / "convergence.png"
    fig_file.write_bytes(b"dummy_png_bytes")

    # Relative to manuscript dir
    resolved_rel = resolve_figure_path(fig_file, manuscript_dir)
    assert resolved_rel == "figures/convergence.png"
    assert "\\" not in resolved_rel

    # External figure outside manuscript dir resolves to valid forward-slash path
    external_fig = tmp_path / "shared" / "external.png"
    external_fig.parent.mkdir(parents=True)
    external_fig.write_bytes(b"dummy_external_bytes")

    resolved_ext = resolve_figure_path(external_fig, manuscript_dir)
    assert "\\" not in resolved_ext
    assert "external.png" in resolved_ext

    # Figure AST node rendering
    fig_node = LatexFigure(
        figure_path=fig_file,
        manuscript_dir=manuscript_dir,
        caption="Convergence under noise <= 10%",
        label="fig:conv",
    )
    fig_tex = fig_node.render()
    assert "\\includegraphics[width=\\columnwidth]{figures/convergence.png}" in fig_tex
    assert "noise $\\le$ 10\\%" in fig_tex

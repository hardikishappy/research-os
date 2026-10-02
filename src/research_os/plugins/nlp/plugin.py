"""NLP Benchmarking Domain Plugin implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from research_os.domains.base import (
    MetricProvenanceReport,
    ValidationResult,
)
from research_os.plugins.base import BaseDomainAdapter
from research_os.models.base import BaseModelAdapter
from research_os.plugins.nlp.experiments.benchmark_generator import (
    get_nlp_benchmark_code,
)
from research_os.plugins.nlp.metrics import compute_nlp_metrics_from_raw
from research_os.plugins.nlp.schemas import NLPBenchmarkConfig
from research_os.schemas.experiment import (
    ExperimentModality,
    ExperimentSpec,
    ExperimentType,
    HardwareRequirements,
)
from research_os.schemas.hypothesis import HypothesisProposal
from research_os.schemas.mechanism import MechanismContract, MechanismEventRequirement


class NLPPlugin(BaseDomainAdapter):
    """Domain plugin for evaluating NLP, RAG, and language model hallucination benchmarks."""

    domain_id: str = "nlp_benchmarking"
    display_name: str = "Natural Language Processing: RAG & Hallucination Benchmarks"
    supported_experiment_types: list[ExperimentType] = [ExperimentType.BENCHMARK]

    def matches_domain(self, hypothesis: HypothesisProposal) -> bool:
        """Check if hypothesis belongs to NLP / language model domain."""
        search_space = " ".join([
            hypothesis.title,
            hypothesis.falsifiable_statement,
            hypothesis.proposed_mechanism,
            hypothesis.theoretical_rationale,
        ]).lower()

        # Check seeds domain
        for seed in hypothesis.inspired_by_seeds:
            seed_domain = seed.domain.lower()
            if any(term in seed_domain for term in ["nlp", "language", "rag", "retrieval", "llm"]):
                return True

        keywords = [
            "nlp",
            "hallucination",
            "rag",
            "retrieval-augmented",
            "language model",
            "prompt",
            "context injection",
            "token overlap",
        ]
        return any(kw in search_space for kw in keywords)

    def validate_hypothesis(self, hypothesis: HypothesisProposal) -> ValidationResult:
        """Validate whether the hypothesis can be evaluated via standard NLP benchmark."""
        if not self.matches_domain(hypothesis):
            return ValidationResult(
                is_valid=False,
                domain_id=self.domain_id,
                reasons=["Hypothesis does not target natural language processing or retrieval models."],
            )

        valid = bool(hypothesis.target_metric and hypothesis.success_threshold is not None)
        reasons = [] if valid else ["Missing quantitative target_metric or success_threshold."]
        return ValidationResult(
            is_valid=valid,
            domain_id=self.domain_id,
            reasons=reasons,
        )

    def plan_experiment(
        self,
        hypothesis: HypothesisProposal,
        spec_requirements: Optional[dict[str, Any]] = None,
    ) -> ExperimentSpec:
        """Compile an NLP hypothesis into an ExperimentSpec."""
        actual_spec_id = f"spec-{hypothesis.hypothesis_id[:12]}"
        default_cfg = NLPBenchmarkConfig(
            hallucination_threshold=hypothesis.success_threshold or 0.25,
        )
        run_config = default_cfg.model_dump()
        run_config.update({
            "target_metric": hypothesis.target_metric,
            "expected_direction": hypothesis.expected_direction,
            "success_threshold": hypothesis.success_threshold,
        })
        if spec_requirements:
            run_config.update(spec_requirements)

        timeout = int(spec_requirements.get("timeout_seconds", 45)) if spec_requirements else 45

        rag_contract = MechanismContract(
            modality=ExperimentModality.RAG,
            required_transitions=[
                MechanismEventRequirement(
                    event_type="QUERY_IN",
                    required_payload_fields=["query_id", "query_text"],
                ),
                MechanismEventRequirement(
                    event_type="RETRIEVAL_INVOKED",
                    required_payload_fields=["query_id"],
                ),
                MechanismEventRequirement(
                    event_type="CANDIDATE_DOCS_RETRIEVED",
                    required_payload_fields=["query_id", "doc_ids", "scores"],
                ),
                MechanismEventRequirement(
                    event_type="CONTEXT_ASSEMBLED",
                    required_payload_fields=["query_id", "context_length"],
                ),
                MechanismEventRequirement(
                    event_type="MODEL_INFERENCE",
                    required_payload_fields=["query_id", "input_tokens", "output_tokens"],
                ),
                MechanismEventRequirement(
                    event_type="FACTUALITY_EVALUATION",
                    required_payload_fields=["query_id", "hallucinated", "token_overlap"],
                ),
            ],
            min_event_count=6,
            enforce_strict_ordering=True,
            enforce_hash_chain=True,
        )

        declared = [
            "hallucination_rate",
            "baseline_hallucination_rate",
            "shuffled_hallucination_rate",
            "hallucination_reduction_pct",
            "token_overlap_score",
            "latency_ms",
            "total_evaluated_queries",
        ]
        if hypothesis.target_metric and hypothesis.target_metric not in declared:
            declared.append(hypothesis.target_metric)

        return ExperimentSpec(
            spec_id=actual_spec_id,
            hypothesis_id=hypothesis.hypothesis_id,
            experiment_type=ExperimentType.BENCHMARK,
            name=f"Empirical Benchmark: {hypothesis.title}",
            description=f"NLP benchmark evaluating: {hypothesis.falsifiable_statement}",
            entry_point="python run_benchmark.py --config config.json --output-dir output",
            run_config=run_config,
            declared_metrics=declared,
            mechanism_contract=rag_contract,
            dependencies=["pydantic>=2.0.0"],
            random_seeds=[42, 101, 2024],
            expected_outputs=["metrics.json", "provenance.json", "trace.jsonl", "raw_data/predictions.jsonl", "summary.txt"],
            timeout_seconds=timeout,
            hardware_requirements=HardwareRequirements(
                cuda_required=False,
                min_ram_gb=1.0,
                max_cpu_cores=2,
            ),
        )

    def generate_experiment_code(
        self,
        spec: ExperimentSpec,
        model_adapter: Optional[BaseModelAdapter] = None,
    ) -> str:
        """Return the complete benchmark evaluation script."""
        return get_nlp_benchmark_code()

    def validate_metric_provenance(
        self,
        raw_data_dir: Path,
        metrics: dict[str, Any],
    ) -> MetricProvenanceReport:
        """Verify metrics.json against raw predictions.jsonl."""
        errors: list[str] = []
        unbacked: list[str] = []

        if not raw_data_dir.exists():
            return MetricProvenanceReport(
                is_valid=False,
                unbacked_metrics=list(metrics.keys()),
                errors=[f"Raw data directory does not exist: {raw_data_dir}"],
            )

        try:
            recomputed_metrics, provenance_records = compute_nlp_metrics_from_raw(
                raw_data_dir=raw_data_dir,
            )
        except Exception as e:
            return MetricProvenanceReport(
                is_valid=False,
                unbacked_metrics=list(metrics.keys()),
                errors=[f"Failed to recompute NLP metrics from raw predictions: {e}"],
            )

        tracked_keys = [
            "hallucination_rate",
            "baseline_hallucination_rate",
            "shuffled_hallucination_rate",
            "hallucination_reduction_pct",
            "token_overlap_score",
        ]
        for k in tracked_keys:
            if k in metrics:
                obs = metrics[k]
                expected = recomputed_metrics.get(k)
                if expected is None:
                    unbacked.append(k)
                elif abs(obs - expected) > 1e-2:
                    errors.append(f"Metric '{k}' mismatch: reported {obs} != recomputed {expected}")
            else:
                unbacked.append(k)

        is_valid = len(errors) == 0 and len(unbacked) == 0
        return MetricProvenanceReport(
            is_valid=is_valid,
            provenance_records=provenance_records,
            unbacked_metrics=unbacked,
            errors=errors,
        )

    def validate_environment(self) -> dict[str, bool]:
        """Validates that NLP domain runtimes and libraries are available."""
        import importlib.util
        packages = ["torch", "transformers", "datasets", "scipy", "numpy", "rank_bm25"]
        return {pkg: importlib.util.find_spec(pkg) is not None for pkg in packages}

    def generate_execution_plan(self, spec: ExperimentSpec) -> dict[str, Any]:
        """Binds experiment specifications to verified domain solvers."""
        return {
            "domain_id": self.domain_id,
            "solver": "BM25Retriever + DeterministicQAEngine",
            "benchmark_size": spec.run_config.get("benchmark_size", 40),
            "retrieval_k": spec.run_config.get("top_k", 3),
            "mechanism": "BM25 Sparse Retrieval Augmented Generation",
            "modality": "BENCHMARK",
        }

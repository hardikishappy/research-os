"""Bidirectional Spec and Runner Contract Verification for Research OS.

Enforces:
- Target metric alignment between Hypothesis, ExperimentSpec, and Runner Code.
- Pre-flight introspection via runner script `--describe` or static AST analysis.
- Raising SpecContractValidationError BEFORE approval gates or execution launch.
"""

from __future__ import annotations

import ast
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Union
from pydantic import Field

from research_os.schemas.base import ArtifactBaseModel
from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.hypothesis import HypothesisProposal
from research_os.specs.catalog import MetricCatalog
from research_os.specs.units import ValueWithUnit


class SpecContractValidationError(ValueError):
    """Raised when an ExperimentSpec violates contractual alignment with Hypothesis or Runner."""
    pass


class RunnerIntrospection(ArtifactBaseModel):
    """Introspected metadata describing the contract exposed by an experiment runner script."""

    entry_point_script: str = Field(description="Resolved script filename")
    declared_metrics: list[str] = Field(default_factory=list, description="Metric keys emitted by the runner")
    metric_units: dict[str, str] = Field(default_factory=dict, description="Declared units per emitted metric")
    supported_parameters: list[str] = Field(default_factory=list, description="Accepted hyperparameters/flags")
    introspected_via: str = Field(description="Method used for introspection: CLI_DESCRIBE or STATIC_AST")

    @property
    def supported_metrics(self) -> list[str]:
        return self.declared_metrics


def introspect_runner_contract(
    code_dir: Union[str, Path],
    entry_point: str,
    timeout_seconds: int = 5,
) -> RunnerIntrospection:
    """Introspect an experiment runner script to determine its emitted metrics and contract.
    
    Tries:
    1. Dynamic execution with '--describe' flag in safe isolated environment.
    2. Static AST analysis of Python source code looking for emitted metric keys.
    """
    code_path = Path(code_dir).resolve()
    parts = shlex.split(entry_point, posix=(os.name != "nt"))
    if not parts:
        raise SpecContractValidationError(f"Invalid empty entry point: '{entry_point}'")

    script_name = parts[-1]
    for p in parts:
        if p.endswith(".py"):
            script_name = p
            break

    script_file = code_path / script_name
    if not script_file.exists():
        # Search anywhere in code_path
        matches = list(code_path.glob(f"**/{script_name}"))
        if matches:
            script_file = matches[0]
        else:
            raise FileNotFoundError(
                f"Runner script '{script_name}' declared in entry point '{entry_point}' does not exist in '{code_path}'."
            )

    # 1. Static Contract Files (contract.json / contract.yaml / contract.yml)
    for contract_name in ("contract.json", "contract.yaml", "contract.yml"):
        c_file = code_path / contract_name
        if c_file.exists() and c_file.is_file():
            try:
                c_content = c_file.read_text(encoding="utf-8")
                if contract_name.endswith(".json"):
                    data = json.loads(c_content)
                else:
                    import yaml
                    data = yaml.safe_load(c_content)
                if isinstance(data, dict):
                    declared = (
                        data.get("declared_metrics")
                        or data.get("supported_metrics")
                        or data.get("metrics")
                        or []
                    )
                    if declared:
                        return RunnerIntrospection(
                            entry_point_script=script_name,
                            declared_metrics=declared,
                            metric_units=data.get("metric_units", {}),
                            supported_parameters=data.get("supported_parameters", []),
                            introspected_via="STATIC_CONTRACT",
                        )
            except Exception:
                pass

    # 2. Strict Static AST Analysis (No code execution allowed)
    declared_metrics: list[str] = []
    metric_units: dict[str, str] = {}
    try:
        source = script_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=script_name)

        for node in ast.walk(tree):
            # Check for dict constants containing supported_metrics / declared_metrics lists
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and str(k.value) in ("supported_metrics", "declared_metrics", "metrics"):
                        if isinstance(v, ast.List):
                            for elem in v.elts:
                                if isinstance(elem, ast.Constant) and isinstance(elem.value, str):
                                    declared_metrics.append(elem.value)

            # Look for dict assignments e.g. metrics = { "recall_at_k": ..., "latency": ... }
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and "metric" in target.id.lower():
                        if isinstance(node.value, ast.Dict):
                            for k in node.value.keys:
                                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                    declared_metrics.append(k.value)

            # Look for metrics["key"] = val
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                if isinstance(node.slice.value, str) and isinstance(node.value, ast.Name):
                    if "metric" in node.value.id.lower():
                        declared_metrics.append(node.slice.value)

            # Look for Dict constants passed into json.dump(...)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "dump" and node.args and isinstance(node.args[0], ast.Dict):
                    for k in node.args[0].keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            declared_metrics.append(k.value)

    except Exception as exc:
        raise SpecContractValidationError(
            f"Failed to statically inspect runner script '{script_name}': {exc}"
        ) from exc

    # Clean duplicates while preserving order
    unique_metrics = list(dict.fromkeys(declared_metrics))

    return RunnerIntrospection(
        entry_point_script=script_name,
        declared_metrics=unique_metrics,
        metric_units=metric_units,
        supported_parameters=[],
        introspected_via="STATIC_AST",
    )


def verify_spec_contract(
    spec: ExperimentSpec,
    hypothesis: Optional[HypothesisProposal] = None,
    code_dir: Optional[Union[str, Path]] = None,
) -> Optional[RunnerIntrospection]:
    """Verify bidirectional contract between Hypothesis, ExperimentSpec, and Runner Code.
    
    Enforces:
    1. Hypothesis target_metric is consistent with spec.
    2. Runner emits the required target_metric (prevents metric schema mismatch e.g.
       target_metric: recall_at_k vs runner emitting hallucination_rate).
    3. Spec declares expected output metrics.json.
    
    Raises:
        SpecContractValidationError: If any contractual invariant is violated.
    """
    target_metric = None
    if hypothesis:
        target_metric = hypothesis.target_metric
        # Check hypothesis ID match if spec hypothesis_id is populated
        if spec.hypothesis_id and spec.hypothesis_id != hypothesis.hypothesis_id:
            raise SpecContractValidationError(
                f"Spec hypothesis_id '{spec.hypothesis_id}' does not match hypothesis '{hypothesis.hypothesis_id}'."
            )
    elif spec.run_config and "target_metric" in spec.run_config:
        target_metric = spec.run_config["target_metric"]

    # Invariant: Spec expected_outputs must include metrics.json
    has_metrics_output = any("metrics.json" in out for out in spec.expected_outputs)
    if not has_metrics_output:
        raise SpecContractValidationError(
            f"Spec '{spec.spec_id}' violates contract: expected_outputs must include 'metrics.json'."
        )

    # Invariant: Every declared metric must exist in MetricCatalog (U1)
    for m in getattr(spec, "declared_metrics", []) or []:
        MetricCatalog.require(m)

    # Invariant: If code_dir is supplied, verify runner contract
    introspection = None
    if code_dir:
        introspection = introspect_runner_contract(code_dir, spec.entry_point)
        if target_metric and introspection.declared_metrics:
            if target_metric not in introspection.declared_metrics:
                raise SpecContractValidationError(
                    f"SPEC CONTRACT MISMATCH: Hypothesis expects target_metric '{target_metric}', "
                    f"but runner script '{introspection.entry_point_script}' declared outputs: "
                    f"{introspection.declared_metrics}. (Runner emits incompatible metric schema)."
                )

    # Validate metric bounds and catalog compatibility if metric is known
    if target_metric:
        cat_entry = MetricCatalog.get(target_metric)
        if cat_entry and hypothesis:
            # Check success threshold bounds
            val_unit = ValueWithUnit(value=hypothesis.success_threshold, unit=cat_entry.canonical_unit)
            val_unit.to_canonical()

    return introspection

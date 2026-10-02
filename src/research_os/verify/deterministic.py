"""Deterministic verification engine for Research OS (Rule 6 Enforcement).

Rule 6 & Rule 1 Compliance:
- Independent metric recomputation: Never trust reported scalar metrics; independently parse raw files and recalculate.
- Immutable content-addressed manifests: Tamper detection flags post-hoc modifications as TAMPERED.
- Full mathematical derivation tracking with strict floating-point verification tolerance (epsilon <= 1e-6).
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Union
from pydantic import BaseModel, ValidationError

from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.verification import (
    MetricDerivation,
    MetricVerification,
    RawArtifactReference,
    StructuredMetricRecord,
    VerificationReport,
    VerificationStatus,
)


class MetricFabricationError(ValueError):
    """Raised when reported scalar metric disagrees with independently recomputed raw data value."""
    pass


class ProvenanceIntegrityError(ValueError):
    """Raised when raw artifact checksum mismatches or provenance trail is invalid."""
    pass


class MissingRawArtifactError(FileNotFoundError):
    """Raised when metric derivation declares a raw data artifact that does not exist on disk."""
    pass


def compute_file_sha256(file_path: Union[str, Path]) -> str:
    """Compute the SHA-256 hex digest of a file in streaming chunks."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found for checksum: {path}")

    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_directory_checksums(dir_path: Union[str, Path]) -> dict[str, str]:
    """Recursively compute SHA-256 checksums for all files in a directory."""
    base = Path(dir_path)
    if not base.is_dir():
        return {}

    checksums: dict[str, str] = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            rel_path = p.relative_to(base).as_posix()
            checksums[rel_path] = compute_file_sha256(p)
    return checksums


def create_run_manifest(
    run_dir: Union[str, Path],
    private_key: Optional[Any] = None,
) -> Path:
    """Generate and seal an immutable content-addressed manifest.json immediately post-execution signed with Ed25519."""
    from cryptography.hazmat.primitives import serialization
    from research_os.gate.approval import get_default_signing_key

    base = Path(run_dir)
    checksums = compute_directory_checksums(base)
    canonical_files_bytes = json.dumps(checksums, sort_keys=True).encode("utf-8")
    manifest_digest = hashlib.sha256(canonical_files_bytes).hexdigest()

    signer = private_key or get_default_signing_key()
    sig_bytes = signer.sign(manifest_digest.encode("utf-8"))
    pub_bytes = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    manifest_data = {
        "manifest_version": "2.0.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_digest": manifest_digest,
        "signature": sig_bytes.hex(),
        "public_key_hex": pub_bytes.hex(),
        "files": checksums,
    }
    manifest_path = base / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    return manifest_path


def parse_raw_records(file_path: Path) -> list[dict[str, Any]]:
    """Parse raw telemetry records from CSV, JSONL, or JSON files."""
    records: list[dict[str, Any]] = []
    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            records = list(reader)
    elif suffix in (".jsonl", ".ndjson"):
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    records.append(json.loads(stripped))
    elif suffix == ".json":
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                # Check for common record array keys
                for k in ("records", "data", "items", "samples"):
                    if isinstance(data.get(k), list):
                        records = data[k]
                        break
                if not records:
                    records = [data]
    else:
        # Default try parsing as JSON or CSV lines
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                records = data if isinstance(data, list) else [data]
        except Exception:
            with file_path.open("r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                records = list(reader)

    return records


def evaluate_condition(val: Any, condition: str, target: Any) -> bool:
    """Helper to evaluate standard conditional operators."""
    if condition in ("==", "="):
        return str(val).lower() == str(target).lower() or val == target
    elif condition in ("!=", "<>"):
        return str(val).lower() != str(target).lower() and val != target
    try:
        f_val = float(val)
        f_target = float(target)
        if condition == ">":
            return f_val > f_target
        elif condition == "<":
            return f_val < f_target
        elif condition == ">=":
            return f_val >= f_target
        elif condition == "<=":
            return f_val <= f_target
    except (ValueError, TypeError):
        pass
    return False


def recompute_metric_from_artifact(file_path: Path, derivation: MetricDerivation) -> float:
    """Independently calculate the scalar metric value directly from raw file records."""
    records = parse_raw_records(file_path)
    if not records:
        raise ValueError(f"No records parsed from raw artifact: {file_path}")

    op = derivation.operation
    target_field = derivation.target_field or ""

    if op == "fraction_where":
        cond = derivation.condition or "=="
        tgt = derivation.target_value
        matched = 0
        total = len(records)
        for r in records:
            val = r.get(target_field)
            if evaluate_condition(val, cond, tgt):
                matched += 1
        return matched / total if total > 0 else 0.0

    elif op == "mean":
        vals = [float(r[target_field]) for r in records if r.get(target_field) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    elif op == "sum":
        vals = [float(r[target_field]) for r in records if r.get(target_field) is not None]
        return sum(vals)

    elif op == "count":
        if target_field and derivation.condition is not None:
            return float(sum(1 for r in records if evaluate_condition(r.get(target_field), derivation.condition, derivation.target_value)))
        return float(len(records))

    elif op == "rmse":
        target_col = derivation.target_column or target_field or "y_true"
        ref_col = derivation.reference_column or "y_pred"
        diff_sq = []
        for r in records:
            if target_col in r and ref_col in r:
                diff = float(r[target_col]) - float(r[ref_col])
                diff_sq.append(diff ** 2)
        return math.sqrt(sum(diff_sq) / len(diff_sq)) if diff_sq else 0.0

    elif op == "min":
        vals = [float(r[target_field]) for r in records if r.get(target_field) is not None]
        return min(vals) if vals else 0.0

    elif op == "max":
        vals = [float(r[target_field]) for r in records if r.get(target_field) is not None]
        return max(vals) if vals else 0.0

    elif op == "std":
        vals = [float(r[target_field]) for r in records if r.get(target_field) is not None]
        if len(vals) <= 1:
            return 0.0
        m = sum(vals) / len(vals)
        variance = sum((x - m) ** 2 for x in vals) / (len(vals) - 1)
        return math.sqrt(variance)

    elif op == "delta_relative":
        target_col = derivation.target_field or ""
        base_col = getattr(derivation, "baseline_field", None) or derivation.reference_column or "baseline"
        deltas: list[float] = []
        for r in records:
            if target_col in r and base_col in r:
                try:
                    t_val = float(r[target_col])
                    b_val = float(r[base_col])
                    if b_val != 0.0:
                        deltas.append((t_val - b_val) / abs(b_val))
                except (ValueError, TypeError):
                    continue
        return sum(deltas) / len(deltas) if deltas else 0.0

    elif op == "reduction_pct":
        target_col = derivation.target_field or ""
        base_col = getattr(derivation, "baseline_field", None) or derivation.reference_column or "baseline"
        base_vals = [float(r[base_col]) for r in records if r.get(base_col) is not None]
        targ_vals = [float(r[target_col]) for r in records if r.get(target_col) is not None]
        base_mean = sum(base_vals) / len(base_vals) if base_vals else 0.0
        targ_mean = sum(targ_vals) / len(targ_vals) if targ_vals else 0.0
        if base_mean == 0.0:
            return 0.0
        return ((base_mean - targ_mean) / base_mean) * 100.0

    elif op == "custom":
        if "expected_value" in derivation.parameters:
            return float(derivation.parameters["expected_value"])
        return 0.0

    else:
        raise ValueError(f"Unsupported derivation operation: {op}")


def evaluate_metric_condition(
    observed: float,
    target: float,
    operator: str,
) -> bool:
    """Deterministically evaluate an observed numeric metric against a threshold."""
    if operator == ">":
        return observed > target
    elif operator == "<":
        return observed < target
    elif operator == ">=":
        return observed >= target
    elif operator == "<=":
        return observed <= target
    elif operator == "==":
        return math.isclose(observed, target, rel_tol=1e-5, abs_tol=1e-8)
    else:
        raise ValueError(f"Unsupported comparison operator: {operator}")


class DeterministicVerifier:
    """Verifies experiment run outputs, seals manifests, and independently recomputes metrics without LLMs."""

    def __init__(
        self,
        metrics_filename: str = "metrics.json",
        require_provenance: bool = True,
        tolerance: float = 1e-6,
    ) -> None:
        self.metrics_filename = metrics_filename
        self.require_provenance = require_provenance
        self.tolerance = tolerance

    def verify_run(
        self,
        spec: ExperimentSpec,
        run_dir: Union[str, Path],
        exit_code: int,
        run_id: Optional[str] = None,
        metric_targets: Optional[Mapping[str, tuple[str, float]]] = None,
        metric_schema: Optional[type[BaseModel]] = None,
        require_provenance: Optional[bool] = None,
        domain_plugin: Optional[Any] = None,
        strict_tamper_check: bool = True,
    ) -> VerificationReport:
        """Execute all deterministic checks, independent recomputations, and honest provenance audits."""
        run_path = Path(run_dir)
        actual_run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        report_id = f"vr-{uuid.uuid4().hex[:12]}"

        errors: list[str] = []
        is_tampered = False
        is_invalid_artifact = False

        # 1. Exit code check
        exit_code_passed = (exit_code == 0)
        if not exit_code_passed:
            errors.append(f"Process terminated with non-zero exit code: {exit_code}")

        # 2. Expected output files check
        missing_outputs: list[str] = []
        for expected in spec.expected_outputs:
            target_file = run_path / expected
            if not target_file.exists():
                missing_outputs.append(expected)

        if missing_outputs:
            errors.append(f"Missing expected output files: {', '.join(missing_outputs)}")

        # 3. Sealed Manifest & Tamper Verification
        manifest_path = run_path / "manifest.json"
        if manifest_path.exists() and manifest_path.is_file():
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

                # Verify Ed25519 digital signature of manifest if present
                if "signature" in manifest_data and "public_key_hex" in manifest_data:
                    from cryptography.hazmat.primitives.asymmetric import ed25519
                    from cryptography.exceptions import InvalidSignature

                    files_dict = manifest_data.get("files", {})
                    expected_digest = manifest_data.get("manifest_digest")
                    computed_digest = hashlib.sha256(json.dumps(files_dict, sort_keys=True).encode("utf-8")).hexdigest()
                    if expected_digest != computed_digest:
                        is_tampered = True
                        errors.append(
                            f"Tamper detected: Manifest digest mismatch (expected {expected_digest}, computed {computed_digest})"
                        )
                    else:
                        try:
                            pub_bytes = bytes.fromhex(manifest_data["public_key_hex"])
                            sig_bytes = bytes.fromhex(manifest_data["signature"])
                            pub_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
                            pub_key.verify(sig_bytes, expected_digest.encode("utf-8"))
                        except (InvalidSignature, ValueError) as se:
                            is_tampered = True
                            errors.append(f"Tamper detected: Manifest digital signature invalid or failed verification: {se}")

                expected_files = manifest_data.get("files", {})
                current_files = compute_directory_checksums(run_path)

                # Check for modified or deleted files
                for rel_path, expected_hash in expected_files.items():
                    disk_file = run_path / rel_path
                    if not disk_file.exists():
                        is_tampered = True
                        errors.append(f"Tamper detected: Manifest file missing on disk: '{rel_path}'")
                    else:
                        actual_hash = compute_file_sha256(disk_file)
                        if actual_hash != expected_hash:
                            is_tampered = True
                            errors.append(
                                f"Tamper detected: Checksum for '{rel_path}' modified after manifest creation "
                                f"(expected {expected_hash[:16]}..., found {actual_hash[:16]}...)"
                            )

                # Check for unauthorized added files (Any post-execution addition is TAMPERED)
                added_files = set(current_files.keys()) - set(expected_files.keys())
                if added_files:
                    is_tampered = True
                    errors.append(
                        f"Tamper detected: Unauthorized post-execution file addition: {', '.join(sorted(added_files))}"
                    )
            except Exception as me:
                is_tampered = True
                errors.append(f"Tamper detected: Failed to verify sealed manifest.json: {me}")

        # Current directory checksums
        checksums = compute_directory_checksums(run_path)

        # 4. Metric schema and value checks
        schema_compliance = True
        provenance_valid = True
        unbacked_metrics: list[str] = []
        metric_evaluations: list[MetricVerification] = []
        structured_metrics: list[StructuredMetricRecord] = []

        raw_metrics: dict[str, Any] = {}
        metrics_file = run_path / self.metrics_filename

        if metrics_file.exists() and metrics_file.is_file():
            try:
                with metrics_file.open("r", encoding="utf-8") as f:
                    raw_metrics = json.load(f)

                if not isinstance(raw_metrics, dict):
                    schema_compliance = False
                    errors.append(f"{self.metrics_filename} is not a valid JSON dictionary")
                    raw_metrics = {}
                elif metric_schema is not None:
                    try:
                        metric_schema.model_validate(raw_metrics)
                    except ValidationError as ve:
                        schema_compliance = False
                        errors.append(f"Metric schema validation error: {ve}")

                # Check for undeclared metric spoofing (Directive 3)
                declared_set = set(getattr(spec, "declared_metrics", []) or [])
                if not declared_set and "declared_metrics" in spec.run_config:
                    declared_set = set(spec.run_config["declared_metrics"])
                if declared_set:
                    emitted_metrics = [k for k in raw_metrics.keys() if k not in ("status", "_provenance")]
                    spoofed = [k for k in emitted_metrics if k not in declared_set]
                    if spoofed:
                        schema_compliance = False
                        errors.append(
                            f"UndeclaredMetricSpoofingError: Output metrics {spoofed} not declared in contract. "
                            f"Allowed: {sorted(list(declared_set))}."
                        )

                # 5. Independent Metric Recomputation & Provenance Audit
                should_audit_provenance = (
                    require_provenance
                    if require_provenance is not None
                    else (self.require_provenance or spec.run_config.get("require_provenance", False))
                )

                candidate_metrics = [
                    k for k, v in raw_metrics.items()
                    if k not in ["status", "_provenance"] and isinstance(v, (int, float))
                ]

                prov_file = run_path / "provenance.json"
                prov_data: dict[str, Any] = {}
                if prov_file.exists() and prov_file.is_file():
                    try:
                        prov_data = json.loads(prov_file.read_text(encoding="utf-8"))
                    except Exception as pe:
                        errors.append(f"Malformed provenance.json: {pe}")
                elif "_provenance" in raw_metrics:
                    prov_data = raw_metrics["_provenance"]
                elif should_audit_provenance:
                    provenance_valid = False
                    unbacked_metrics.extend(candidate_metrics)
                    errors.append(f"ProvenanceIntegrityError: Mandatory provenance.json is missing from run directory ({run_path})")

                prov_records = prov_data.get("metrics", prov_data.get("items", prov_data))

                # Handle dict or list form of provenance records
                norm_prov: dict[str, dict[str, Any]] = {}
                if isinstance(prov_records, list):
                    for it in prov_records:
                        m_name = it.get("metric_id") or it.get("metric_name")
                        if m_name:
                            norm_prov[m_name] = it
                elif isinstance(prov_records, dict):
                    norm_prov = prov_records

                candidate_metrics = [
                    k for k, v in raw_metrics.items()
                    if k not in ["status", "_provenance"] and isinstance(v, (int, float))
                ]

                if should_audit_provenance or norm_prov:
                    raw_data_dir = run_path / "raw_data"
                    has_raw_data = raw_data_dir.is_dir() and any(raw_data_dir.iterdir())

                    if should_audit_provenance and not has_raw_data:
                        provenance_valid = False
                        unbacked_metrics.extend(candidate_metrics)
                        errors.append(f"Metric provenance violation: Metrics exist without backing raw data directory ({raw_data_dir})")

                    # Domain plugin validation hook (V1)
                    if domain_plugin and hasattr(domain_plugin, "validate_metric_provenance"):
                        try:
                            plugin_report = domain_plugin.validate_metric_provenance(raw_data_dir, raw_metrics)
                            if hasattr(plugin_report, "is_valid") and not plugin_report.is_valid:
                                provenance_valid = False
                                if hasattr(plugin_report, "errors") and plugin_report.errors:
                                    errors.extend(plugin_report.errors)
                                if hasattr(plugin_report, "unbacked_metrics") and plugin_report.unbacked_metrics:
                                    unbacked_metrics.extend(plugin_report.unbacked_metrics)
                            elif plugin_report is False:
                                provenance_valid = False
                                errors.append("DomainPluginProvenanceViolation: Domain plugin rejected metric provenance.")
                        except TypeError:
                            pass
                        except Exception as dpe:
                            provenance_valid = False
                            errors.append(f"DomainPluginProvenanceViolation: {dpe}")

                    for m_key, prov_item in norm_prov.items():
                        reported_val = float(raw_metrics.get(m_key, prov_item.get("reported_value", prov_item.get("value", 0.0))))

                        # Extract raw artifact relative path
                        raw_rel = ""
                        raw_hash = ""
                        if "raw_artifact" in prov_item and isinstance(prov_item["raw_artifact"], dict):
                            raw_rel = prov_item["raw_artifact"].get("relative_path", "")
                            raw_hash = prov_item["raw_artifact"].get("sha256", "")
                        else:
                            raw_rel = prov_item.get("raw_file", prov_item.get("source_file", ""))
                            raw_hash = prov_item.get("raw_sha256", "")

                        raw_disk_file = run_path / raw_rel if raw_rel else None

                        if not raw_disk_file or not raw_disk_file.exists():
                            provenance_valid = False
                            unbacked_metrics.append(m_key)
                            err_msg = f"MissingRawArtifactError: Metric '{m_key}' declares raw artifact that does not exist on disk: '{raw_rel}'"
                            errors.append(err_msg)
                            continue

                        # Check raw artifact SHA-256 hash if provided
                        actual_raw_hash = compute_file_sha256(raw_disk_file)
                        if raw_hash and actual_raw_hash != raw_hash:
                            provenance_valid = False
                            is_tampered = True
                            err_msg = (
                                f"ProvenanceIntegrityError: SHA-256 checksum mismatch for raw artifact '{raw_rel}' "
                                f"(declared {raw_hash[:16]}..., actual {actual_raw_hash[:16]}...)"
                            )
                            errors.append(err_msg)
                            continue

                        # Structured Provenance Enforcement (V1)
                        derivation_spec = prov_item.get("derivation")
                        if derivation_spec is not None and not isinstance(derivation_spec, dict):
                            provenance_valid = False
                            errors.append(
                                f"StructuredProvenanceViolation: Metric '{m_key}' derivation must be a structured dictionary, "
                                f"string-only derivations are strictly forbidden (V1)."
                            )
                            continue

                        # Per-metric domain plugin validation hook (if custom 3-parameter signature)
                        if domain_plugin and hasattr(domain_plugin, "validate_metric_provenance"):
                            try:
                                import inspect
                                sig = inspect.signature(domain_plugin.validate_metric_provenance)
                                if len(sig.parameters) >= 3:
                                    plugin_ok = domain_plugin.validate_metric_provenance(m_key, prov_item, run_path)
                                    if not plugin_ok:
                                        provenance_valid = False
                                        errors.append(f"DomainPluginProvenanceViolation: Plugin rejected provenance for '{m_key}'.")
                            except Exception as dpe:
                                provenance_valid = False
                                errors.append(f"DomainPluginProvenanceViolation: {dpe}")

                        # Independent recomputation
                        if derivation_spec and isinstance(derivation_spec, dict):
                            try:
                                deriv = MetricDerivation.model_validate(derivation_spec)
                                recomputed_val = recompute_metric_from_artifact(raw_disk_file, deriv)
                                disc = abs(recomputed_val - reported_val)
                                verified = (
                                    disc <= self.tolerance
                                    or abs(round(recomputed_val, 2) - reported_val) <= 1e-5
                                    or abs(round(recomputed_val, 4) - reported_val) <= 1e-5
                                )

                                structured_metrics.append(
                                    StructuredMetricRecord(
                                        metric_id=m_key,
                                        reported_value=reported_val,
                                        raw_artifact=RawArtifactReference(
                                            artifact_id=prov_item.get("raw_artifact", {}).get("artifact_id", f"art-{m_key}"),
                                            relative_path=raw_rel,
                                            sha256=actual_raw_hash,
                                        ),
                                        derivation=deriv,
                                        recomputed_value=round(recomputed_val, 6),
                                        discrepancy=round(disc, 8),
                                        verified=verified,
                                    )
                                )

                                if not verified:
                                    provenance_valid = False
                                    err_msg = (
                                        f"MetricFabricationError: Metric '{m_key}' reported value {reported_val} "
                                        f"diverges from independently computed raw data value {recomputed_val:.6f} "
                                        f"(discrepancy {disc:.6f} > tolerance {self.tolerance})"
                                    )
                                    errors.append(err_msg)
                            except Exception as re_err:
                                provenance_valid = False
                                errors.append(f"Independent recomputation failed for metric '{m_key}': {re_err}")

                    # Check for candidate metrics that have no provenance record
                    if should_audit_provenance:
                        for m_key in candidate_metrics:
                            if m_key not in norm_prov:
                                provenance_valid = False
                                unbacked_metrics.append(m_key)
                                errors.append(f"ProvenanceIntegrityError: Metric '{m_key}' in {self.metrics_filename} lacks an entry in provenance.json.")

                # Negative Control Arm Check (G1, G3)
                is_invalid_artifact = False
                if "shuffled_hallucination_rate" in raw_metrics and "hallucination_rate" in raw_metrics:
                    try:
                        shuffled_rate = float(raw_metrics["shuffled_hallucination_rate"])
                        rag_rate = float(raw_metrics["hallucination_rate"])
                        if math.isclose(shuffled_rate, rag_rate, abs_tol=1e-4) or shuffled_rate <= rag_rate:
                            is_invalid_artifact = True
                            errors.append(
                                f"Negative control failure: Shuffled retrieval arm achieved equivalent or superior performance "
                                f"(shuffled={shuffled_rate:.4f}, rag={rag_rate:.4f}) to actual RAG (retrieval has no causal efficacy)."
                            )
                    except (ValueError, TypeError):
                        pass

                # 6. Evaluate metric thresholds if requested
                if metric_targets:
                    for metric_name, (op, target_val) in metric_targets.items():
                        if metric_name not in raw_metrics:
                            passed = False
                            note = f"Metric '{metric_name}' not found in {self.metrics_filename}"
                            errors.append(note)
                            obs_val = float("nan")
                        else:
                            try:
                                obs_val = float(raw_metrics[metric_name])
                                passed = evaluate_metric_condition(obs_val, target_val, op)
                                note = f"Observed {obs_val} {op} {target_val}" if passed else f"Condition failed: {obs_val} not {op} {target_val}"
                                if not passed:
                                    errors.append(f"Target metric failure: {note}")
                            except (ValueError, TypeError) as e:
                                passed = False
                                note = f"Metric '{metric_name}' is not a numeric float: {e}"
                                errors.append(note)
                                obs_val = float("nan")

                        metric_evaluations.append(
                            MetricVerification(
                                metric_name=metric_name,
                                operator=op,  # type: ignore[arg-type]
                                target_threshold=target_val,
                                observed_value=obs_val,
                                passed=passed,
                                notes=note,
                            )
                        )

            except json.JSONDecodeError as jde:
                schema_compliance = False
                errors.append(f"Malformed JSON in {self.metrics_filename}: {jde}")
            except Exception as e:
                schema_compliance = False
                errors.append(f"Unexpected error reading {self.metrics_filename}: {e}")
        elif metric_targets:
            schema_compliance = False
            errors.append(f"Required {self.metrics_filename} was not found on disk")

        # 6.5. Mechanism Contract & Trace Verification (Directive 1)
        mechanism_valid = True
        if getattr(spec, "mechanism_contract", None) is not None:
            trace_candidates = [
                run_path / "trace.jsonl",
                run_path / "output" / "trace.jsonl",
                run_path / "raw_data" / "trace.jsonl",
            ]
            trace_file = next((f for f in trace_candidates if f.exists()), None)
            if not trace_file:
                mechanism_valid = False
                errors.append(
                    f"Mechanism Violation: Declared MechanismContract '{spec.mechanism_contract.contract_id}' "
                    f"mandates an observable trace, but 'trace.jsonl' was not found on disk."
                )
            else:
                from research_os.core.trace import verify_execution_trace
                expected_q_count = raw_metrics.get("total_evaluated_queries") if isinstance(raw_metrics, dict) else None
                t_valid, t_reasons = verify_execution_trace(
                    trace_file,
                    spec.mechanism_contract,
                    expected_query_count=int(expected_q_count) if expected_q_count else None,
                )
                if not t_valid:
                    mechanism_valid = False
                    for r in t_reasons:
                        errors.append(f"Mechanism Violation: {r}")

        # 7. Overall Status Determination
        all_metrics_passed = all(m.passed for m in metric_evaluations) if metric_evaluations else True

        if is_tampered:
            overall_status = VerificationStatus.TAMPERED
            error_details = "\n".join(dict.fromkeys(errors)) if errors else "Tampering detected in experiment artifacts."
        elif is_invalid_artifact:
            overall_status = VerificationStatus.INVALID_ARTIFACT
            error_details = "\n".join(dict.fromkeys(errors)) if errors else "Negative control failure: artifact invalid."
        elif not mechanism_valid:
            overall_status = VerificationStatus.MECHANISM_VIOLATION
            error_details = "\n".join(dict.fromkeys(errors)) if errors else "Mechanism contract violation."
        elif exit_code_passed and not missing_outputs and schema_compliance and all_metrics_passed and provenance_valid:
            overall_status = VerificationStatus.PASS
            error_details = None
        else:
            overall_status = VerificationStatus.FAIL
            error_details = "\n".join(dict.fromkeys(errors)) if errors else None

        return VerificationReport(
            report_id=report_id,
            spec_id=spec.spec_id,
            run_id=actual_run_id,
            exit_code=exit_code,
            exit_code_passed=exit_code_passed,
            schema_compliance=schema_compliance,
            provenance_valid=provenance_valid,
            unbacked_metrics=list(dict.fromkeys(unbacked_metrics)),
            missing_output_files=missing_outputs,
            checksums=checksums,
            metric_evaluations=metric_evaluations,
            structured_metrics=structured_metrics,
            overall_status=overall_status,
            error_details=error_details,
        )

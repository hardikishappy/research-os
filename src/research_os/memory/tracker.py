"""Experiment run tracker and memory manager for Research OS (Rules 4 & 5).

Guarantees:
- Structured run bundle layout under experiments/runs/<run_id>/
- Preservation of failed runs with complete telemetry (Rule 5)
- Deterministic cryptographic checksum manifest (Rule 4)
- Auditable provenance from hypothesis -> spec -> approval -> code -> output -> verification
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.gate import HumanGateToken
from research_os.schemas.verification import VerificationReport
from research_os.verify.deterministic import compute_directory_checksums


def get_git_revision() -> str:
    """Safely obtain current git commit hash if available, or return fallback."""
    try:
        rev = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return rev
    except Exception:
        return "v0.1.0-uncommitted"


class ExperimentTracker:
    """Auditable filesystem experiment memory and manifest bookkeeping manager."""

    def __init__(self, base_dir: Union[str, Path] = "experiments/runs") -> None:
        self.base_dir = Path(base_dir).resolve()

    def get_run_dir(self, run_id: str) -> Path:
        """Get the directory path for a specific experiment run."""
        return self.base_dir / run_id

    def init_run(self, run_id: Optional[str] = None) -> tuple[str, Path]:
        """Initialize the run bundle directory structure.

        Layout:
          experiments/runs/<run_id>/
            code/
            output/

        Returns:
            tuple[str, Path]: The run ID and run directory path.
        """
        actual_run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        run_dir = self.get_run_dir(actual_run_id)

        (run_dir / "code").mkdir(parents=True, exist_ok=True)
        (run_dir / "output").mkdir(parents=True, exist_ok=True)

        return actual_run_id, run_dir

    def record_spec(self, run_id: str, spec: ExperimentSpec) -> Path:
        """Record the experiment specification artifact."""
        run_dir = self.get_run_dir(run_id)
        spec_path = run_dir / "spec.json"
        spec_path.write_text(spec.to_json(), encoding="utf-8")
        return spec_path

    def record_approval_token(self, run_id: str, token: HumanGateToken) -> Path:
        """Record the human gate authorization token."""
        run_dir = self.get_run_dir(run_id)
        token_path = run_dir / "approval_token.json"
        token_path.write_text(token.to_json(), encoding="utf-8")
        return token_path

    def record_code(self, run_id: str, filename: str, code: str) -> Path:
        """Record a generated/executed script inside the run's code/ directory."""
        run_dir = self.get_run_dir(run_id)
        code_file = run_dir / "code" / filename
        code_file.parent.mkdir(parents=True, exist_ok=True)
        code_file.write_text(code, encoding="utf-8")
        return code_file

    def record_verification(self, run_id: str, report: VerificationReport) -> Path:
        """Record deterministic verification report."""
        run_dir = self.get_run_dir(run_id)
        report_path = run_dir / "verification.json"
        report_path.write_text(report.to_json(), encoding="utf-8")
        return report_path

    def generate_manifest(
        self,
        run_id: str,
        spec: Optional[ExperimentSpec] = None,
        report: Optional[VerificationReport] = None,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Compute SHA-256 checksums and write manifest.json for the run bundle.

        Preserves:
        - Code version / git revision
        - Platform / OS / Python runtime metadata
        - Evaluated seeds
        - Checksum dictionary for all files
        - Verification outcome (PASS / FAIL / ERROR)
        """
        run_dir = self.get_run_dir(run_id)
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")

        checksums = compute_directory_checksums(run_dir)
        # Exclude manifest itself from checksum list if it previously existed
        checksums.pop("manifest.json", None)

        status = report.overall_status.value if report else "UNKNOWN"

        manifest: dict[str, Any] = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "git_commit": get_git_revision(),
            "environment": {
                "python_version": sys.version,
                "platform": platform.platform(),
                "machine": platform.machine(),
                "system": platform.system(),
            },
            "spec_id": spec.spec_id if spec else None,
            "hypothesis_id": spec.hypothesis_id if spec else None,
            "random_seeds": spec.random_seeds if spec else [],
            "artifacts": checksums,
        }

        if extra_metadata:
            manifest.update(extra_metadata)

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

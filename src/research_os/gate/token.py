"""Human Gate Token manager and issuance helpers (Rule 3 Human Gate)."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from research_os.gate.approval import (
    KeyBackend,
    UnauthorizedExecutionMutation,
    canonicalize_gate_payload,
    compute_canonical_spec_hash,
    compute_child_execution_hash,
    generate_keyed_signature,
    get_default_signing_key,
    get_key_backend,
    mint_child_delegation_token,
    verify_approval_token,
)
from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.gate import GateKind, GateStatus, HumanGateToken


def _validate_spec_digest(digest: str) -> None:
    """Ensure canonical_spec_hash is an authentic 64-character SHA-256 hex string and not a placeholder."""
    if not isinstance(digest, str) or not digest:
        raise ValueError("canonical_spec_hash is required and cannot be empty.")
    if digest.startswith("hash-") or "hash-" in digest:
        raise ValueError(
            f"Invalid canonical_spec_hash '{digest}': placeholder or dummy digests like 'hash-{{spec_id}}' are strictly prohibited. "
            "An actual ExperimentSpec or genuine 64-character SHA-256 hex digest is required."
        )
    if len(digest) != 64:
        raise ValueError(
            f"Invalid canonical_spec_hash '{digest}': must be exactly 64 hexadecimal characters."
        )
    try:
        int(digest, 16)
    except ValueError:
        raise ValueError(
            f"Invalid canonical_spec_hash '{digest}': digest contains invalid hexadecimal characters."
        )


class HumanGateTokenManager:
    """Manages creation, asymmetric cryptographic signing, and verification of Rule 3 Human Gate Tokens."""

    def __init__(
        self,
        project_id: str = "research-os",
        key_backend: Optional[KeyBackend] = None,
        private_key: Optional[Any] = None,
    ):
        self.project_id = project_id
        if key_backend is not None:
            self._key_backend = key_backend
            self._private_key = key_backend.get_private_key()
        elif private_key is not None:
            self._private_key = private_key
            self._key_backend = None
        else:
            self._key_backend = get_key_backend()
            self._private_key = self._key_backend.get_private_key()

    def issue_token(
        self,
        spec: Optional[ExperimentSpec] = None,
        spec_id: Optional[str] = None,
        canonical_spec_hash: Optional[str] = None,
        decision: GateStatus | str = GateStatus.APPROVED,
        reason: Optional[str] = None,
        approver_id: str = "human_operator",
        gate_kind: GateKind = GateKind.EXPERIMENT_LAUNCH,
        payload: Optional[dict[str, Any]] = None,
        validity_duration: timedelta = timedelta(hours=2),
    ) -> HumanGateToken:
        """Issue a cryptographically signed HumanGateToken bound strictly to spec parameters.
        
        Strict Invariants:
        - Requires an actual ExperimentSpec or a genuine 64-character canonical SHA-256 digest.
        - Dummy/placeholder hashes like 'hash-{spec_id}' are strictly rejected.
        - Signs exclusively using Ed25519 asymmetric cryptography.
        """
        env_mode = os.environ.get("RESEARCH_OS_ENV", "development").lower()
        status = (
            GateStatus.APPROVED
            if str(decision).upper() in ("APPROVED", "GATESTATUS.APPROVED", "GATEDECISION.APPROVED")
            else GateStatus.REJECTED
        )

        if env_mode == "production" and approver_id in ("auto", "ci_bot", "automated"):
            raise PermissionError("Automated approvals are forbidden in production mode.")

        pay = payload.copy() if payload else {}

        # Resolve spec details and canonical hash
        if spec is not None:
            effective_spec_id = spec.spec_id
            effective_spec_hash = compute_canonical_spec_hash(spec)
            effective_entry_point = spec.entry_point
            effective_hypothesis_id = spec.hypothesis_id
            effective_resources = {
                "min_ram_gb": spec.hardware_requirements.min_ram_gb,
                "max_cpu_cores": spec.hardware_requirements.max_cpu_cores,
                "timeout_seconds": spec.timeout_seconds,
            }
        else:
            effective_spec_id = spec_id or pay.get("spec_id")
            if not effective_spec_id:
                raise ValueError("Must provide either spec (ExperimentSpec) or spec_id.")

            # Validate canonical_spec_hash
            raw_hash = canonical_spec_hash or pay.get("canonical_spec_hash")
            if raw_hash is not None:
                _validate_spec_digest(raw_hash)
                effective_spec_hash = raw_hash
            elif gate_kind == GateKind.DOMAIN_PLUGIN_INSTALL:
                # Compute authentic SHA-256 for plugin identifier
                effective_spec_hash = hashlib.sha256(effective_spec_id.encode("utf-8")).hexdigest()
            else:
                raise ValueError(
                    "The token generation API strictly requires an actual ExperimentSpec or its canonical SHA-256 digest."
                )

            effective_entry_point = pay.get("entry_point", "python run.py")
            effective_hypothesis_id = pay.get("hypothesis_id", "hyp-unspecified")
            effective_resources = pay.get("allowed_resources", {})

        gate_id = f"gate-{effective_spec_id[:12]}-{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc)
        expires_at = now + validity_duration

        pay["spec_id"] = effective_spec_id
        pay["hypothesis_id"] = pay.get("hypothesis_id", effective_hypothesis_id)
        pay["canonical_spec_hash"] = effective_spec_hash
        pay["entry_point"] = pay.get("entry_point", effective_entry_point)
        pay["allowed_resources"] = pay.get("allowed_resources", effective_resources)
        pay["expiration_timestamp"] = expires_at.isoformat()
        pay["approver_identity"] = approver_id

        token = HumanGateToken(
            gate_id=gate_id,
            project_id=self.project_id,
            voyage_id=effective_spec_id,
            kind=gate_kind,
            status=status,
            payload=pay,
            created_at=now,
            expires_at=expires_at,
        )

        if status == GateStatus.APPROVED:
            message_bytes = canonicalize_gate_payload(
                spec_id=pay["spec_id"],
                hypothesis_id=pay["hypothesis_id"],
                canonical_spec_hash=pay["canonical_spec_hash"],
                entry_point=pay["entry_point"],
                allowed_resources=pay["allowed_resources"],
                expiration_timestamp=pay["expiration_timestamp"],
                approver_identity=approver_id,
                additional_payload=pay,
            )
            sig, pub_hex = generate_keyed_signature(message_bytes, private_key=self._private_key)
            token.public_key_hex = pub_hex
            token.approve(user=approver_id, signature=sig, notes=reason)
        else:
            token.reject(user=approver_id, notes=reason)

        return token

    def mint_child_delegation_token(
        self,
        parent_token: HumanGateToken,
        seed: int,
        seed_spec: ExperimentSpec,
        seed_code_dir: Any,
        actual_seed_id: str,
        grid_cell_params: Optional[dict[str, Any]] = None,
    ) -> HumanGateToken:
        """Derive an attested child token for a specific seed under parent authorization."""
        return mint_child_delegation_token(
            parent_token=parent_token,
            seed=seed,
            seed_spec=seed_spec,
            seed_code_dir=seed_code_dir,
            actual_seed_id=actual_seed_id,
            grid_cell_params=grid_cell_params,
            private_key=self._private_key,
        )


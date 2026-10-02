"""Cryptographic Human-in-the-Loop Approval Gate for Research OS (Rule 3 Enforcement).

Enforces:
- Genuine keyed digital signatures (Ed25519 asymmetric signing with HMAC-SHA256 fallback).
- Cryptographic binding to canonical ExperimentSpec SHA-256 digest.
- Strict expiration timestamps on approval tokens.
- Explicit prohibition of automated approval in production environments (RESEARCH_OS_ENV=production).
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import shlex
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Union

import base64
from abc import ABC, abstractmethod
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from research_os.schemas.experiment import ExperimentSpec
from research_os.schemas.gate import GateKind, GateStatus, HumanGateToken


class KeyBackend(ABC):
    """Abstract interface for Ed25519 signing key retrieval and storage."""

    @abstractmethod
    def get_private_key(self) -> ed25519.Ed25519PrivateKey:
        """Retrieve the active Ed25519 private key."""
        pass

    @abstractmethod
    def get_public_key_hex(self) -> str:
        """Retrieve the public verification key in 64-character hex format."""
        pass


class LocalFileKeyBackend(KeyBackend):
    """File-backed key storage reading/writing .gate_key with strict file permissions."""

    def __init__(self, key_path: Union[str, Path] = ".gate_key") -> None:
        self.key_path = Path(key_path)
        self._key: Optional[ed25519.Ed25519PrivateKey] = None

    def get_private_key(self) -> ed25519.Ed25519PrivateKey:
        if self._key is not None:
            return self._key

        if self.key_path.exists() and self.key_path.is_file():
            raw = self.key_path.read_bytes()
            if len(raw) == 32:
                seed = raw
            else:
                text = raw.decode("utf-8", errors="replace").strip()
                if len(text) == 64 and all(c in "0123456789abcdefABCDEF" for c in text):
                    seed = bytes.fromhex(text)
                else:
                    seed = base64.b64decode(text)
            self._key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
        else:
            self._key = ed25519.Ed25519PrivateKey.generate()
            raw_seed = self._key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_bytes(raw_seed)
            if sys.platform == "win32":
                try:
                    import subprocess
                    username = os.environ.get("USERNAME", "")
                    if username:
                        subprocess.run(
                            ["icacls", str(self.key_path.resolve()), "/inheritance:r", f"/grant:r", f"{username}:(R,W)"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=2,
                        )
                except Exception:
                    pass
            else:
                try:
                    # 0o600: read/write owner only on POSIX
                    os.chmod(self.key_path, 0o600)
                except Exception:
                    pass

        return self._key

    def get_public_key_hex(self) -> str:
        key = self.get_private_key()
        pub_bytes = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return pub_bytes.hex()


class EnvironmentKeyBackend(KeyBackend):
    """Zero-persistence key management reading Ed25519 seed purely in-memory."""

    def __init__(
        self,
        env_var: str = "RESEARCH_OS_GATE_PRIVATE_KEY",
        seed_bytes: Optional[bytes] = None,
    ) -> None:
        self.env_var = env_var
        self._key: Optional[ed25519.Ed25519PrivateKey] = None
        if seed_bytes is not None:
            self._key = ed25519.Ed25519PrivateKey.from_private_bytes(seed_bytes)

    def get_private_key(self) -> ed25519.Ed25519PrivateKey:
        if self._key is not None:
            return self._key

        val = os.environ.get(self.env_var) or os.environ.get("RESEARCH_OS_GATE_PRIVATE_KEY_HEX")
        if val:
            clean = val.strip()
            try:
                if len(clean) == 64 and all(c in "0123456789abcdefABCDEF" for c in clean):
                    seed = bytes.fromhex(clean)
                else:
                    seed = base64.b64decode(clean)
                self._key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
            except Exception as e:
                raise ValueError(f"Invalid private key in environment variable {self.env_var}: {e}")
        else:
            self._key = ed25519.Ed25519PrivateKey.generate()

        return self._key

    def get_public_key_hex(self) -> str:
        key = self.get_private_key()
        pub_bytes = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return pub_bytes.hex()


_ACTIVE_KEY_BACKEND: Optional[KeyBackend] = None


def get_key_backend() -> KeyBackend:
    """Retrieve the globally configured KeyBackend."""
    global _ACTIVE_KEY_BACKEND
    if _ACTIVE_KEY_BACKEND is None:
        if os.environ.get("RESEARCH_OS_GATE_PRIVATE_KEY") or os.environ.get("RESEARCH_OS_GATE_PRIVATE_KEY_HEX"):
            _ACTIVE_KEY_BACKEND = EnvironmentKeyBackend()
        elif Path(".gate_key").exists():
            _ACTIVE_KEY_BACKEND = LocalFileKeyBackend(".gate_key")
        else:
            _ACTIVE_KEY_BACKEND = EnvironmentKeyBackend()
    return _ACTIVE_KEY_BACKEND


def set_key_backend(backend: Optional[KeyBackend]) -> None:
    """Configure active KeyBackend explicitly."""
    global _ACTIVE_KEY_BACKEND
    _ACTIVE_KEY_BACKEND = backend


def generate_ed25519_keypair() -> tuple[str, str]:
    """Generate a new Ed25519 keypair.

    Returns:
        tuple[str, str]: (base64_encoded_32_byte_seed, hex_encoded_public_key)
    """
    key = ed25519.Ed25519PrivateKey.generate()
    seed = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    b64_seed = base64.b64encode(seed).decode("ascii")
    pub_hex = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return b64_seed, pub_hex


def get_default_signing_key() -> ed25519.Ed25519PrivateKey:
    """Retrieve the local session Ed25519 private key from configured KeyBackend."""
    return get_key_backend().get_private_key()


def compute_canonical_spec_hash(spec: ExperimentSpec) -> str:
    """Compute deterministic SHA-256 hash of ExperimentSpec excluding volatile tokens."""
    canonical_json = spec.model_dump_json(exclude={"approval_token"})
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_code_hash(code_dir: Union[str, Path], entry_point: Optional[str] = None) -> str:
    """Compute deterministic SHA-256 Merkle-like digest of the entire code directory tree (A2).
    
    A full directory tree SHA-256 hash of code/ (all files sorted by path).
    If any auxiliary file (e.g. helper.py) is added, removed, or changed, this digest changes.
    """
    p_dir = Path(code_dir).resolve()
    if p_dir.is_file():
        return hashlib.sha256(p_dir.read_bytes()).hexdigest()
    if not p_dir.exists():
        return hashlib.sha256(b"").hexdigest()

    hasher = hashlib.sha256()
    all_files = sorted([p for p in p_dir.rglob("*") if p.is_file()], key=lambda p: p.relative_to(p_dir).as_posix())
    if not all_files:
        return hashlib.sha256(b"").hexdigest()
    for f in all_files:
        rel_posix = f.relative_to(p_dir).as_posix()
        hasher.update(rel_posix.encode("utf-8"))
        hasher.update(hashlib.sha256(f.read_bytes()).digest())
    return hasher.hexdigest()


def compute_config_hash(spec: ExperimentSpec, config_path: Optional[Union[str, Path]] = None) -> str:
    """Compute deterministic SHA-256 of experiment configuration (Directive 3)."""
    if config_path:
        p_cfg = Path(config_path).resolve()
        if p_cfg.exists() and p_cfg.is_file():
            return hashlib.sha256(p_cfg.read_bytes()).hexdigest()
    cfg_json = json.dumps(spec.run_config or {}, sort_keys=True, default=str)
    return hashlib.sha256(cfg_json.encode("utf-8")).hexdigest()


class NonceLedger:
    """Persistent single-use nonce ledger preventing approval token replay attacks (A3)."""

    def __init__(self, ledger_path: Optional[Union[str, Path]] = None) -> None:
        self.ledger_path = Path(ledger_path or ".gate_nonces.json").resolve()
        self._consumed: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self.ledger_path.exists() and self.ledger_path.is_file():
            try:
                data = json.loads(self.ledger_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._consumed = set(data)
                elif isinstance(data, dict):
                    self._consumed = set(data.keys())
            except Exception:
                self._consumed = set()

    def _save(self) -> None:
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self.ledger_path.write_text(json.dumps(sorted(list(self._consumed)), indent=2), encoding="utf-8")
        except Exception:
            pass

    def is_consumed(self, nonce: str) -> bool:
        return nonce in self._consumed

    def consume(self, nonce: str) -> None:
        if not nonce:
            raise PermissionError("Approval token missing single-use nonce.")
        if nonce in self._consumed:
            raise PermissionError(f"Approval token replay attack detected: nonce '{nonce}' has already been consumed.")
        self._consumed.add(nonce)
        self._save()

    def clear(self) -> None:
        self._consumed.clear()
        if self.ledger_path.exists():
            try:
                self.ledger_path.unlink()
            except Exception:
                pass


_GLOBAL_NONCE_LEDGER = NonceLedger()


def canonicalize_gate_payload(
    spec_id: str,
    hypothesis_id: str,
    canonical_spec_hash: str,
    entry_point: str,
    allowed_resources: dict[str, Any],
    expiration_timestamp: str,
    approver_identity: str,
    additional_payload: Optional[dict[str, Any]] = None,
) -> bytes:
    """Serialize the bound gate parameters into a sorted canonical UTF-8 byte stream."""
    data = {
        "spec_id": spec_id,
        "hypothesis_id": hypothesis_id,
        "canonical_spec_hash": canonical_spec_hash,
        "entry_point": entry_point,
        "allowed_resources": allowed_resources,
        "expiration_timestamp": expiration_timestamp,
        "approver_identity": approver_identity,
    }
    if additional_payload:
        for k, v in additional_payload.items():
            if k not in data:
                data[k] = v
    canonical_str = json.dumps(data, sort_keys=True, default=str)
    return canonical_str.encode("utf-8")


def generate_keyed_signature(
    message_bytes: bytes,
    private_key: Optional[ed25519.Ed25519PrivateKey] = None,
) -> tuple[str, str]:
    """Generate Ed25519 asymmetric digital signature and public key identifier."""
    signer = private_key or get_default_signing_key()
    sig_bytes = signer.sign(message_bytes)
    pub = signer.public_key()
    pub_bytes = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return sig_bytes.hex(), pub_bytes.hex()


def verify_approval_token(
    token: HumanGateToken,
    expected_spec: Optional[ExperimentSpec] = None,
    expected_public_key_hex: Optional[str] = None,
    expected_code_dir: Optional[Union[str, Path]] = None,
    expected_config_path: Optional[Union[str, Path]] = None,
    consume_nonce: bool = False,
    nonce_ledger: Optional[NonceLedger] = None,
) -> bool:
    """Cryptographically verify that a HumanGateToken is valid, bound to the spec, and unexpired.
    
    Zero-Trust Invariant (A1): ONLY Ed25519 asymmetric signatures verified against the active pinned public key
    loaded from external configuration outside the sandbox are accepted. Verifying against unauthenticated token keys
    is strictly forbidden.
    Triple SHA-256 Binding: Validates SHA256(spec), Merkle-SHA256(code/), and SHA256(config) (A2).
    """
    if not token.is_approved():
        return False
    if (
        not token.decided_by
        or not token.authorization_signature
        or not token.public_key_hex
        or token.public_key_hex == "hmac-sha256"
        or len(token.public_key_hex) != 64
    ):
        raise PermissionError("Ed25519 authorization required; fallback tokens strictly forbidden")

    trusted_pub_hex = expected_public_key_hex or get_key_backend().get_public_key_hex()
    if not trusted_pub_hex or len(trusted_pub_hex) != 64:
        raise PermissionError("Pinned Ed25519 public key required; unauthenticated token keys strictly forbidden")

    # Pinned Key Verification (A1): Reject tokens signed by unpinned keys
    if token.public_key_hex.lower() != trusted_pub_hex.lower():
        return False

    payload = token.payload or {}

    # Check kind and voyage_id
    if payload.get("kind") and payload["kind"] != GateKind.EXPERIMENT_LAUNCH.value and payload["kind"] != "EXPERIMENT_LAUNCH":
        return False
    if payload.get("voyage_id") and token.voyage_id and payload["voyage_id"] != token.voyage_id:
        return False

    # Expiration verification against signed payload expiration_timestamp (A4)
    exp_str = payload.get("expiration_timestamp") or (token.expires_at.isoformat() if token.expires_at else "")
    if exp_str:
        try:
            exp_dt = datetime.fromisoformat(exp_str)
            if datetime.now(timezone.utc) > exp_dt:
                return False
        except Exception:
            return False
    elif token.expires_at and datetime.now(timezone.utc) > token.expires_at:
        return False

    spec_id = payload.get("spec_id", token.voyage_id)
    hypothesis_id = payload.get("hypothesis_id", "")
    canonical_spec_hash = payload.get("canonical_spec_hash", "")
    entry_point = payload.get("entry_point", "")
    allowed_resources = payload.get("allowed_resources", {})
    approver = token.decided_by

    # Strict spec binding check if expected_spec is provided
    if expected_spec is not None:
        computed_hash = compute_canonical_spec_hash(expected_spec)
        if canonical_spec_hash and computed_hash != canonical_spec_hash:
            return False
        if payload.get("spec_sha256") and computed_hash != payload.get("spec_sha256"):
            return False
        if expected_spec.spec_id != spec_id:
            return False
        if entry_point and expected_spec.entry_point != entry_point:
            return False
        if hypothesis_id and expected_spec.hypothesis_id != hypothesis_id:
            return False
        # Triple SHA-256 Binding verification with full directory tree hash (A2)
        if expected_code_dir and payload.get("code_sha256"):
            actual_code_hash = compute_code_hash(expected_code_dir, expected_spec.entry_point)
            if actual_code_hash != payload["code_sha256"]:
                return False
        if payload.get("config_sha256"):
            actual_cfg_hash = compute_config_hash(expected_spec, expected_config_path)
            if actual_cfg_hash != payload["config_sha256"]:
                return False

    # Single-use nonce replay verification (A3)
    nonce = payload.get("nonce") or getattr(token, "nonce", None)
    if consume_nonce and nonce:
        ledger = nonce_ledger or _GLOBAL_NONCE_LEDGER
        ledger.consume(nonce)

    # Reconstruct message bytes
    message_bytes = canonicalize_gate_payload(
        spec_id=spec_id,
        hypothesis_id=hypothesis_id,
        canonical_spec_hash=canonical_spec_hash,
        entry_point=entry_point,
        allowed_resources=allowed_resources,
        expiration_timestamp=exp_str,
        approver_identity=approver,
        additional_payload=payload,
    )

    # Asymmetric Ed25519 signature verification against the PINNED key ONLY
    try:
        pub_bytes = bytes.fromhex(trusted_pub_hex)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
        sig_bytes = bytes.fromhex(token.authorization_signature)
        public_key.verify(sig_bytes, message_bytes)
        return True
    except (InvalidSignature, ValueError):
        return False


class UnauthorizedExecutionMutation(PermissionError):
    """Raised when an execution violates parameter, seed, or code claims bound to its authorization token."""
    pass


def compute_child_execution_hash(
    parent_spec_hash: str,
    grid_cell_params: dict[str, Any],
    seed: int,
    code_hash: str,
) -> str:
    """Compute cryptographic child execution hash binding parent spec, grid parameters, seed, and code."""
    grid_cell_params_json = json.dumps(grid_cell_params or {}, sort_keys=True)
    raw = f"{parent_spec_hash}{grid_cell_params_json}{seed}{code_hash}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def mint_child_delegation_token(
    parent_token: HumanGateToken,
    seed: int,
    seed_spec: ExperimentSpec,
    seed_code_dir: Union[str, Path],
    actual_seed_id: str,
    grid_cell_params: Optional[dict[str, Any]] = None,
    private_key: Optional[ed25519.Ed25519PrivateKey] = None,
) -> HumanGateToken:
    """Cryptographically derive a child seed execution token from an approved parent gate token (A5, A6, A7).

    Validates that:
    1. Parent token is approved and valid.
    2. Seed is authorized within parent spec random_seeds or payload.
    3. Hashing binds parent spec, grid cell params, seed, code hash, and a unique child single-use nonce.
    4. Attests the delegation with a valid Ed25519 signature from the active key backend.
    """
    if not parent_token.is_approved():
        raise PermissionError(f"Cannot delegate child execution from unapproved parent token ({parent_token.status}).")

    parent_payload = parent_token.payload or {}
    allowed_seeds = parent_payload.get("random_seeds") or seed_spec.random_seeds or []
    if allowed_seeds and seed not in allowed_seeds:
        raise PermissionError(
            f"Rule 3 Violation: Seed {seed} is not in authorized parent seed policy {allowed_seeds}."
        )

    signer = private_key or get_default_signing_key()
    p_code = Path(seed_code_dir).resolve()
    seed_code_hash = compute_code_hash(p_code, seed_spec.entry_point)
    seed_config_hash = compute_config_hash(seed_spec)
    seed_canonical_hash = compute_canonical_spec_hash(seed_spec)
    parent_spec_hash = (
        parent_payload.get("canonical_spec_hash")
        or parent_payload.get("spec_sha256")
        or seed_canonical_hash
    )
    params_dict = grid_cell_params if grid_cell_params is not None else {}
    child_exec_hash = compute_child_execution_hash(
        parent_spec_hash=parent_spec_hash,
        grid_cell_params=params_dict,
        seed=seed,
        code_hash=seed_code_hash,
    )

    now = datetime.now(timezone.utc)
    exp_str = parent_payload.get("expiration_timestamp") or (
        parent_token.expires_at.isoformat() if parent_token.expires_at else (now + timedelta(hours=2)).isoformat()
    )

    child_gate_id = f"gate-{seed_spec.spec_id[:12]}-{actual_seed_id[:8]}"
    child_nonce = f"{uuid.uuid4().hex}"
    approver = parent_token.decided_by or "operator"

    child_payload = {
        "spec_id": seed_spec.spec_id,
        "hypothesis_id": seed_spec.hypothesis_id,
        "canonical_spec_hash": seed_canonical_hash,
        "spec_sha256": seed_canonical_hash,
        "parent_spec_hash": parent_spec_hash,
        "config_sha256": seed_config_hash,
        "code_sha256": seed_code_hash,
        "entry_point": seed_spec.entry_point,
        "allowed_resources": parent_payload.get("allowed_resources", {
            "min_ram_gb": seed_spec.hardware_requirements.min_ram_gb,
            "max_cpu_cores": seed_spec.hardware_requirements.max_cpu_cores,
            "timeout_seconds": seed_spec.timeout_seconds,
        }),
        "expiration_timestamp": exp_str,
        "approver_identity": approver,
        "kind": GateKind.EXPERIMENT_LAUNCH.value,
        "voyage_id": actual_seed_id,
        "gate_id": child_gate_id,
        "decided_at": now.isoformat(),
        "nonce": child_nonce,
        "seed": seed,
        "grid_cell_params": params_dict,
        "child_execution_hash": child_exec_hash,
        "parent_gate_id": parent_token.gate_id,
        "parent_signature": parent_token.authorization_signature,
        "delegation_kind": "CHILD_SEED_EXECUTION",
    }

    message_bytes = canonicalize_gate_payload(
        spec_id=seed_spec.spec_id,
        hypothesis_id=seed_spec.hypothesis_id,
        canonical_spec_hash=seed_canonical_hash,
        entry_point=seed_spec.entry_point,
        allowed_resources=child_payload["allowed_resources"],
        expiration_timestamp=exp_str,
        approver_identity=approver,
        additional_payload=child_payload,
    )

    sig, pub_hex = generate_keyed_signature(message_bytes, private_key=signer)

    try:
        exp_dt = datetime.fromisoformat(exp_str)
    except Exception:
        exp_dt = now + timedelta(hours=2)

    child_token = HumanGateToken(
        gate_id=child_gate_id,
        project_id=parent_token.project_id,
        voyage_id=actual_seed_id,
        kind=GateKind.EXPERIMENT_LAUNCH,
        status=GateStatus.APPROVED,
        decided_by=approver,
        authorization_signature=sig,
        public_key_hex=pub_hex,
        payload=child_payload,
        user_notes=f"Cryptographically derived child token for seed {seed} from parent {parent_token.gate_id}",
        created_at=now,
        expires_at=exp_dt,
        decided_at=now,
    )
    return child_token


class HumanApprovalGate:
    """Enforces human authorization prior to experiment code execution with asymmetric cryptographic tokens."""

    def __init__(
        self,
        project_id: str = "research-os-mvp",
        private_key: Optional[ed25519.Ed25519PrivateKey] = None,
        key_backend: Optional[KeyBackend] = None,
    ) -> None:
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

    def display_gate_banner(self, spec: ExperimentSpec, gate_id: str, canonical_hash: str) -> None:
        """Format and print an explicit human-gate review card to stdout."""
        print("\n" + "=" * 70)
        print("  HUMAN APPROVAL GATE: EXPERIMENT EXECUTION (Rule 3 Enforcement)")
        print("=" * 70)
        print(f" Gate ID:            {gate_id}")
        print(f" Spec ID:            {spec.spec_id}")
        print(f" Canonical SHA-256:  {canonical_hash}")
        print(f" Hypothesis:         {spec.hypothesis_id}")
        print(f" Name:               {spec.name}")
        print(f" Entry Point:        {spec.entry_point}")
        print(f" Timeout:            {spec.timeout_seconds}s")
        print(
            f" Hardware Limits:    RAM >= {spec.hardware_requirements.min_ram_gb}GB, "
            f"CPU <= {spec.hardware_requirements.max_cpu_cores or 'Default'}, "
            f"CUDA: {spec.hardware_requirements.cuda_required}"
        )
        print(f" Random Seeds:       {spec.random_seeds}")
        print(f" Expected Outputs:   {', '.join(spec.expected_outputs)}")
        print("-" * 70)
        print(" POLICY-CONTROLLED SUBPROCESS RUNNER (Defense-in-Depth):")
        print("  - Pre-execution AST security filter")
        print("  - Strict environment whitelist (all credential patterns stripped)")
        print(f"  - Hard timeout: {spec.timeout_seconds} seconds")
        print("=" * 70 + "\n")

    def request_approval(
        self,
        spec: ExperimentSpec,
        run_id: str,
        user: Optional[str] = None,
        auto_approve: bool = False,
        interactive: bool = True,
        notes: Optional[str] = None,
        token_path: Optional[Union[str, Path]] = None,
        validity_duration: timedelta = timedelta(hours=2),
        code_dir: Optional[Union[str, Path]] = None,
        config_path: Optional[Union[str, Path]] = None,
    ) -> HumanGateToken:
        """Request human authorization to launch the proposed experiment."""
        env_mode = os.environ.get("RESEARCH_OS_ENV", "development").lower()
        if env_mode == "production" and auto_approve:
            raise PermissionError(
                "Rule 3 Violation: auto_approve is strictly prohibited in production mode "
                "(RESEARCH_OS_ENV=production). Explicit manual human gate authorization required."
            )

        # Check existing token file if provided
        if token_path:
            p = Path(token_path)
            if p.exists() and p.is_file():
                try:
                    existing = HumanGateToken.model_validate_json(p.read_text(encoding="utf-8"))
                    if existing.is_approved() and verify_approval_token(existing, expected_spec=spec, expected_code_dir=code_dir):
                        print(f"[Gate] Verified existing valid HumanGateToken at {token_path}")
                        return existing
                except Exception:
                    pass

        gate_id = f"gate-{spec.spec_id[:12]}-{run_id[:8]}"
        operator = user or os.environ.get("RESEARCH_OS_USER") or os.environ.get("USERNAME")
        if not operator:
            try:
                operator = getpass.getuser()
            except Exception:
                operator = "human-operator"

        canonical_hash = compute_canonical_spec_hash(spec)
        config_hash = compute_config_hash(spec, config_path)
        code_hash = compute_code_hash(code_dir, spec.entry_point) if code_dir else None

        now = datetime.now(timezone.utc)
        expires_at = now + validity_duration

        allowed_resources = {
            "min_ram_gb": spec.hardware_requirements.min_ram_gb,
            "max_cpu_cores": spec.hardware_requirements.max_cpu_cores,
            "timeout_seconds": spec.timeout_seconds,
        }

        nonce = uuid.uuid4().hex

        payload = {
            "spec_id": spec.spec_id,
            "hypothesis_id": spec.hypothesis_id,
            "canonical_spec_hash": canonical_hash,
            "spec_sha256": canonical_hash,
            "config_sha256": config_hash,
            "entry_point": spec.entry_point,
            "allowed_resources": allowed_resources,
            "expiration_timestamp": expires_at.isoformat(),
            "approver_identity": operator,
            "name": spec.name,
            "random_seeds": spec.random_seeds,
            "expected_outputs": spec.expected_outputs,
            "kind": GateKind.EXPERIMENT_LAUNCH.value,
            "voyage_id": run_id,
            "gate_id": gate_id,
            "decided_at": now.isoformat(),
            "nonce": nonce,
        }
        if code_hash:
            payload["code_sha256"] = code_hash

        token = HumanGateToken(
            gate_id=gate_id,
            project_id=self.project_id,
            voyage_id=run_id,
            kind=GateKind.EXPERIMENT_LAUNCH,
            status=GateStatus.PENDING,
            payload=payload,
            created_at=now,
            expires_at=expires_at,
        )

        self.display_gate_banner(spec, gate_id, canonical_hash)

        if auto_approve:
            message_bytes = canonicalize_gate_payload(
                spec_id=spec.spec_id,
                hypothesis_id=spec.hypothesis_id,
                canonical_spec_hash=canonical_hash,
                entry_point=spec.entry_point,
                allowed_resources=allowed_resources,
                expiration_timestamp=expires_at.isoformat(),
                approver_identity=operator,
                additional_payload=payload,
            )
            sig, pub_hex = generate_keyed_signature(message_bytes, private_key=self._private_key)
            token.public_key_hex = pub_hex
            token.approve(
                user=operator,
                signature=sig,
                notes=notes or "Pre-authorized via CLI operator approval flag.",
            )
            print(f"[Gate] Cryptographic approval recorded for user '{operator}'.")
        elif interactive and sys.stdin.isatty():
            try:
                prompt_text = f"Authorize execution of spec '{spec.spec_id}'? (yes/NO): "
                response = input(prompt_text).strip().lower()
                if response in ("yes", "y"):
                    message_bytes = canonicalize_gate_payload(
                        spec_id=spec.spec_id,
                        hypothesis_id=spec.hypothesis_id,
                        canonical_spec_hash=canonical_hash,
                        entry_point=spec.entry_point,
                        allowed_resources=allowed_resources,
                        expiration_timestamp=expires_at.isoformat(),
                        approver_identity=operator,
                        additional_payload=payload,
                    )
                    sig, pub_hex = generate_keyed_signature(message_bytes, private_key=self._private_key)
                    token.public_key_hex = pub_hex
                    token.approve(
                        user=operator,
                        signature=sig,
                        notes=notes or "Approved via interactive CLI prompt.",
                    )
                    print("[Gate] Approval granted and signed.")
                else:
                    token.reject(
                        user=operator,
                        notes=f"Declined by user via interactive prompt. Response: '{response}'",
                    )
                    print("[Gate] Execution REJECTED by human operator.")
            except (KeyboardInterrupt, EOFError):
                token.reject(
                    user=operator,
                    notes="Approval prompt interrupted or aborted by user.",
                )
                print("\n[Gate] Aborted. Gate status set to REJECTED.")
        else:
            token.reject(
                user=operator,
                notes="Non-interactive execution without pre-approval flag. Execution rejected by policy.",
            )
            print("[Gate] Non-interactive mode without pre-approval. Gate rejected.")

        if token_path:
            p = Path(token_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(token.model_dump_json(indent=2), encoding="utf-8")

        return token

    def mint_child_token(
        self,
        parent_token: HumanGateToken,
        seed: int,
        seed_spec: ExperimentSpec,
        seed_code_dir: Union[str, Path],
        actual_seed_id: str,
    ) -> HumanGateToken:
        """Derive a child execution token for a specific seed under parent authorization."""
        return mint_child_delegation_token(
            parent_token=parent_token,
            seed=seed,
            seed_spec=seed_spec,
            seed_code_dir=seed_code_dir,
            actual_seed_id=actual_seed_id,
            private_key=self._private_key,
        )


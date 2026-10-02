"""Cryptographic Approval Gate for Staged Domain Plugins (Rule 3 Enforcement).

Enforces:
- Cryptographic binding of plugin.json and generator.py to canonical Ed25519 digital signature.
- Immediate fail-closed tamper interception if staged files are altered post-approval.
- Complete separation between experimental capability generation and trusted verification authority.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Union
from pydantic import Field

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from research_os.domains.declarative import DeclarativePluginSpec
from research_os.gate.approval import get_default_signing_key, get_key_backend
from research_os.schemas.base import ArtifactBaseModel
from research_os.verify.deterministic import compute_file_sha256


class PluginApprovalToken(ArtifactBaseModel):
    """Cryptographic authorization token admitting a staged domain plugin into the registry."""

    token_id: str = Field(default_factory=lambda: f"tok-plugin-{uuid.uuid4().hex[:8]}")
    domain_id: str = Field(description="Approved domain identifier")
    canonical_plugin_hash: str = Field(description="SHA-256 digest of spec_sha + generator_sha + interface_version")
    generator_sha256: str = Field(description="SHA-256 hash of generator.py on disk")
    spec_sha256: str = Field(description="SHA-256 hash of plugin.json on disk")
    interface_version: str = Field(default="1.0.0", description="Contract interface version")
    allowed_dependencies: list[str] = Field(default_factory=list, description="Permitted runtime library dependencies")
    expiration_timestamp: str = Field(description="ISO-8601 UTC timestamp after which token expires")
    approver_identity: str = Field(description="Human operator identifier who granted authorization")
    signature: str = Field(description="Hex-encoded Ed25519 signature over canonical token payload")
    public_key_hex: str = Field(description="Hex-encoded Ed25519 public verification key")


def compute_canonical_plugin_hash(
    plugin_json_sha256: str,
    generator_py_sha256: str,
    interface_version: str,
) -> str:
    """Compute deterministic SHA-256 digest: SHA256(plugin.json_sha256 + generator.py_sha256 + interface_version)."""
    raw = f"{plugin_json_sha256}{generator_py_sha256}{interface_version}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def canonicalize_plugin_token_payload(
    domain_id: str,
    canonical_plugin_hash: str,
    generator_sha256: str,
    spec_sha256: str,
    interface_version: str,
    allowed_dependencies: list[str],
    expiration_timestamp: str,
    approver_identity: str,
) -> bytes:
    """Serialize the bound plugin parameters into a canonical sorted UTF-8 JSON byte stream."""
    data = {
        "allowed_dependencies": sorted(allowed_dependencies),
        "approver_identity": approver_identity,
        "canonical_plugin_hash": canonical_plugin_hash,
        "domain_id": domain_id,
        "expiration_timestamp": expiration_timestamp,
        "generator_sha256": generator_sha256,
        "interface_version": interface_version,
        "spec_sha256": spec_sha256,
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def create_plugin_approval_token(
    staged_dir: Union[str, Path],
    approver_identity: str = "Operator",
    expiration_hours: int = 72,
    private_key: Optional[ed25519.Ed25519PrivateKey] = None,
    allowed_dependencies: Optional[list[str]] = None,
) -> PluginApprovalToken:
    """Cryptographically sign a staged domain plugin with Ed25519 signature."""
    staged_path = Path(staged_dir).resolve()
    spec_file = staged_path / "plugin.json"
    generator_file = staged_path / "generator.py"

    if not spec_file.exists():
        raise FileNotFoundError(f"Missing staged plugin.json at: {spec_file}")
    if not generator_file.exists():
        raise FileNotFoundError(f"Missing staged generator.py at: {generator_file}")

    # Validate DeclarativePluginSpec schema
    spec_data = json.loads(spec_file.read_text(encoding="utf-8"))
    spec = DeclarativePluginSpec.model_validate(spec_data)

    spec_sha = compute_file_sha256(spec_file)
    gen_sha = compute_file_sha256(generator_file)
    canonical_hash = compute_canonical_plugin_hash(spec_sha, gen_sha, spec.interface_version)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=expiration_hours)
    deps = allowed_dependencies or spec.allowed_dependencies or ["numpy", "pydantic"]

    signer = private_key or get_default_signing_key()
    pub_bytes = signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    payload_bytes = canonicalize_plugin_token_payload(
        domain_id=spec.domain_id,
        canonical_plugin_hash=canonical_hash,
        generator_sha256=gen_sha,
        spec_sha256=spec_sha,
        interface_version=spec.interface_version,
        allowed_dependencies=deps,
        expiration_timestamp=expires_at.isoformat(),
        approver_identity=approver_identity,
    )
    sig_bytes = signer.sign(payload_bytes)

    token = PluginApprovalToken(
        domain_id=spec.domain_id,
        canonical_plugin_hash=canonical_hash,
        generator_sha256=gen_sha,
        spec_sha256=spec_sha,
        interface_version=spec.interface_version,
        allowed_dependencies=sorted(deps),
        expiration_timestamp=expires_at.isoformat(),
        approver_identity=approver_identity,
        signature=sig_bytes.hex(),
        public_key_hex=pub_bytes.hex(),
    )

    token_file = staged_path / "plugin_approval.token"
    token_file.write_text(token.to_json(), encoding="utf-8")
    return token


def verify_plugin_approval_token(
    staged_dir: Union[str, Path],
    token: Optional[PluginApprovalToken] = None,
    expected_public_key: Optional[str] = None,
) -> bool:
    """Verify cryptographic authenticity and tamper-resistance of a staged plugin."""
    staged_path = Path(staged_dir).resolve()
    spec_file = staged_path / "plugin.json"
    generator_file = staged_path / "generator.py"
    token_file = staged_path / "plugin_approval.token"

    if token is None:
        if not token_file.exists():
            raise PermissionError(f"Plugin admission rejected: missing plugin_approval.token in {staged_path}")
        token_data = json.loads(token_file.read_text(encoding="utf-8"))
        token = PluginApprovalToken.model_validate(token_data)

    if not spec_file.exists():
        raise PermissionError("Plugin tampered post-approval: plugin.json missing on disk")
    if not generator_file.exists():
        raise PermissionError("Plugin tampered post-approval: generator.py missing on disk")

    # Expiration check
    now = datetime.now(timezone.utc)
    try:
        exp_dt = datetime.fromisoformat(token.expiration_timestamp)
        if now > exp_dt:
            raise PermissionError(f"Plugin authorization expired at {token.expiration_timestamp}")
    except (ValueError, TypeError):
        raise PermissionError("Plugin admission rejected: malformed expiration timestamp")

    # Check file checksums against token
    cur_spec_sha = compute_file_sha256(spec_file)
    cur_gen_sha = compute_file_sha256(generator_file)

    if cur_spec_sha != token.spec_sha256:
        raise PermissionError(
            f"Plugin tampered post-approval: plugin.json hash mismatch "
            f"(expected {token.spec_sha256[:8]}, got {cur_spec_sha[:8]})"
        )

    if cur_gen_sha != token.generator_sha256:
        raise PermissionError(
            f"Plugin tampered post-approval: generator.py hash mismatch "
            f"(expected {token.generator_sha256[:8]}, got {cur_gen_sha[:8]})"
        )

    cur_canonical_hash = compute_canonical_plugin_hash(cur_spec_sha, cur_gen_sha, token.interface_version)
    if cur_canonical_hash != token.canonical_plugin_hash:
        raise PermissionError("Plugin tampered post-approval: canonical plugin hash mismatch")

    # Validate Ed25519 signature
    pub_key_hex = expected_public_key or token.public_key_hex
    if len(pub_key_hex) != 64:
        raise PermissionError("Plugin admission rejected: invalid public key length")

    try:
        pub_key_bytes = bytes.fromhex(pub_key_hex)
        verifier = ed25519.Ed25519PublicKey.from_public_bytes(pub_key_bytes)
        payload_bytes = canonicalize_plugin_token_payload(
            domain_id=token.domain_id,
            canonical_plugin_hash=token.canonical_plugin_hash,
            generator_sha256=token.generator_sha256,
            spec_sha256=token.spec_sha256,
            interface_version=token.interface_version,
            allowed_dependencies=token.allowed_dependencies,
            expiration_timestamp=token.expiration_timestamp,
            approver_identity=token.approver_identity,
        )
        sig_bytes = bytes.fromhex(token.signature)
        verifier.verify(sig_bytes, payload_bytes)
    except InvalidSignature:
        raise PermissionError("Plugin tampered post-approval: cryptographic signature invalid")
    except Exception as exc:
        raise PermissionError(f"Plugin tampered post-approval: verification failure: {exc}")

    return True

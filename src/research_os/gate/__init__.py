"""Human approval gate package for Research OS (Rule 3 Enforcement)."""

from __future__ import annotations

from .approval import (
    EnvironmentKeyBackend,
    HumanApprovalGate,
    KeyBackend,
    LocalFileKeyBackend,
    UnauthorizedExecutionMutation,
    compute_canonical_spec_hash,
    compute_child_execution_hash,
    generate_ed25519_keypair,
    generate_keyed_signature,
    get_key_backend,
    mint_child_delegation_token,
    set_key_backend,
    verify_approval_token,
)
from .plugin_approval import (
    PluginApprovalToken,
    compute_canonical_plugin_hash,
    create_plugin_approval_token,
    verify_plugin_approval_token,
)
from .token import HumanGateTokenManager

__all__ = [
    "EnvironmentKeyBackend",
    "HumanApprovalGate",
    "HumanGateTokenManager",
    "KeyBackend",
    "LocalFileKeyBackend",
    "PluginApprovalToken",
    "UnauthorizedExecutionMutation",
    "compute_canonical_spec_hash",
    "compute_child_execution_hash",
    "compute_canonical_plugin_hash",
    "create_plugin_approval_token",
    "generate_ed25519_keypair",
    "generate_keyed_signature",
    "get_key_backend",
    "mint_child_delegation_token",
    "set_key_backend",
    "verify_approval_token",
    "verify_plugin_approval_token",
]

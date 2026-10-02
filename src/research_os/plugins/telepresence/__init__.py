"""Telepresence domain plugin package."""

from .plugin import TelepresencePlugin
from .schemas import TelepresenceConfig

__all__ = [
    "TelepresencePlugin",
    "TelepresenceConfig",
]

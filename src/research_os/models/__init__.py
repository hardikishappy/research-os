"""Pluggable model provider interfaces for Research OS."""

from __future__ import annotations

import os
from typing import Any, Optional
from .base import BaseModelAdapter, ModelResponse, ModelUsage
from .mock import MockModelAdapter
from .openai_adapter import OpenAIModelAdapter
from .anthropic_adapter import AnthropicModelAdapter
from .gemini_adapter import GeminiModelAdapter
from .local_adapter import LocalModelAdapter


def get_model_adapter(
    provider: str,
    model_name: Optional[str] = None,
    **kwargs: Any,
) -> BaseModelAdapter:
    """Factory creating a model adapter by provider name without vendor lock-in.

    Supported providers:
      - 'mock': MockModelAdapter (for offline unit testing)
      - 'openai': OpenAIModelAdapter
      - 'anthropic': AnthropicModelAdapter
      - 'gemini' or 'google': GeminiModelAdapter
      - 'local': LocalModelAdapter (Ollama / vLLM)
    """
    provider_lower = provider.lower().strip()
    if provider_lower == "mock":
        return MockModelAdapter(model_name=model_name or "mock-model", **kwargs)
    elif provider_lower == "openai":
        return OpenAIModelAdapter(model_name=model_name or "gpt-4o", **kwargs)
    elif provider_lower == "anthropic":
        return AnthropicModelAdapter(model_name=model_name or "claude-3-5-sonnet-20241022", **kwargs)
    elif provider_lower in ("gemini", "google"):
        resolved_gemini = (
            model_name
            or os.environ.get("RESEARCH_OS_GEMINI_MODEL")
            or "gemini-3.5-flash"
        )
        return GeminiModelAdapter(model_name=resolved_gemini, **kwargs)
    elif provider_lower == "local":
        return LocalModelAdapter(model_name=model_name or "llama3:latest", **kwargs)
    else:
        raise ValueError(
            f"Unsupported model provider '{provider}'. Must be one of: "
            f"['mock', 'openai', 'anthropic', 'gemini', 'local']"
        )


__all__ = [
    "BaseModelAdapter",
    "ModelResponse",
    "ModelUsage",
    "MockModelAdapter",
    "OpenAIModelAdapter",
    "AnthropicModelAdapter",
    "GeminiModelAdapter",
    "LocalModelAdapter",
    "get_model_adapter",
]

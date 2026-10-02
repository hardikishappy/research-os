"""Base model adapter interfaces for Research OS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class ModelUsage(BaseModel):
    """Token consumption statistics for a model invocation."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ModelResponse(BaseModel):
    """Standardized completion response from any model provider."""

    content: str = Field(description="Raw text content produced by the model")
    model_name: str = Field(description="Identifier of model that generated this completion")
    usage: ModelUsage = Field(default_factory=ModelUsage, description="Token consumption metrics")
    finish_reason: Optional[str] = Field(default=None, description="Completion stop reason")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Provider-specific response metadata")


class BaseModelAdapter(ABC):
    """Abstract base class for all pluggable model providers in Research OS.

    Enforces uniform interfaces for text generation and structured Pydantic
    extraction across OpenAI, Anthropic, Gemini, Local (Ollama/vLLM), and Mock providers.
    """

    def __init__(
        self,
        model_name: str,
        temperature: float = 0.2,
        max_tokens: Optional[int] = 4096,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_key = api_key
        self.base_url = base_url
        self.extra_config = kwargs

    @abstractmethod
    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Generate unstructured text from a prompt."""
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> T:
        """Generate and deterministically validate a structured Pydantic artifact."""
        pass

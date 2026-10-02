"""Mock model adapter for deterministic offline unit testing."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional, TypeVar
from pydantic import BaseModel
from .base import BaseModelAdapter, ModelResponse, ModelUsage

T = TypeVar("T", bound=BaseModel)


class MockModelAdapter(BaseModelAdapter):
    """Deterministic mock provider that records calls and returns predefined outputs."""

    def __init__(
        self,
        model_name: str = "mock-model",
        default_text: str = "Mock response from Research OS model provider.",
        **kwargs: Any,
    ) -> None:
        super().__init__(model_name=model_name, **kwargs)
        self.default_text = default_text
        self.call_history: list[dict[str, Any]] = []
        self._text_queue: list[str] = []
        self._structured_queue: list[Any] = []
        self._custom_handler: Optional[Callable[[str, Optional[str]], str]] = None

    def queue_text_response(self, text: str) -> None:
        """Enqueue a text completion to be returned on subsequent calls."""
        self._text_queue.append(text)

    def queue_structured_response(self, response: Any) -> None:
        """Enqueue an object, dict, or Pydantic instance to be returned on structured calls."""
        self._structured_queue.append(response)

    def set_custom_handler(self, handler: Callable[[str, Optional[str]], str]) -> None:
        """Set a dynamic callback function for generating responses."""
        self._custom_handler = handler

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> ModelResponse:
        self.call_history.append({
            "type": "text",
            "prompt": prompt,
            "system_prompt": system_prompt,
            "kwargs": kwargs,
        })
        if self._custom_handler:
            content = self._custom_handler(prompt, system_prompt)
        elif self._text_queue:
            content = self._text_queue.pop(0)
        else:
            content = self.default_text

        return ModelResponse(
            content=content,
            model_name=self.model_name,
            usage=ModelUsage(prompt_tokens=len(prompt) // 4, completion_tokens=len(content) // 4, total_tokens=(len(prompt) + len(content)) // 4),
            finish_reason="stop",
            metadata={"mock": True},
        )

    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> T:
        self.call_history.append({
            "type": "structured",
            "prompt": prompt,
            "system_prompt": system_prompt,
            "response_model": response_model.__name__,
            "kwargs": kwargs,
        })
        if self._structured_queue:
            item = self._structured_queue.pop(0)
            if isinstance(item, response_model):
                return item
            if isinstance(item, dict):
                return response_model.model_validate(item)
            if isinstance(item, str):
                return response_model.model_validate_json(item)

        # Fallback: check if text queue has valid JSON
        if self._text_queue:
            text = self._text_queue.pop(0)
            return response_model.model_validate_json(text)

        # Build dummy instance using model schema defaults if available
        raise ValueError(
            f"MockModelAdapter has no queued response for structured model: {response_model.__name__}"
        )

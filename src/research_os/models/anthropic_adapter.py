"""Anthropic Claude model provider adapter."""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error
from typing import Any, Optional, TypeVar
from pydantic import BaseModel
from .base import BaseModelAdapter, ModelResponse, ModelUsage

T = TypeVar("T", bound=BaseModel)


class AnthropicModelAdapter(BaseModelAdapter):
    """Adapter for Anthropic Claude models (e.g. claude-3-5-sonnet, claude-3-5-haiku)."""

    def __init__(
        self,
        model_name: str = "claude-3-5-sonnet-20241022",
        temperature: float = 0.2,
        max_tokens: Optional[int] = 4096,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        url = base_url or os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
        super().__init__(
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=key,
            base_url=url.rstrip("/"),
            **kwargs,
        )

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic API request failed ({e.code}): {err_body}") from e
        except Exception as e:
            raise RuntimeError(f"Anthropic connection error: {e}") from e

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens or 4096,
            "temperature": kwargs.get("temperature", self.temperature),
        }
        if system_prompt:
            payload["system"] = system_prompt

        resp = self._post("messages", payload)
        content_blocks = resp.get("content", [])
        text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
        usage_data = resp.get("usage", {})
        usage = ModelUsage(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
        )
        return ModelResponse(
            content=text,
            model_name=self.model_name,
            usage=usage,
            finish_reason=resp.get("stop_reason"),
            metadata=resp,
        )

    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> T:
        schema = response_model.model_json_schema()
        instructions = (
            f"You are a structured data extractor. You must respond ONLY with a raw JSON object "
            f"validating against this JSON schema:\n{json.dumps(schema, indent=2)}\n"
            f"Do not write markdown ```json code blocks or preamble."
        )
        combined_sys = f"{system_prompt or ''}\n\n{instructions}".strip()
        resp = self.generate_text(prompt, system_prompt=combined_sys, **kwargs)
        raw_text = resp.content.strip()

        # Handle markdown fence if model included it
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1)

        return response_model.model_validate_json(raw_text)

"""Local model provider adapter for Ollama, vLLM, and LM Studio."""

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


class LocalModelAdapter(BaseModelAdapter):
    """Adapter for locally hosted models running via Ollama, vLLM, or LM Studio."""

    def __init__(
        self,
        model_name: str = "llama3:latest",
        temperature: float = 0.2,
        max_tokens: Optional[int] = 4096,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        url = base_url or os.environ.get("LOCAL_MODEL_BASE_URL", "http://localhost:11434/v1")
        key = api_key or os.environ.get("LOCAL_MODEL_API_KEY", "no-key-required")
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
            "Authorization": f"Bearer {self.api_key}",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Local model request failed ({e.code}): {err_body}") from e
        except Exception as e:
            raise RuntimeError(f"Local model connection error: {e}") from e

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> ModelResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        resp = self._post("chat/completions", payload)
        choice = resp["choices"][0]
        content = choice["message"]["content"] or ""
        usage_data = resp.get("usage", {})
        usage = ModelUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )
        return ModelResponse(
            content=content,
            model_name=self.model_name,
            usage=usage,
            finish_reason=choice.get("finish_reason"),
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
            f"\nStrict requirement: Respond ONLY with a valid JSON object conforming to this schema:\n"
            f"{json.dumps(schema, indent=2)}\n"
            f"Do not write markdown fences or explanation."
        )
        combined_sys = f"{system_prompt or ''}\n{instructions}".strip()

        messages = [
            {"role": "system", "content": combined_sys},
            {"role": "user", "content": prompt},
        ]
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "response_format": {"type": "json_object"},
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        resp = self._post("chat/completions", payload)
        content = resp["choices"][0]["message"]["content"].strip()
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            content = match.group(1)

        return response_model.model_validate_json(content)

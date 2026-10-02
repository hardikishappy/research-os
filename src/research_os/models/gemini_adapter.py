"""Google Gemini model provider adapter."""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Optional, TypeVar
from pydantic import BaseModel
from .base import BaseModelAdapter, ModelResponse, ModelUsage

T = TypeVar("T", bound=BaseModel)


class GeminiModelAdapter(BaseModelAdapter):
    """Adapter for Google Gemini models (e.g. gemini-2.5-pro, gemini-2.5-flash)."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = 4096,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        resolved_model = (
            model_name
            or os.environ.get("RESEARCH_OS_GEMINI_MODEL")
            or "gemini-3.5-flash"
        )
        key = api_key or os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            for p in (Path(".env"), Path(__file__).resolve().parents[3] / ".env"):
                if p.exists():
                    for line in p.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line.startswith("GEMINI_API_KEY="):
                            key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
                    if key:
                        break
        url = base_url or "https://generativelanguage.googleapis.com/v1beta"
        super().__init__(
            model_name=resolved_model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=key,
            base_url=url.rstrip("/"),
            **kwargs,
        )

    def _post(self, model: str, payload: dict[str, Any], max_retries: int = 2) -> dict[str, Any]:
        import time
        url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        data = json.dumps(payload).encode("utf-8")

        last_error = None
        for attempt in range(max_retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = resp.read().decode("utf-8")
                    return json.loads(body)
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                try:
                    err_json = json.loads(err_body)
                    err_msg = err_json.get("error", {}).get("message", err_body)
                except Exception:
                    err_msg = err_body

                # Check if quota exceeded on gemini-3.5-flash, attempt high-throughput fallback
                if e.code == 429 and "Quota exceeded" in err_msg and "gemini-3.5-flash" in model and "lite" not in model:
                    fallback_url = f"{self.base_url}/models/gemini-3.5-flash-lite:generateContent?key={self.api_key}"
                    fallback_req = urllib.request.Request(fallback_url, data=data, headers=headers, method="POST")
                    try:
                        with urllib.request.urlopen(fallback_req, timeout=60) as resp:
                            return json.loads(resp.read().decode("utf-8"))
                    except Exception:
                        pass

                # Check if transient 503 or 429
                if e.code in (503, 429) and attempt < max_retries:
                    wait_time = 2.0 * (attempt + 1)
                    time.sleep(wait_time)
                    continue

                raise RuntimeError(f"Gemini API request failed ({e.code}): {err_msg}") from e
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(1.0)
                    continue
                raise RuntimeError(f"Gemini connection error: {e}") from e

        if last_error:
            raise RuntimeError(f"Gemini connection failed after retries: {last_error}")
        raise RuntimeError("Gemini request failed: unexpected loop exit")

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> ModelResponse:
        gen_config: dict[str, Any] = {
            "temperature": kwargs.get("temperature", self.temperature),
        }
        if self.max_tokens:
            gen_config["maxOutputTokens"] = self.max_tokens

        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        resp = self._post(self.model_name, payload)
        candidates = resp.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Gemini returned no candidates: {resp}")

        first = candidates[0]
        parts = first.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        usage_meta = resp.get("usageMetadata", {})
        usage = ModelUsage(
            prompt_tokens=usage_meta.get("promptTokenCount", 0),
            completion_tokens=usage_meta.get("candidatesTokenCount", 0),
            total_tokens=usage_meta.get("totalTokenCount", 0),
        )
        return ModelResponse(
            content=text,
            model_name=self.model_name,
            usage=usage,
            finish_reason=first.get("finishReason"),
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
        gen_config: dict[str, Any] = {
            "temperature": kwargs.get("temperature", self.temperature),
            "responseMimeType": "application/json",
            "responseSchema": schema,
        }
        if self.max_tokens:
            gen_config["maxOutputTokens"] = self.max_tokens

        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        try:
            resp = self._post(self.model_name, payload)
            candidates = resp.get("candidates", [])
            if candidates:
                raw_text = candidates[0]["content"]["parts"][0].get("text", "")
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
                if match:
                    raw_text = match.group(1)
                return response_model.model_validate_json(raw_text)
        except Exception:
            # Fallback to plain prompt with json schema instructions
            pass

        json_prompt = (
            f"{prompt}\n\nIMPORTANT: Respond ONLY with a valid JSON object matching this schema:\n"
            f"{json.dumps(schema, indent=2)}"
        )
        resp = self.generate_text(json_prompt, system_prompt=system_prompt, **kwargs)
        raw_text = resp.content
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1)
        else:
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                raw_text = raw_text[start : end + 1]
        return response_model.model_validate_json(raw_text)

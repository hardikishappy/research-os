"""Health check utilities for model provider connectivity."""

from __future__ import annotations

import time
from typing import Any, Optional
from pydantic import BaseModel, Field

from research_os.models import get_model_adapter


class HealthCheckResult(BaseModel):
    """Result of a model adapter health connectivity check."""

    provider: str
    model_name: str
    status: str = Field(description="'OK', 'DEGRADED', or 'FAILED'")
    text_generation_ok: bool = False
    structured_generation_ok: bool = False
    latency_ms: float = 0.0
    message: str = ""
    error: Optional[str] = None


class _HealthPingResponse(BaseModel):
    ping: str
    status: int


def check_model_health(
    provider: str = "gemini",
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
) -> HealthCheckResult:
    """Perform a live smoke test against a model provider adapter.

    Tests both basic text generation and schema-constrained structured output.
    Catches rate limits, authentication failures, and network errors gracefully.
    """
    start_time = time.perf_counter()
    try:
        adapter = get_model_adapter(provider, model_name=model_name, api_key=api_key)
    except Exception as exc:
        return HealthCheckResult(
            provider=provider,
            model_name=model_name or "unknown",
            status="FAILED",
            message=f"Failed to initialize adapter for provider '{provider}'",
            error=str(exc),
        )

    from research_os.models.mock import MockModelAdapter
    if isinstance(adapter, MockModelAdapter):
        adapter.queue_structured_response(_HealthPingResponse(ping="pong", status=200))

    resolved_model = adapter.model_name
    result = HealthCheckResult(
        provider=provider,
        model_name=resolved_model,
        status="FAILED",
    )

    # 1. Text generation smoke test
    try:
        resp = adapter.generate_text("Respond with PONG", max_tokens=10)
        if resp and resp.content:
            result.text_generation_ok = True
        else:
            result.message = "Empty response returned from model"
            return result
    except Exception as exc:
        err_msg = str(exc)
        if "429" in err_msg or "ResourceExhausted" in err_msg:
            result.message = "Rate limit exceeded (HTTP 429)"
        elif "401" in err_msg or "403" in err_msg or "API_KEY_INVALID" in err_msg:
            result.message = "Authentication failure: invalid or missing API key"
        elif "404" in err_msg:
            result.message = f"Model '{resolved_model}' not found (HTTP 404)"
        else:
            result.message = f"Text generation failed: {err_msg}"
        result.error = err_msg
        result.latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return result

    # 2. Structured generation smoke test
    try:
        structured_resp = adapter.generate_structured(
            prompt="Respond with ping='pong' and status=200",
            response_model=_HealthPingResponse,
            max_tokens=50,
        )
        if structured_resp and structured_resp.status == 200:
            result.structured_generation_ok = True
        else:
            result.status = "DEGRADED"
            result.message = "Text generation passed, but structured output returned unexpected payload"
    except Exception as exc:
        result.status = "DEGRADED"
        result.message = f"Text generation succeeded, but structured generation failed: {exc}"
        result.error = str(exc)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    result.latency_ms = round(elapsed_ms, 2)

    if result.text_generation_ok and result.structured_generation_ok:
        result.status = "OK"
        result.message = f"Successfully authenticated and verified {provider} ({resolved_model})"

    return result

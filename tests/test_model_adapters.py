"""Tests for pluggable model provider adapters in Research OS."""

import pytest
from pydantic import BaseModel, Field

from research_os.models.base import BaseModelAdapter, ModelResponse
from research_os.models.mock import MockModelAdapter
from research_os.models.openai_adapter import OpenAIModelAdapter
from research_os.models.anthropic_adapter import AnthropicModelAdapter
from research_os.models.gemini_adapter import GeminiModelAdapter
from research_os.models.local_adapter import LocalModelAdapter
from research_os.models import get_model_adapter


class SampleOutput(BaseModel):
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    score: int


def test_model_adapter_factory():
    mock_adapter = get_model_adapter("mock")
    assert isinstance(mock_adapter, MockModelAdapter)

    openai_adapter = get_model_adapter("openai", model_name="gpt-4o-mini")
    assert isinstance(openai_adapter, OpenAIModelAdapter)
    assert openai_adapter.model_name == "gpt-4o-mini"

    anthropic_adapter = get_model_adapter("anthropic")
    assert isinstance(anthropic_adapter, AnthropicModelAdapter)

    gemini_adapter = get_model_adapter("gemini")
    assert isinstance(gemini_adapter, GeminiModelAdapter)

    google_adapter = get_model_adapter("google")
    assert isinstance(google_adapter, GeminiModelAdapter)

    local_adapter = get_model_adapter("local", base_url="http://localhost:11434/v1")
    assert isinstance(local_adapter, LocalModelAdapter)
    assert local_adapter.base_url == "http://localhost:11434/v1"

    with pytest.raises(ValueError) as exc_info:
        get_model_adapter("unsupported_vendor")
    assert "Unsupported model provider" in str(exc_info.value)


def test_mock_adapter_text_generation():
    adapter = MockModelAdapter(default_text="Default offline text.")
    resp1 = adapter.generate_text("Explain attention mechanism.")
    assert resp1.content == "Default offline text."
    assert resp1.model_name == "mock-model"
    assert len(adapter.call_history) == 1

    # Queued responses
    adapter.queue_text_response("Queued answer 1.")
    adapter.queue_text_response("Queued answer 2.")

    assert adapter.generate_text("Prompt 1").content == "Queued answer 1."
    assert adapter.generate_text("Prompt 2").content == "Queued answer 2."
    assert adapter.generate_text("Prompt 3").content == "Default offline text."


def test_mock_adapter_custom_handler():
    adapter = MockModelAdapter()
    adapter.set_custom_handler(lambda p, sys: f"ECHO: {p}")

    resp = adapter.generate_text("Hello Research OS")
    assert resp.content == "ECHO: Hello Research OS"


def test_mock_adapter_structured_generation():
    adapter = MockModelAdapter()

    # 1. Enqueue as Pydantic instance
    expected_obj = SampleOutput(summary="Deep research analysis", confidence=0.98, score=10)
    adapter.queue_structured_response(expected_obj)

    result1 = adapter.generate_structured("Extract structured data", SampleOutput)
    assert result1 == expected_obj

    # 2. Enqueue as raw dict
    adapter.queue_structured_response({
        "summary": "Dict representation",
        "confidence": 0.85,
        "score": 8,
    })
    result2 = adapter.generate_structured("Extract from dict", SampleOutput)
    assert result2.summary == "Dict representation"
    assert result2.confidence == 0.85

    # 3. Enqueue as JSON string
    adapter.queue_structured_response('{"summary": "JSON string", "confidence": 0.75, "score": 6}')
    result3 = adapter.generate_structured("Extract from string", SampleOutput)
    assert result3.score == 6

    # 4. Empty queue error
    with pytest.raises(ValueError) as exc:
        adapter.generate_structured("Should fail", SampleOutput)
    assert "no queued response" in str(exc.value)


def test_concrete_adapters_inheritance():
    """Verify that all adapters inherit from BaseModelAdapter and follow uniform contract."""
    adapters = [
        OpenAIModelAdapter(api_key="test-key"),
        AnthropicModelAdapter(api_key="test-key"),
        GeminiModelAdapter(api_key="test-key"),
        LocalModelAdapter(),
    ]
    for adapter in adapters:
        assert isinstance(adapter, BaseModelAdapter)
        assert hasattr(adapter, "generate_text")
        assert hasattr(adapter, "generate_structured")
        assert hasattr(adapter, "model_name")
        assert hasattr(adapter, "temperature")

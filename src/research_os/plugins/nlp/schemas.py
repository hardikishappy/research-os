"""Schemas and data models for NLP Benchmarking domain."""

from __future__ import annotations

from typing import Optional
from pydantic import Field
from research_os.schemas.base import ArtifactBaseModel


class NLPBenchmarkConfig(ArtifactBaseModel):
    """Configuration for NLP hallucination and retrieval benchmark."""

    benchmark_size: int = Field(default=40, ge=5, description="Number of query-context evaluation pairs")
    temperature: float = Field(default=0.7, ge=0.0, le=1.0, description="Sampling temperature")
    max_tokens: int = Field(default=128, ge=16, description="Max generated tokens per prompt")
    hallucination_threshold: float = Field(default=0.20, ge=0.0, le=1.0, description="Target hallucination rate cap")
    seed: int = Field(default=42, description="Random seed for data shuffling")


class NLPPredictionItem(ArtifactBaseModel):
    """Traceable evaluation record for a single benchmark query."""

    item_id: str = Field(description="Unique benchmark query ID")
    query: str = Field(description="User prompt or question")
    gold_answer: str = Field(description="Ground truth reference answer")
    retrieved_context: str = Field(description="Injected retrieval context")
    baseline_answer: str = Field(description="Output produced by baseline direct generation")
    rag_answer: str = Field(description="Output produced by retrieval-augmented generation")
    baseline_hallucinated: bool = Field(description="Whether baseline hallucinated ungrounded entities")
    rag_hallucinated: bool = Field(description="Whether RAG hallucinated ungrounded entities")
    token_overlap: float = Field(description="Token recall against gold answer")
    latency_ms: float = Field(description="Execution latency in milliseconds")

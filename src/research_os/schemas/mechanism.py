"""Mechanism execution contract schemas for Research OS (Directive 1)."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import Field

from .base import ArtifactBaseModel


class MechanismEventRequirement(ArtifactBaseModel):
    """Specification of an expected event transition in the execution trace."""

    event_type: str = Field(description="Canonical event identifier (e.g. QUERY_IN, RETRIEVAL_INVOKED)")
    required_payload_keys: list[str] = Field(
        default_factory=list,
        description="Keys that must be present and non-empty in the event payload",
    )
    description: str = Field(default="", description="Scientific purpose of this event transition")

    def __init__(self, **data: Any) -> None:
        if "required_payload_fields" in data and "required_payload_keys" not in data:
            data["required_payload_keys"] = data.pop("required_payload_fields")
        super().__init__(**data)


class MechanismContract(ArtifactBaseModel):
    """Contract defining the structural mechanics required for a valid experimental run."""

    contract_id: str = Field(default="contract-mech-default", description="Unique mechanism contract identifier")
    modality: Optional[str] = Field(default=None, description="Domain modality (e.g. 'RAG', 'DISTRIBUTED_CONSENSUS')")
    expected_event_sequence: list[str] = Field(
        default_factory=list,
        description="Ordered sequence of mandatory event types that must appear in trace.jsonl",
    )
    event_requirements: dict[str, MechanismEventRequirement] = Field(
        default_factory=dict,
        description="Detailed payload requirements per event type",
    )
    min_event_count: int = Field(default=1, ge=1, description="Minimum number of trace events required")
    allow_interleaved_events: bool = Field(
        default=True,
        description="Whether other auxiliary events may occur between expected transitions",
    )
    enforce_strict_ordering: bool = Field(
        default=True,
        description="Whether event sequence must strictly maintain chronological order",
    )
    enforce_hash_chain: bool = Field(
        default=True,
        description="Whether cryptographic hash chain verification is enforced",
    )

    def __init__(self, **data: Any) -> None:
        if "required_transitions" in data:
            transitions = data.pop("required_transitions")
            if isinstance(transitions, list):
                seq = []
                reqs = dict(data.get("event_requirements", {}))
                for t in transitions:
                    if isinstance(t, MechanismEventRequirement):
                        seq.append(t.event_type)
                        reqs[t.event_type] = t
                    elif isinstance(t, dict):
                        req_obj = MechanismEventRequirement(**t)
                        seq.append(req_obj.event_type)
                        reqs[req_obj.event_type] = req_obj
                data["expected_event_sequence"] = seq
                data["event_requirements"] = reqs
        if "modality" in data and hasattr(data["modality"], "value"):
            data["modality"] = data["modality"].value
        super().__init__(**data)

"""Execution Trace Logging and Cryptographic Trace Verification for Research OS (Directive 1 & P0 Hardening).

Enforces:
- Keyed / hash-chained observable execution traces in append-only JSONL format (trace.jsonl).
- Per-query state machine lifecycle enforcement:
    QUERY_IN -> RETRIEVAL_INVOKED -> DOCS_RETRIEVED -> CONTEXT_ASSEMBLED -> MODEL_INFERENCE -> EVALUATED
- Cross-artifact consistency: query count matching predictions.jsonl and corpus doc ID existence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Optional, Sequence, Union
from pydantic import Field

from research_os.schemas.base import ArtifactBaseModel
from research_os.specs.mechanism import MechanismContract


class ExecutionTraceRecord(ArtifactBaseModel):
    """Individual observable event record within an execution trace."""

    sequence_idx: int = Field(ge=0, description="Monotonically increasing event index")
    event_type: str = Field(description="Event transition identifier")
    timestamp_utc: str = Field(description="ISO 8601 UTC timestamp")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event telemetry payload")
    prev_hash: str = Field(description="SHA-256 or HMAC digest of previous record (or 'GENESIS' for index 0)")
    trace_hash: str = Field(description="Chained cryptographic digest of this record")


def compute_trace_record_hash(
    sequence_idx: int,
    event_type: str,
    timestamp_utc: str,
    payload: dict[str, Any],
    prev_hash: str,
    hmac_key: Optional[bytes] = None,
) -> str:
    """Compute deterministic chained SHA-256 or keyed HMAC digest for a trace event."""
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    content = f"{sequence_idx}|{event_type}|{timestamp_utc}|{canonical_payload}|{prev_hash}"
    if hmac_key:
        return hmac.new(hmac_key, content.encode("utf-8"), hashlib.sha256).hexdigest()
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class TraceLogger:
    """Append-only cryptographic trace logger for experimental processes."""

    def __init__(self, trace_path: Union[str, Path], hmac_key: Optional[bytes] = None) -> None:
        self.trace_path = Path(trace_path)
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self.hmac_key = hmac_key
        self._seq = 0
        self._last_hash = "GENESIS"

        # If file already exists, fast-forward to end
        if self.trace_path.exists() and self.trace_path.is_file():
            try:
                for line in self.trace_path.read_text(encoding="utf-8").strip().splitlines():
                    if line.strip():
                        rec = json.loads(line)
                        self._seq = rec["sequence_idx"] + 1
                        self._last_hash = rec["trace_hash"]
            except Exception:
                pass

    def log(self, event_type: str, payload: Optional[dict[str, Any]] = None) -> ExecutionTraceRecord:
        """Append an observable execution event to trace.jsonl with hash-chaining."""
        ts = datetime.now(timezone.utc).isoformat()
        clean_payload = payload or {}
        curr_hash = compute_trace_record_hash(
            sequence_idx=self._seq,
            event_type=event_type,
            timestamp_utc=ts,
            payload=clean_payload,
            prev_hash=self._last_hash,
            hmac_key=self.hmac_key,
        )

        record = ExecutionTraceRecord(
            sequence_idx=self._seq,
            event_type=event_type,
            timestamp_utc=ts,
            payload=clean_payload,
            prev_hash=self._last_hash,
            trace_hash=curr_hash,
        )

        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

        self._seq += 1
        self._last_hash = curr_hash
        return record


def verify_execution_trace(
    trace_path: Union[str, Path],
    contract: MechanismContract,
    hmac_key: Optional[bytes] = None,
    expected_query_count: Optional[int] = None,
    corpus_doc_ids: Optional[set[str]] = None,
) -> tuple[bool, list[str]]:
    """Verify an execution trace against a declared MechanismContract.

    Validates:
    1. File existence and non-zero record count.
    2. Chained cryptographic integrity (no record modified or omitted).
    3. Structural event sequence presence and ordering.
    4. Per-query state machine enforcement (T3).
    5. Required payload keys for each expected event type.
    6. Cross-artifact consistency (query count and corpus document IDs).
    """
    path = Path(trace_path)
    if not path.exists() or not path.is_file():
        return False, [f"Execution trace artifact missing at '{path}'."]

    records: list[ExecutionTraceRecord] = []
    reasons: list[str] = []

    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for line in lines:
            data = json.loads(line)
            rec = ExecutionTraceRecord.model_validate(data)
            records.append(rec)
    except Exception as exc:
        return False, [f"Failed to parse trace.jsonl: {exc}"]

    if not records:
        return False, ["Execution trace contains zero records."]

    if len(records) < contract.min_event_count:
        reasons.append(
            f"Insufficient trace events: recorded {len(records)} events, contract requires at least {contract.min_event_count}."
        )

    # 1. Cryptographic chain verification
    expected_prev = "GENESIS"
    for idx, rec in enumerate(records):
        if rec.sequence_idx != idx:
            reasons.append(f"Sequence index broken at record {idx}: found sequence_idx={rec.sequence_idx}.")
            break
        if rec.prev_hash != expected_prev:
            reasons.append(
                f"Trace chain broken at record {idx} ('{rec.event_type}'): expected prev_hash '{expected_prev}', got '{rec.prev_hash}'."
            )
            break
        computed = compute_trace_record_hash(
            sequence_idx=rec.sequence_idx,
            event_type=rec.event_type,
            timestamp_utc=rec.timestamp_utc,
            payload=rec.payload,
            prev_hash=rec.prev_hash,
            hmac_key=hmac_key,
        )
        if computed != rec.trace_hash:
            reasons.append(
                f"Trace integrity violation at record {idx} ('{rec.event_type}'): computed hash '{computed}' != recorded '{rec.trace_hash}'."
            )
            break
        expected_prev = rec.trace_hash

    # 2. Structural event sequence verification
    if contract.expected_event_sequence:
        rec_events = [r.event_type for r in records]
        current_seq_idx = 0
        missing_transitions: list[str] = []

        for expected in contract.expected_event_sequence:
            found_idx = None
            for i in range(current_seq_idx, len(rec_events)):
                if rec_events[i] == expected:
                    found_idx = i
                    break

            if found_idx is not None:
                current_seq_idx = found_idx + 1
            else:
                missing_transitions.append(expected)

        if missing_transitions:
            reasons.append(
                f"Mechanism transition sequence incomplete. Missing required events in order: {missing_transitions}. "
                f"Recorded trace sequence: {rec_events}."
            )

    # 3. Payload requirement verification
    for rec in records:
        req = contract.event_requirements.get(rec.event_type)
        if req and req.required_payload_keys:
            for k in req.required_payload_keys:
                if k not in rec.payload or rec.payload[k] is None or rec.payload[k] == "":
                    reasons.append(
                        f"Event '{rec.event_type}' at sequence_idx {rec.sequence_idx} missing required non-empty payload key '{k}'."
                    )

    # 4. Per-Query State Machine Enforcement (T3)
    # Group records by query_id if query_id is present in payloads
    query_events: dict[str, list[str]] = {}
    for rec in records:
        qid = rec.payload.get("query_id")
        if qid:
            query_events.setdefault(str(qid), []).append(rec.event_type)

    if query_events:
        # Standard RAG lifecycle transitions per query:
        # 1. QUERY_IN
        # 2. RETRIEVAL_INVOKED
        # 3. CANDIDATE_DOCS_RETRIEVED or DOCS_RETRIEVED
        # 4. CONTEXT_ASSEMBLED
        # 5. MODEL_INFERENCE
        # 6. FACTUALITY_EVALUATION or EVALUATED
        expected_query_lifecycle = [
            {"QUERY_IN"},
            {"RETRIEVAL_INVOKED"},
            {"CANDIDATE_DOCS_RETRIEVED", "DOCS_RETRIEVED"},
            {"CONTEXT_ASSEMBLED"},
            {"MODEL_INFERENCE"},
            {"FACTUALITY_EVALUATION", "EVALUATED"},
        ]

        for qid, ev_list in query_events.items():
            ev_idx = 0
            lifecycle_failed = False
            for step_set in expected_query_lifecycle:
                # Find matching step in ev_list starting from ev_idx
                found = False
                while ev_idx < len(ev_list):
                    if ev_list[ev_idx] in step_set:
                        found = True
                        ev_idx += 1
                        break
                    ev_idx += 1
                if not found:
                    lifecycle_failed = True
                    break

            if lifecycle_failed:
                reasons.append(
                    f"PerQueryLifecycleViolation: Query '{qid}' violated mandatory lifecycle state machine. "
                    f"Observed events: {ev_list}."
                )

        # Cross-artifact consistency: query count
        if expected_query_count is not None and len(query_events) != expected_query_count:
            reasons.append(
                f"QueryCountMismatch: Trace contains {len(query_events)} distinct queries, "
                f"but metrics/predictions artifact expects {expected_query_count}."
            )

    # 5. Corpus Document ID verification
    if corpus_doc_ids:
        for rec in records:
            if rec.event_type in ("CANDIDATE_DOCS_RETRIEVED", "DOCS_RETRIEVED"):
                doc_ids = rec.payload.get("doc_ids", [])
                for d in doc_ids:
                    if d not in corpus_doc_ids:
                        reasons.append(
                            f"UnknownDocIdViolation: Query '{rec.payload.get('query_id')}' retrieved non-existent "
                            f"document '{d}' not present in corpus index."
                        )

    is_valid = len(reasons) == 0
    return is_valid, reasons

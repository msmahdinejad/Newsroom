"""Provider-neutral editorial attempt metadata shared across pipeline layers."""

from __future__ import annotations

from dataclasses import dataclass

from newsroom.editorial.schema import EditorialOutput


@dataclass
class EditorialAttempt:
    """Safe record of one editorial attempt for persistence and delivery policy."""

    provider: str = "deterministic"
    model: str = ""
    prompt_version: str = ""
    evidence_set_hash: str = ""
    schema_version: str = ""
    report_mode: str = "scheduled"
    started_at: str = ""
    completed_at: str = ""
    latency_ms: int = 0
    status: str = "ok"
    retry_count: int = 0
    fallback_used: bool = False
    validation_result: str = ""
    grounding_result: str = ""
    usage: dict[str, int] | None = None
    error_category: str = ""
    error_summary: str = ""
    output: EditorialOutput | None = None

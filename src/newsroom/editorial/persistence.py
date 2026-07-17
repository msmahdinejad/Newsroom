"""Editorial persistence — attempt records, caching, and health state.

Persists for every editorial attempt:
- provider, model, prompt version, evidence-set hash, schema version
- started/completed timestamps, latency, status, retry count
- fallback used, validation result, grounding result
- token usage metadata, error category, redacted error summary
- structured output for cache reuse

No API key is ever stored.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from newsroom.editorial.orchestrator import EditorialAttempt
from newsroom.logging import get_logger
from newsroom.storage.models import EditorialAttempt as EditorialAttemptModel
from newsroom.storage.models import EditorialHealth

logger = get_logger(__name__)


def compute_cache_key(
    report_mode: str,
    evidence_hash: str,
    prompt_version: str,
    provider: str,
    model: str,
) -> str:
    """Deterministic cache key for editorial idempotency.

    Same (mode, evidence, prompt, provider, model) = same key.
    """
    raw = f"{report_mode}:{evidence_hash}:{prompt_version}:{provider}:{model}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def find_cached_attempt(
    db: Session,
    cache_key: str,
) -> EditorialAttemptModel | None:
    """Find an existing accepted editorial attempt by cache key."""
    return (
        db.query(EditorialAttemptModel)
        .filter_by(cache_key=cache_key, status="ok")
        .order_by(EditorialAttemptModel.id.desc())
        .first()
    )


def persist_attempt(
    db: Session,
    attempt: EditorialAttempt,
    report_id: int | None,
    cache_key: str | None,
) -> EditorialAttemptModel:
    """Persist an editorial attempt record. Does NOT store API key."""
    record = EditorialAttemptModel(
        report_id=report_id,
        provider=attempt.provider,
        model=attempt.model,
        prompt_version=attempt.prompt_version,
        evidence_set_hash=attempt.evidence_set_hash,
        schema_version=attempt.schema_version,
        report_mode=attempt.report_mode,
        started_at=_parse_iso(attempt.started_at) if attempt.started_at else datetime.now(UTC),
        completed_at=_parse_iso(attempt.completed_at) if attempt.completed_at else None,
        latency_ms=attempt.latency_ms,
        status=attempt.status,
        retry_count=attempt.retry_count,
        fallback_used=attempt.fallback_used,
        validation_result=attempt.validation_result if attempt.validation_result else None,
        grounding_result=attempt.grounding_result if attempt.grounding_result else None,
        usage=attempt.usage,
        output_json=attempt.output.model_dump(mode="json") if attempt.output else None,
        error_category=attempt.error_category if attempt.error_category else None,
        error_summary=attempt.error_summary if attempt.error_summary else None,
        cache_key=cache_key,
    )
    db.add(record)
    db.flush()
    _update_health(db, attempt)
    return record


def update_attempt_with_report(
    db: Session,
    attempt_id: int,
    report_id: int,
) -> None:
    """Link an editorial attempt to its generated report."""
    record = db.get(EditorialAttemptModel, attempt_id)
    if record:
        record.report_id = report_id


def _update_health(db: Session, attempt: EditorialAttempt) -> None:
    """Update the singleton editorial health record."""
    from newsroom.config import settings

    health = db.query(EditorialHealth).filter_by(id=1).first()
    if not health:
        health = EditorialHealth(id=1)
        db.add(health)

    health.enabled = settings.editorial_enabled
    health.provider = attempt.provider
    health.model = attempt.model

    now = datetime.now(UTC)
    if attempt.status == "ok":
        health.last_success_at = now
        health.last_latency_ms = attempt.latency_ms
    elif attempt.status in ("fallback", "validation_failed", "grounding_failed", "provider_error"):
        health.last_failure_at = now
        if attempt.status == "validation_failed":
            health.validation_failure_count += 1
        elif attempt.status == "grounding_failed":
            health.grounding_failure_count += 1
        if attempt.fallback_used:
            health.fallback_count += 1

    if attempt.error_category == "rate_limit":
        health.rate_limited = True
        health.rate_limit_until = datetime.now(UTC)

    health.updated_at = now


def _parse_iso(iso: str) -> datetime:
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return datetime.now(UTC)


def get_editorial_health(db: Session) -> dict[str, Any]:
    """Get editorial health for health endpoint — no secrets."""
    from newsroom.config import settings

    health = db.query(EditorialHealth).filter_by(id=1).first()
    if not health:
        return {
            "enabled": settings.editorial_enabled,
            "provider": settings.editorial_provider,
            "model": settings.editorial_model or "",
            "healthy": True,
            "status": "disabled",
        }

    return {
        "enabled": settings.editorial_enabled,
        "provider": health.provider,
        "model": health.model or "",
        "last_success_at": health.last_success_at.isoformat() if health.last_success_at else None,
        "last_failure_at": health.last_failure_at.isoformat() if health.last_failure_at else None,
        "last_latency_ms": health.last_latency_ms,
        "validation_failure_count": health.validation_failure_count,
        "grounding_failure_count": health.grounding_failure_count,
        "fallback_count": health.fallback_count,
        "rate_limited": health.rate_limited,
        "rate_limit_until": health.rate_limit_until.isoformat() if health.rate_limit_until else None,
        "in_flight": health.in_flight,
        "configured_budgets": {
            "max_stories_per_call": settings.editorial_max_stories_per_call,
            "max_input_tokens": settings.editorial_max_input_tokens,
            "max_output_tokens": settings.editorial_max_output_tokens,
            "scheduled_run_budget": settings.editorial_scheduled_run_budget,
            "manual_run_budget": settings.editorial_manual_run_budget,
        },
        "healthy": True,  # editorial failure never marks other services unhealthy
        "status": "enabled" if settings.editorial_enabled else "disabled",
    }

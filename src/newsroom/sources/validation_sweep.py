"""Reconcile bounded source attempts into an honest production registry.

The network collectors own attempts.  This module turns their latest durable
``collection_runs`` records into the source-level validation fields required
for scheduling.  It never probes credentials and never stores raw exception
text in the safe category fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from newsroom.storage.database import engine
from newsroom.storage.models import CollectionCursor, CollectionRun, Source, SourceInventory


@dataclass(frozen=True)
class ValidationSweepResult:
    attempted: int = 0
    active: int = 0
    healthy: int = 0
    degraded: int = 0
    inactive: int = 0


_TRANSIENT = {"rate_limit", "timeout", "network_error", "provider_unavailable"}


def safe_failure_category(error: str | None) -> str:
    """Reduce arbitrary collector details to a bounded, non-secret category."""
    value = (error or "").lower()
    if "429" in value or "rate" in value and "limit" in value:
        return "rate_limit"
    if any(code in value for code in ("500", "502", "503", "504")):
        return "provider_unavailable"
    if "timeout" in value or "timed out" in value:
        return "timeout"
    if "403" in value or "forbidden" in value:
        return "access_forbidden"
    if "401" in value or "unauthor" in value or "auth" in value:
        return "authentication_required"
    if "404" in value or "not found" in value:
        return "not_found"
    if "private" in value and "address" in value:
        return "private_address_blocked"
    if "dns" in value or "name resolution" in value or "getaddrinfo" in value:
        return "dns_failure"
    if "ssl" in value or "certificate" in value:
        return "tls_failure"
    if "too large" in value or "size" in value and "limit" in value:
        return "response_too_large"
    if "connection" in value or "network" in value or "server closed" in value:
        return "network_error"
    if "invalid" in value or "malformed" in value:
        return "invalid_source"
    return "collector_error"


def _deactivate_inventory(session: Session, source: Source, reason: str) -> None:
    rows = session.query(SourceInventory).filter_by(source_id=source.id).all()
    for inventory in rows:
        inventory.operational_state = "inactive"
        inventory.inactive_reason = reason[:100]


def reconcile_source_validation(session: Session) -> ValidationSweepResult:
    """Reconcile every enabled source from its latest durable attempt.

    A transiently rate-limited or timed-out source remains active but degraded.
    A source with no attempt, or a permanent access/identity failure, is made
    inactive.  Therefore every source left enabled has an attempt timestamp and
    an explicit cursor or no-cursor reason.
    """
    attempted = 0
    active = 0
    healthy = 0
    degraded = 0
    inactive = 0

    sources = session.query(Source).order_by(Source.id).all()
    for source in sources:
        latest = (
            session.query(CollectionRun)
            .filter_by(source_id=source.id)
            .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
            .first()
        )
        has_cursor = (
            session.query(CollectionCursor.id).filter_by(source_id=source.id).first() is not None
        )

        if latest is None:
            source.enabled = False
            source.last_attempt_at = None
            source.validation_status = "untested"
            source.health_status = "unavailable"
            source.failure_category = "not_attempted"
            source.no_cursor_reason = "not_attempted"
            source.inactive_reason = "validation:not_attempted"
            _deactivate_inventory(session, source, source.inactive_reason)
            inactive += 1
            continue

        attempted += 1
        source.last_attempt_at = latest.started_at
        if has_cursor:
            source.no_cursor_reason = None
        elif latest.status == "ok" and latest.items_collected == 0:
            source.no_cursor_reason = "no_new_items"
        elif source.type == "telegram":
            source.no_cursor_reason = "telegram_channel_cursor_unavailable"
        else:
            source.no_cursor_reason = "attempt_failed_before_cursor"

        if latest.status == "ok":
            source.validation_status = "validated"
            source.health_status = "healthy"
            source.failure_category = None
            if source.enabled:
                source.inactive_reason = None
                active += 1
                healthy += 1
            else:
                # Validation never silently reactivates a source that an
                # inventory or platform-specific decision disabled.
                inactive += 1
            continue

        category = safe_failure_category(latest.error)
        source.failure_category = category
        source.validation_status = "failed"
        if category in _TRANSIENT:
            source.health_status = "degraded"
            if source.enabled:
                # Preserve an already-approved scheduled source through a
                # transient outage, but never activate a source whose first
                # bounded validation attempt only produced a transient error.
                source.inactive_reason = None
                active += 1
                degraded += 1
            else:
                source.inactive_reason = f"validation:{category}"
                _deactivate_inventory(session, source, source.inactive_reason)
                inactive += 1
        else:
            source.enabled = False
            source.health_status = "unavailable"
            source.inactive_reason = f"validation:{category}"
            _deactivate_inventory(session, source, source.inactive_reason)
            inactive += 1

    session.flush()
    return ValidationSweepResult(
        attempted=attempted,
        active=active,
        healthy=healthy,
        degraded=degraded,
        inactive=inactive,
    )


def main() -> None:
    with Session(engine) as session:
        result = reconcile_source_validation(session)
        session.commit()
    print(
        {
            "completed_at": datetime.now(UTC).isoformat(),
            "attempted": result.attempted,
            "active": result.active,
            "healthy": result.healthy,
            "degraded": result.degraded,
            "inactive": result.inactive,
        }
    )


if __name__ == "__main__":
    main()

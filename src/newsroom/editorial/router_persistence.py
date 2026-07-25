"""PostgreSQL adapter for safe multi-provider router state.

The router stays database-agnostic. Callers pass immutable snapshots/events
containing only provider/model identifiers, one-way SHA-256 fingerprints,
bounded counters, timestamps, and classified outcomes. This module never
accepts or persists provider access values, headers, prompts, responses, or
raw error text.

Functions flush but never commit; the caller owns the transaction.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from newsroom.logging import get_logger
from newsroom.storage.models import (
    ProviderCircuitState,
    ProviderKeyState,
    ProviderModelHealth,
    ProviderQuotaState,
    ProviderRouteAttempt,
    utcnow,
)

_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ModelHealthSnapshot:
    provider: str
    model: str
    validation_status: str
    latency_ms: int | None
    last_success_at: datetime | None
    last_failure_category: str | None
    supported_capabilities: tuple[str, ...]
    enabled: bool
    last_failure_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class KeyStateSnapshot:
    provider: str
    key_fingerprint: str
    enabled: bool
    last_use_at: datetime | None
    failure_count: int
    cooldown_until: datetime | None
    last_failure_category: str | None
    success_count: int


@dataclass(frozen=True, slots=True)
class QuotaStateSnapshot:
    provider: str
    model: str
    scope_fingerprint: str
    rpm_used: int
    tpm_used: int
    rpd_used: int
    reserved_tokens: int
    window_started_at: datetime | None
    day_started_at: datetime | None
    cooldown_until: datetime | None


@dataclass(frozen=True, slots=True)
class CircuitStateSnapshot:
    provider: str
    state: str
    consecutive_failures: int
    cooldown_until: datetime | None
    last_failure_category: str | None
    half_open_probe_in_flight: bool
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RouteAttemptEvent:
    event_id: str
    stage: str
    provider: str
    model: str
    status: str
    editorial_job_id: str | None = None
    shard_id: str | None = None
    report_id: int | None = None
    artifact_id: int | None = None
    key_fingerprint: str | None = None
    failure_category: str | None = None
    latency_ms: int = 0
    estimated_input_tokens: int = 0
    actual_input_tokens: int = 0
    actual_output_tokens: int = 0
    retry_after_seconds: float | None = None
    accepted: bool = False
    created_at: datetime = field(default_factory=utcnow)
    completed_at: datetime | None = None


type RouterStateSnapshot = (
    ModelHealthSnapshot | KeyStateSnapshot | QuotaStateSnapshot | CircuitStateSnapshot
)


@dataclass(frozen=True, slots=True)
class RouterPersistenceSnapshot:
    """Complete restart-safe state needed to rehydrate the router."""

    model_health: tuple[ModelHealthSnapshot, ...]
    keys: tuple[KeyStateSnapshot, ...]
    quotas: tuple[QuotaStateSnapshot, ...]
    circuits: tuple[CircuitStateSnapshot, ...]


@dataclass(frozen=True, slots=True)
class RouterRestoredState:
    """Restart payload plus the enabled, validated model IDs by provider."""

    validated_model_ids: dict[str, tuple[str, ...]]
    snapshots: RouterPersistenceSnapshot


class PostgresRouterStateSink:
    """Production router sink using one short independent transaction per event.

    Persistence failures are logged only by exception category and do not turn
    a recoverable provider failure into a report-generation outage.
    """

    def __init__(self, session_provider: Callable[[], Session] | None = None) -> None:
        if session_provider is None:
            from newsroom.storage.database import session_factory

            session_provider = session_factory
        self._session_provider = session_provider

    def record_snapshot(self, snapshot: object) -> None:
        from newsroom.editorial.router.types import (
            CircuitStateSnapshot as CoreCircuitStateSnapshot,
        )
        from newsroom.editorial.router.types import KeyStateSnapshot as CoreKeyStateSnapshot
        from newsroom.editorial.router.types import (
            ModelHealthSnapshot as CoreModelHealthSnapshot,
        )
        from newsroom.editorial.router.types import QuotaStateSnapshot as CoreQuotaStateSnapshot

        translated: RouterStateSnapshot
        if isinstance(snapshot, CoreModelHealthSnapshot):
            translated = ModelHealthSnapshot(
                provider=snapshot.provider,
                model=snapshot.model,
                validation_status=snapshot.validation_status,
                latency_ms=snapshot.latency_ms,
                last_success_at=snapshot.last_success_at,
                last_failure_category=snapshot.last_failure_category,
                supported_capabilities=snapshot.supported_capabilities,
                enabled=snapshot.enabled,
                last_failure_at=(
                    utcnow() if snapshot.last_failure_category is not None else None
                ),
            )
        elif isinstance(snapshot, CoreKeyStateSnapshot):
            translated = KeyStateSnapshot(
                provider=snapshot.provider,
                key_fingerprint=snapshot.key_fingerprint,
                enabled=snapshot.enabled,
                last_use_at=snapshot.last_use_at,
                failure_count=snapshot.failure_count,
                cooldown_until=snapshot.cooldown_until,
                last_failure_category=snapshot.last_failure_category,
                success_count=snapshot.successful_request_count,
            )
        elif isinstance(snapshot, CoreQuotaStateSnapshot):
            translated = QuotaStateSnapshot(
                provider=snapshot.provider,
                model=snapshot.model,
                scope_fingerprint=snapshot.scope_fingerprint,
                rpm_used=snapshot.rpm_used,
                tpm_used=snapshot.tpm_used,
                rpd_used=snapshot.rpd_used,
                reserved_tokens=snapshot.reserved_tokens,
                window_started_at=snapshot.window_started_at,
                day_started_at=snapshot.day_started_at,
                cooldown_until=snapshot.cooldown_until,
            )
        elif isinstance(snapshot, CoreCircuitStateSnapshot):
            translated = CircuitStateSnapshot(
                provider=snapshot.provider,
                state=snapshot.state,
                consecutive_failures=snapshot.consecutive_failures,
                cooldown_until=snapshot.cooldown_until,
                last_failure_category=snapshot.last_failure_category,
                half_open_probe_in_flight=snapshot.half_open_probe_in_flight,
            )
        else:
            raise TypeError("unsupported router snapshot type")
        self._write(lambda db: persist_router_snapshot(db, translated))

    def record_attempt(self, event: object) -> None:
        from newsroom.editorial.router.types import RouteAttemptEvent as CoreRouteAttemptEvent

        if not isinstance(event, CoreRouteAttemptEvent):
            raise TypeError("unsupported route attempt event type")
        terminal = event.status not in {"queued", "started", "running"}
        translated = RouteAttemptEvent(
            event_id=event.event_id,
            editorial_job_id=event.job_id,
            shard_id=event.shard_id,
            report_id=event.report_id,
            artifact_id=event.artifact_id,
            stage=event.stage,
            provider=event.provider,
            model=event.model,
            key_fingerprint=event.key_fingerprint,
            status=event.status,
            failure_category=event.failure_category,
            latency_ms=event.latency_ms,
            estimated_input_tokens=event.estimated_input_tokens,
            actual_input_tokens=event.actual_input_tokens or 0,
            actual_output_tokens=event.actual_output_tokens or 0,
            retry_after_seconds=event.retry_after_seconds,
            accepted=event.status in {"ok", "accepted", "success", "validated"},
            created_at=event.created_at,
            completed_at=event.created_at if terminal else None,
        )
        self._write(lambda db: persist_route_attempt(db, translated))

    def load(self) -> RouterRestoredState:
        """Read restart state in a short independent transaction."""

        db = self._session_provider()
        try:
            snapshots = load_router_snapshots(db)
            grouped: dict[str, list[str]] = {}
            for health in snapshots.model_health:
                if health.enabled and health.validation_status == "validated":
                    grouped.setdefault(health.provider, []).append(health.model)
            validated = {
                provider: tuple(sorted(set(models)))
                for provider, models in sorted(grouped.items())
            }
            db.commit()
            return RouterRestoredState(validated_model_ids=validated, snapshots=snapshots)
        except Exception:
            db.rollback()
            logger.warning("router state load failed: persistence_error")
            return RouterRestoredState(
                validated_model_ids={},
                snapshots=RouterPersistenceSnapshot((), (), (), ()),
            )
        finally:
            db.close()

    def _write(self, operation: Callable[[Session], object]) -> None:
        db = self._session_provider()
        try:
            operation(db)
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("router state write failed: persistence_error")
        finally:
            db.close()


def persist_router_snapshot(
    db: Session,
    snapshot: RouterStateSnapshot,
) -> ProviderModelHealth | ProviderKeyState | ProviderQuotaState | ProviderCircuitState:
    """Upsert one safe router snapshot and flush without committing."""

    now = utcnow()
    if isinstance(snapshot, ModelHealthSnapshot):
        _validate_model_health(snapshot)
        existing = db.scalar(
            select(ProviderModelHealth).where(
                ProviderModelHealth.provider == snapshot.provider,
                ProviderModelHealth.model == snapshot.model,
            )
        )
        values = {
            "provider": snapshot.provider,
            "model": snapshot.model,
            "validation_status": snapshot.validation_status,
            "latency_ms": (
                snapshot.latency_ms
                if snapshot.latency_ms is not None
                else (existing.latency_ms if existing is not None else 0)
            ),
            "last_success_at": snapshot.last_success_at
            or (existing.last_success_at if existing is not None else None),
            "last_failure_at": snapshot.last_failure_at
            or (existing.last_failure_at if existing is not None else None),
            "last_failure_category": snapshot.last_failure_category,
            "supported_capabilities": sorted(set(snapshot.supported_capabilities)),
            "enabled": snapshot.enabled,
            "updated_at": now,
        }
        return _upsert(db, ProviderModelHealth, values, ("provider", "model"))

    if isinstance(snapshot, KeyStateSnapshot):
        _validate_key_state(snapshot)
        values = {
            "provider": snapshot.provider,
            "key_fingerprint": snapshot.key_fingerprint,
            "enabled": snapshot.enabled,
            "last_use_at": snapshot.last_use_at,
            "failure_count": snapshot.failure_count,
            "cooldown_until": snapshot.cooldown_until,
            "last_failure_category": snapshot.last_failure_category,
            "success_count": snapshot.success_count,
            "updated_at": now,
        }
        return _upsert(db, ProviderKeyState, values, ("provider", "key_fingerprint"))

    if isinstance(snapshot, QuotaStateSnapshot):
        _validate_quota_state(snapshot)
        values = {
            "provider": snapshot.provider,
            "model": snapshot.model,
            "scope_fingerprint": snapshot.scope_fingerprint,
            "rpm_used": snapshot.rpm_used,
            "tpm_used": snapshot.tpm_used,
            "rpd_used": snapshot.rpd_used,
            "reserved_tokens": snapshot.reserved_tokens,
            "window_started_at": snapshot.window_started_at,
            "day_started_at": snapshot.day_started_at,
            "cooldown_until": snapshot.cooldown_until,
            "updated_at": now,
        }
        return _upsert(
            db,
            ProviderQuotaState,
            values,
            ("provider", "model", "scope_fingerprint"),
        )

    if isinstance(snapshot, CircuitStateSnapshot):
        _validate_circuit_state(snapshot)
        values = {
            "provider": snapshot.provider,
            "state": snapshot.state,
            "consecutive_failures": snapshot.consecutive_failures,
            "cooldown_until": snapshot.cooldown_until,
            "last_failure_category": snapshot.last_failure_category,
            "half_open_probe_in_flight": snapshot.half_open_probe_in_flight,
            "last_success_at": snapshot.last_success_at,
            "last_failure_at": snapshot.last_failure_at,
            "updated_at": now,
        }
        return _upsert(db, ProviderCircuitState, values, ("provider",))

    raise TypeError("unsupported router snapshot type")


def persist_route_attempt(db: Session, event: RouteAttemptEvent) -> ProviderRouteAttempt:
    """Idempotently record or reconcile one route-attempt lifecycle event.

    The event ID owns immutable lineage. A replay may update status, usage,
    completion, and classified failure fields, but cannot rewrite the original
    job/shard/stage/provider/model/key identity.
    """

    _validate_route_attempt(event)
    values = {
        "event_id": event.event_id,
        "editorial_job_id": event.editorial_job_id,
        "shard_id": event.shard_id,
        "report_id": event.report_id,
        "artifact_id": event.artifact_id,
        "stage": event.stage,
        "provider": event.provider,
        "model": event.model,
        "key_fingerprint": event.key_fingerprint,
        "status": event.status,
        "failure_category": event.failure_category,
        "latency_ms": event.latency_ms,
        "estimated_input_tokens": event.estimated_input_tokens,
        "actual_input_tokens": event.actual_input_tokens,
        "actual_output_tokens": event.actual_output_tokens,
        "retry_after_seconds": event.retry_after_seconds,
        "accepted": event.accepted,
        "created_at": event.created_at,
        "completed_at": event.completed_at,
        "updated_at": utcnow(),
    }
    statement = insert(ProviderRouteAttempt).values(**values)
    immutable = (
        "editorial_job_id",
        "shard_id",
        "report_id",
        "artifact_id",
        "stage",
        "provider",
        "model",
        "key_fingerprint",
    )
    same_lineage = and_(
        *(
            getattr(ProviderRouteAttempt.__table__.c, name).is_not_distinct_from(
                getattr(statement.excluded, name)
            )
            for name in immutable
        )
    )
    mutable = {
        name: getattr(statement.excluded, name)
        for name in (
            "status",
            "failure_category",
            "latency_ms",
            "estimated_input_tokens",
            "actual_input_tokens",
            "actual_output_tokens",
            "retry_after_seconds",
            "accepted",
            "completed_at",
            "updated_at",
        )
    }
    upsert_statement = statement.on_conflict_do_update(
        index_elements=[ProviderRouteAttempt.event_id],
        set_=mutable,
        where=same_lineage,
    ).returning(ProviderRouteAttempt.id)
    record_id = db.execute(upsert_statement).scalar_one_or_none()
    if record_id is None:
        raise ValueError("route attempt event ID conflicts with immutable lineage")
    db.flush()
    record = db.get(ProviderRouteAttempt, record_id)
    if record is None:  # pragma: no cover - database RETURNING guarantees this
        raise RuntimeError("persisted route attempt could not be reloaded")
    db.refresh(record)
    return record


def load_router_snapshots(db: Session) -> RouterPersistenceSnapshot:
    """Load all safe state required for restart recovery."""

    model_rows = db.scalars(
        select(ProviderModelHealth).order_by(
            ProviderModelHealth.provider,
            ProviderModelHealth.model,
        )
    ).all()
    key_rows = db.scalars(
        select(ProviderKeyState).order_by(
            ProviderKeyState.provider,
            ProviderKeyState.key_fingerprint,
        )
    ).all()
    quota_rows = db.scalars(
        select(ProviderQuotaState).order_by(
            ProviderQuotaState.provider,
            ProviderQuotaState.model,
            ProviderQuotaState.scope_fingerprint,
        )
    ).all()
    circuit_rows = db.scalars(
        select(ProviderCircuitState).order_by(ProviderCircuitState.provider)
    ).all()
    return RouterPersistenceSnapshot(
        model_health=tuple(
            ModelHealthSnapshot(
                provider=row.provider,
                model=row.model,
                validation_status=row.validation_status,
                latency_ms=row.latency_ms,
                last_success_at=row.last_success_at,
                last_failure_category=row.last_failure_category,
                supported_capabilities=tuple(row.supported_capabilities or ()),
                enabled=row.enabled,
                last_failure_at=row.last_failure_at,
            )
            for row in model_rows
        ),
        keys=tuple(
            KeyStateSnapshot(
                provider=row.provider,
                key_fingerprint=row.key_fingerprint,
                enabled=row.enabled,
                last_use_at=row.last_use_at,
                failure_count=row.failure_count,
                cooldown_until=row.cooldown_until,
                last_failure_category=row.last_failure_category,
                success_count=row.success_count,
            )
            for row in key_rows
        ),
        quotas=tuple(
            QuotaStateSnapshot(
                provider=row.provider,
                model=row.model,
                scope_fingerprint=row.scope_fingerprint,
                rpm_used=row.rpm_used,
                tpm_used=row.tpm_used,
                rpd_used=row.rpd_used,
                reserved_tokens=row.reserved_tokens,
                window_started_at=row.window_started_at,
                day_started_at=row.day_started_at,
                cooldown_until=row.cooldown_until,
            )
            for row in quota_rows
        ),
        circuits=tuple(
            CircuitStateSnapshot(
                provider=row.provider,
                state=row.state,
                consecutive_failures=row.consecutive_failures,
                cooldown_until=row.cooldown_until,
                last_failure_category=row.last_failure_category,
                half_open_probe_in_flight=row.half_open_probe_in_flight,
                last_success_at=row.last_success_at,
                last_failure_at=row.last_failure_at,
            )
            for row in circuit_rows
        ),
    )


def _upsert[ModelT](
    db: Session,
    model: type[ModelT],
    values: dict,
    identity: tuple[str, ...],
) -> ModelT:
    statement = insert(model).values(**values)
    mutable = {
        name: getattr(statement.excluded, name)
        for name in values
        if name not in identity
    }
    upsert_statement = statement.on_conflict_do_update(
        index_elements=[getattr(model, name) for name in identity],
        set_=mutable,
    ).returning(model.id)  # type: ignore[attr-defined]
    record_id = db.execute(upsert_statement).scalar_one()
    db.flush()
    return _reload(db, model, record_id)


def _reload[ModelT](db: Session, model: type[ModelT], record_id: int) -> ModelT:
    record = db.get(model, record_id)
    if record is None:  # pragma: no cover - database RETURNING guarantees this
        raise RuntimeError("persisted router state could not be reloaded")
    db.refresh(record)
    return record


def _validate_model_health(snapshot: ModelHealthSnapshot) -> None:
    _identifier(snapshot.provider, "provider", 50)
    _identifier(snapshot.model, "model", 150)
    _identifier(snapshot.validation_status, "validation status", 30)
    if snapshot.latency_ms is not None:
        _nonnegative(snapshot.latency_ms, "latency")
    _optional_identifier(snapshot.last_failure_category, "failure category", 50)
    for capability in snapshot.supported_capabilities:
        _identifier(capability, "supported capability", 50)


def _validate_key_state(snapshot: KeyStateSnapshot) -> None:
    _identifier(snapshot.provider, "provider", 50)
    _fingerprint(snapshot.key_fingerprint, "key fingerprint")
    _nonnegative(snapshot.failure_count, "failure count")
    _nonnegative(snapshot.success_count, "success count")
    _optional_identifier(snapshot.last_failure_category, "failure category", 50)


def _validate_quota_state(snapshot: QuotaStateSnapshot) -> None:
    _identifier(snapshot.provider, "provider", 50)
    _identifier(snapshot.model, "model", 150, allow_empty=True)
    _fingerprint(snapshot.scope_fingerprint, "scope fingerprint")
    _nonnegative(snapshot.rpm_used, "RPM usage")
    _nonnegative(snapshot.tpm_used, "TPM usage")
    _nonnegative(snapshot.rpd_used, "RPD usage")
    _nonnegative(snapshot.reserved_tokens, "reserved tokens")


def _validate_circuit_state(snapshot: CircuitStateSnapshot) -> None:
    _identifier(snapshot.provider, "provider", 50)
    if snapshot.state not in {"closed", "open", "half_open"}:
        raise ValueError("invalid circuit state")
    _nonnegative(snapshot.consecutive_failures, "consecutive failures")
    _optional_identifier(snapshot.last_failure_category, "failure category", 50)


def _validate_route_attempt(event: RouteAttemptEvent) -> None:
    _identifier(event.event_id, "event ID", 100)
    _optional_identifier(event.editorial_job_id, "editorial job ID", 100)
    _optional_identifier(event.shard_id, "shard ID", 100)
    if event.report_id is not None:
        _nonnegative(event.report_id, "report ID")
    if event.artifact_id is not None:
        _nonnegative(event.artifact_id, "artifact ID")
    _identifier(event.stage, "stage", 30)
    _identifier(event.provider, "provider", 50)
    _identifier(event.model, "model", 150, allow_empty=True)
    if event.key_fingerprint is not None:
        _fingerprint(event.key_fingerprint, "key fingerprint")
    _identifier(event.status, "status", 30)
    _optional_identifier(event.failure_category, "failure category", 50)
    _nonnegative(event.latency_ms, "latency")
    _nonnegative(event.estimated_input_tokens, "estimated input tokens")
    _nonnegative(event.actual_input_tokens, "actual input tokens")
    _nonnegative(event.actual_output_tokens, "actual output tokens")
    if event.retry_after_seconds is not None:
        _nonnegative(event.retry_after_seconds, "retry-after seconds")


def _fingerprint(value: str, label: str) -> None:
    if not _FINGERPRINT_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 fingerprint")


def _identifier(value: str, label: str, max_length: int, *, allow_empty: bool = False) -> None:
    if allow_empty and value == "":
        return
    if len(value) > max_length or not _SAFE_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{label} is not a safe identifier")


def _optional_identifier(value: str | None, label: str, max_length: int) -> None:
    if value is not None:
        _identifier(value, label, max_length)


def _nonnegative(value: int | float, label: str) -> None:
    if value < 0:
        raise ValueError(f"{label} cannot be negative")


__all__ = [
    "CircuitStateSnapshot",
    "KeyStateSnapshot",
    "ModelHealthSnapshot",
    "PostgresRouterStateSink",
    "QuotaStateSnapshot",
    "RouteAttemptEvent",
    "RouterPersistenceSnapshot",
    "RouterRestoredState",
    "load_router_snapshots",
    "persist_route_attempt",
    "persist_router_snapshot",
]

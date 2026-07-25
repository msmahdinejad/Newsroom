"""Reusable in-memory provider key pool with safe snapshots."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import timedelta

from newsroom.editorial.router.types import (
    Clock,
    KeyStateSnapshot,
    RouteFailureCategory,
    RouterStateSink,
    SystemClock,
)


@dataclass
class _KeyRecord:
    provider: str
    safe_id: str
    fingerprint: str
    value: str = field(repr=False)
    enabled: bool = True
    last_use_monotonic: float | None = None
    failure_count: int = 0
    cooldown_until_monotonic: float | None = None
    last_failure_category: str | None = None
    successful_request_count: int = 0


@dataclass(frozen=True)
class KeyLease:
    provider: str
    safe_id: str
    fingerprint: str
    value: str = field(repr=False)


class KeyPool:
    def __init__(
        self,
        provider: str,
        values: tuple[str, ...],
        *,
        clock: Clock | None = None,
        default_cooldown_seconds: float = 60.0,
        sink: RouterStateSink | None = None,
    ) -> None:
        self.provider = provider
        self.clock = clock or SystemClock()
        self.default_cooldown_seconds = default_cooldown_seconds
        self.sink = sink
        self._records = [
            _KeyRecord(
                provider=provider,
                safe_id=f"{provider}-key-{index}",
                fingerprint=hashlib.sha256(value.encode("utf-8")).hexdigest(),
                value=value,
            )
            for index, value in enumerate(dict.fromkeys(values), start=1)
        ]
        self._cursor = 0
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return f"KeyPool(provider={self.provider!r}, key_count={len(self._records)})"

    @property
    def key_count(self) -> int:
        return len(self._records)

    def reset_rotation(self) -> None:
        with self._lock:
            self._cursor = 0

    def acquire(self, *, exclude: set[str] | None = None) -> KeyLease:
        excluded = exclude or set()
        with self._lock:
            if not self._records:
                raise LookupError(f"no configured keys for {self.provider}")
            now = self.clock.monotonic()
            for offset in range(len(self._records)):
                index = (self._cursor + offset) % len(self._records)
                record = self._records[index]
                cooling = (
                    record.cooldown_until_monotonic is not None
                    and record.cooldown_until_monotonic > now
                )
                if record.enabled and not cooling and record.fingerprint not in excluded:
                    record.last_use_monotonic = now
                    self._cursor = (index + 1) % len(self._records)
                    self._emit(record)
                    return KeyLease(record.provider, record.safe_id, record.fingerprint, record.value)
            raise LookupError(f"no healthy keys for {self.provider}")

    def success(self, lease: KeyLease) -> None:
        with self._lock:
            record = self._find(lease)
            # A bounded live validation may prove that an access value which
            # was previously rejected has been corrected provider-side.
            record.enabled = True
            record.successful_request_count += 1
            record.failure_count = 0
            record.last_failure_category = None
            record.cooldown_until_monotonic = None
            self._emit(record)

    def invalid(self, lease: KeyLease) -> None:
        with self._lock:
            record = self._find(lease)
            record.enabled = False
            record.failure_count += 1
            record.last_failure_category = RouteFailureCategory.INVALID_KEY.value
            self._emit(record)

    def rate_limited(self, lease: KeyLease, *, retry_after_seconds: float | None = None) -> None:
        with self._lock:
            record = self._find(lease)
            seconds = self.default_cooldown_seconds if retry_after_seconds is None else max(0.0, retry_after_seconds)
            record.failure_count += 1
            record.last_failure_category = RouteFailureCategory.RATE_LIMIT.value
            record.cooldown_until_monotonic = self.clock.monotonic() + seconds
            self._emit(record)

    def failure(self, lease: KeyLease, category: RouteFailureCategory) -> None:
        with self._lock:
            record = self._find(lease)
            record.failure_count += 1
            record.last_failure_category = category.value
            self._emit(record)

    def snapshot(self) -> tuple[KeyStateSnapshot, ...]:
        with self._lock:
            return tuple(self._snapshot(record) for record in self._records)

    def validation_leases(self) -> tuple[KeyLease, ...]:
        """Return every configured value for an explicit bounded validation.

        Normal routing never selects a disabled value. This separate seam lets
        the operator recheck a value after correcting an owner/provider-side
        condition without deleting durable health history first.
        """
        with self._lock:
            return tuple(
                KeyLease(record.provider, record.safe_id, record.fingerprint, record.value)
                for record in self._records
            )

    def has_healthy_key(self) -> bool:
        with self._lock:
            now = self.clock.monotonic()
            return any(
                record.enabled
                and (record.cooldown_until_monotonic is None or record.cooldown_until_monotonic <= now)
                for record in self._records
            )

    def restore(self, snapshots: tuple[object, ...]) -> None:
        """Rehydrate safe state by fingerprint; configured values stay memory-only."""
        with self._lock:
            by_fingerprint = {
                str(getattr(snapshot, "key_fingerprint")): snapshot  # noqa: B009 - generic persisted snapshot
                for snapshot in snapshots
                if getattr(snapshot, "provider", None) == self.provider
            }
            now_mono = self.clock.monotonic()
            now_utc = self.clock.utcnow()
            for record in self._records:
                snapshot = by_fingerprint.get(record.fingerprint)
                if snapshot is None:
                    continue
                record.enabled = bool(getattr(snapshot, "enabled", True))
                record.failure_count = max(0, int(getattr(snapshot, "failure_count", 0)))
                record.last_failure_category = getattr(snapshot, "last_failure_category", None)
                record.successful_request_count = max(
                    0,
                    int(
                        getattr(
                            snapshot,
                            "success_count",
                            getattr(snapshot, "successful_request_count", 0),
                        )
                    ),
                )
                last_use = getattr(snapshot, "last_use_at", None)
                if last_use is not None:
                    record.last_use_monotonic = now_mono - max(
                        0.0,
                        (now_utc - last_use).total_seconds(),
                    )
                cooldown = getattr(snapshot, "cooldown_until", None)
                if cooldown is not None and cooldown > now_utc:
                    record.cooldown_until_monotonic = now_mono + (
                        cooldown - now_utc
                    ).total_seconds()

    def _find(self, lease: KeyLease) -> _KeyRecord:
        for record in self._records:
            if record.fingerprint == lease.fingerprint:
                return record
        raise KeyError(lease.safe_id)

    def _snapshot(self, record: _KeyRecord) -> KeyStateSnapshot:
        last_use = None
        if record.last_use_monotonic is not None:
            elapsed = max(0.0, self.clock.monotonic() - record.last_use_monotonic)
            last_use = self.clock.utcnow() - timedelta(seconds=elapsed)
        cooldown = None
        if record.cooldown_until_monotonic is not None:
            remaining = max(0.0, record.cooldown_until_monotonic - self.clock.monotonic())
            cooldown = self.clock.utcnow() + timedelta(seconds=remaining)
        return KeyStateSnapshot(
            provider=record.provider,
            key_fingerprint=record.fingerprint,
            safe_id=record.safe_id,
            enabled=record.enabled,
            last_use_at=last_use,
            failure_count=record.failure_count,
            cooldown_until=cooldown,
            last_failure_category=record.last_failure_category,
            successful_request_count=record.successful_request_count,
        )

    def _emit(self, record: _KeyRecord) -> None:
        if self.sink:
            self.sink.record_snapshot(self._snapshot(record))

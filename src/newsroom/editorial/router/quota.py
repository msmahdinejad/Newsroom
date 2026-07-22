"""Atomic per-model/project RPM, TPM, and RPD admission accounting."""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from newsroom.editorial.router.types import (
    Clock,
    ModelRoute,
    QuotaStateSnapshot,
    RouteFailure,
    RouteFailureCategory,
    RouterStateSink,
    SystemClock,
    Usage,
)


@dataclass
class _TokenEntry:
    at: float
    tokens: int
    reservation_id: str


@dataclass
class _QuotaState:
    request_times: deque[float]
    token_entries: deque[_TokenEntry]
    day: date
    daily_count: int = 0
    cooldown_until_monotonic: float | None = None
    cooldown_category: RouteFailureCategory | None = None


@dataclass(frozen=True)
class QuotaReservation:
    reservation_id: str
    state_key: tuple[str, str, str]
    estimated_tokens: int


class QuotaController:
    def __init__(self, *, clock: Clock | None = None, sink: RouterStateSink | None = None) -> None:
        self.clock = clock or SystemClock()
        self.sink = sink
        self._states: dict[tuple[str, str, str], _QuotaState] = {}
        self._routes: dict[tuple[str, str, str], ModelRoute] = {}
        self._lock = threading.RLock()

    def reserve(
        self,
        route: ModelRoute,
        estimated_input_tokens: int,
        *,
        key_fingerprint: str | None = None,
    ) -> QuotaReservation:
        del key_fingerprint  # capacity is scope/model based, never key based
        with self._lock:
            key = self._state_key(route)
            state = self._state(key)
            self._routes[key] = route
            self._purge(state)
            now = self.clock.monotonic()
            estimate = max(0, int(estimated_input_tokens))
            if state.cooldown_until_monotonic is not None and now < state.cooldown_until_monotonic:
                raise RouteFailure(
                    state.cooldown_category or RouteFailureCategory.RATE_LIMIT,
                    retry_after_seconds=state.cooldown_until_monotonic - now,
                )
            if len(state.request_times) >= route.limits.rpm:
                retry = max(0.0, 60.0 - (now - state.request_times[0]))
                raise RouteFailure(RouteFailureCategory.RPM_EXHAUSTED, retry_after_seconds=retry)
            if sum(entry.tokens for entry in state.token_entries) + estimate > route.limits.tpm:
                retry = max(0.0, 60.0 - (now - state.token_entries[0].at)) if state.token_entries else 60.0
                raise RouteFailure(RouteFailureCategory.TPM_EXHAUSTED, retry_after_seconds=retry)
            if state.daily_count >= route.limits.rpd:
                raise RouteFailure(RouteFailureCategory.RPD_EXHAUSTED, retry_after_seconds=self._seconds_to_day_reset())

            reservation_id = uuid.uuid4().hex
            state.request_times.append(now)
            state.token_entries.append(_TokenEntry(now, estimate, reservation_id))
            state.daily_count += 1
            reservation = QuotaReservation(reservation_id, key, estimate)
            self._emit(key, state)
            return reservation

    def reconcile(self, reservation: QuotaReservation, usage: Usage | None) -> None:
        if usage is None:
            return
        with self._lock:
            state = self._states.get(reservation.state_key)
            if not state:
                return
            for entry in state.token_entries:
                if entry.reservation_id == reservation.reservation_id:
                    entry.tokens = usage.total_tokens
                    break
            self._emit(reservation.state_key, state)

    def exhaust_daily(self, route: ModelRoute, reset_at: datetime | None = None) -> None:
        with self._lock:
            key = self._state_key(route)
            state = self._state(key)
            self._routes[key] = route
            seconds = self._seconds_to_day_reset()
            if reset_at is not None:
                seconds = max(0.0, (reset_at - self.clock.utcnow()).total_seconds())
            state.cooldown_until_monotonic = self.clock.monotonic() + seconds
            state.cooldown_category = RouteFailureCategory.DAILY_QUOTA
            state.daily_count = max(state.daily_count, route.limits.rpd)
            self._emit(key, state)

    def cool_down(
        self,
        route: ModelRoute,
        retry_after_seconds: float | None,
        *,
        category: RouteFailureCategory = RouteFailureCategory.RATE_LIMIT,
    ) -> None:
        """Cool a project/model quota bucket without multiplying it by keys."""
        with self._lock:
            key = self._state_key(route)
            state = self._state(key)
            self._routes[key] = route
            seconds = 60.0 if retry_after_seconds is None else max(0.0, retry_after_seconds)
            state.cooldown_until_monotonic = self.clock.monotonic() + seconds
            state.cooldown_category = category
            self._emit(key, state)

    def snapshot(self) -> tuple[QuotaStateSnapshot, ...]:
        with self._lock:
            for state in self._states.values():
                self._purge(state)
            return tuple(self._snapshot(key, state) for key, state in self._states.items())

    def restore(self, snapshots: tuple[object, ...], routes: list[ModelRoute]) -> None:
        """Rehydrate safe rolling usage/cooldowns after process restart."""
        with self._lock:
            now_utc = self.clock.utcnow()
            now_mono = self.clock.monotonic()
            for route in routes:
                key = self._state_key(route)
                scope_hash = hashlib.sha256(route.quota_scope.encode("utf-8")).hexdigest()
                snapshot = next(
                    (
                        item
                        for item in snapshots
                        if getattr(item, "provider", None) == key[0]
                        and getattr(item, "model", None) == key[1]
                        and getattr(item, "scope_fingerprint", None) == scope_hash
                    ),
                    None,
                )
                if snapshot is None or key in self._states:
                    continue
                day_started = getattr(snapshot, "day_started_at", None)
                day = day_started.date() if day_started is not None else now_utc.date()
                state = _QuotaState(deque(), deque(), day)
                if day == now_utc.date():
                    state.daily_count = max(0, int(getattr(snapshot, "rpd_used", 0)))
                window_started = getattr(snapshot, "window_started_at", None)
                elapsed = (
                    max(0.0, (now_utc - window_started).total_seconds())
                    if window_started is not None
                    else 0.0
                )
                if elapsed < 60.0:
                    at = now_mono - elapsed
                    for _ in range(max(0, int(getattr(snapshot, "rpm_used", 0)))):
                        state.request_times.append(at)
                    tokens = max(0, int(getattr(snapshot, "tpm_used", 0)))
                    if tokens:
                        state.token_entries.append(_TokenEntry(at, tokens, f"restored-{uuid.uuid4().hex}"))
                cooldown = getattr(snapshot, "cooldown_until", None)
                if cooldown is not None and cooldown > now_utc:
                    state.cooldown_until_monotonic = now_mono + (
                        cooldown - now_utc
                    ).total_seconds()
                    state.cooldown_category = RouteFailureCategory.RATE_LIMIT
                self._states[key] = state
                self._routes[key] = route

    def _state(self, key: tuple[str, str, str]) -> _QuotaState:
        today = self.clock.utcnow().date()
        state = self._states.get(key)
        if state is None:
            state = _QuotaState(deque(), deque(), today)
            self._states[key] = state
        elif state.day != today:
            state.day = today
            state.daily_count = 0
            state.cooldown_until_monotonic = None
            state.cooldown_category = None
        return state

    @staticmethod
    def _state_key(route: ModelRoute) -> tuple[str, str, str]:
        # Capacity is project-and-model scoped, never key scoped. Rotating a
        # key therefore cannot manufacture additional capacity for a route.
        return route.provider, route.model, route.quota_scope

    def _purge(self, state: _QuotaState) -> None:
        now = self.clock.monotonic()
        while state.request_times and now - state.request_times[0] >= 60.0:
            state.request_times.popleft()
        while state.token_entries and now - state.token_entries[0].at >= 60.0:
            state.token_entries.popleft()

    def _seconds_to_day_reset(self) -> float:
        now = self.clock.utcnow()
        tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
        return max(0.0, (tomorrow - now).total_seconds())

    def _snapshot(self, key: tuple[str, str, str], state: _QuotaState) -> QuotaStateSnapshot:
        provider, model, scope = key
        window = None
        if state.request_times:
            elapsed = max(0.0, self.clock.monotonic() - state.request_times[0])
            window = self.clock.utcnow() - timedelta(seconds=elapsed)
        cooldown = None
        if state.cooldown_until_monotonic is not None:
            remaining = max(0.0, state.cooldown_until_monotonic - self.clock.monotonic())
            cooldown = self.clock.utcnow() + timedelta(seconds=remaining)
        return QuotaStateSnapshot(
            provider=provider,
            model=model,
            scope_fingerprint=hashlib.sha256(scope.encode("utf-8")).hexdigest(),
            rpm_used=len(state.request_times),
            tpm_used=sum(entry.tokens for entry in state.token_entries),
            rpd_used=state.daily_count,
            reserved_tokens=sum(entry.tokens for entry in state.token_entries),
            window_started_at=window,
            day_started_at=datetime.combine(state.day, datetime.min.time(), tzinfo=self.clock.utcnow().tzinfo),
            cooldown_until=cooldown,
        )

    def _emit(self, key: tuple[str, str, str], state: _QuotaState) -> None:
        if self.sink:
            self.sink.record_snapshot(self._snapshot(key, state))

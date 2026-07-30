"""Safe public types for the Production multi-provider editorial router."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from newsroom.editorial.schema import EditorialRequest, EditorialResponse


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def utcnow(self) -> datetime: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def utcnow(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class ManualClock:
    """Thread-safe deterministic clock used at the public time boundary."""

    def __init__(self, start: datetime | None = None) -> None:
        self._elapsed = 0.0
        self._start = start or datetime(2026, 1, 1, tzinfo=UTC)
        self._lock = threading.RLock()

    def monotonic(self) -> float:
        with self._lock:
            return self._elapsed

    def utcnow(self) -> datetime:
        with self._lock:
            return self._start + timedelta(seconds=self._elapsed)

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._elapsed += max(0.0, float(seconds))


@dataclass(frozen=True)
class RateLimits:
    rpm: int = 60
    tpm: int = 1_000_000
    rpd: int = 1_000


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    keys: tuple[str, ...] = field(default_factory=tuple, repr=False)
    models: tuple[str, ...] = field(default_factory=tuple)
    api_base: str = ""
    protocol: str = "openai"
    quota_scope: str = "default-project"
    limits: RateLimits = field(default_factory=RateLimits)
    concurrency: int = 1
    min_spacing_seconds: float = 0.0


@dataclass(frozen=True)
class RouterConfig:
    providers: tuple[ProviderConfig, ...]
    enabled: bool = True
    provider_order: tuple[str, ...] = ("gemini", "mistral", "groq", "nvidia")
    proxy_url: str | None = field(default=None, repr=False)
    queue_size: int = 32
    provider_cooldown_seconds: float = 300.0
    key_cooldown_seconds: float = 60.0
    transient_retry_jitter_seconds: float = 0.25
    max_route_attempts: int = 64

    def provider(self, name: str) -> ProviderConfig:
        normalized = name.strip().lower()
        for provider in self.providers:
            if provider.name == normalized:
                return provider
        raise KeyError(normalized)


@dataclass
class ModelRoute:
    provider: str
    model: str
    limits: RateLimits = field(default_factory=RateLimits)
    quota_scope: str = "default-project"
    concurrency: int = 1
    min_spacing_seconds: float = 0.0
    validation_status: str = "unvalidated"
    enabled: bool = False
    supported_capabilities: frozenset[str] = field(default_factory=frozenset)
    last_failure_category: str | None = None

    @classmethod
    def validated(
        cls,
        provider: str,
        model: str,
        *,
        limits: RateLimits | None = None,
        quota_scope: str = "default-project",
        concurrency: int = 1,
        min_spacing_seconds: float = 0.0,
        supported_capabilities: frozenset[str] | None = None,
    ) -> ModelRoute:
        return cls(
            provider=provider,
            model=model,
            limits=limits or RateLimits(),
            quota_scope=quota_scope,
            concurrency=max(1, concurrency),
            min_spacing_seconds=max(0.0, min_spacing_seconds),
            validation_status="validated",
            enabled=True,
            supported_capabilities=supported_capabilities
            or frozenset({"connectivity", "persian", "structured", "grounding", "bounded_output"}),
        )


class RouteFailureCategory(StrEnum):
    INVALID_KEY = "invalid_key"
    RATE_LIMIT = "rate_limit"
    DAILY_QUOTA = "daily_quota"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    NETWORK_ERROR = "network_error"
    INVALID_MODEL = "invalid_model"
    UNSUPPORTED_PARAMETER = "unsupported_parameter"
    MALFORMED_SCHEMA = "malformed_schema"
    POLICY_REJECTION = "policy_rejection"
    CONTEXT_LENGTH = "context_length"
    RPM_EXHAUSTED = "rpm_exhausted"
    TPM_EXHAUSTED = "tpm_exhausted"
    RPD_EXHAUSTED = "rpd_exhausted"
    QUEUE_FULL = "queue_full"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNKNOWN = "unknown"


@dataclass(eq=False)
class RouteFailure(Exception):  # noqa: N818 - domain vocabulary: a failed route attempt
    category: RouteFailureCategory
    safe_detail: str = ""
    retry_after_seconds: float | None = None
    daily_reset_at: datetime | None = None
    repair_payload: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.safe_detail = self.safe_detail[:300]
        Exception.__init__(self, self.category.value)

    @property
    def provider_level(self) -> bool:
        return self.category in {
            RouteFailureCategory.TIMEOUT,
            RouteFailureCategory.SERVER_ERROR,
            RouteFailureCategory.NETWORK_ERROR,
            RouteFailureCategory.PROVIDER_UNAVAILABLE,
        }

    def __str__(self) -> str:
        return self.category.value


class DispatchQueueFull(RouteFailure):
    def __init__(self) -> None:
        super().__init__(RouteFailureCategory.QUEUE_FULL, "bounded dispatcher queue is full")


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return max(0, self.input_tokens) + max(0, self.output_tokens)

    @classmethod
    def from_response(cls, response: EditorialResponse) -> Usage | None:
        if not response.usage:
            return None
        return cls(
            input_tokens=int(response.usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(response.usage.get("completion_tokens", 0) or 0),
        )


@dataclass(frozen=True)
class RouterRequestContext:
    job_id: str | None = None
    shard_id: str | None = None
    stage: str = "map"
    report_id: int | None = None
    artifact_id: int | None = None
    repair_payload: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class RoutedEditorialResponse:
    response: EditorialResponse
    fallback_used: bool = False
    repaired: bool = False


class RouteTransport(Protocol):
    def execute(
        self,
        route: ModelRoute,
        key_value: str,
        request: EditorialRequest,
        context: RouterRequestContext,
    ) -> EditorialResponse: ...


@dataclass(frozen=True)
class KeyStateSnapshot:
    provider: str
    key_fingerprint: str
    safe_id: str
    enabled: bool
    last_use_at: datetime | None
    failure_count: int
    cooldown_until: datetime | None
    last_failure_category: str | None
    successful_request_count: int


@dataclass(frozen=True)
class QuotaStateSnapshot:
    provider: str
    model: str
    scope_fingerprint: str
    rpm_used: int
    tpm_used: int
    rpd_used: int
    reserved_tokens: int
    window_started_at: datetime | None
    day_started_at: datetime
    cooldown_until: datetime | None


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitStateSnapshot:
    provider: str
    state: str
    consecutive_failures: int
    cooldown_until: datetime | None
    last_failure_category: str | None
    half_open_probe_in_flight: bool


@dataclass(frozen=True)
class ModelHealthSnapshot:
    provider: str
    model: str
    validation_status: str
    latency_ms: int | None
    last_success_at: datetime | None
    last_failure_category: str | None
    supported_capabilities: tuple[str, ...]
    enabled: bool


@dataclass(frozen=True)
class RouteAttemptEvent:
    event_id: str
    job_id: str | None
    shard_id: str | None
    stage: str
    report_id: int | None
    artifact_id: int | None
    provider: str
    model: str
    key_fingerprint: str | None
    status: str
    failure_category: str | None
    latency_ms: int
    estimated_input_tokens: int
    actual_input_tokens: int | None
    actual_output_tokens: int | None
    retry_after_seconds: float | None
    created_at: datetime

    @classmethod
    def new(cls, **values: Any) -> RouteAttemptEvent:
        return cls(event_id=uuid.uuid4().hex, **values)


class RouterStateSink(Protocol):
    def record_snapshot(
        self,
        snapshot: KeyStateSnapshot
        | QuotaStateSnapshot
        | CircuitStateSnapshot
        | ModelHealthSnapshot,
    ) -> None: ...

    def record_attempt(self, event: RouteAttemptEvent) -> None: ...


class InMemoryRouterStateSink:
    """Safe test/default sink. It never receives a provider access value."""

    def __init__(self) -> None:
        self.snapshots: list[object] = []
        self.attempts: list[RouteAttemptEvent] = []

    def record_snapshot(self, snapshot: object) -> None:
        self.snapshots.append(snapshot)

    def record_attempt(self, event: RouteAttemptEvent) -> None:
        self.attempts.append(event)


class ProviderCircuit:
    def __init__(
        self,
        provider: str,
        *,
        clock: Clock,
        cooldown_seconds: float = 300.0,
        failure_threshold: int = 3,
        sink: RouterStateSink | None = None,
    ) -> None:
        self.provider = provider
        self.clock = clock
        self.cooldown_seconds = cooldown_seconds
        self.failure_threshold = failure_threshold
        self.sink = sink
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.cooldown_until_monotonic: float | None = None
        self.last_failure_category: str | None = None
        self.half_open_probe_in_flight = False

    def allow_request(self) -> bool:
        now = self.clock.monotonic()
        if self.state is CircuitState.CLOSED:
            return True
        if self.state is CircuitState.OPEN:
            if self.cooldown_until_monotonic is None or now < self.cooldown_until_monotonic:
                return False
            self.state = CircuitState.HALF_OPEN
            self.half_open_probe_in_flight = True
            self._emit()
            return True
        if self.half_open_probe_in_flight:
            return False
        self.half_open_probe_in_flight = True
        self._emit()
        return True

    def success(self) -> None:
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.cooldown_until_monotonic = None
        self.last_failure_category = None
        self.half_open_probe_in_flight = False
        self._emit()

    def failure(self, category: RouteFailureCategory, *, provider_level: bool = True) -> None:
        self.last_failure_category = category.value
        if provider_level:
            self.consecutive_failures += 1
        if (
            self.state is CircuitState.HALF_OPEN
            or self.consecutive_failures >= self.failure_threshold
        ):
            self.open(category)
        else:
            self._emit()

    def open(
        self, category: RouteFailureCategory = RouteFailureCategory.PROVIDER_UNAVAILABLE
    ) -> None:
        self.state = CircuitState.OPEN
        self.last_failure_category = category.value
        self.cooldown_until_monotonic = self.clock.monotonic() + self.cooldown_seconds
        self.half_open_probe_in_flight = False
        self._emit()

    def snapshot(self) -> CircuitStateSnapshot:
        cooldown = None
        if self.cooldown_until_monotonic is not None:
            seconds = max(0.0, self.cooldown_until_monotonic - self.clock.monotonic())
            cooldown = self.clock.utcnow() + timedelta(seconds=seconds)
        return CircuitStateSnapshot(
            provider=self.provider,
            state=self.state.value,
            consecutive_failures=self.consecutive_failures,
            cooldown_until=cooldown,
            last_failure_category=self.last_failure_category,
            half_open_probe_in_flight=self.half_open_probe_in_flight,
        )

    def restore(self, snapshot: object) -> None:
        """Rehydrate a persisted circuit without exposing provider access."""
        if getattr(snapshot, "provider", None) != self.provider:
            return
        try:
            self.state = CircuitState(str(getattr(snapshot, "state")))  # noqa: B009 - generic persisted snapshot
        except ValueError:
            return
        self.consecutive_failures = max(
            0,
            int(getattr(snapshot, "consecutive_failures", 0)),
        )
        self.last_failure_category = getattr(snapshot, "last_failure_category", None)
        self.half_open_probe_in_flight = False
        cooldown = getattr(snapshot, "cooldown_until", None)
        if cooldown is not None and cooldown > self.clock.utcnow():
            self.cooldown_until_monotonic = (
                self.clock.monotonic() + (cooldown - self.clock.utcnow()).total_seconds()
            )
        elif self.state is CircuitState.OPEN:
            # Expired persisted OPEN state enters half-open on the next call.
            self.cooldown_until_monotonic = self.clock.monotonic()

    def _emit(self) -> None:
        if self.sink:
            self.sink.record_snapshot(self.snapshot())

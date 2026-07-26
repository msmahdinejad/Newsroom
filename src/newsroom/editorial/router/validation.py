"""Bounded real model capability validation before route enablement."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from functools import partial

from newsroom.editorial.grounding import validate_grounding
from newsroom.editorial.router.dispatcher import QueuedDispatcher
from newsroom.editorial.router.key_pool import KeyLease, KeyPool
from newsroom.editorial.router.types import (
    Clock,
    ModelHealthSnapshot,
    ModelRoute,
    RouteAttemptEvent,
    RouteFailure,
    RouteFailureCategory,
    RouterRequestContext,
    RouterStateSink,
    RouteTransport,
    SystemClock,
    Usage,
)
from newsroom.editorial.schema import (
    EditorialEvidenceSet,
    EditorialRequest,
    EditorialResponse,
    EvidenceSourceItem,
    EvidenceStoryPacket,
)
from newsroom.editorial.validation import parse_and_validate

PERSIAN_RE = re.compile(r"[\u0600-\u06ff]")


@dataclass(frozen=True)
class ModelValidationResult:
    provider: str
    model: str
    status: str
    latency_ms: int | None
    failure_category: str | None
    supported_capabilities: tuple[str, ...]


@dataclass(frozen=True)
class AccessValidationResult:
    provider: str
    safe_id: str
    model: str | None
    status: str
    latency_ms: int | None
    failure_category: str | None


def validation_request() -> EditorialRequest:
    evidence = EditorialEvidenceSet(
        report_mode="validation",
        stories=[
            EvidenceStoryPacket(
                story_id=1,
                headline="A test release is available",
                facts=["A test release is available."],
                sources=[
                    EvidenceSourceItem(
                        ref_id="ev-1-0",
                        item_id=1,
                        original_title="A test release is available",
                        excerpt="A test release is available.",
                        original_url="https://example.test/release",
                    )
                ],
            )
        ],
    )
    return EditorialRequest(evidence=evidence, temperature=0.0, max_input_tokens=1500, max_output_tokens=800, timeout_seconds=45)


class ModelValidator:
    def __init__(
        self,
        *,
        transport: RouteTransport,
        dispatcher: QueuedDispatcher,
        key_pools: dict[str, KeyPool],
        clock: Clock | None = None,
        sink: RouterStateSink | None = None,
    ) -> None:
        self.transport = transport
        self.dispatcher = dispatcher
        self.key_pools = key_pools
        self.clock = clock or SystemClock()
        self.sink = sink

    def validate(self, route: ModelRoute) -> ModelValidationResult:
        request = validation_request()
        pool = self.key_pools[route.provider]
        if pool.key_count == 0:
            return self._failure(route, "not_configured", None, None)
        if not pool.has_healthy_key():
            return self._failure(route, "unavailable", RouteFailureCategory.INVALID_KEY, None)
        started = time.monotonic()
        tried_keys: set[str] = set()
        last_failure = RouteFailureCategory.INVALID_KEY
        while True:
            try:
                lease = pool.acquire(exclude=tried_keys)
            except LookupError:
                status = "failed" if tried_keys else "unavailable"
                return self._failure(
                    route,
                    status,
                    last_failure,
                    int((time.monotonic() - started) * 1000) if tried_keys else None,
                )
            tried_keys.add(lease.fingerprint)
            try:
                transient_retry_used = False
                while True:
                    attempt_started = self.clock.monotonic()
                    try:
                        response = self.dispatcher.dispatch(
                            route,
                            400,
                            partial(
                                self.transport.execute,
                                route,
                                lease.value,
                                request,
                                RouterRequestContext(stage="validation"),
                            ),
                            key_fingerprint=lease.fingerprint,
                        )
                    except RouteFailure as failure:
                        self._record_attempt(
                            route,
                            lease,
                            "validation",
                            attempt_started,
                            "failed",
                            failure,
                        )
                        if (
                            failure.category
                            in {
                                RouteFailureCategory.TIMEOUT,
                                RouteFailureCategory.SERVER_ERROR,
                                RouteFailureCategory.NETWORK_ERROR,
                            }
                            and not transient_retry_used
                        ):
                            transient_retry_used = True
                            self.clock.sleep(0.25)
                            continue
                        raise
                    try:
                        capabilities = self._validate_capabilities(
                            route,
                            request,
                            response,
                        )
                    except RouteFailure as failure:
                        self._record_attempt(
                            route,
                            lease,
                            "validation",
                            attempt_started,
                            "failed",
                            failure,
                        )
                        raise
                    self._record_attempt(
                        route,
                        lease,
                        "validation",
                        attempt_started,
                        "validated",
                        None,
                        response,
                    )
                    break
                latency_ms = int((time.monotonic() - started) * 1000)
                route.enabled = True
                route.validation_status = "validated"
                route.supported_capabilities = frozenset(capabilities)
                pool.success(lease)
                result = ModelValidationResult(
                    route.provider,
                    route.model,
                    "validated",
                    latency_ms,
                    None,
                    capabilities,
                )
                self._emit(route, result)
                return result
            except RouteFailure as failure:
                last_failure = failure.category
                route.enabled = False
                route.validation_status = "failed"
                route.last_failure_category = failure.category.value
                if failure.category is RouteFailureCategory.INVALID_KEY:
                    pool.invalid(lease)
                    continue
                if failure.category is RouteFailureCategory.RATE_LIMIT:
                    if route.provider == "gemini":
                        self.dispatcher.quota.cool_down(
                            route,
                            failure.retry_after_seconds,
                        )
                        pool.failure(lease, failure.category)
                        return self._failure(
                            route,
                            "failed",
                            failure.category,
                            int((time.monotonic() - started) * 1000),
                        )
                    pool.rate_limited(lease, retry_after_seconds=failure.retry_after_seconds)
                    continue
                if failure.category in {
                    RouteFailureCategory.TIMEOUT,
                    RouteFailureCategory.SERVER_ERROR,
                    RouteFailureCategory.NETWORK_ERROR,
                }:
                    pool.failure(lease, failure.category)
                    continue
                pool.failure(lease, failure.category)
                return self._failure(
                    route,
                    "failed",
                    failure.category,
                    int((time.monotonic() - started) * 1000),
                )

    def validate_all(self, routes: list[ModelRoute]) -> list[ModelValidationResult]:
        return [self.validate(route) for route in routes]

    def validate_access_values(
        self,
        routes: list[ModelRoute],
    ) -> list[AccessValidationResult]:
        """Probe every configured access value through one validated route.

        Disabled values are intentionally included. This is an explicit,
        bounded operator validation path, not normal request routing.
        """
        results: list[AccessValidationResult] = []
        request = validation_request()
        for provider, pool in self.key_pools.items():
            route = next(
                (
                    item
                    for item in routes
                    if item.provider == provider
                    and item.enabled
                    and item.validation_status == "validated"
                ),
                None,
            )
            if route is None:
                route = next(
                    (item for item in routes if item.provider == provider),
                    None,
                )
            for lease in pool.validation_leases():
                if route is None:
                    results.append(
                        AccessValidationResult(
                            provider=provider,
                            safe_id=lease.safe_id,
                            model=None,
                            status="unavailable",
                            latency_ms=None,
                            failure_category=RouteFailureCategory.PROVIDER_UNAVAILABLE.value,
                        )
                    )
                    continue
                started = time.monotonic()
                transient_retry_used = False
                try:
                    while True:
                        attempt_started = self.clock.monotonic()
                        try:
                            response = self.dispatcher.dispatch(
                                route,
                                400,
                                partial(
                                    self.transport.execute,
                                    route,
                                    lease.value,
                                    request,
                                    RouterRequestContext(stage="access_validation"),
                                ),
                                key_fingerprint=lease.fingerprint,
                            )
                        except RouteFailure as failure:
                            self._record_attempt(
                                route,
                                lease,
                                "access_validation",
                                attempt_started,
                                "failed",
                                failure,
                            )
                            if (
                                failure.category
                                in {
                                    RouteFailureCategory.TIMEOUT,
                                    RouteFailureCategory.SERVER_ERROR,
                                    RouteFailureCategory.NETWORK_ERROR,
                                }
                                and not transient_retry_used
                            ):
                                transient_retry_used = True
                                self.clock.sleep(0.25)
                                continue
                            raise
                        try:
                            self._validate_capabilities(route, request, response)
                        except RouteFailure as failure:
                            self._record_attempt(
                                route,
                                lease,
                                "access_validation",
                                attempt_started,
                                "failed",
                                failure,
                            )
                            raise
                        self._record_attempt(
                            route,
                            lease,
                            "access_validation",
                            attempt_started,
                            "validated",
                            None,
                            response,
                        )
                        break
                    pool.success(lease)
                    results.append(
                        AccessValidationResult(
                            provider=provider,
                            safe_id=lease.safe_id,
                            model=route.model,
                            status="validated",
                            latency_ms=int((time.monotonic() - started) * 1000),
                            failure_category=None,
                        )
                    )
                except RouteFailure as failure:
                    if failure.category is RouteFailureCategory.INVALID_KEY:
                        pool.invalid(lease)
                    elif failure.category is RouteFailureCategory.RATE_LIMIT:
                        if provider == "gemini":
                            self.dispatcher.quota.cool_down(
                                route,
                                failure.retry_after_seconds,
                            )
                            pool.failure(lease, failure.category)
                        else:
                            pool.rate_limited(
                                lease,
                                retry_after_seconds=failure.retry_after_seconds,
                            )
                    elif failure.category is RouteFailureCategory.DAILY_QUOTA:
                        self.dispatcher.quota.exhaust_daily(
                            route,
                            failure.daily_reset_at,
                        )
                        pool.failure(lease, failure.category)
                    else:
                        pool.failure(lease, failure.category)
                    results.append(
                        AccessValidationResult(
                            provider=provider,
                            safe_id=lease.safe_id,
                            model=route.model,
                            status="failed",
                            latency_ms=int((time.monotonic() - started) * 1000),
                            failure_category=failure.category.value,
                        )
                    )
        return results

    @staticmethod
    def _validate_capabilities(
        route: ModelRoute,
        request: EditorialRequest,
        response: EditorialResponse,
    ) -> tuple[str, ...]:
        output = response.output
        persian = " ".join(f"{story.headline_fa} {story.summary_fa}" for story in output.stories)
        if not PERSIAN_RE.search(persian):
            raise RouteFailure(
                RouteFailureCategory.MALFORMED_SCHEMA,
                "Persian capability validation failed",
            )
        parsed, validation = parse_and_validate(
            output.model_dump_json(),
            request.evidence,
            request.max_output_tokens,
        )
        if parsed is None or not validation.valid:
            raise RouteFailure(
                RouteFailureCategory.MALFORMED_SCHEMA,
                "structured capability validation failed",
            )
        grounded, grounding = validate_grounding(request.evidence, parsed)
        if not grounding.valid or not grounded.stories:
            raise RouteFailure(
                RouteFailureCategory.MALFORMED_SCHEMA,
                "grounding parse validation failed",
            )
        usage = Usage.from_response(response)
        if usage and usage.output_tokens > request.max_output_tokens:
            raise RouteFailure(
                RouteFailureCategory.MALFORMED_SCHEMA,
                "bounded output validation failed",
            )
        return (
            "bounded_output",
            "connectivity",
            "grounding",
            "persian",
            "structured",
        )

    def _record_attempt(
        self,
        route: ModelRoute,
        lease: KeyLease,
        stage: str,
        started: float,
        status: str,
        failure: RouteFailure | None,
        response: EditorialResponse | None = None,
    ) -> None:
        if self.sink is None:
            return
        usage = Usage.from_response(response) if response is not None else None
        self.sink.record_attempt(
            RouteAttemptEvent.new(
                job_id=None,
                shard_id=None,
                stage=stage,
                report_id=None,
                artifact_id=None,
                provider=route.provider,
                model=route.model,
                key_fingerprint=lease.fingerprint,
                status=status,
                failure_category=failure.category.value if failure else None,
                latency_ms=int((self.clock.monotonic() - started) * 1000),
                estimated_input_tokens=400,
                actual_input_tokens=usage.input_tokens if usage else None,
                actual_output_tokens=usage.output_tokens if usage else None,
                retry_after_seconds=(
                    failure.retry_after_seconds if failure else None
                ),
                created_at=self.clock.utcnow(),
            )
        )

    def _failure(
        self,
        route: ModelRoute,
        status: str,
        category: RouteFailureCategory | None,
        latency_ms: int | None,
    ) -> ModelValidationResult:
        route.enabled = False
        route.validation_status = status
        route.last_failure_category = category.value if category is not None else None
        result = ModelValidationResult(
            route.provider,
            route.model,
            status,
            latency_ms,
            category.value if category is not None else None,
            (),
        )
        self._emit(route, result)
        return result

    def _emit(self, route: ModelRoute, result: ModelValidationResult) -> None:
        if self.sink:
            self.sink.record_snapshot(
                ModelHealthSnapshot(
                    provider=route.provider,
                    model=route.model,
                    validation_status=result.status,
                    latency_ms=result.latency_ms,
                    last_success_at=self.clock.utcnow() if result.status == "validated" else None,
                    last_failure_category=result.failure_category,
                    supported_capabilities=result.supported_capabilities,
                    enabled=route.enabled,
                )
            )

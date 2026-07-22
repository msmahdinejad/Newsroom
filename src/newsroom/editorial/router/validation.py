"""Bounded real model capability validation before route enablement."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from functools import partial

from newsroom.editorial.grounding import validate_grounding
from newsroom.editorial.router.dispatcher import QueuedDispatcher
from newsroom.editorial.router.key_pool import KeyPool
from newsroom.editorial.router.types import (
    Clock,
    ModelHealthSnapshot,
    ModelRoute,
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
                        break
                    except RouteFailure as failure:
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
                latency_ms = int((time.monotonic() - started) * 1000)
                output = response.output
                persian = " ".join(
                    f"{story.headline_fa} {story.summary_fa} {story.why_it_matters_fa}"
                    for story in output.stories
                )
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

                capabilities = (
                    "bounded_output",
                    "connectivity",
                    "grounding",
                    "persian",
                    "structured",
                )
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

    def _failure(
        self,
        route: ModelRoute,
        status: str,
        category: RouteFailureCategory,
        latency_ms: int | None,
    ) -> ModelValidationResult:
        route.enabled = False
        route.validation_status = status
        route.last_failure_category = category.value
        result = ModelValidationResult(route.provider, route.model, status, latency_ms, category.value, ())
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

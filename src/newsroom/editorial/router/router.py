"""Persistent-state-ready multi-provider routing and bounded failure policy."""

from __future__ import annotations

from dataclasses import replace

from newsroom.editorial.deterministic_provider import DeterministicEditorialProvider
from newsroom.editorial.provider import EditorialProvider
from newsroom.editorial.router.dispatcher import QueuedDispatcher
from newsroom.editorial.router.key_pool import KeyLease, KeyPool
from newsroom.editorial.router.types import (
    CircuitState,
    Clock,
    InMemoryRouterStateSink,
    ModelHealthSnapshot,
    ModelRoute,
    ProviderCircuit,
    RouteAttemptEvent,
    RoutedEditorialResponse,
    RouteFailure,
    RouteFailureCategory,
    RouterConfig,
    RouterRequestContext,
    RouterStateSink,
    RouteTransport,
    SystemClock,
    Usage,
)
from newsroom.editorial.router.validation import ModelValidationResult, ModelValidator
from newsroom.editorial.schema import EditorialRequest, EditorialResponse


class MultiProviderRouter(EditorialProvider):
    """Gemini → Mistral → Groq → NVIDIA → deterministic editorial router."""

    def __init__(
        self,
        config: RouterConfig,
        *,
        routes: list[ModelRoute],
        key_pools: dict[str, KeyPool],
        transport: RouteTransport,
        dispatcher: QueuedDispatcher,
        circuits: dict[str, ProviderCircuit],
        clock: Clock,
        state_sink: RouterStateSink,
        fallback: EditorialProvider,
    ) -> None:
        self.config = config
        self.routes = routes
        self.key_pools = key_pools
        self.transport = transport
        self.dispatcher = dispatcher
        self.circuits = circuits
        self.clock = clock
        self.state_sink = state_sink
        self.fallback = fallback

    @classmethod
    def from_config(
        cls,
        config: RouterConfig,
        *,
        transport: RouteTransport,
        validated_models: dict[str, tuple[str, ...]] | None = None,
        clock: Clock | None = None,
        state_sink: RouterStateSink | None = None,
        fallback: EditorialProvider | None = None,
    ) -> MultiProviderRouter:
        actual_clock = clock or SystemClock()
        sink = state_sink or InMemoryRouterStateSink()
        validated_models = validated_models or {}
        routes: list[ModelRoute] = []
        pools: dict[str, KeyPool] = {}
        circuits: dict[str, ProviderCircuit] = {}
        for provider in config.providers:
            pools[provider.name] = KeyPool(
                provider.name,
                provider.keys,
                clock=actual_clock,
                default_cooldown_seconds=config.key_cooldown_seconds,
                sink=sink,
            )
            circuits[provider.name] = ProviderCircuit(
                provider.name,
                clock=actual_clock,
                cooldown_seconds=config.provider_cooldown_seconds,
                sink=sink,
            )
            enabled = set(validated_models.get(provider.name, ()))
            for model in provider.models:
                if model in enabled:
                    route = ModelRoute.validated(
                        provider.name,
                        model,
                        limits=provider.limits,
                        quota_scope=provider.quota_scope,
                        concurrency=provider.concurrency,
                        min_spacing_seconds=provider.min_spacing_seconds,
                    )
                else:
                    route = ModelRoute(
                        provider=provider.name,
                        model=model,
                        limits=provider.limits,
                        quota_scope=provider.quota_scope,
                        concurrency=provider.concurrency,
                        min_spacing_seconds=provider.min_spacing_seconds,
                    )
                routes.append(route)

        dispatcher = QueuedDispatcher(
            max_queue_size=config.queue_size,
            clock=actual_clock,
            sink=sink,
        )
        return cls(
            config,
            routes=routes,
            key_pools=pools,
            transport=transport,
            dispatcher=dispatcher,
            circuits=circuits,
            clock=actual_clock,
            state_sink=sink,
            fallback=fallback or DeterministicEditorialProvider(),
        )

    @property
    def name(self) -> str:
        return "multi_provider_router"

    @property
    def model_name(self) -> str:
        return "dynamic-validated-route"

    def generate(self, request: EditorialRequest) -> EditorialResponse:
        """EditorialProvider-compatible entrypoint for existing orchestration."""
        context = RouterRequestContext(
            job_id=request.job_id or None,
            shard_id=request.shard_id or None,
            stage=request.stage,
        )
        routed = self.route(request, context)
        routed.response.fallback_used = routed.fallback_used
        return routed.response

    def route(
        self,
        request: EditorialRequest,
        context: RouterRequestContext | None = None,
    ) -> RoutedEditorialResponse:
        actual_context = context or RouterRequestContext()
        result = self._route_validated(request, actual_context)
        if result is not None:
            return result
        response = self.fallback.generate(request)
        response.fallback_used = True
        return RoutedEditorialResponse(response=response, fallback_used=True)

    def validate_models(self) -> list[ModelValidationResult]:
        validator = ModelValidator(
            transport=self.transport,
            dispatcher=self.dispatcher,
            key_pools=self.key_pools,
            clock=self.clock,
            sink=self.state_sink,
        )
        return validator.validate_all(self.routes)

    def key_pool(self, provider: str) -> KeyPool:
        return self.key_pools[provider]

    def model_route(self, provider: str, model: str) -> ModelRoute:
        for route in self.routes:
            if route.provider == provider and route.model == model:
                return route
        raise KeyError((provider, model))

    def circuit(self, provider: str) -> ProviderCircuit:
        return self.circuits[provider]

    def health(self) -> dict[str, object]:
        providers: dict[str, object] = {}
        for provider in self.config.provider_order:
            pool = self.key_pools.get(provider)
            circuit = self.circuits.get(provider)
            if pool is None or circuit is None:
                continue
            providers[provider] = {
                "circuit": circuit.snapshot().state,
                "keys": [
                    {
                        "safe_id": state.safe_id,
                        "enabled": state.enabled,
                        "last_use_at": state.last_use_at,
                        "failure_count": state.failure_count,
                        "cooldown_until": state.cooldown_until,
                        "last_failure_category": state.last_failure_category,
                        "successful_request_count": state.successful_request_count,
                    }
                    for state in pool.snapshot()
                ],
                "models": {
                    route.model: {
                        "validation_status": route.validation_status,
                        "enabled": route.enabled,
                        "supported_capabilities": sorted(route.supported_capabilities),
                        "last_failure_category": route.last_failure_category,
                    }
                    for route in self.routes
                    if route.provider == provider
                },
            }
        return {"providers": providers, "queue_depth": self.dispatcher.queued_count}

    def restore(self, persistence_snapshot: object) -> None:
        """Rehydrate persisted safe cooldown/usage state after restart."""
        key_snapshots = tuple(getattr(persistence_snapshot, "keys", ()))
        quota_snapshots = tuple(getattr(persistence_snapshot, "quotas", ()))
        circuit_snapshots = tuple(getattr(persistence_snapshot, "circuits", ()))
        for pool in self.key_pools.values():
            pool.restore(key_snapshots)
        self.dispatcher.quota.restore(quota_snapshots, self.routes)
        for provider, circuit in self.circuits.items():
            snapshot = next(
                (
                    item
                    for item in circuit_snapshots
                    if getattr(item, "provider", None) == provider
                ),
                None,
            )
            if snapshot is not None:
                circuit.restore(snapshot)

    def _route_validated(
        self,
        request: EditorialRequest,
        context: RouterRequestContext,
    ) -> RoutedEditorialResponse | None:
        attempts = 0
        for provider in self.config.provider_order:
            pool = self.key_pools.get(provider)
            circuit = self.circuits.get(provider)
            if pool is None or circuit is None or not circuit.allow_request():
                continue
            provider_routes = [
                route for route in self.routes
                if route.provider == provider and route.enabled and route.validation_status == "validated"
            ]
            if not provider_routes or not pool.has_healthy_key():
                circuit.open()
                continue
            stop_provider = False
            for route in provider_routes:
                if stop_provider:
                    break
                tried_keys: set[str] = set()
                stop_model = False
                while not stop_model and attempts < self.config.max_route_attempts:
                    try:
                        lease = pool.acquire(exclude=tried_keys)
                    except LookupError:
                        break
                    tried_keys.add(lease.fingerprint)
                    transient_retry_used = False
                    while True:
                        attempts += 1
                        started = self.clock.monotonic()
                        try:
                            def execute_current(
                                selected_route: ModelRoute = route,
                                selected_lease: KeyLease = lease,
                            ) -> EditorialResponse:
                                return self.transport.execute(
                                    selected_route, selected_lease.value, request, context
                                )

                            response = self.dispatcher.dispatch(
                                route,
                                self._estimate_input_tokens(request),
                                execute_current,
                                key_fingerprint=lease.fingerprint,
                            )
                            self._force_actual_identity(response, route)
                            pool.success(lease)
                            circuit.success()
                            self._record_attempt(
                                context, route, lease, "success", None, started,
                                self._estimate_input_tokens(request), Usage.from_response(response), None,
                            )
                            self.state_sink.record_snapshot(self._model_snapshot(route, self.clock, success=True))
                            return RoutedEditorialResponse(response=response)
                        except RouteFailure as failure:
                            self._record_attempt(
                                context, route, lease, "failed", failure.category, started,
                                self._estimate_input_tokens(request), None, failure.retry_after_seconds,
                            )
                            route.last_failure_category = failure.category.value
                            if failure.provider_level:
                                circuit.failure(failure.category)
                                if circuit.state is CircuitState.OPEN:
                                    stop_provider = True
                            category = failure.category
                            if category is RouteFailureCategory.INVALID_KEY:
                                pool.invalid(lease)
                                break
                            if category is RouteFailureCategory.RATE_LIMIT:
                                if route.provider == "gemini":
                                    self.dispatcher.quota.cool_down(
                                        route,
                                        failure.retry_after_seconds,
                                    )
                                    stop_model = True
                                else:
                                    pool.rate_limited(
                                        lease,
                                        retry_after_seconds=failure.retry_after_seconds,
                                    )
                                break
                            if category is RouteFailureCategory.DAILY_QUOTA:
                                self.dispatcher.quota.exhaust_daily(route, failure.daily_reset_at)
                                stop_model = True
                                break
                            if category in {
                                RouteFailureCategory.TIMEOUT,
                                RouteFailureCategory.SERVER_ERROR,
                                RouteFailureCategory.NETWORK_ERROR,
                            }:
                                if not transient_retry_used and circuit.state is not CircuitState.OPEN:
                                    transient_retry_used = True
                                    self.clock.sleep(self._retry_jitter(lease))
                                    continue
                                pool.failure(lease, category)
                                break
                            if category in {
                                RouteFailureCategory.INVALID_MODEL,
                                RouteFailureCategory.UNSUPPORTED_PARAMETER,
                            }:
                                route.enabled = False
                                route.validation_status = "disabled"
                                self.state_sink.record_snapshot(self._model_snapshot(route, self.clock))
                                stop_model = True
                                break
                            if category is RouteFailureCategory.MALFORMED_SCHEMA:
                                repaired = self._one_alternate(
                                    request,
                                    replace(context, stage="repair", repair_payload=failure.repair_payload),
                                    exclude={(route.provider, route.model)},
                                )
                                if repaired is not None:
                                    return RoutedEditorialResponse(response=repaired, repaired=True)
                                return None
                            if category is RouteFailureCategory.POLICY_REJECTION:
                                alternate = self._one_alternate(
                                    request,
                                    context,
                                    exclude={(route.provider, route.model)},
                                )
                                if alternate is not None:
                                    return RoutedEditorialResponse(response=alternate)
                                return None
                            # Quota admission/context/unknown failures move to the next model.
                            stop_model = True
                            break
                    if stop_provider:
                        break
            # Every validated route/key combination for this provider was
            # exhausted without success. Treat the provider as unavailable
            # even when a transiently failed key remains otherwise enabled.
            circuit.open()
        return None

    def _one_alternate(
        self,
        request: EditorialRequest,
        context: RouterRequestContext,
        *,
        exclude: set[tuple[str, str]],
    ) -> EditorialResponse | None:
        """Execute exactly one compatible alternate route request."""
        for provider in self.config.provider_order:
            pool = self.key_pools.get(provider)
            circuit = self.circuits.get(provider)
            if pool is None or circuit is None or not circuit.allow_request() or not pool.has_healthy_key():
                continue
            for route in self.routes:
                if (
                    route.provider != provider
                    or (route.provider, route.model) in exclude
                    or not route.enabled
                    or route.validation_status != "validated"
                ):
                    continue
                try:
                    lease = pool.acquire()
                except LookupError:
                    continue
                started = self.clock.monotonic()
                try:
                    def execute_alternate(
                        selected_route: ModelRoute = route,
                        selected_lease: KeyLease = lease,
                    ) -> EditorialResponse:
                        return self.transport.execute(
                            selected_route, selected_lease.value, request, context
                        )

                    response = self.dispatcher.dispatch(
                        route,
                        self._estimate_input_tokens(request),
                        execute_alternate,
                        key_fingerprint=lease.fingerprint,
                    )
                    self._force_actual_identity(response, route)
                    pool.success(lease)
                    circuit.success()
                    self._record_attempt(
                        context, route, lease, "success", None, started,
                        self._estimate_input_tokens(request), Usage.from_response(response), None,
                    )
                    return response
                except RouteFailure as failure:
                    self._record_attempt(
                        context, route, lease, "failed", failure.category, started,
                        self._estimate_input_tokens(request), None, failure.retry_after_seconds,
                    )
                    if failure.provider_level:
                        circuit.failure(failure.category)
                    if failure.category is RouteFailureCategory.INVALID_KEY:
                        pool.invalid(lease)
                    elif failure.category is RouteFailureCategory.RATE_LIMIT:
                        pool.rate_limited(lease, retry_after_seconds=failure.retry_after_seconds)
                    else:
                        pool.failure(lease, failure.category)
                    return None
        return None

    def _record_attempt(
        self,
        context: RouterRequestContext,
        route: ModelRoute,
        lease: KeyLease,
        status: str,
        category: RouteFailureCategory | None,
        started: float,
        estimate: int,
        usage: Usage | None,
        retry_after: float | None,
    ) -> None:
        self.state_sink.record_attempt(
            RouteAttemptEvent.new(
                job_id=context.job_id,
                shard_id=context.shard_id,
                stage=context.stage,
                report_id=context.report_id,
                artifact_id=context.artifact_id,
                provider=route.provider,
                model=route.model,
                key_fingerprint=lease.fingerprint,
                status=status,
                failure_category=category.value if category else None,
                latency_ms=int((self.clock.monotonic() - started) * 1000),
                estimated_input_tokens=estimate,
                actual_input_tokens=usage.input_tokens if usage else None,
                actual_output_tokens=usage.output_tokens if usage else None,
                retry_after_seconds=retry_after,
                created_at=self.clock.utcnow(),
            )
        )

    @staticmethod
    def _estimate_input_tokens(request: EditorialRequest) -> int:
        estimate = max(1, len(request.evidence.model_dump_json()) // 4)
        return min(estimate, request.max_input_tokens)

    def _retry_jitter(self, lease: KeyLease) -> float:
        fraction = int(lease.fingerprint[:2], 16) / 255.0
        return self.config.transient_retry_jitter_seconds * (1.0 + fraction)

    @staticmethod
    def _force_actual_identity(response: EditorialResponse, route: ModelRoute) -> None:
        response.provider = route.provider
        response.model = route.model
        response.output.metadata.provider = route.provider
        response.output.metadata.model_name = route.model

    @staticmethod
    def _model_snapshot(
        route: ModelRoute,
        clock: Clock,
        *,
        success: bool = False,
    ) -> ModelHealthSnapshot:
        return ModelHealthSnapshot(
            provider=route.provider,
            model=route.model,
            validation_status=route.validation_status,
            latency_ms=None,
            last_success_at=clock.utcnow() if success else None,
            last_failure_category=route.last_failure_category,
            supported_capabilities=tuple(sorted(route.supported_capabilities)),
            enabled=route.enabled,
        )

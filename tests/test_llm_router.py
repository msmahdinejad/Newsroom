"""Deterministic Production multi-provider router contract tests.

The public seams under test are the local-file config loader, key pool, quota
controller, queued dispatcher, HTTP payload builder, and MultiProviderRouter.
No test performs network I/O or uses a real provider access value.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from pathlib import Path

import httpx
import pytest

from newsroom.editorial.router import (
    CircuitState,
    DispatchQueueFull,
    InMemoryRouterStateSink,
    KeyPool,
    ManualClock,
    ModelRoute,
    MultiProviderRouter,
    ProviderConfig,
    QuotaController,
    QuotaStateSnapshot,
    RateLimits,
    RouteFailure,
    RouteFailureCategory,
    RouterConfig,
    RouterRequestContext,
    Usage,
    build_chat_payload,
    load_router_config,
)
from newsroom.editorial.router import config as router_config
from newsroom.editorial.router.dispatcher import QueuedDispatcher
from newsroom.editorial.schema import (
    EditorialEvidenceSet,
    EditorialOutput,
    EditorialRequest,
    EditorialResponse,
    EvidenceSourceItem,
    EvidenceStoryPacket,
    KeyClaim,
    ReportMetadata,
    StoryEditorialResult,
)


def _request() -> EditorialRequest:
    evidence = EditorialEvidenceSet(
        stories=[
            EvidenceStoryPacket(
                story_id=1,
                headline="A bounded model was released",
                sources=[
                    EvidenceSourceItem(
                        ref_id="ev-1-0",
                        item_id=10,
                        original_title="A bounded model was released",
                        excerpt="The release is available today.",
                        original_url="https://example.test/release",
                    )
                ],
                facts=["The release is available today."],
            )
        ]
    )
    return EditorialRequest(evidence=evidence, max_output_tokens=200)


def _response(provider: str, model: str) -> EditorialResponse:
    output = EditorialOutput(
        metadata=ReportMetadata(
            provider=provider,
            model_name=model,
            evidence_set_hash=_request().evidence.evidence_hash(),
        ),
        stories=[
            StoryEditorialResult(
                story_id=1,
                headline_fa="\u0645\u062f\u0644 \u062c\u062f\u06cc\u062f \u0645\u0646\u062a\u0634\u0631 \u0634\u062f",
                summary_fa="\u0627\u06cc\u0646 \u0645\u062f\u0644 \u0628\u0647 \u0635\u0648\u0631\u062a \u0645\u062d\u062f\u0648\u062f \u0645\u0646\u062a\u0634\u0631 \u0634\u062f\u0647 \u0627\u0633\u062a.",
                source_ref_ids=["ev-1-0"],
                source_links=["https://example.test/release"],
                key_claims=[
                    KeyClaim(
                        claim_text="The release is available today.",
                        supporting_evidence_refs=["ev-1-0"],
                        support_status="supported",
                    )
                ],
            )
        ],
    )
    return EditorialResponse(
        output=output,
        provider=provider,
        model=model,
        usage={"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60},
    )


class FakeTransport:
    """Scriptable external-provider boundary."""

    def __init__(self, scripts: dict[tuple[str, str], list[object]] | None = None) -> None:
        self.scripts = {key: deque(value) for key, value in (scripts or {}).items()}
        self.calls: list[tuple[str, str, str, str, float]] = []
        self.clock: ManualClock | None = None

    def execute(self, route, key_value, request, context):
        self.calls.append(
            (route.provider, route.model, context.stage, key_value, self.clock.monotonic() if self.clock else 0.0)
        )
        scripted = self.scripts.get((route.provider, route.model))
        value = scripted.popleft() if scripted else _response(route.provider, route.model)
        if isinstance(value, Exception):
            raise value
        return value


class FakeFallback:
    name = "deterministic"
    model_name = "deterministic-v1"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        return _response(self.name, self.model_name)


def _provider(
    name: str,
    keys: tuple[str, ...] = ("unit-key-1",),
    models: tuple[str, ...] = ("model",),
    *,
    rpm: int = 100,
    tpm: int = 100_000,
    rpd: int = 1000,
    concurrency: int = 1,
    spacing: float = 0.0,
) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        keys=keys,
        models=models,
        api_base=f"https://{name}.example.test/v1",
        quota_scope=f"{name}-project",
        limits=RateLimits(rpm=rpm, tpm=tpm, rpd=rpd),
        concurrency=concurrency,
        min_spacing_seconds=spacing,
    )


def _router(
    providers: tuple[ProviderConfig, ...],
    transport: FakeTransport,
    clock: ManualClock,
    *,
    validated: dict[str, tuple[str, ...]] | None = None,
    fallback: FakeFallback | None = None,
    queue_size: int = 8,
) -> MultiProviderRouter:
    transport.clock = clock
    config = RouterConfig(
        providers=providers,
        provider_order=tuple(p.name for p in providers),
        queue_size=queue_size,
        provider_cooldown_seconds=300,
        key_cooldown_seconds=60,
        transient_retry_jitter_seconds=0.25,
    )
    return MultiProviderRouter.from_config(
        config,
        transport=transport,
        clock=clock,
        validated_models=validated or {p.name: p.models for p in providers},
        fallback=fallback or FakeFallback(),
    )


def test_local_config_uses_only_canonical_provider_file(tmp_path: Path, monkeypatch):
    provider_file = tmp_path / ".env.providers.local"
    provider_file.write_text(
        "GEMINI_API_KEYS=file-key-1,file-key-2\n"
        "GEMINI_MODELS=gemini-3.6-flash\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GEMINI_API_KEYS", "ambient-key-must-not-win")

    config = load_router_config(provider_file)

    gemini = config.provider("gemini")
    assert len(gemini.keys) == 2
    assert "ambient-key-must-not-win" not in gemini.keys
    assert "file-key-1" not in repr(config)


def test_default_gemini_capacity_is_effectively_bounded(tmp_path: Path):
    provider_file = tmp_path / ".env.providers.local"
    provider_file.write_text("GEMINI_API_KEYS=one\n", encoding="utf-8")

    gemini = load_router_config(provider_file).provider("gemini")

    assert gemini.limits == RateLimits(rpm=12, tpm=200_000, rpd=450)
    assert gemini.concurrency == 1
    assert gemini.min_spacing_seconds == 5.0


def test_llm_proxy_is_loaded_only_from_canonical_file_and_hidden(tmp_path: Path):
    provider_file = tmp_path / ".env.providers.local"
    protected_proxy = "socks5://user:password@proxy.invalid:1080"
    provider_file.write_text(f"LLM_PROXY_URL={protected_proxy}\n", encoding="utf-8")

    config = load_router_config(provider_file)

    assert config.proxy_url == protected_proxy
    assert protected_proxy not in repr(config)


def test_container_rewrites_local_loopback_proxy_with_canonical_host_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    provider_file = tmp_path / ".env.providers.local"
    provider_file.write_text(
        "LLM_PROXY_URL=socks5://user:password@127.0.0.1:1080\n"
        "LLM_PROXY_CONTAINER_HOST=host.docker.internal\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(router_config, "_running_in_container", lambda: True)

    config = load_router_config(provider_file)

    assert config.proxy_url == "socks5://user:password@host.docker.internal:1080"


def test_invalid_llm_proxy_configuration_fails_without_echoing_value(tmp_path: Path):
    provider_file = tmp_path / ".env.providers.local"
    protected_proxy = "file://protected-local-value"
    provider_file.write_text(f"LLM_PROXY_URL={protected_proxy}\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_router_config(provider_file)

    assert protected_proxy not in str(exc.value)


def test_multiple_keys_are_safe_and_round_robin():
    clock = ManualClock()
    pool = KeyPool("gemini", ("secret-a", "secret-b", "secret-c"), clock=clock)

    leases = [pool.acquire() for _ in range(4)]

    assert [lease.safe_id for lease in leases] == ["gemini-key-1", "gemini-key-2", "gemini-key-3", "gemini-key-1"]
    assert "secret-a" not in repr(pool.snapshot())


def test_key_cooldown_rotates_then_returns_to_first_key():
    clock = ManualClock()
    pool = KeyPool("gemini", ("key-a", "key-b"), clock=clock)
    first = pool.acquire()
    pool.rate_limited(first, retry_after_seconds=10)

    assert pool.acquire().safe_id == "gemini-key-2"
    clock.advance(10)
    pool.reset_rotation()
    assert pool.acquire().safe_id == "gemini-key-1"


def test_invalid_key_isolated_without_disabling_other_keys():
    clock = ManualClock()
    pool = KeyPool("gemini", ("key-a", "key-b"), clock=clock)
    first = pool.acquire()
    pool.invalid(first)

    assert pool.acquire().safe_id == "gemini-key-2"
    states = pool.snapshot()
    assert states[0].enabled is False
    assert states[1].enabled is True


@pytest.mark.parametrize(
    ("limits", "estimated", "count", "category"),
    [
        (RateLimits(rpm=1, tpm=1000, rpd=100), 10, 2, RouteFailureCategory.RPM_EXHAUSTED),
        (RateLimits(rpm=10, tpm=50, rpd=100), 30, 2, RouteFailureCategory.TPM_EXHAUSTED),
        (RateLimits(rpm=10, tpm=1000, rpd=1), 10, 2, RouteFailureCategory.RPD_EXHAUSTED),
    ],
)
def test_rate_admission_limits(limits, estimated, count, category):
    clock = ManualClock()
    quota = QuotaController(clock=clock)
    route = ModelRoute.validated("gemini", "model", limits=limits, quota_scope="project")
    quota.reserve(route, estimated)

    with pytest.raises(RouteFailure, match=category.value) as exc:
        for _ in range(count - 1):
            quota.reserve(route, estimated)

    assert exc.value.category is category


def test_actual_usage_reconciles_estimated_tpm():
    clock = ManualClock()
    quota = QuotaController(clock=clock)
    route = ModelRoute.validated(
        "gemini", "model", limits=RateLimits(rpm=10, tpm=100, rpd=100), quota_scope="project"
    )
    reservation = quota.reserve(route, 80)
    quota.reconcile(reservation, Usage(input_tokens=20, output_tokens=10))

    quota.reserve(route, 70)


def test_same_project_quota_is_shared_across_keys():
    clock = ManualClock()
    quota = QuotaController(clock=clock)
    route = ModelRoute.validated(
        "gemini", "model", limits=RateLimits(rpm=1, tpm=1000, rpd=100), quota_scope="same-project"
    )
    quota.reserve(route, 10, key_fingerprint="a" * 64)

    with pytest.raises(RouteFailure) as exc:
        quota.reserve(route, 10, key_fingerprint="b" * 64)

    assert exc.value.category is RouteFailureCategory.RPM_EXHAUSTED


def test_gemini_project_quota_is_per_model_but_not_per_key():
    clock = ManualClock()
    quota = QuotaController(clock=clock)
    limits = RateLimits(rpm=1, tpm=1000, rpd=100)
    first = ModelRoute.validated(
        "gemini", "gemini-3.6-flash", limits=limits, quota_scope="same-project"
    )
    second = ModelRoute.validated(
        "gemini", "gemini-2.5-flash", limits=limits, quota_scope="same-project"
    )
    quota.reserve(first, 10)

    quota.reserve(second, 10)

    with pytest.raises(RouteFailure) as exc:
        quota.reserve(first, 10, key_fingerprint="b" * 64)

    assert exc.value.category is RouteFailureCategory.RPM_EXHAUSTED


def test_queue_backpressure_is_bounded():
    clock = ManualClock()
    dispatcher = QueuedDispatcher(max_queue_size=1, clock=clock)
    route = ModelRoute.validated(
        "gemini",
        "model",
        limits=RateLimits(rpm=100, tpm=100_000, rpd=1000),
        quota_scope="project",
        concurrency=1,
    )
    entered = threading.Event()
    release = threading.Event()

    def blocking_call():
        entered.set()
        release.wait(timeout=3)
        return _response("gemini", "model")

    first = threading.Thread(target=lambda: dispatcher.dispatch(route, 10, blocking_call))
    first.start()
    assert entered.wait(timeout=1)
    second = threading.Thread(
        target=lambda: dispatcher.dispatch(route, 10, lambda: _response("gemini", "model"))
    )
    second.start()

    with pytest.raises(DispatchQueueFull):
        dispatcher.dispatch(route, 10, lambda: _response("gemini", "model"))

    release.set()
    first.join(timeout=2)
    second.join(timeout=2)


def test_gemini_concurrency_one():
    clock = ManualClock()
    dispatcher = QueuedDispatcher(max_queue_size=2, clock=clock)
    route = ModelRoute.validated(
        "gemini",
        "model",
        limits=RateLimits(rpm=100, tpm=100_000, rpd=1000),
        quota_scope="project",
        concurrency=1,
    )
    lock = threading.Lock()
    active = 0
    peak = 0
    first_entered = threading.Event()
    release = threading.Event()

    def call():
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            first_entered.set()
        release.wait(timeout=2)
        with lock:
            active -= 1
        return _response("gemini", "model")

    threads = [threading.Thread(target=lambda: dispatcher.dispatch(route, 10, call)) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert first_entered.wait(timeout=1)
    release.set()
    for thread in threads:
        thread.join(timeout=2)

    assert peak == 1


def test_five_second_spacing_uses_injected_clock():
    clock = ManualClock()
    dispatcher = QueuedDispatcher(max_queue_size=2, clock=clock)
    route = ModelRoute.validated(
        "gemini",
        "model",
        limits=RateLimits(rpm=100, tpm=100_000, rpd=1000),
        quota_scope="project",
        concurrency=1,
        min_spacing_seconds=5,
    )
    starts = []
    for _ in range(2):
        dispatcher.dispatch(route, 10, lambda: starts.append(clock.monotonic()) or _response("gemini", "model"))

    assert starts == [0.0, 5.0]


def test_new_gemini_models_receive_no_deprecated_sampling_parameters():
    request = _request()
    for model in ("gemini-3.6-flash", "gemini-3.5-flash-lite"):
        payload = build_chat_payload(ModelRoute.validated("gemini", model), request)
        assert {"temperature", "top_p", "top_k"}.isdisjoint(payload)


def test_regular_model_keeps_supported_temperature():
    payload = build_chat_payload(ModelRoute.validated("mistral", "mistral-medium-3-5"), _request())
    assert payload["temperature"] == 0.3


def test_round_robin_retry_after_and_successful_rotation():
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("mistral", "model"): [
                RouteFailure(RouteFailureCategory.RATE_LIMIT, retry_after_seconds=30),
                _response("mistral", "model"),
            ]
        }
    )
    router = _router((_provider("mistral", keys=("key-a", "key-b")),), transport, clock)

    result = router.route(_request())

    assert result.response.provider == "mistral"
    assert [call[3] for call in transport.calls] == ["key-a", "key-b"]
    assert router.key_pool("mistral").snapshot()[0].cooldown_until is not None


def test_gemini_project_rate_limit_moves_to_next_model_not_next_key():
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("gemini", "preferred"): [
                RouteFailure(RouteFailureCategory.RATE_LIMIT, retry_after_seconds=30),
            ],
            ("gemini", "alternate"): [_response("gemini", "alternate")],
        }
    )
    router = _router(
        (_provider("gemini", keys=("key-a", "key-b"), models=("preferred", "alternate")),),
        transport,
        clock,
    )

    result = router.route(_request())

    assert result.response.model == "alternate"
    assert [(call[1], call[3]) for call in transport.calls] == [
        ("preferred", "key-a"),
        ("alternate", "key-b"),
    ]


@pytest.mark.parametrize("category", [RouteFailureCategory.TIMEOUT, RouteFailureCategory.SERVER_ERROR])
def test_timeout_and_5xx_retry_once_then_rotate(category):
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("gemini", "model"): [
                RouteFailure(category),
                RouteFailure(category),
                _response("gemini", "model"),
            ]
        }
    )
    router = _router((_provider("gemini", keys=("key-a", "key-b")),), transport, clock)

    router.route(_request())

    assert [call[3] for call in transport.calls] == ["key-a", "key-a", "key-b"]
    assert clock.monotonic() >= 0.25


def test_invalid_model_disables_route_and_uses_next_gemini_model():
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("gemini", "bad-model"): [RouteFailure(RouteFailureCategory.INVALID_MODEL)],
            ("gemini", "good-model"): [_response("gemini", "good-model")],
        }
    )
    router = _router((_provider("gemini", models=("bad-model", "good-model")),), transport, clock)

    result = router.route(_request())

    assert result.response.model == "good-model"
    assert router.model_route("gemini", "bad-model").enabled is False


@pytest.mark.parametrize(
    ("providers", "scripts", "expected"),
    [
        (("gemini", "mistral"), {("gemini", "model"): [RouteFailure(RouteFailureCategory.INVALID_KEY)]}, "mistral"),
        (("gemini", "mistral", "groq"), {
            ("gemini", "model"): [RouteFailure(RouteFailureCategory.INVALID_KEY)],
            ("mistral", "model"): [RouteFailure(RouteFailureCategory.INVALID_KEY)],
        }, "groq"),
        (("gemini", "mistral", "groq", "nvidia"), {
            ("gemini", "model"): [RouteFailure(RouteFailureCategory.INVALID_KEY)],
            ("mistral", "model"): [RouteFailure(RouteFailureCategory.INVALID_KEY)],
            ("groq", "model"): [RouteFailure(RouteFailureCategory.INVALID_KEY)],
        }, "nvidia"),
    ],
)
def test_cross_provider_fallback_order(providers, scripts, expected):
    clock = ManualClock()
    transport = FakeTransport(scripts)
    configs = tuple(_provider(name) for name in providers)
    router = _router(configs, transport, clock)

    assert router.route(_request()).response.provider == expected


def test_complete_gemini_failure_opens_circuit_and_falls_back():
    clock = ManualClock()
    failures = [RouteFailure(RouteFailureCategory.SERVER_ERROR) for _ in range(4)]
    transport = FakeTransport(
        {
            ("gemini", "model-a"): failures[:2],
            ("gemini", "model-b"): failures[2:],
            ("mistral", "model"): [_response("mistral", "model")],
        }
    )
    router = _router(
        (_provider("gemini", models=("model-a", "model-b")), _provider("mistral")),
        transport,
        clock,
    )

    result = router.route(_request())

    assert result.response.provider == "mistral"
    assert router.circuit("gemini").state is CircuitState.OPEN


def test_provider_half_open_probe_recovers_after_cooldown():
    clock = ManualClock()
    transport = FakeTransport(
        {("gemini", "model"): [
            RouteFailure(RouteFailureCategory.SERVER_ERROR),
            RouteFailure(RouteFailureCategory.SERVER_ERROR),
            _response("gemini", "model"),
        ]}
    )
    router = _router((_provider("gemini"),), transport, clock)
    router.route(_request())
    assert router.circuit("gemini").state is CircuitState.OPEN

    clock.advance(300)
    result = router.route(_request())

    assert result.response.provider == "gemini"
    assert router.circuit("gemini").state is CircuitState.CLOSED


def test_malformed_schema_repairs_through_another_validated_route():
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("gemini", "map-model"): [
                RouteFailure(RouteFailureCategory.MALFORMED_SCHEMA, repair_payload="bounded malformed output")
            ],
            ("mistral", "repair-model"): [_response("mistral", "repair-model")],
        }
    )
    router = _router((_provider("gemini", models=("map-model",)), _provider("mistral", models=("repair-model",))), transport, clock)

    result = router.route(_request())

    assert result.repaired is True
    assert result.response.provider == "mistral"
    assert [call[2] for call in transport.calls] == ["map", "repair"]


def test_malformed_schema_repair_uses_the_next_provider_not_another_gemini_model():
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("gemini", "map-model"): [
                RouteFailure(RouteFailureCategory.MALFORMED_SCHEMA, repair_payload="bounded malformed output")
            ],
            ("mistral", "repair-model"): [_response("mistral", "repair-model")],
        }
    )
    router = _router(
        (
            _provider("gemini", models=("map-model", "other-gemini")),
            _provider("mistral", models=("repair-model",)),
        ),
        transport,
        clock,
    )

    result = router.route(_request())

    assert result.response.provider == "mistral"
    assert [(call[0], call[1]) for call in transport.calls] == [
        ("gemini", "map-model"),
        ("mistral", "repair-model"),
    ]


def test_orchestrator_can_request_one_cross_provider_schema_repair():
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("mistral", "repair-model"): [_response("mistral", "repair-model")],
        }
    )
    router = _router(
        (
            _provider("gemini", models=("map-model",)),
            _provider("mistral", models=("repair-model",)),
        ),
        transport,
        clock,
    )

    repaired = router.repair(_request(), _response("gemini", "map-model"))

    assert repaired is not None
    assert repaired.response.provider == "mistral"
    assert [call[2] for call in transport.calls] == ["repair"]


def test_policy_rejection_tries_only_one_compatible_alternate():
    clock = ManualClock()
    fallback = FakeFallback()
    transport = FakeTransport(
        {
            ("gemini", "model"): [RouteFailure(RouteFailureCategory.POLICY_REJECTION)],
            ("mistral", "model"): [RouteFailure(RouteFailureCategory.POLICY_REJECTION)],
            ("groq", "model"): [_response("groq", "model")],
        }
    )
    router = _router(
        (_provider("gemini"), _provider("mistral"), _provider("groq")),
        transport,
        clock,
        fallback=fallback,
    )

    result = router.route(_request())

    assert result.fallback_used is True
    assert fallback.calls == 1
    assert [call[0] for call in transport.calls] == ["gemini", "mistral"]


def test_attempts_and_health_contain_no_provider_value():
    clock = ManualClock()
    sink = InMemoryRouterStateSink()
    transport = FakeTransport()
    config = RouterConfig(providers=(_provider("gemini", keys=("very-secret-provider-value",)),), provider_order=("gemini",))
    router = MultiProviderRouter.from_config(
        config,
        transport=transport,
        clock=clock,
        validated_models={"gemini": ("model",)},
        state_sink=sink,
        fallback=FakeFallback(),
    )

    router.route(_request(), RouterRequestContext(job_id="job-1", shard_id="s1", stage="map"))
    serialized = repr((sink.attempts, sink.snapshots, router.health()))

    assert "very-secret-provider-value" not in serialized
    assert sink.attempts[0].key_fingerprint and len(sink.attempts[0].key_fingerprint) == 64


def test_unvalidated_model_is_never_enabled():
    clock = ManualClock()
    transport = FakeTransport()
    fallback = FakeFallback()
    router = _router(
        (_provider("gemini", models=("unvalidated",)),),
        transport,
        clock,
        validated={"gemini": ()},
        fallback=fallback,
    )

    result = router.route(_request())

    assert result.fallback_used is True
    assert transport.calls == []


def test_runtime_construction_does_not_overwrite_persisted_validation_metadata():
    clock = ManualClock()
    sink = InMemoryRouterStateSink()
    MultiProviderRouter.from_config(
        RouterConfig(
            providers=(_provider("gemini"),),
            provider_order=("gemini",),
        ),
        transport=FakeTransport(),
        clock=clock,
        validated_models={"gemini": ("model",)},
        state_sink=sink,
        fallback=FakeFallback(),
    )

    assert sink.snapshots == []


def test_editorial_provider_seam_marks_deterministic_fallback():
    clock = ManualClock()
    router = _router(
        (_provider("gemini"),),
        FakeTransport(),
        clock,
        validated={"gemini": ()},
        fallback=FakeFallback(),
    )

    response = router.generate(_request())

    assert response.provider == "deterministic"
    assert response.fallback_used is True


def test_bounded_validator_enables_only_a_model_that_passes_all_capabilities():
    clock = ManualClock()
    sink = InMemoryRouterStateSink()
    transport = FakeTransport()
    transport.clock = clock
    config = RouterConfig(providers=(_provider("gemini"),), provider_order=("gemini",))
    router = MultiProviderRouter.from_config(
        config,
        transport=transport,
        clock=clock,
        validated_models={"gemini": ()},
        state_sink=sink,
        fallback=FakeFallback(),
    )

    results = router.validate_models()

    assert results[0].status == "validated"
    assert results[0].supported_capabilities == (
        "bounded_output",
        "connectivity",
        "grounding",
        "persian",
        "structured",
    )
    assert router.model_route("gemini", "model").enabled is True


def test_bounded_validator_keeps_non_persian_model_disabled():
    clock = ManualClock()
    response = _response("gemini", "model")
    response.output.stories[0].headline_fa = "English only"
    response.output.stories[0].summary_fa = "No Persian output"
    transport = FakeTransport({("gemini", "model"): [response]})
    transport.clock = clock
    config = RouterConfig(providers=(_provider("gemini"),), provider_order=("gemini",))
    router = MultiProviderRouter.from_config(
        config,
        transport=transport,
        clock=clock,
        validated_models={"gemini": ()},
        fallback=FakeFallback(),
    )

    result = router.validate_models()[0]

    assert result.status == "failed"
    assert router.model_route("gemini", "model").enabled is False


def test_bounded_validator_isolates_invalid_key_and_uses_next_key():
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("gemini", "model"): [
                RouteFailure(RouteFailureCategory.INVALID_KEY),
                _response("gemini", "model"),
            ]
        }
    )
    transport.clock = clock
    config = RouterConfig(
        providers=(_provider("gemini", keys=("bad-key", "healthy-key")),),
        provider_order=("gemini",),
    )
    router = MultiProviderRouter.from_config(
        config,
        transport=transport,
        clock=clock,
        validated_models={"gemini": ()},
        fallback=FakeFallback(),
    )

    result = router.validate_models()[0]

    assert result.status == "validated"
    assert [call[3] for call in transport.calls] == ["bad-key", "healthy-key"]
    assert router.key_pool("gemini").snapshot()[0].enabled is False


def test_access_validation_can_recheck_a_persisted_disabled_key():
    clock = ManualClock()
    transport = FakeTransport()
    router = _router((_provider("gemini"),), transport, clock)
    pool = router.key_pool("gemini")
    lease = pool.acquire()
    pool.invalid(lease)

    results = router.validate_access_values()

    assert [(result.safe_id, result.status) for result in results] == [
        ("gemini-key-1", "validated"),
    ]
    assert pool.snapshot()[0].enabled is True
    assert [call[3] for call in transport.calls] == ["unit-key-1"]


def test_access_validation_persists_only_safe_attempt_metadata():
    clock = ManualClock()
    sink = InMemoryRouterStateSink()
    protected_value = "protected-unit-access-value"
    router = MultiProviderRouter.from_config(
        RouterConfig(
            providers=(
                _provider("gemini", keys=(protected_value,)),
            ),
            provider_order=("gemini",),
        ),
        transport=FakeTransport(),
        clock=clock,
        validated_models={"gemini": ("model",)},
        state_sink=sink,
        fallback=FakeFallback(),
    )

    router.validate_access_values()

    assert len(sink.attempts) == 1
    attempt = sink.attempts[0]
    assert attempt.stage == "access_validation"
    assert attempt.status == "validated"
    assert attempt.key_fingerprint is not None
    assert len(attempt.key_fingerprint) == 64
    assert protected_value not in repr((sink.attempts, sink.snapshots))


def test_access_validation_attempts_every_value_without_a_validated_model():
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("mistral", "candidate"): [
                RouteFailure(RouteFailureCategory.INVALID_KEY),
                RouteFailure(RouteFailureCategory.INVALID_KEY),
            ]
        }
    )
    router = _router(
        (
            _provider(
                "mistral",
                keys=("key-a", "key-b"),
                models=("candidate",),
            ),
        ),
        transport,
        clock,
        validated={"mistral": ()},
    )

    results = router.validate_access_values()

    assert [(result.safe_id, result.status, result.failure_category) for result in results] == [
        ("mistral-key-1", "failed", "invalid_key"),
        ("mistral-key-2", "failed", "invalid_key"),
    ]
    assert [call[3] for call in transport.calls] == ["key-a", "key-b"]


def test_unconfigured_provider_is_not_reported_as_auth_failure():
    clock = ManualClock()
    router = _router(
        (_provider("groq", keys=()),),
        FakeTransport(),
        clock,
        validated={"groq": ()},
    )

    result = router.validate_models()[0]

    assert result.status == "not_configured"
    assert result.failure_category is None


def test_unconfigured_provider_does_not_open_a_failure_circuit():
    clock = ManualClock()
    router = _router(
        (_provider("groq", keys=()),),
        FakeTransport(),
        clock,
        validated={"groq": ()},
    )

    result = router.route(_request())

    assert result.fallback_used is True
    assert router.circuit("groq").state is CircuitState.CLOSED


def test_repair_alternate_invalid_model_is_disabled():
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("gemini", "map-model"): [
                RouteFailure(
                    RouteFailureCategory.MALFORMED_SCHEMA,
                    repair_payload="bounded malformed output",
                )
            ],
            ("mistral", "bad-repair-model"): [
                RouteFailure(RouteFailureCategory.INVALID_MODEL)
            ],
        }
    )
    router = _router(
        (
            _provider("gemini", models=("map-model",)),
            _provider("mistral", models=("bad-repair-model",)),
        ),
        transport,
        clock,
    )

    result = router.route(_request())

    assert result.fallback_used is True
    failed_route = router.model_route("mistral", "bad-repair-model")
    assert failed_route.enabled is False
    assert failed_route.validation_status == "disabled"


def test_repair_alternate_gemini_rate_limit_cools_project_bucket():
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("mistral", "map-model"): [
                RouteFailure(
                    RouteFailureCategory.MALFORMED_SCHEMA,
                    repair_payload="bounded malformed output",
                )
            ],
            ("gemini", "repair-model"): [
                RouteFailure(
                    RouteFailureCategory.RATE_LIMIT,
                    retry_after_seconds=30,
                )
            ],
        }
    )
    router = _router(
        (
            _provider("mistral", models=("map-model",)),
            _provider("gemini", models=("repair-model",)),
        ),
        transport,
        clock,
    )

    router.route(_request())

    quota = router.dispatcher.quota.snapshot()
    gemini_quota = next(item for item in quota if item.provider == "gemini")
    assert gemini_quota.cooldown_until is not None
    assert router.key_pool("gemini").snapshot()[0].cooldown_until is None


def test_gemini_http_400_invalid_key_is_key_local():
    from newsroom.editorial.router import HttpEditorialTransport

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": 400,
                    "message": "Please pass a valid API key",
                    "status": "INVALID_ARGUMENT",
                }
            },
        )

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    provider = _provider("gemini")
    transport = HttpEditorialTransport((provider,), client_factory=MockClient)

    with pytest.raises(RouteFailure) as exc:
        transport.execute(
            ModelRoute.validated("gemini", "model"),
            "unit-test-key",
            _request(),
            RouterRequestContext(),
        )

    assert exc.value.category is RouteFailureCategory.INVALID_KEY


def test_gemini_location_rejection_is_provider_policy():
    from newsroom.editorial.router import HttpEditorialTransport

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json=[{
                "error": {
                    "code": 400,
                    "message": "User location is not supported for the API use.",
                    "status": "FAILED_PRECONDITION",
                }
            }],
        )

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    transport = HttpEditorialTransport(
        (_provider("gemini"),),
        client_factory=MockClient,
    )

    with pytest.raises(RouteFailure) as exc:
        transport.execute(
            ModelRoute.validated("gemini", "model"),
            "unit-test-key",
            _request(),
            RouterRequestContext(),
        )

    assert exc.value.category is RouteFailureCategory.POLICY_REJECTION


def test_llm_proxy_reaches_transport_but_health_exposes_only_protocol():
    from newsroom.editorial.router import HttpEditorialTransport

    protected_proxy = "socks5://user:password@proxy.invalid:1080"
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "bounded"})

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            seen["proxy"] = kwargs.pop("proxy", None)
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    provider = _provider("gemini")
    transport = HttpEditorialTransport(
        (provider,),
        proxy_url=protected_proxy,
        client_factory=MockClient,
    )
    router = MultiProviderRouter.from_config(
        RouterConfig(
            providers=(provider,),
            provider_order=("gemini",),
            proxy_url=protected_proxy,
        ),
        transport=transport,
        clock=ManualClock(),
        validated_models={"gemini": ("model",)},
        fallback=FakeFallback(),
    )

    with pytest.raises(RouteFailure):
        transport.execute(
            ModelRoute.validated("gemini", "model"),
            "unit-test-key",
            _request(),
            RouterRequestContext(),
        )

    assert seen["proxy"] == protected_proxy
    assert router.health()["transport"] == "socks5_proxy"
    assert protected_proxy not in repr(router.health())


def test_router_overwrites_untrusted_provider_identity_with_actual_route():
    clock = ManualClock()
    transport = FakeTransport({("gemini", "model"): [_response("untrusted", "wrong-model")]})
    router = _router((_provider("gemini"),), transport, clock)

    response = router.route(_request()).response

    assert (response.provider, response.model) == ("gemini", "model")
    assert (response.output.metadata.provider, response.output.metadata.model_name) == (
        "gemini",
        "model",
    )


def test_transport_safely_coerces_an_unknown_optional_classification():
    from newsroom.editorial.router import HttpEditorialTransport

    payload = _response("mistral", "model").output.model_dump(mode="json")
    payload["stories"][0]["classification"] = "provider_specific_label"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}],
                "usage": {},
            },
        )

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    response = HttpEditorialTransport((_provider("mistral"),), client_factory=MockClient).execute(
        ModelRoute.validated("mistral", "model"),
        "unit-test-key",
        _request(),
        RouterRequestContext(),
    )

    assert response.output.stories[0].classification.value == "unverified"


def test_production_transport_parses_retry_after_without_exposing_body():
    from newsroom.editorial.router import HttpEditorialTransport

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "17"}, json={"error": "bounded"})

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    provider = _provider("gemini")
    transport = HttpEditorialTransport((provider,), client_factory=MockClient)
    route = ModelRoute.validated("gemini", "model")

    with pytest.raises(RouteFailure) as exc:
        transport.execute(route, "unit-test-key", _request(), RouterRequestContext())

    assert exc.value.category is RouteFailureCategory.RATE_LIMIT
    assert exc.value.retry_after_seconds == 17
    assert "bounded" not in str(exc.value)


def test_daily_quota_is_not_retried_with_another_same_project_key():
    clock = ManualClock()
    transport = FakeTransport(
        {
            ("gemini", "model"): [RouteFailure(RouteFailureCategory.DAILY_QUOTA)],
            ("mistral", "model"): [_response("mistral", "model")],
        }
    )
    router = _router(
        (
            _provider("gemini", keys=("key-a", "key-b")),
            _provider("mistral"),
        ),
        transport,
        clock,
    )

    result = router.route(_request())

    assert result.response.provider == "mistral"
    assert [call[3] for call in transport.calls if call[0] == "gemini"] == ["key-a"]


def test_daily_quota_category_survives_restart():
    clock = ManualClock()
    route = ModelRoute.validated(
        "gemini",
        "model",
        limits=RateLimits(rpm=12, tpm=200_000, rpd=1),
        quota_scope="project",
    )
    original = QuotaController(clock=clock)
    original.exhaust_daily(route)
    snapshots: tuple[QuotaStateSnapshot, ...] = original.snapshot()
    restored = QuotaController(clock=clock)
    restored.restore(snapshots, [route])

    with pytest.raises(RouteFailure) as exc:
        restored.reserve(route, 10)

    assert exc.value.category is RouteFailureCategory.DAILY_QUOTA


def test_route_context_preserves_job_and_shard_in_attempt_lineage():
    clock = ManualClock()
    sink = InMemoryRouterStateSink()
    transport = FakeTransport()
    config = RouterConfig(providers=(_provider("gemini"),), provider_order=("gemini",))
    router = MultiProviderRouter.from_config(
        config,
        transport=transport,
        clock=clock,
        validated_models={"gemini": ("model",)},
        state_sink=sink,
        fallback=FakeFallback(),
    )

    router.route(_request(), RouterRequestContext(job_id="editorial-42", shard_id="shard-03", stage="map"))

    attempt = sink.attempts[0]
    assert (attempt.job_id, attempt.shard_id, attempt.stage) == ("editorial-42", "shard-03", "map")


def test_dispatch_usage_is_reported_by_safe_health():
    clock = ManualClock()
    transport = FakeTransport()
    router = _router((_provider("gemini"),), transport, clock)

    router.route(_request())

    health = router.health()
    assert health["providers"]["gemini"]["keys"][0]["successful_request_count"] == 1
    assert health["providers"]["gemini"]["models"]["model"]["validation_status"] == "validated"

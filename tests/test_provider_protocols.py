"""Provider protocol adapters share one safe editorial transport seam."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from newsroom.editorial.router import (
    HttpEditorialTransport,
    ModelRoute,
    ProviderConfig,
    RouterRequestContext,
    build_chat_payload,
    load_router_config,
)
from newsroom.editorial.router.model_catalog import ProviderModelCatalog
from newsroom.editorial.schema import (
    ClaimStatus,
    EditorialEvidenceSet,
    EditorialOutput,
    EditorialRequest,
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
                sources=[
                    EvidenceSourceItem(
                        ref_id="ev-1-0",
                        item_id=10,
                        original_title="A verified release is available",
                        excerpt="The release is available.",
                        original_url="https://example.test/release",
                    )
                ],
                facts=["The release is available."],
            )
        ]
    )
    return EditorialRequest(evidence=evidence, max_output_tokens=500)


def _output() -> dict[str, Any]:
    request = _request()
    return EditorialOutput(
        metadata=ReportMetadata(
            evidence_set_hash=request.evidence.evidence_hash(),
        ),
        stories=[
            StoryEditorialResult(
                story_id=1,
                headline_fa="\u0646\u0633\u062e\u0647\u0654 \u062a\u0627\u0632\u0647 \u0645\u0646\u062a\u0634\u0631 \u0634\u062f",
                summary_fa="\u0627\u06cc\u0646 \u0646\u0633\u062e\u0647 \u0627\u06a9\u0646\u0648\u0646 \u062f\u0631 \u062f\u0633\u062a\u0631\u0633 \u0627\u0633\u062a.",
                source_ref_ids=["ev-1-0"],
                source_links=["https://example.test/release"],
                key_claims=[
                    KeyClaim(
                        claim_text="The release is available.",
                        supporting_evidence_refs=["ev-1-0"],
                        support_status=ClaimStatus.SUPPORTED,
                    )
                ],
            )
        ],
    ).model_dump(mode="json")


def _client_for(
    handler: Callable[[httpx.Request], httpx.Response],
    captured: list[httpx.Request],
) -> type[httpx.Client]:
    class MockClient(httpx.Client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            def capture(request: httpx.Request) -> httpx.Response:
                captured.append(request)
                return handler(request)

            kwargs["transport"] = httpx.MockTransport(capture)
            super().__init__(*args, **kwargs)

    return MockClient


def test_native_gemini_adapter_uses_header_auth_and_native_schema() -> None:
    captured: list[httpx.Request] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": json.dumps(_output())}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 40,
                    "candidatesTokenCount": 20,
                },
            },
        )

    provider = ProviderConfig(
        name="gemini",
        keys=("protected",),
        models=("gemini-3.6-flash",),
        api_base="https://generativelanguage.googleapis.com/v1beta/openai",
        protocol="gemini",
    )
    response = HttpEditorialTransport(
        (provider,),
        client_factory=_client_for(handler, captured),
    ).execute(
        ModelRoute.validated("gemini", "gemini-3.6-flash"),
        "protected",
        _request(),
        RouterRequestContext(stage="reduce"),
    )

    request = captured[0]
    payload = json.loads(request.content)
    assert request.url.path.endswith("/models/gemini-3.6-flash:generateContent")
    assert request.headers["x-goog-api-key"] == "protected"
    assert "authorization" not in request.headers
    assert "temperature" not in payload["generationConfig"]
    assert response.usage == {
        "prompt_tokens": 40,
        "completion_tokens": 20,
        "total_tokens": 60,
    }


def test_deprecated_sampling_is_omitted_for_gemini_model_on_custom_provider() -> None:
    route = ModelRoute.validated("operator-provider", "gemini-3.5-flash-lite")

    payload = build_chat_payload(route, _request())

    assert "temperature" not in payload
    assert "top_p" not in payload
    assert "top_k" not in payload


def test_anthropic_adapter_parses_messages_response() -> None:
    captured: list[httpx.Request] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": json.dumps(_output())}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 30, "output_tokens": 15},
            },
        )

    provider = ProviderConfig(
        name="anthropic",
        keys=("protected",),
        models=("claude-example",),
        api_base="https://api.anthropic.com/v1",
        protocol="anthropic",
    )
    response = HttpEditorialTransport(
        (provider,),
        client_factory=_client_for(handler, captured),
    ).execute(
        ModelRoute.validated("anthropic", "claude-example"),
        "protected",
        _request(),
        RouterRequestContext(),
    )

    assert captured[0].url.path.endswith("/v1/messages")
    assert captured[0].headers["x-api-key"] == "protected"
    assert response.provider == "anthropic"
    assert response.model == "claude-example"


def test_custom_provider_protocol_is_loaded_only_from_canonical_file(
    tmp_path: Path,
) -> None:
    provider_file = tmp_path / ".env.providers.local"
    provider_file.write_text(
        "LLM_PROVIDER_ORDER=acme\n"
        "ACME_API_KEYS=protected\n"
        "ACME_MODELS=model-one,model-two\n"
        "ACME_API_BASE=https://provider.example/v1\n"
        "ACME_PROTOCOL=anthropic\n",
        encoding="utf-8",
    )

    provider = load_router_config(provider_file).provider("acme")

    assert provider.protocol == "anthropic"
    assert provider.models == ("model-one", "model-two")
    assert "protected" not in repr(provider)


def test_model_discovery_filters_non_generation_gemini_models() -> None:
    captured: list[httpx.Request] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-generate",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/text-embedding",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
        )

    provider = ProviderConfig(
        name="gemini",
        keys=("protected",),
        api_base="https://generativelanguage.googleapis.com/v1beta",
        protocol="gemini",
    )
    result = ProviderModelCatalog(
        (provider,),
        client_factory=_client_for(handler, captured),
    ).discover()[0]

    assert result.models == ("gemini-generate",)
    assert captured[0].headers["x-goog-api-key"] == "protected"
    assert "protected" not in repr(result)


def test_openai_compatible_gemini_catalog_canonicalizes_and_filters_models() -> None:
    captured: list[httpx.Request] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "models/gemini-2.5-flash"},
                    {"id": "models/gemini-2.5-flash-preview-tts"},
                    {"id": "models/gemini-2.5-flash-image"},
                ]
            },
        )

    provider = ProviderConfig(
        name="gemini",
        keys=("protected",),
        api_base="https://generativelanguage.googleapis.com/v1beta/openai",
        protocol="openai",
    )

    result = ProviderModelCatalog(
        (provider,),
        client_factory=_client_for(handler, captured),
    ).discover()[0]

    assert result.models == ("gemini-2.5-flash",)


def test_openai_catalog_excludes_non_editorial_services() -> None:
    captured: list[httpx.Request] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "whisper-large-v3"},
                    {"id": "meta-llama/llama-prompt-guard-2-86m"},
                    {"id": "llama-3.3-70b-versatile"},
                ]
            },
        )

    provider = ProviderConfig(
        name="groq",
        keys=("protected",),
        api_base="https://api.groq.com/openai/v1",
        protocol="openai",
    )

    result = ProviderModelCatalog(
        (provider,),
        client_factory=_client_for(handler, captured),
    ).discover()[0]

    assert result.models == ("llama-3.3-70b-versatile",)


def test_model_discovery_isolates_invalid_key_and_uses_next_key() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["authorization"] == "Bearer invalid":
            return httpx.Response(401)
        return httpx.Response(200, json={"data": [{"id": "model-one"}]})

    provider = ProviderConfig(
        name="operator_provider",
        keys=("invalid", "healthy"),
        api_base="https://provider.example/v1",
        protocol="openai",
    )

    result = ProviderModelCatalog(
        (provider,),
        client_factory=_client_for(handler, captured),
    ).discover()[0]

    assert result.models == ("model-one",)
    assert len(captured) == 2

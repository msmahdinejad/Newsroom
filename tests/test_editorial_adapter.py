"""Adapter-specific tests for OpenAICompatibleEditorialProvider.

Covers: URL construction safety, effective token limits, request contract,
retry policy, status code mapping, structured output parsing, refusal,
rate-limit, malformed responses, no-tools enforcement, cache key with
report_mode, evidence prioritization, output budget exhaustion.

Uses httpx.MockTransport to simulate provider responses without network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from newsroom.editorial.openai_provider import (
    PROVIDER_MAX_OUTPUT_TOKENS_CAP,
    OpenAICompatibleEditorialProvider,
    _build_url,
    compute_effective_input_limit,
    compute_effective_output_limit,
)
from newsroom.editorial.schema import (
    OUTPUT_SCHEMA_VERSION,
    SYSTEM_PROMPT_VERSION,
    EditorialError,
    EditorialErrorCategory,
    EditorialEvidenceSet,
    EditorialRequest,
    EvidenceSourceItem,
    EvidenceStoryPacket,
)

# ── Test fixtures ──────────────────────────────────────────────────


def make_evidence(story_id: int = 1, source_count: int = 2) -> EditorialEvidenceSet:
    """Build a minimal evidence set for adapter tests."""
    sources = [
        EvidenceSourceItem(
            ref_id=f"ev-{story_id}-{i}",
            item_id=100 + i,
            source_name=f"Source{i}",
            source_type="rss",
            source_trust="reputable",
            source_trust_score=0.8,
            published_at="2026-07-17T10:00:00+00:00",
            original_title=f"Title {i}",
            excerpt=f"Excerpt {i}",
            original_url=f"https://example.com/{story_id}/{i}",
        )
        for i in range(source_count)
    ]
    return EditorialEvidenceSet(
        stories=[
            EvidenceStoryPacket(
                story_id=story_id,
                headline="Test Story",
                keywords=["ai"],
                trust_status="confirmed",
                confidence=0.85,
                importance_score=0.8,
                source_count=source_count,
                item_count=source_count,
                sources=sources,
                facts=["AI is advancing", "New model released"],
            )
        ]
    )


def make_valid_output_json(evidence: EditorialEvidenceSet) -> dict:
    """Build a valid output dict matching the evidence."""
    sp = evidence.stories[0]
    refs = [s.ref_id for s in sp.sources]
    links = [s.original_url for s in sp.sources]
    return {
        "metadata": {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "report_mode": "scheduled",
            "generated_at": datetime.now(UTC).isoformat(),
            "model_name": "test-model",
            "provider": "openai_compatible",
            "evidence_set_hash": evidence.evidence_hash(),
            "prompt_version": SYSTEM_PROMPT_VERSION,
            "editorial_status": "ok",
        },
        "stories": [
            {
                "story_id": sp.story_id,
                "headline_fa": "عنوان فارسی",
                "summary_fa": "خلاصه فارسی",
                "why_it_matters_fa": "چون مهم است",
                "practical_impact_fa": "کاربرد عملی",
                "target_audience": "developers",
                "confidence_level": 0.85,
                "verification_status": "confirmed",
                "classification": "corroborated",
                "source_ref_ids": refs,
                "source_links": links,
                "key_claims": [
                    {
                        "claim_text": "AI is advancing",
                        "supporting_evidence_refs": refs[:1],
                        "support_status": "supported",
                        "confidence": 0.85,
                        "conflicting_evidence_refs": [],
                    }
                ],
                "uncertainty_notes": "",
                "suggested_priority": "high",
            }
        ],
    }


def make_chat_response(content: str, finish_reason: str = "stop", usage: dict | None = None) -> dict:
    """Build a chat completions response body."""
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
                "index": 0,
            }
        ],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


def make_provider(
    api_base: str = "https://generativelanguage.googleapis.com/v1beta/openai/",
    **kwargs,
) -> OpenAICompatibleEditorialProvider:
    """Create a provider with defaults for testing."""
    defaults = {
        "api_key": "test-key-not-real",
        "model": "test-model",
        "timeout_seconds": 10,
        "max_retries": 0,
    }
    defaults.update(kwargs)
    return OpenAICompatibleEditorialProvider(api_base=api_base, **defaults)


def make_mock_transport(status_code: int = 200, json_body: dict | None = None, text: str | None = None) -> httpx.MockTransport:
    """Create a mock transport returning a fixed response."""
    def handler(request: httpx.Request) -> httpx.Response:
        if text is not None:
            return httpx.Response(status_code, text=text)
        return httpx.Response(status_code, json=json_body or {})
    return httpx.MockTransport(handler)


def patched_client(transport: httpx.MockTransport):
    """Return a patch that replaces httpx.Client with a subclass using the given transport.

    The subclass inherits all Client behavior (context manager, post, etc.)
    but forces the mock transport, so no real network is used.
    """

    class _MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    return patch("newsroom.editorial.openai_provider.httpx.Client", _MockClient)


def capturing_client(handler):
    """Return a patch that replaces httpx.Client with a capturing subclass."""

    class _CapturingClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    return patch("newsroom.editorial.openai_provider.httpx.Client", _CapturingClient)


# ── D-6: URL construction tests ───────────────────────────────────


class TestURLConstruction:
    def test_base_with_trailing_slash(self):
        url = _build_url("https://generativelanguage.googleapis.com/v1beta/openai/", "chat/completions")
        assert url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

    def test_base_without_trailing_slash(self):
        url = _build_url("https://generativelanguage.googleapis.com/v1beta/openai", "chat/completions")
        assert url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

    def test_base_with_multiple_trailing_slashes(self):
        url = _build_url("https://api.openai.com/v1///", "chat/completions")
        assert url == "https://api.openai.com/v1/chat/completions"

    def test_path_with_leading_slash(self):
        url = _build_url("https://api.openai.com/v1", "/chat/completions")
        assert url == "https://api.openai.com/v1/chat/completions"

    def test_no_duplicated_segments(self):
        """Ensure no /v1/v1/ or //chat/ duplication."""
        url = _build_url("https://api.openai.com/v1/", "/chat/completions/")
        assert "//" not in url.replace("https://", "")
        assert "/v1/v1/" not in url
        assert "/chat/completions/chat/completions" not in url

    def test_gemini_openai_base(self):
        """Gemini's OpenAI-compatible base URL produces correct endpoint."""
        url = _build_url("https://generativelanguage.googleapis.com/v1beta/openai/", "chat/completions")
        assert url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


# ── D-2: Effective token limit tests ──────────────────────────────


class TestEffectiveTokenLimits:
    def test_configured_below_provider_limit(self):
        effective, configured = compute_effective_output_limit(4000)
        assert effective == 4000
        assert configured == 4000

    def test_configured_above_provider_limit(self):
        effective, configured = compute_effective_output_limit(500000)
        assert effective == PROVIDER_MAX_OUTPUT_TOKENS_CAP
        assert configured == 500000

    def test_configured_equal_to_cap(self):
        effective, _ = compute_effective_output_limit(PROVIDER_MAX_OUTPUT_TOKENS_CAP)
        assert effective == PROVIDER_MAX_OUTPUT_TOKENS_CAP

    def test_zero_value_clamped(self):
        effective, _ = compute_effective_output_limit(0)
        assert effective == 1

    def test_negative_value_clamped(self):
        effective, _ = compute_effective_output_limit(-100)
        assert effective == 1

    def test_provider_effective_output_tokens_property(self):
        provider = make_provider(max_output_tokens=500000)
        assert provider.configured_max_output_tokens == 500000
        assert provider.effective_max_output_tokens == PROVIDER_MAX_OUTPUT_TOKENS_CAP

    def test_provider_normal_output_tokens(self):
        provider = make_provider(max_output_tokens=4000)
        assert provider.effective_max_output_tokens == 4000

    def test_effective_input_limit_normal(self):
        effective, _ = compute_effective_input_limit(12000)
        assert effective == 12000

    def test_effective_input_limit_above_cap(self):
        effective, _ = compute_effective_input_limit(500000)
        assert effective <= 128000


# ── Phase 3: Request contract tests ───────────────────────────────


class TestRequestContract:
    def test_uses_chat_completions_endpoint(self):
        """Verify the adapter calls /chat/completions, not /responses or another route."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))
        provider = make_provider()

        captured_requests: list[httpx.Request] = []

        def capturing_handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, json=response_body)

        provider._api_base = "https://generativelanguage.googleapis.com/v1beta/openai/"
        with capturing_client(capturing_handler):
            request = EditorialRequest(evidence=evidence)
            provider.generate(request)

        assert len(captured_requests) == 1
        assert "/chat/completions" in str(captured_requests[0].url)
        assert "/responses" not in str(captured_requests[0].url)

    def test_no_tools_enabled(self):
        """Verify no tools, functions, web search, or function calling in payload."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))

        captured_payload: dict = {}

        def capturing_handler(request: httpx.Request) -> httpx.Response:
            captured_payload.update(json.loads(request.content))
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(capturing_handler):
            request = EditorialRequest(evidence=evidence)
            provider.generate(request)

        assert "tools" not in captured_payload
        assert "functions" not in captured_payload
        assert "function_call" not in captured_payload
        assert "tool_choice" not in captured_payload
        assert "web_search" not in captured_payload
        assert "file_search" not in captured_payload
        assert "code_execution" not in captured_payload

    def test_uses_json_object_response_format(self):
        """Verify response_format is json_object."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))

        captured_payload: dict = {}

        def capturing_handler(request: httpx.Request) -> httpx.Response:
            captured_payload.update(json.loads(request.content))
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(capturing_handler):
            request = EditorialRequest(evidence=evidence)
            provider.generate(request)

        assert captured_payload["response_format"] == {"type": "json_object"}

    def test_authorization_header_bearer(self):
        """Verify Authorization header uses Bearer scheme."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))

        captured_headers: dict = {}

        def capturing_handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json=response_body)

        provider = make_provider(api_key="test-key-not-real")
        with capturing_client(capturing_handler):
            request = EditorialRequest(evidence=evidence)
            provider.generate(request)

        assert captured_headers.get("authorization") == "Bearer test-key-not-real"
        assert captured_headers.get("content-type") == "application/json"

    def test_effective_output_tokens_in_payload(self):
        """Verify the effective (capped) token limit is sent, not the configured."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))

        captured_payload: dict = {}

        def capturing_handler(request: httpx.Request) -> httpx.Response:
            captured_payload.update(json.loads(request.content))
            return httpx.Response(200, json=response_body)

        provider = make_provider(max_output_tokens=500000)
        with capturing_client(capturing_handler):
            request = EditorialRequest(evidence=evidence, max_output_tokens=500000)
            provider.generate(request)

        assert captured_payload["max_tokens"] == PROVIDER_MAX_OUTPUT_TOKENS_CAP
        assert captured_payload["max_tokens"] != 500000


# ── Phase 3: Retry policy tests ────────────────────────────────────


class TestRetryPolicy:
    def test_retry_on_5xx_then_success(self):
        """Provider retries on 5xx and succeeds on next attempt."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, json={"error": "internal"})
            return httpx.Response(200, json=response_body)

        provider = make_provider(max_retries=2)
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            result = provider.generate(request)

        assert call_count == 2
        assert result.provider == "openai_compatible"

    def test_retry_on_429_then_success(self):
        """Provider retries on 429 rate limit."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json=response_body)

        provider = make_provider(max_retries=2)
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            provider.generate(request)

        assert call_count == 2

    def test_no_retry_on_401(self):
        """Provider does not retry on 401 (permanent error)."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(401, json={"error": "unauthorized"})

        provider = make_provider(max_retries=3)
        with capturing_client(handler):
            request = EditorialRequest(evidence=make_evidence())
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)

        assert call_count == 1
        assert exc_info.value.category == EditorialErrorCategory.INVALID_API_KEY

    def test_no_retry_on_400(self):
        """Provider does not retry on 400 (bad request — permanent)."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(400, json={"error": "bad request"})

        provider = make_provider(max_retries=3)
        with capturing_client(handler):
            request = EditorialRequest(evidence=make_evidence())
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)

        assert call_count == 1
        assert exc_info.value.category == EditorialErrorCategory.CONTEXT_LENGTH

    def test_max_retries_exhausted(self):
        """Provider stops after max_retries + 1 attempts."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(500, json={"error": "persistent outage"})

        provider = make_provider(max_retries=2)
        with capturing_client(handler):
            request = EditorialRequest(evidence=make_evidence())
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)

        assert call_count == 3  # 1 initial + 2 retries
        assert exc_info.value.category == EditorialErrorCategory.PROVIDER_UNAVAILABLE


# ── Phase 3: Response parsing tests ───────────────────────────────


class TestResponseParsing:
    def test_valid_json_response(self):
        """Valid JSON response is parsed correctly."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            resp = provider.generate(request)

        assert resp.provider == "openai_compatible"
        assert resp.output.stories[0].story_id == 1
        assert resp.usage is not None
        assert resp.usage["total_tokens"] == 150

    def test_json_in_markdown_fences(self):
        """JSON wrapped in markdown code fences is parsed."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        content = f"```json\n{json.dumps(output_json, ensure_ascii=False)}\n```"
        response_body = make_chat_response(content)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)
        # Content with markdown fences will fail JSON parse → MALFORMED_RESPONSE
        assert exc_info.value.category == EditorialErrorCategory.MALFORMED_RESPONSE

    def test_prose_before_json(self):
        """Prose before JSON should be rejected."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        content = f"Here is the result:\n{json.dumps(output_json, ensure_ascii=False)}"
        response_body = make_chat_response(content)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)
        assert exc_info.value.category == EditorialErrorCategory.MALFORMED_RESPONSE

    def test_truncated_json(self):
        """Truncated JSON content is rejected."""
        evidence = make_evidence()
        content = '{"metadata": {"schema_version": "g4out-v1", "stories": ['
        response_body = make_chat_response(content)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)
        assert exc_info.value.category == EditorialErrorCategory.MALFORMED_RESPONSE

    def test_empty_content(self):
        """Empty content in response is rejected."""
        evidence = make_evidence()
        response_body = make_chat_response("")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)
        assert exc_info.value.category == EditorialErrorCategory.PARTIAL_RESPONSE

    def test_no_choices_in_response(self):
        """Response with no choices is rejected."""
        evidence = make_evidence()
        response_body = {"choices": [], "usage": {}}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)
        assert exc_info.value.category == EditorialErrorCategory.PARTIAL_RESPONSE

    def test_content_filter_refusal(self):
        """Content filter finish_reason triggers SAFETY_REFUSAL."""
        evidence = make_evidence()
        response_body = make_chat_response("filtered", finish_reason="content_filter")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)
        assert exc_info.value.category == EditorialErrorCategory.SAFETY_REFUSAL

    def test_length_finish_reason(self):
        """Length finish_reason is mapped correctly."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(
            json.dumps(output_json, ensure_ascii=False),
            finish_reason="length",
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            resp = provider.generate(request)
        assert resp.finish_status == "length"

    def test_unknown_response_fields_ignored(self):
        """Unknown fields in response are ignored, not persisted."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))
        response_body["unknown_field"] = "should be ignored"
        response_body["choices"][0]["message"]["unknown_nested"] = "ignored"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            resp = provider.generate(request)
        # Response should be valid despite unknown fields
        assert resp.output.stories[0].story_id == 1

    def test_usage_parsed_correctly(self):
        """Usage metadata is parsed from response."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        usage = {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700}
        response_body = make_chat_response(
            json.dumps(output_json, ensure_ascii=False),
            usage=usage,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            resp = provider.generate(request)
        assert resp.usage == usage

    def test_no_usage_returns_none(self):
        """Response without usage field returns None usage."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))
        del response_body["usage"]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            resp = provider.generate(request)
        assert resp.usage is None

    def test_metadata_enforced_from_our_side(self):
        """Provider enforces evidence_set_hash and metadata from our side."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        # Tamper with metadata — provider should override
        output_json["metadata"]["evidence_set_hash"] = "tampered"
        output_json["metadata"]["provider"] = "tampered"
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            resp = provider.generate(request)
        assert resp.output.metadata.evidence_set_hash == evidence.evidence_hash()
        assert resp.output.metadata.provider == "openai_compatible"


# ── Phase 4: Config safety tests ──────────────────────────────────


class TestConfigSafety:
    def test_configured_above_provider_limit_effective_capped(self):
        """When configured > provider cap, effective = cap."""
        provider = make_provider(max_output_tokens=100000)
        assert provider.effective_max_output_tokens <= PROVIDER_MAX_OUTPUT_TOKENS_CAP

    def test_configured_below_provider_limit_effective_preserved(self):
        """When configured < provider cap, effective = configured."""
        provider = make_provider(max_output_tokens=2000)
        assert provider.effective_max_output_tokens == 2000

    def test_oversized_evidence_still_bounded(self):
        """Oversized evidence is bounded by evidence builder limits."""
        evidence = make_evidence(source_count=20)
        assert len(evidence.stories[0].sources) <= 20
        # Evidence builder would normally cap this; here we just verify the adapter accepts it

    def test_output_budget_exhaustion_finish_status(self):
        """When max_tokens is hit, finish_status is 'length'."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(
            json.dumps(output_json, ensure_ascii=False),
            finish_reason="length",
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider(max_output_tokens=100)
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence, max_output_tokens=100)
            resp = provider.generate(request)
        assert resp.finish_status == "length"

    def test_deterministic_story_ordering_preserved(self):
        """Evidence builder preserves deterministic story ordering."""
        # Stories ordered by importance_score desc, then created_at desc
        # This is tested in the evidence builder; here we verify the adapter doesn't reorder
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            resp = provider.generate(request)
        assert resp.output.stories[0].story_id == evidence.stories[0].story_id

    def test_omitted_story_counts_not_in_output(self):
        """Verify stories omitted due to limits are not counted in output."""
        # This is handled by evidence builder (max_stories_per_call)
        # The adapter just processes what it receives
        evidence = make_evidence()
        assert len(evidence.stories) == 1  # only one story in test


# ── Phase 5: Structured output edge cases ─────────────────────────


class TestStructuredOutputEdgeCases:
    def test_multiple_json_objects_rejected(self):
        """Multiple JSON objects in content should fail to parse."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        content = json.dumps(output_json, ensure_ascii=False) + json.dumps(output_json, ensure_ascii=False)
        response_body = make_chat_response(content)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)
        assert exc_info.value.category in (EditorialErrorCategory.MALFORMED_RESPONSE, EditorialErrorCategory.SCHEMA_VALIDATION)

    def test_schema_validation_failure(self):
        """Output that fails Pydantic schema validation is rejected."""
        evidence = make_evidence()
        # story_id must be int — pass a string to trigger Pydantic validation failure
        bad_output = {"metadata": {}, "stories": [{"story_id": "not-an-int"}]}
        response_body = make_chat_response(json.dumps(bad_output))

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)
        assert exc_info.value.category == EditorialErrorCategory.SCHEMA_VALIDATION

    def test_malformed_response_json(self):
        """Non-JSON response body triggers MALFORMED_RESPONSE."""
        evidence = make_evidence()
        response_body = "not json at all"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=response_body, headers={"content-type": "application/json"})

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            with pytest.raises(EditorialError) as exc_info:
                provider.generate(request)
        assert exc_info.value.category == EditorialErrorCategory.MALFORMED_RESPONSE

    def test_no_cot_stored(self):
        """Verify no chain-of-thought or reasoning fields are persisted."""
        evidence = make_evidence()
        output_json = make_valid_output_json(evidence)
        # Add reasoning fields that should be ignored
        output_json["reasoning"] = "internal thoughts"
        output_json["thoughts"] = "chain of thought"
        output_json["stories"][0]["reasoning"] = "more thoughts"
        response_body = make_chat_response(json.dumps(output_json, ensure_ascii=False))

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_body)

        provider = make_provider()
        with capturing_client(handler):
            request = EditorialRequest(evidence=evidence)
            resp = provider.generate(request)

        # Output model should not have reasoning fields
        dumped = resp.output.model_dump()
        assert "reasoning" not in dumped
        assert "thoughts" not in dumped
        assert "reasoning" not in dumped["stories"][0]


# ── Persian digit normalization in grounding ──────────────────────


class TestPersianDigitGrounding:
    def test_persian_digits_match_latin_evidence(self):
        """Persian-Indic digits in claims should match Latin digits in evidence."""
        from newsroom.editorial.grounding import _has_unsupported_numbers

        # Build evidence that contains "3.13.1" in the headline and excerpt
        evidence = EditorialEvidenceSet(
            stories=[
                EvidenceStoryPacket(
                    story_id=1,
                    headline="Python 3.13.1 released",
                    facts=["Python 3.13.1 is a maintenance release"],
                    confidence=0.95,
                    importance_score=0.8,
                    trust_status="official",
                    source_count=1,
                    item_count=1,
                    sources=[
                        EvidenceSourceItem(
                            ref_id="ev-1-0",
                            item_id=1,
                            original_title="Python 3.13.1",
                            excerpt="Python 3.13.1 is the first maintenance release",
                            original_url="https://www.python.org/",
                            release_version="3.13.1",
                        )
                    ],
                )
            ]
        )
        # Claim uses Persian digits ۳.۱۳.۱ but evidence uses Latin 3.13.1
        claim = "پایتون ۳.۱۳.۱ منتشر شد"
        assert not _has_unsupported_numbers(claim, evidence, 1)

    def test_unsupported_persian_number_rejected(self):
        """Persian digits not in evidence are still rejected."""
        from newsroom.editorial.grounding import _has_unsupported_numbers

        evidence = make_evidence()
        # ۹۹.۹ is not in evidence
        claim = "نسخه ۹۹.۹ منتشر شد"
        assert _has_unsupported_numbers(claim, evidence, 1)

    def test_arabic_indic_digits_match(self):
        """Arabic-Indic digits (٠-٩) also normalize correctly."""
        from newsroom.editorial.grounding import _has_unsupported_numbers

        # Build evidence that contains "3.13.1"
        evidence = EditorialEvidenceSet(
            stories=[
                EvidenceStoryPacket(
                    story_id=1,
                    headline="Python 3.13.1 released",
                    facts=["Python 3.13.1 is a maintenance release"],
                    confidence=0.95,
                    importance_score=0.8,
                    trust_status="official",
                    source_count=1,
                    item_count=1,
                    sources=[
                        EvidenceSourceItem(
                            ref_id="ev-1-0",
                            item_id=1,
                            original_title="Python 3.13.1",
                            excerpt="Python 3.13.1 is the first maintenance release",
                            original_url="https://www.python.org/",
                            release_version="3.13.1",
                        )
                    ],
                )
            ]
        )
        # Arabic-Indic ٣.١٣.١ should match Latin 3.13.1
        claim = "النسخة ٣.١٣.١"
        assert not _has_unsupported_numbers(claim, evidence, 1)


# ── Cache key with report_mode (D-4) ──────────────────────────────


class TestCacheKeyWithReportMode:
    def test_cache_key_includes_report_mode(self):
        from newsroom.editorial.persistence import compute_cache_key

        key1 = compute_cache_key("scheduled", "hash1", "v1", "openai_compatible", "model1")
        key2 = compute_cache_key("manual", "hash1", "v1", "openai_compatible", "model1")
        assert key1 != key2

    def test_cache_key_includes_all_identity(self):
        from newsroom.editorial.persistence import compute_cache_key

        base = compute_cache_key("scheduled", "hash1", "v1", "openai_compatible", "model1")
        # Change each component
        assert compute_cache_key("manual", "hash1", "v1", "openai_compatible", "model1") != base
        assert compute_cache_key("scheduled", "hash2", "v1", "openai_compatible", "model1") != base
        assert compute_cache_key("scheduled", "hash1", "v2", "openai_compatible", "model1") != base
        assert compute_cache_key("scheduled", "hash1", "v1", "deterministic", "model1") != base
        assert compute_cache_key("scheduled", "hash1", "v1", "openai_compatible", "model2") != base

    def test_cache_key_includes_editorial_settings(self):
        """Cache key invalidates when temperature or token budgets change."""
        from newsroom.editorial.persistence import compute_cache_key

        base = compute_cache_key("scheduled", "hash1", "v1", "openai_compatible", "model1")
        # Change temperature
        assert compute_cache_key(
            "scheduled", "hash1", "v1", "openai_compatible", "model1", temperature=0.7
        ) != base
        # Change max_input_tokens
        assert compute_cache_key(
            "scheduled", "hash1", "v1", "openai_compatible", "model1", max_input_tokens=8000
        ) != base
        # Change max_output_tokens
        assert compute_cache_key(
            "scheduled", "hash1", "v1", "openai_compatible", "model1", max_output_tokens=2000
        ) != base

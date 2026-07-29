"""Provider HTTP protocol adapters behind one transport interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote

from newsroom.editorial.prompt import build_prompt
from newsroom.editorial.router.types import ModelRoute, RouterRequestContext
from newsroom.editorial.schema import EditorialRequest

OMIT_SAMPLING_MODELS = frozenset(
    {
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
    }
)


@dataclass(frozen=True)
class HttpCall:
    """A bounded request specification whose credentials never appear in repr."""

    url: str
    payload: dict[str, Any]
    headers: dict[str, str] = field(repr=False)


@dataclass(frozen=True)
class ProviderPayload:
    """Protocol-independent model output consumed by the editorial transport."""

    content: Any
    finish_reason: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ProviderProtocolAdapter(Protocol):
    """Deep adapter interface implemented by each provider wire protocol."""

    protocol: str

    def build_call(
        self,
        *,
        api_base: str,
        route: ModelRoute,
        key_value: str,
        request: EditorialRequest,
        context: RouterRequestContext,
    ) -> HttpCall: ...

    def parse_payload(self, body: Any) -> ProviderPayload: ...


def protocol_api_base(api_base: str, protocol: str) -> str:
    """Normalize known compatibility suffixes at the protocol boundary."""
    normalized = api_base.rstrip("/")
    if protocol == "gemini" and normalized.endswith("/openai"):
        return normalized.removesuffix("/openai")
    return normalized


def _omit_sampling(route: ModelRoute) -> bool:
    model = route.model.removeprefix("models/")
    return model in OMIT_SAMPLING_MODELS


def _messages(
    request: EditorialRequest,
    context: RouterRequestContext,
) -> list[dict[str, str]]:
    messages = build_prompt(request.evidence)
    if context.stage != "repair" or not context.repair_payload:
        return messages
    return [
        *messages,
        {
            "role": "user",
            "content": (
                "Regenerate a complete response for EVERY evidence story into the "
                "required JSON schema. Do not preserve omissions; use only facts and "
                "references from the supplied evidence.\n"
                "<<<REPAIR_BEGIN>>>\n"
                f"{context.repair_payload[:12000]}\n<<<REPAIR_END>>>"
            ),
        },
    ]


class OpenAIProtocolAdapter:
    """Adapter for OpenAI-compatible chat completion APIs."""

    protocol = "openai"

    def build_call(
        self,
        *,
        api_base: str,
        route: ModelRoute,
        key_value: str,
        request: EditorialRequest,
        context: RouterRequestContext,
    ) -> HttpCall:
        payload: dict[str, Any] = {
            "model": route.model,
            "messages": _messages(request, context),
            "max_tokens": max(1, min(request.max_output_tokens, 8192)),
            "response_format": {"type": "json_object"},
        }
        if not _omit_sampling(route):
            payload["temperature"] = request.temperature
        return HttpCall(
            url=f"{protocol_api_base(api_base, self.protocol)}/chat/completions",
            payload=payload,
            headers={
                "Authorization": f"Bearer {key_value}",
                "Content-Type": "application/json",
            },
        )

    def parse_payload(self, body: Any) -> ProviderPayload:
        choices = body.get("choices") or []
        content = choices[0]["message"]["content"]
        usage = body.get("usage") or {}
        return ProviderPayload(
            content=content,
            finish_reason=choices[0].get("finish_reason") or "stop",
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        )


class GeminiProtocolAdapter:
    """Adapter for the native Google Generative Language API."""

    protocol = "gemini"

    def build_call(
        self,
        *,
        api_base: str,
        route: ModelRoute,
        key_value: str,
        request: EditorialRequest,
        context: RouterRequestContext,
    ) -> HttpCall:
        messages = _messages(request, context)
        system_parts = [{"text": item["content"]} for item in messages if item["role"] == "system"]
        contents = [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in messages
            if item["role"] != "system"
        ]
        generation_config: dict[str, Any] = {
            "maxOutputTokens": max(1, min(request.max_output_tokens, 8192)),
            "responseMimeType": "application/json",
        }
        if not _omit_sampling(route):
            generation_config["temperature"] = request.temperature
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        return HttpCall(
            url=(
                f"{protocol_api_base(api_base, self.protocol)}/models/"
                f"{quote(route.model, safe='')}:generateContent"
            ),
            payload=payload,
            headers={
                "x-goog-api-key": key_value,
                "Content-Type": "application/json",
            },
        )

    def parse_payload(self, body: Any) -> ProviderPayload:
        candidate = (body.get("candidates") or [])[0]
        parts = candidate["content"]["parts"]
        content = "".join(str(part.get("text") or "") for part in parts)
        usage = body.get("usageMetadata") or {}
        return ProviderPayload(
            content=content,
            finish_reason=str(candidate.get("finishReason") or "STOP").lower(),
            prompt_tokens=int(usage.get("promptTokenCount", 0) or 0),
            completion_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
        )


class AnthropicProtocolAdapter:
    """Adapter for Anthropic's Messages API."""

    protocol = "anthropic"

    def build_call(
        self,
        *,
        api_base: str,
        route: ModelRoute,
        key_value: str,
        request: EditorialRequest,
        context: RouterRequestContext,
    ) -> HttpCall:
        messages = _messages(request, context)
        system = "\n\n".join(item["content"] for item in messages if item["role"] == "system")
        payload: dict[str, Any] = {
            "model": route.model,
            "max_tokens": max(1, min(request.max_output_tokens, 8192)),
            "system": system,
            "messages": [
                {
                    "role": item["role"],
                    "content": item["content"],
                }
                for item in messages
                if item["role"] != "system"
            ],
            "temperature": request.temperature,
        }
        return HttpCall(
            url=f"{protocol_api_base(api_base, self.protocol)}/messages",
            payload=payload,
            headers={
                "x-api-key": key_value,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )

    def parse_payload(self, body: Any) -> ProviderPayload:
        content = "".join(
            str(block.get("text") or "")
            for block in body.get("content") or []
            if block.get("type") == "text"
        )
        usage = body.get("usage") or {}
        return ProviderPayload(
            content=content,
            finish_reason=str(body.get("stop_reason") or "end_turn"),
            prompt_tokens=int(usage.get("input_tokens", 0) or 0),
            completion_tokens=int(usage.get("output_tokens", 0) or 0),
        )


DEFAULT_PROTOCOL_ADAPTERS: tuple[ProviderProtocolAdapter, ...] = (
    OpenAIProtocolAdapter(),
    GeminiProtocolAdapter(),
    AnthropicProtocolAdapter(),
)

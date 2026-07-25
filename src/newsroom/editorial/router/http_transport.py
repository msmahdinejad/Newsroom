"""Production HTTP transport for OpenAI-compatible provider endpoints."""

from __future__ import annotations

import email.utils
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from newsroom.editorial.prompt import build_prompt
from newsroom.editorial.router.types import (
    ModelRoute,
    ProviderConfig,
    RouteFailure,
    RouteFailureCategory,
    RouterRequestContext,
)
from newsroom.editorial.schema import EditorialOutput, EditorialRequest, EditorialResponse

OMIT_SAMPLING_PARAMETERS = {
    ("gemini", "gemini-3.6-flash"),
    ("gemini", "gemini-3.5-flash-lite"),
}


def build_chat_payload(route: ModelRoute, request: EditorialRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": route.model,
        "messages": build_prompt(request.evidence),
        "max_tokens": max(1, min(request.max_output_tokens, 8192)),
        "response_format": {"type": "json_object"},
    }
    if (route.provider, route.model) not in OMIT_SAMPLING_PARAMETERS:
        payload["temperature"] = request.temperature
    return payload


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        try:
            target = email.utils.parsedate_to_datetime(value)
            current = now or datetime.now(UTC)
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            return max(0.0, (target - current).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


class HttpEditorialTransport:
    """Bounded synchronous transport; access values are header-only and never logged."""

    def __init__(
        self,
        providers: tuple[ProviderConfig, ...],
        *,
        timeout_seconds: float = 45.0,
        proxy_url: str | None = None,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ) -> None:
        self._providers = {provider.name: provider for provider in providers}
        self._timeout_seconds = max(1.0, timeout_seconds)
        self._proxy_url = proxy_url
        self._client_factory = client_factory

    @property
    def transport_label(self) -> str:
        """Credential-safe aggregate transport label."""
        if self._proxy_url is None:
            return "direct"
        return f"{urlparse(self._proxy_url).scheme.lower()}_proxy"

    def execute(
        self,
        route: ModelRoute,
        key_value: str,
        request: EditorialRequest,
        context: RouterRequestContext,
    ) -> EditorialResponse:
        provider = self._providers[route.provider]
        url = f"{provider.api_base.rstrip('/')}/chat/completions"
        payload = build_chat_payload(route, request)
        if context.stage == "repair" and context.repair_payload:
            payload["messages"] = [
                *payload["messages"],
                {
                    "role": "user",
                    "content": (
                        "Repair the following bounded response into the required JSON schema. "
                        "Do not add facts or references.\n<<<REPAIR_BEGIN>>>\n"
                        f"{context.repair_payload[:12000]}\n<<<REPAIR_END>>>"
                    ),
                },
            ]
        try:
            client_kwargs: dict[str, Any] = {
                "timeout": httpx.Timeout(
                    self._timeout_seconds,
                    connect=min(15.0, self._timeout_seconds),
                )
            }
            if self._proxy_url is not None:
                client_kwargs["proxy"] = self._proxy_url
            with self._client_factory(**client_kwargs) as client:
                response = client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {key_value}", "Content-Type": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise RouteFailure(RouteFailureCategory.TIMEOUT, "provider request timed out") from exc
        except httpx.HTTPError as exc:
            raise RouteFailure(RouteFailureCategory.NETWORK_ERROR, "provider network failure") from exc

        self._raise_for_status(response)
        try:
            body = response.json()
            choices = body.get("choices") or []
            content = choices[0]["message"]["content"]
            finish_reason = choices[0].get("finish_reason") or "stop"
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise RouteFailure(RouteFailureCategory.MALFORMED_SCHEMA, "missing structured response") from exc
        if finish_reason in {"content_filter", "safety", "refusal"}:
            raise RouteFailure(RouteFailureCategory.POLICY_REJECTION, "provider policy rejection")
        if finish_reason in {"length", "max_tokens"}:
            raise RouteFailure(RouteFailureCategory.MALFORMED_SCHEMA, "bounded response was incomplete", repair_payload=str(content)[:12000])
        try:
            decoded = json.loads(content) if isinstance(content, str) else content
            decoded.setdefault("metadata", {})
            decoded["metadata"].update(
                {
                    "provider": route.provider,
                    "model_name": route.model,
                    "evidence_set_hash": request.evidence.evidence_hash(),
                    "prompt_version": request.evidence.prompt_version,
                }
            )
            output = EditorialOutput.model_validate(decoded)
        except (ValueError, TypeError, AttributeError) as exc:
            repair = content[:12000] if isinstance(content, str) else json.dumps(content, ensure_ascii=False)[:12000]
            raise RouteFailure(RouteFailureCategory.MALFORMED_SCHEMA, "structured schema validation failed", repair_payload=repair) from exc

        raw_usage = body.get("usage") or {}
        usage = {
            "prompt_tokens": int(raw_usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(raw_usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(raw_usage.get("total_tokens", 0) or 0),
        }
        return EditorialResponse(
            output=output,
            provider=route.provider,
            model=route.model,
            finish_status="stop",
            usage=usage,
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status in {401, 403}:
            raise RouteFailure(RouteFailureCategory.INVALID_KEY, "provider authentication rejected")
        if status == 429:
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            body = response.text.lower()[:2000]
            if retry_after is None:
                match = re.search(r"(?:retry(?:\s+in|delay)[^0-9]{0,20})([0-9]+(?:\.[0-9]+)?)s", body)
                if match:
                    retry_after = float(match.group(1))
            if any(marker in body for marker in ("daily", "per day", "rpd", "quota_day")):
                raise RouteFailure(RouteFailureCategory.DAILY_QUOTA, "daily provider quota exhausted", retry_after_seconds=retry_after)
            raise RouteFailure(RouteFailureCategory.RATE_LIMIT, "provider rate limited", retry_after_seconds=retry_after)
        if status in {408, 504}:
            raise RouteFailure(RouteFailureCategory.TIMEOUT, "provider timeout status")
        if status >= 500:
            raise RouteFailure(RouteFailureCategory.SERVER_ERROR, f"provider server status {status}")
        if status == 400:
            body = response.text.lower()[:3000]
            # Gemini's OpenAI-compatible endpoint reports an invalid API key as
            # HTTP 400/INVALID_ARGUMENT rather than 401. Treat that response as
            # key-local so a bad key cannot disable a healthy model route.
            if any(
                marker in body
                for marker in (
                    "please pass a valid api key",
                    "api key not valid",
                    "api_key_invalid",
                    "invalid api key",
                )
            ):
                raise RouteFailure(
                    RouteFailureCategory.INVALID_KEY,
                    "provider authentication rejected",
                )
            if any(marker in body for marker in ("model not found", "invalid model", "unknown model", "does not exist")):
                raise RouteFailure(RouteFailureCategory.INVALID_MODEL, "provider rejected model identifier")
            if any(marker in body for marker in ("unsupported parameter", "unknown parameter", "temperature is not supported")):
                raise RouteFailure(RouteFailureCategory.UNSUPPORTED_PARAMETER, "provider rejected request parameter")
            if any(marker in body for marker in ("context length", "too many tokens", "maximum context")):
                raise RouteFailure(RouteFailureCategory.CONTEXT_LENGTH, "provider context limit exceeded")
            if any(
                marker in body
                for marker in (
                    "user location is not supported",
                    "location is not supported for the api use",
                )
            ):
                raise RouteFailure(
                    RouteFailureCategory.POLICY_REJECTION,
                    "provider location policy rejected request",
                )
            raise RouteFailure(RouteFailureCategory.UNKNOWN, "provider rejected bounded request")
        if status in {409, 422, 451}:
            raise RouteFailure(RouteFailureCategory.POLICY_REJECTION, "provider policy rejection")
        if status == 404:
            raise RouteFailure(
                RouteFailureCategory.INVALID_MODEL,
                "provider rejected model identifier",
            )
        if status < 200 or status >= 300:
            raise RouteFailure(RouteFailureCategory.UNKNOWN, f"unexpected provider status {status}")

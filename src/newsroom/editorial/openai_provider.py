"""OpenAI-compatible editorial provider adapter.

Configurable base URL, model, API key from environment only.
Structured output via JSON mode or validated JSON response.
No vendor-specific types outside this adapter.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from newsroom.editorial.prompt import build_prompt
from newsroom.editorial.provider import EditorialProvider, time_ms
from newsroom.editorial.schema import (
    EditorialError,
    EditorialErrorCategory,
    EditorialOutput,
    EditorialRequest,
    EditorialResponse,
)


class OpenAICompatibleEditorialProvider(EditorialProvider):
    """OpenAI-compatible chat completions adapter.

    Works with any endpoint that accepts the OpenAI /chat/completions schema.
    API key is read only from the environment — never logged.
    """

    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 60,
        max_retries: int = 2,
        temperature: float = 0.3,
        max_output_tokens: int = 4000,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens

    @property
    def name(self) -> str:
        return "openai_compatible"

    @property
    def model_name(self) -> str:
        return self._model

    def generate(self, request: EditorialRequest) -> EditorialResponse:
        """Synchronous wrapper — runs async generation in event loop."""
        return asyncio.run(self._generate_async(request))

    async def _generate_async(self, request: EditorialRequest) -> EditorialResponse:
        """Generate with bounded retries on transient errors."""
        messages = build_prompt(request.evidence)
        last_error: EditorialError | None = None
        retry_count = 0

        for attempt in range(self._max_retries + 1):
            start = time.monotonic()
            try:
                result = await self._call_api(messages, request)
                result.retry_count = retry_count
                result.latency_ms = time_ms(start)
                return result
            except EditorialError as e:
                last_error = e
                if not e.retryable or attempt >= self._max_retries:
                    raise
                retry_count += 1
                delay = min(2.0 * (2**attempt), 30.0)
                await asyncio.sleep(delay)

        raise last_error or EditorialError(
            EditorialErrorCategory.UNKNOWN, "max retries exhausted", retryable=False
        )

    async def _call_api(
        self,
        messages: list[dict[str, str]],
        request: EditorialRequest,
    ) -> EditorialResponse:
        """Call the OpenAI-compatible chat completions endpoint."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=15.0),
            ) as client:
                resp = await client.post(
                    f"{self._api_base}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.TimeoutException as e:
            raise EditorialError(
                EditorialErrorCategory.TIMEOUT,
                str(e)[:200],
                retryable=True,
            ) from e
        except httpx.ConnectError as e:
            raise EditorialError(
                EditorialErrorCategory.NETWORK_ERROR,
                str(e)[:200],
                retryable=True,
            ) from e
        except httpx.HTTPError as e:
            raise EditorialError(
                EditorialErrorCategory.NETWORK_ERROR,
                str(e)[:200],
                retryable=True,
            ) from e

        if resp.status_code == 401:
            raise EditorialError(
                EditorialErrorCategory.INVALID_API_KEY,
                "authentication failed",
                retryable=False,
            )
        if resp.status_code == 429:
            raise EditorialError(
                EditorialErrorCategory.RATE_LIMIT,
                "rate limited",
                retryable=True,
            )
        if resp.status_code >= 500:
            raise EditorialError(
                EditorialErrorCategory.PROVIDER_UNAVAILABLE,
                f"server error {resp.status_code}",
                retryable=True,
            )

        if resp.status_code != 200:
            raise EditorialError(
                EditorialErrorCategory.UNKNOWN,
                f"unexpected status {resp.status_code}: {resp.text[:200]}",
                retryable=False,
            )

        try:
            data = resp.json()
        except Exception as e:
            raise EditorialError(
                EditorialErrorCategory.MALFORMED_RESPONSE,
                f"JSON parse failed: {e}",
                retryable=False,
            ) from e

        # Extract content
        try:
            choices = data.get("choices", [])
            if not choices:
                raise EditorialError(
                    EditorialErrorCategory.PARTIAL_RESPONSE,
                    "no choices in response",
                    retryable=False,
                )
            content = choices[0].get("message", {}).get("content", "")
            if not content:
                raise EditorialError(
                    EditorialErrorCategory.PARTIAL_RESPONSE,
                    "empty content",
                    retryable=False,
                )
            finish_reason = choices[0].get("finish_reason", "stop")
        except (KeyError, IndexError) as e:
            raise EditorialError(
                EditorialErrorCategory.MALFORMED_RESPONSE,
                f"missing choices: {e}",
                retryable=False,
            ) from e

        # Map finish reason
        finish_status = "stop"
        if finish_reason == "length":
            finish_status = "length"
        elif finish_reason == "content_filter":
            finish_status = "refusal"
            raise EditorialError(
                EditorialErrorCategory.SAFETY_REFUSAL,
                "content filtered by safety system",
                retryable=False,
            )

        # Parse the JSON content into EditorialOutput
        try:
            output_dict = json.loads(content)
        except json.JSONDecodeError as e:
            raise EditorialError(
                EditorialErrorCategory.MALFORMED_RESPONSE,
                f"output JSON parse failed: {e}",
                retryable=False,
            ) from e

        # Enforce evidence_set_hash and metadata from our side
        output_dict.setdefault("metadata", {})
        output_dict["metadata"]["evidence_set_hash"] = request.evidence.evidence_hash()
        output_dict["metadata"]["prompt_version"] = (
            output_dict["metadata"].get("prompt_version")
            or request.evidence.prompt_version
        )
        output_dict["metadata"]["provider"] = self.name
        output_dict["metadata"]["model_name"] = self._model

        try:
            output = EditorialOutput.model_validate(output_dict)
        except Exception as e:
            raise EditorialError(
                EditorialErrorCategory.SCHEMA_VALIDATION,
                f"output schema validation failed: {e}",
                retryable=False,
            ) from e

        usage = data.get("usage")
        usage_dict = None
        if usage:
            usage_dict = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }

        return EditorialResponse(
            output=output,
            model=self._model,
            provider=self.name,
            latency_ms=0,  # set by caller
            finish_status=finish_status,
            usage=usage_dict,
            retry_count=0,
            fallback_used=False,
        )


def create_provider_from_settings() -> OpenAICompatibleEditorialProvider | None:
    """Factory: create provider from environment settings. Returns None if no key."""
    from newsroom.config import settings

    if not settings.editorial_api_key or not settings.editorial_model:
        return None
    return OpenAICompatibleEditorialProvider(
        api_base=settings.editorial_api_base,
        api_key=settings.editorial_api_key,
        model=settings.editorial_model,
        timeout_seconds=settings.editorial_timeout_seconds,
        max_retries=settings.editorial_max_retries,
        temperature=settings.editorial_temperature,
        max_output_tokens=settings.editorial_max_output_tokens,
    )

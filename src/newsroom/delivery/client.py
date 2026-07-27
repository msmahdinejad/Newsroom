"""Telegram Bot API client — error classification, bounded retries, redaction.

Never logs the token. Classifies errors into categories for retry decisions.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Any

import httpx

from newsroom.config import settings
from newsroom.logging import get_logger

logger = get_logger(__name__)

TG_API = "https://api.telegram.org/bot{token}"
TG_FILE_API = "https://api.telegram.org/file/bot{token}/{path}"


class ErrorCategory(StrEnum):
    """Classified error categories for retry decisions."""

    INVALID_TOKEN = "invalid_token"
    UNAUTHORIZED = "unauthorized"
    RATE_LIMITED = "rate_limited"  # 429
    NETWORK_TIMEOUT = "network_timeout"
    SERVER_ERROR = "server_error"  # 5xx
    MALFORMED_RESPONSE = "malformed_response"
    BLOCKED_BOT = "blocked_bot"
    CHAT_NOT_FOUND = "chat_not_found"
    MESSAGE_TOO_LONG = "message_too_long"
    INVALID_FORMATTING = "invalid_formatting"
    DUPLICATE_UPDATE = "duplicate_update"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


# Categories that should NOT be retried
PERMANENT_ERRORS = frozenset({
    ErrorCategory.INVALID_TOKEN,
    ErrorCategory.UNAUTHORIZED,
    ErrorCategory.BLOCKED_BOT,
    ErrorCategory.CHAT_NOT_FOUND,
    ErrorCategory.MESSAGE_TOO_LONG,
    ErrorCategory.INVALID_FORMATTING,
    ErrorCategory.DUPLICATE_UPDATE,
})


class TelegramAPIError(Exception):
    """Classified Telegram API error."""

    def __init__(self, category: ErrorCategory, detail: str, status_code: int | None = None) -> None:
        self.category = category
        self.detail = detail
        self.status_code = status_code
        super().__init__(f"[{category.value}] {detail}")

    @property
    def retryable(self) -> bool:
        return self.category not in PERMANENT_ERRORS


class TelegramBotClient:
    """Async Bot API client with error classification and bounded retries."""

    def __init__(
        self,
        token: str | None = None,
        *,
        max_retries: int | None = None,
        base_delay: float | None = None,
    ) -> None:
        self.token = token or settings.telegram_bot_token
        self.max_retries = max_retries if max_retries is not None else settings.telegram_max_retries
        self.base_delay = base_delay if base_delay is not None else settings.telegram_retry_base_delay
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15, read=60, write=30, pool=30),
        )

    def _api_url(self, method: str) -> str:
        return f"{TG_API.format(token=self.token)}/{method}"

    def _classify_http_error(self, e: httpx.HTTPStatusError) -> TelegramAPIError:
        status = e.response.status_code
        body = ""
        try:
            body = e.response.json().get("description", e.response.text[:200])
        except Exception:
            body = e.response.text[:200] if e.response.text else ""

        if status == 401:
            return TelegramAPIError(ErrorCategory.INVALID_TOKEN, body, status)
        if status == 403:
            if "blocked" in body.lower() or "bot was blocked" in body.lower():
                return TelegramAPIError(ErrorCategory.BLOCKED_BOT, body, status)
            return TelegramAPIError(ErrorCategory.UNAUTHORIZED, body, status)
        if status == 429:
            return TelegramAPIError(ErrorCategory.RATE_LIMITED, body, status)
        if status == 400:
            low = body.lower()
            if "chat not found" in low:
                return TelegramAPIError(ErrorCategory.CHAT_NOT_FOUND, body, status)
            if "message is too long" in low:
                return TelegramAPIError(ErrorCategory.MESSAGE_TOO_LONG, body, status)
            if "can't parse entities" in low or "bad request" in low:
                return TelegramAPIError(ErrorCategory.INVALID_FORMATTING, body, status)
            return TelegramAPIError(ErrorCategory.INVALID_FORMATTING, body, status)
        if 500 <= status < 600:
            return TelegramAPIError(ErrorCategory.SERVER_ERROR, body, status)
        return TelegramAPIError(ErrorCategory.UNKNOWN, body, status)

    def _classify_exception(self, e: Exception) -> TelegramAPIError:
        if isinstance(e, httpx.ConnectTimeout | httpx.ReadTimeout | httpx.PoolTimeout):
            return TelegramAPIError(ErrorCategory.NETWORK_TIMEOUT, str(e)[:200])
        if isinstance(e, httpx.ConnectError):
            return TelegramAPIError(ErrorCategory.NETWORK_TIMEOUT, str(e)[:200])
        if isinstance(e, httpx.HTTPStatusError):
            return self._classify_http_error(e)
        return TelegramAPIError(ErrorCategory.UNKNOWN, str(e)[:200])

    async def call(
        self,
        method: str,
        *,
        json: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        """Call a Bot API method with bounded retry on transient errors."""
        last_error: TelegramAPIError | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.post(self._api_url(method), json=json)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
                if not data.get("ok"):
                    desc = data.get("description", "unknown")
                    # "Conflict: terminated by other getUpdates request" = duplicate poller
                    if "conflict" in desc.lower():
                        return data  # handle at caller level
                    raise TelegramAPIError(
                        ErrorCategory.MALFORMED_RESPONSE,
                        f"ok=false: {desc}",
                    )
                return data
            except httpx.HTTPStatusError as e:
                err = self._classify_http_error(e)
                last_error = err
                if not err.retryable or not retry:
                    logger.error(f"Telegram API {method} failed: {err.category.value} ({err.status_code})")
                    raise err from e
            except httpx.TimeoutException as e:
                err = self._classify_exception(e)
                last_error = err
                if not retry:
                    raise err from e
            except httpx.ConnectError as e:
                err = self._classify_exception(e)
                last_error = err
                if not retry:
                    raise err from e
            except TelegramAPIError:
                raise
            except Exception as e:
                err = self._classify_exception(e)
                last_error = err
                if not err.retryable or not retry:
                    raise err from e

            # Backoff: base * 2^attempt, capped at 30s
            delay = min(self.base_delay * (2**attempt), 30.0)
            logger.warning(
                f"Telegram API {method} attempt {attempt + 1} failed: "
                f"{last_error.category.value if last_error else 'unknown'}, retrying in {delay:.1f}s"
            )
            await asyncio.sleep(delay)

        raise last_error or TelegramAPIError(ErrorCategory.UNKNOWN, "max retries exhausted")

    async def get_me(self) -> dict[str, Any]:
        """Get bot identity. Used for health checks."""
        return await self.call("getMe", retry=False)

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool = True,
        reply_markup: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        """Send a message. Returns full API response including message_id."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("sendMessage", json=payload, retry=retry)

    async def answer_callback_query(self, callback_query_id: str) -> dict[str, Any]:
        return await self.call(
            "answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
            retry=False,
        )

    async def get_updates(self, offset: int, timeout: int | None = None) -> dict[str, Any]:
        return await self.call(
            "getUpdates",
            json={"offset": offset, "timeout": timeout or settings.telegram_poll_timeout},
            retry=False,
        )

    async def delete_webhook(self) -> dict[str, Any]:
        return await self.call("deleteWebhook", retry=False)

    async def set_my_commands(
        self,
        commands: list[dict[str, str]],
    ) -> dict[str, Any]:
        return await self.call(
            "setMyCommands",
            json={"commands": commands},
            retry=False,
        )

    async def download_file(self, file_id: str, *, max_bytes: int) -> bytes:
        """Download one bounded Bot API file without logging its protected URL."""
        metadata = await self.call(
            "getFile",
            json={"file_id": file_id},
            retry=False,
        )
        file_path = str(metadata.get("result", {}).get("file_path") or "")
        if not file_path or ".." in file_path:
            raise TelegramAPIError(
                ErrorCategory.MALFORMED_RESPONSE,
                "getFile returned an invalid file path",
            )
        try:
            async with self.client.stream(
                "GET",
                TG_FILE_API.format(token=self.token, path=file_path),
            ) as response:
                response.raise_for_status()
                declared_size = int(response.headers.get("content-length") or 0)
                if declared_size > max_bytes:
                    raise ValueError("Telegram file exceeds configured size limit")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise ValueError("Telegram file exceeds configured size limit")
                return bytes(content)
        except ValueError:
            raise
        except Exception as exc:
            raise self._classify_exception(exc) from exc

    async def close(self) -> None:
        await self.client.aclose()


def redact_token(_token: str | None = None) -> str:
    """Never show Token or Token fragments in logs, health, or evidence."""
    return "[REDACTED]"

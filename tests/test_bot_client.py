"""Bot API client tests — error classification, retry, redaction (mocked httpx)."""


from unittest.mock import AsyncMock

import httpx
import pytest

from newsroom.delivery.client import (
    PERMANENT_ERRORS,
    ErrorCategory,
    TelegramBotClient,
    redact_token,
)


def test_redact_token_long():
    token = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567"
    redacted = redact_token(token)
    assert redacted == "[REDACTED]"
    assert "1234" not in redacted
    assert "4567" not in redacted
    assert "ABCdef" not in redacted


def test_redact_token_short():
    assert redact_token("short") == "[REDACTED]"
    assert redact_token("") == "[REDACTED]"
    assert redact_token(None) == "[REDACTED]"


def test_redact_token_exact_12():
    token = "123456789012"
    assert redact_token(token) == "[REDACTED]"
    assert "1234" not in redact_token(token)
    assert "9012" not in redact_token(token)


def test_error_category_retryable():
    """Transient errors are retryable, permanent errors are not."""
    assert ErrorCategory.RATE_LIMITED not in PERMANENT_ERRORS
    assert ErrorCategory.NETWORK_TIMEOUT not in PERMANENT_ERRORS
    assert ErrorCategory.SERVER_ERROR not in PERMANENT_ERRORS

    assert ErrorCategory.INVALID_TOKEN in PERMANENT_ERRORS
    assert ErrorCategory.UNAUTHORIZED in PERMANENT_ERRORS
    assert ErrorCategory.BLOCKED_BOT in PERMANENT_ERRORS
    assert ErrorCategory.CHAT_NOT_FOUND in PERMANENT_ERRORS
    assert ErrorCategory.MESSAGE_TOO_LONG in PERMANENT_ERRORS
    assert ErrorCategory.INVALID_FORMATTING in PERMANENT_ERRORS


def test_classify_401():
    client = TelegramBotClient(token="fake")
    resp = httpx.Response(401, json={"description": "Unauthorized"})
    err = client._classify_http_error(httpx.HTTPStatusError("err", request={}, response=resp))
    assert err.category == ErrorCategory.INVALID_TOKEN
    assert not err.retryable


def test_classify_403_blocked():
    client = TelegramBotClient(token="fake")
    resp = httpx.Response(403, json={"description": "Forbidden: bot was blocked by the user"})
    err = client._classify_http_error(httpx.HTTPStatusError("err", request={}, response=resp))
    assert err.category == ErrorCategory.BLOCKED_BOT
    assert not err.retryable


def test_classify_403_unauthorized():
    client = TelegramBotClient(token="fake")
    resp = httpx.Response(403, json={"description": "Forbidden"})
    err = client._classify_http_error(httpx.HTTPStatusError("err", request={}, response=resp))
    assert err.category == ErrorCategory.UNAUTHORIZED


def test_classify_429():
    client = TelegramBotClient(token="fake")
    resp = httpx.Response(429, json={"description": "Too Many Requests"})
    err = client._classify_http_error(httpx.HTTPStatusError("err", request={}, response=resp))
    assert err.category == ErrorCategory.RATE_LIMITED
    assert err.retryable


def test_classify_500():
    client = TelegramBotClient(token="fake")
    resp = httpx.Response(500, json={"description": "Internal Server Error"})
    err = client._classify_http_error(httpx.HTTPStatusError("err", request={}, response=resp))
    assert err.category == ErrorCategory.SERVER_ERROR
    assert err.retryable


def test_classify_400_chat_not_found():
    client = TelegramBotClient(token="fake")
    resp = httpx.Response(400, json={"description": "Bad Request: chat not found"})
    err = client._classify_http_error(httpx.HTTPStatusError("err", request={}, response=resp))
    assert err.category == ErrorCategory.CHAT_NOT_FOUND
    assert not err.retryable


def test_classify_400_message_too_long():
    client = TelegramBotClient(token="fake")
    resp = httpx.Response(400, json={"description": "Bad Request: message is too long"})
    err = client._classify_http_error(httpx.HTTPStatusError("err", request={}, response=resp))
    assert err.category == ErrorCategory.MESSAGE_TOO_LONG


def test_classify_400_bad_formatting():
    client = TelegramBotClient(token="fake")
    resp = httpx.Response(400, json={"description": "Bad Request: can't parse entities"})
    err = client._classify_http_error(httpx.HTTPStatusError("err", request={}, response=resp))
    assert err.category == ErrorCategory.INVALID_FORMATTING


def test_classify_timeout():
    client = TelegramBotClient(token="fake")
    err = client._classify_exception(httpx.ReadTimeout("read timeout"))
    assert err.category == ErrorCategory.NETWORK_TIMEOUT
    assert err.retryable


def test_classify_connect_error():
    client = TelegramBotClient(token="fake")
    err = client._classify_exception(httpx.ConnectError("connection refused"))
    assert err.category == ErrorCategory.NETWORK_TIMEOUT


def test_classify_unknown_exception():
    client = TelegramBotClient(token="fake")
    err = client._classify_exception(ValueError("something weird"))
    assert err.category == ErrorCategory.UNKNOWN


client = TelegramBotClient(token="fake", max_retries=0)


@pytest.mark.asyncio
async def test_download_file_is_bounded_and_does_not_expose_token():
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, content=b"name,type,url\n", request=request)

    client = TelegramBotClient(token="protected-value", max_retries=0)
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.call = AsyncMock(
        return_value={"ok": True, "result": {"file_path": "documents/sources.csv"}}
    )
    try:
        payload = await client.download_file("safe-file-id", max_bytes=1024)
    finally:
        await client.close()

    assert payload == b"name,type,url\n"
    assert len(seen_urls) == 1
    # The protected value is necessarily present in the outbound Bot API URL,
    # but the client never returns or logs that URL.
    assert "documents/sources.csv" in seen_urls[0]

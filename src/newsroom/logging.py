"""Structured logging with correlation IDs and secret redaction."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from newsroom.config import settings

# Patterns redacted from every log message. The Telegram Bot API embeds the
# bot token in the request URL; httpx logs that URL, so we scrub it here.
_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(?:https?|socks5h?)://[^/\s:@]+:[^@/\s]+@"),
    re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}"),  # Telegram bot token in URLs
    re.compile(r"(?i)(api[_-]?key|token|password|secret|auth)[=:]\s*[^\s&\"']+"),
    re.compile(r"Bearer\s+[A-Za-z0-9_.\-]+"),
)
_PROXY_URL_PATTERN = re.compile(
    r"(?i)\b(proxy|via)\s+(?:https?|socks5h?)://[^\s\]\[\"']+"
)


def redact(message: str) -> str:
    """Redact known secret patterns from a log message."""
    configured_proxy = settings.telegram_proxy_url.strip()
    if configured_proxy:
        message = message.replace(configured_proxy, "***")
    message = _PROXY_URL_PATTERN.sub(r"\1 ***", message)
    for pat in _REDACT_PATTERNS:
        message = pat.sub("***", message)
    return message


class RedactingFilter(logging.Filter):
    """Filter that redacts secrets from log records before emission."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


class JsonFormatter(logging.Formatter):
    """Format logs as JSON with timezone-aware timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        if hasattr(record, "correlation_id"):
            log_data["correlation_id"] = record.correlation_id
        if record.exc_info:
            log_data["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(log_data, default=str, ensure_ascii=False)


def setup_logging() -> None:
    """Configure logging based on settings."""
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
    handler.addFilter(RedactingFilter())
    logging.root.setLevel(settings.log_level)
    # Avoid duplicate handlers on re-init
    if not logging.root.handlers:
        logging.root.addHandler(handler)
    else:
        for h in logging.root.handlers:
            if RedactingFilter() not in h.filters:
                h.addFilter(RedactingFilter())
    # Also silence httpx request-URL INFO noise (and token leakage) by default.
    for noisy in ("httpx", "telethon", "httpcore"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, logging.getLevelName(settings.log_level)))


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)

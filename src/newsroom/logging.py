"""Structured logging with correlation IDs."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from newsroom.config import settings


class JsonFormatter(logging.Formatter):
    """Format logs as JSON with timezone-aware timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        if hasattr(record, "correlation_id"):
            log_data["correlation_id"] = record.correlation_id
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
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
    logging.root.setLevel(settings.log_level)
    # Avoid duplicate handlers on re-init
    if not logging.root.handlers:
        logging.root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)

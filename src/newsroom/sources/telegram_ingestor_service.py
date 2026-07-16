"""Idle MTProto ingestor service — disabled without credentials (Gate 1)."""

from __future__ import annotations

import json
import time

from newsroom.logging import get_logger, setup_logging
from newsroom.service_status import telegram_ingestor_status

logger = get_logger(__name__)


def main() -> None:
    setup_logging()
    status = telegram_ingestor_status()
    try:
        with open("/tmp/newsroom_ingestor_status.json", "w", encoding="utf-8") as f:
            json.dump(status, f)
    except OSError:
        pass
    if status["status"] != "enabled":
        logger.info(f"Telegram ingestor {status['status']} — idle (no MTProto auth)")
        while True:
            time.sleep(3600)
        return
    # Gate 1: never activate live MTProto even if flags set without explicit Gate 2 work
    logger.warning(
        "TELEGRAM_INGESTOR_ENABLED=true but Gate 1 keeps ingestor idle; enable in Gate 2"
    )
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()

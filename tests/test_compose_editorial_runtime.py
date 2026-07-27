"""Production Compose wiring for editorial generation."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_telegram_bot_receives_editorial_runtime_configuration() -> None:
    compose = yaml.safe_load((REPO_ROOT / "compose.yaml").read_text(encoding="utf-8"))
    environment = compose["services"]["telegram-bot"]["environment"]

    assert "EDITORIAL_ENABLED" in environment
    assert "EDITORIAL_TIMEOUT_SECONDS" in environment
    assert "EDITORIAL_MAX_INPUT_TOKENS" in environment
    assert "EDITORIAL_MAX_OUTPUT_TOKENS" in environment
    assert "EDITORIAL_MAX_STORIES_PER_CALL" in environment
    assert environment["LLM_PROVIDER_ENV_FILE"] == "/run/newsroom/.env.providers.local"

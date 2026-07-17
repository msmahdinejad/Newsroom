"""Configuration management using pydantic-settings."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    if v is None or v == "":
        return False
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseSettings):
    """Application settings from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://newsroom:newsroom_dev@127.0.0.1:55432/newsroom"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Collection
    collection_timeout_connect: int = 30
    collection_timeout_read: int = 60
    collection_max_size_mb: int = 2
    collection_user_agent: str = "newsroom/2.0"

    # Processing
    dedup_time_window_hours: int = 24
    cluster_keyword_threshold: float = 0.35

    # Report schedules (Asia/Tehran = UTC+3:30)
    schedule_morning: str = "09:00"
    schedule_afternoon: str = "15:00"
    schedule_evening: str = "21:00"
    timezone: str = "Asia/Tehran"

    # Manual report cooldown (seconds)
    manual_cooldown_seconds: int = 600

    # Telegram output bot
    telegram_bot_token: str = ""  # env: TELEGRAM_BOT_TOKEN
    telegram_authorized_user_ids: str = ""  # comma-separated numeric Telegram user IDs
    telegram_chat_id: str = ""  # default delivery chat
    # Feature flags — false = no network auth, stable idle, honest health
    telegram_bot_enabled: bool = False
    telegram_ingestor_enabled: bool = False

    # Gate 2: delivery config
    telegram_chunk_size: int = 3800  # safe below 4096 limit
    telegram_parse_mode: str = "HTML"  # HTML for safe entity escaping
    telegram_poll_timeout: int = 30  # long-poll seconds
    telegram_max_retries: int = 3  # bounded retry for transient errors
    telegram_retry_base_delay: float = 1.0  # base backoff seconds
    telegram_test_chat_id: str = ""  # optional explicit test chat

    # Telegram MTProto (source collector — Gate 3, not Gate 2)
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    telegram_phone: str = ""
    telegram_session_path: str = "./data/sessions/newsroom_ingestor.session"

    # Pipeline lock timeout (seconds) — advisory lock is session-held; timeout is soft doc
    pipeline_lock_timeout: int = 300

    # Gate 4: AI editorial layer
    editorial_enabled: bool = False
    editorial_provider: str = "deterministic"  # deterministic | openai_compatible
    editorial_model: str = ""
    editorial_api_base: str = "https://api.openai.com/v1"
    editorial_api_key: str = ""  # env: EDITORIAL_API_KEY — never logged
    editorial_timeout_seconds: int = 60
    editorial_max_retries: int = 2
    editorial_max_input_tokens: int = 12000
    editorial_max_output_tokens: int = 4000
    editorial_temperature: float = 0.3
    editorial_fallback_enabled: bool = True
    editorial_max_stories_per_call: int = 15
    editorial_max_evidence_per_story: int = 10
    editorial_max_excerpt_length: int = 300
    editorial_concurrency_limit: int = 1
    editorial_scheduled_run_budget: int = 1
    editorial_manual_run_budget: int = 3

    # Retention
    raw_retention_days: int = 30
    normalized_retention_days: int = 90

    @field_validator(
        "telegram_bot_enabled",
        "telegram_ingestor_enabled",
        "editorial_enabled",
        "editorial_fallback_enabled",
        mode="before",
    )
    @classmethod
    def parse_bool(cls, v: object) -> bool:
        return _env_bool(v)

    def authorized_user_ids(self) -> set[int]:
        """Parse comma-separated numeric IDs into a set. Empty/malformed = empty set (deny all)."""
        raw = self.telegram_authorized_user_ids.strip()
        if not raw:
            return set()
        ids: set[int] = set()
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.add(int(part))
            except ValueError:
                # malformed entry — skip it (deny that ID)
                continue
        return ids

    def telegram_bot_ready(self) -> bool:
        return bool(self.telegram_bot_enabled and self.telegram_bot_token)

    def telegram_ingestor_ready(self) -> bool:
        return bool(
            self.telegram_ingestor_enabled
            and self.telegram_api_id
            and self.telegram_api_hash
            and self.telegram_phone
        )

    def editorial_ready(self) -> bool:
        """True only when editorial is enabled AND a non-deterministic provider has credentials."""
        return bool(
            self.editorial_enabled
            and self.editorial_provider != "deterministic"
            and self.editorial_api_key
            and self.editorial_model
        )


settings = Settings()

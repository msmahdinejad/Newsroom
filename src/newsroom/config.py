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
    collection_user_agent: str = "newsroom/3.0"
    collection_proxy_url: str = ""

    # Processing
    dedup_time_window_hours: int = 24
    cluster_keyword_threshold: float = 0.35
    processing_batch_size: int = 500
    processing_loop_seconds: int = 60
    # Process this platform first when it has a backlog. Empty disables priority.
    processing_priority_source_type: str = "telegram"

    # Report schedules (Asia/Tehran = UTC+3:30)
    schedule_morning: str = "09:00"
    schedule_afternoon: str = "15:00"
    schedule_evening: str = "21:00"
    timezone: str = "Asia/Tehran"

    # Production: six-hour reporting cadence (00/06/12/18 Tehran). The four
    # scheduled jobs are registered in newsroom.scheduler with these hours.
    schedule_report_hours: str = "0,6,12,18"

    # Production: safe per-platform collection intervals (seconds).
    # Telegram/X: frequent incremental; RSS: conditional; websites: conservative;
    # GitHub: release polling; YouTube: channel incremental; Reddit/forums: bounded.
    collect_interval_telegram_seconds: int = 300
    collect_interval_x_seconds: int = 1800
    collect_interval_rss_seconds: int = 900
    collect_interval_web_seconds: int = 3600
    collect_interval_github_seconds: int = 1800
    collect_interval_youtube_seconds: int = 1200
    collect_interval_reddit_seconds: int = 900
    # Bounded concurrency across sources during one collection pass.
    collect_concurrency: int = 4
    # Bounded backfill window per source per pass.
    collect_limit_per_source: int = 10
    # Bounded fair batch per stateless collector cycle.
    collect_max_sources_per_cycle: int = 20
    # Minimum delay between stateless source request starts.
    collect_source_spacing_seconds: float = 1.0
    # Retry delay base with jitter (seconds). Exponential backoff + jitter.
    collect_retry_base_delay_seconds: float = 5.0
    collect_retry_max_delay_seconds: float = 3600.0
    # Soak-test bounds.
    soak_max_cycles: int = 3
    soak_cycle_pause_seconds: int = 2

    # Manual report cooldown (seconds)
    manual_cooldown_seconds: int = 600

    # Telegram output bot
    telegram_bot_token: str = ""  # env: TELEGRAM_BOT_TOKEN
    telegram_authorized_user_ids: str = ""  # comma-separated numeric Telegram user IDs
    telegram_chat_id: str = ""  # default delivery chat
    # Feature flags — false = no network auth, stable idle, honest health
    telegram_bot_enabled: bool = False
    telegram_ingestor_enabled: bool = False

    # Delivery: delivery config
    telegram_chunk_size: int = 3800  # safe below 4096 limit
    telegram_parse_mode: str = "HTML"  # HTML for safe entity escaping
    telegram_poll_timeout: int = 30  # long-poll seconds
    telegram_max_retries: int = 3  # bounded retry for transient errors
    telegram_retry_base_delay: float = 1.0  # base backoff seconds
    telegram_test_chat_id: str = ""  # optional explicit test chat

    # Telegram MTProto (source collector — MTProto, not Delivery)
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    telegram_phone: str = ""
    telegram_session_path: str = "./data/sessions/newsroom_ingestor.session"
    # Bounded MTProto connection and optional owner-configured transport.
    telegram_connect_timeout_seconds: int = 12
    telegram_connection_retries: int = 1
    telegram_retry_delay_seconds: int = 2
    telegram_reconnect_cooldown_seconds: int = 300
    telegram_max_sources_per_cycle: int = 20
    telegram_source_spacing_seconds: float = 1.0
    telegram_proxy_url: str = ""
    telegram_proxy_type: str = ""
    telegram_connection_mode: str = "direct"
    telegram_mtproxy_host: str = ""
    telegram_mtproxy_port: int = 0
    telegram_mtproxy_secret: str = ""

    # Pipeline lock timeout (seconds) — advisory lock is session-held; timeout is soft doc
    pipeline_lock_timeout: int = 300

    # Editorial: AI editorial layer
    editorial_enabled: bool = False
    editorial_timeout_seconds: int = 60
    editorial_max_retries: int = 2
    editorial_max_input_tokens: int = 12000
    editorial_max_output_tokens: int = 8000
    editorial_temperature: float = 0.3
    editorial_fallback_enabled: bool = True
    editorial_max_stories_per_call: int = 15
    editorial_max_evidence_per_story: int = 10
    editorial_max_excerpt_length: int = 300
    editorial_min_telegram_stories: int = 2
    editorial_concurrency_limit: int = 1
    editorial_scheduled_run_budget: int = 1
    editorial_manual_run_budget: int = 3

    # Editorial scalable: hierarchical editorial controls
    editorial_max_stories_per_shard: int = 8
    editorial_max_map_calls_per_report: int = 12
    editorial_max_reduction_calls_per_report: int = 4
    editorial_max_hierarchy_depth: int = 3
    editorial_max_concurrent_map: int = 2
    editorial_max_total_input_tokens_per_report: int = 100000
    editorial_max_total_output_tokens_per_report: int = 30000
    editorial_shard_input_token_limit: int = 8000
    editorial_shard_output_token_limit: int = 4000
    editorial_max_pending_jobs: int = 3
    editorial_stale_job_timeout_seconds: int = 600

    # Social collection: Agent-Reach capability layer (external internet/social platforms)
    # Agent-Reach is a capability-selection, diagnostics, and backend-routing layer.
    # Newsroom owns source config, cursors, retries, normalization, persistence, and security.
    agent_reach_enabled: bool = False
    agent_reach_executable: str = "agent-reach"  # resolved from PATH or absolute
    agent_reach_config_dir: str = "./data/agent-reach"  # isolated writable config dir
    agent_reach_timeout_seconds: int = 60  # per-call timeout
    agent_reach_max_output_bytes: int = 2 * 1024 * 1024  # 2 MiB stdout/stderr cap
    agent_reach_max_retries: int = 1
    agent_reach_concurrency_limit: int = 2  # bounded parallel upstream calls
    # Channel allowlist — comma-separated. Empty = all known channels (with safe defaults).
    agent_reach_allowed_channels: str = "web,rss,github,youtube"
    agent_reach_pinned_version: str = ""  # required for production; pinned revision
    # Allow authenticated channels (cookies/tokens). Default false — owner must opt in.
    agent_reach_allow_authenticated_channels: bool = False
    agent_reach_health_interval_seconds: int = 300  # min seconds between doctor runs
    x_worker_poll_seconds: int = 900
    x_worker_batch_size: int = 12
    x_worker_spacing_seconds: float = 2.0

    # Retention
    raw_retention_days: int = 30
    normalized_retention_days: int = 90

    @field_validator(
        "telegram_bot_enabled",
        "telegram_ingestor_enabled",
        "editorial_enabled",
        "editorial_fallback_enabled",
        "agent_reach_enabled",
        "agent_reach_allow_authenticated_channels",
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
        """Return the non-secret feature flag; route readiness lives in PostgreSQL."""
        return self.editorial_enabled

    def agent_reach_allowed_channels_set(self) -> set[str]:
        """Parse comma-separated channel allowlist. Empty entries skipped.

        Order preserved by the caller; empty string yields empty set (deny all
        upstream Agent-Reach channels) — production safety default.
        """
        raw = self.agent_reach_allowed_channels.strip()
        if not raw:
            return set()
        result: set[str] = set()
        for part in raw.split(","):
            channel = part.strip().lower()
            if channel:
                result.add(channel)
        return result

    def agent_reach_ready(self) -> bool:
        """True only when Agent-Reach is enabled AND a pinned version is recorded."""
        return bool(self.agent_reach_enabled and self.agent_reach_pinned_version)


settings = Settings()

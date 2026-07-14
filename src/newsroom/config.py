"""Configuration management using pydantic-settings."""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    telegram_authorized_users: str = ""  # comma-separated numeric IDs
    telegram_chat_id: str = ""  # default delivery chat

    # Telegram MTProto (source collector)
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    telegram_phone: str = ""
    telegram_session_dir: str = "./data/sessions"

    # Pipeline lock timeout (seconds)
    pipeline_lock_timeout: int = 300

    # Retention
    raw_retention_days: int = 30
    normalized_retention_days: int = 90


settings = Settings()

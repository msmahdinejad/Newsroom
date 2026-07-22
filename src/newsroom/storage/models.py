"""SQLAlchemy database models — V2 schema authority.

All timestamps are timezone-aware UTC. JSON fields use JSONB for query efficiency.
No raw secrets stored — only references to external secret storage.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Timezone-aware UTC now — replaces deprecated datetime.utcnow."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


# ── Source registry ──────────────────────────────────────────────

class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # rss, github_releases, telegram, youtube
    url: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en")
    category: Mapped[str] = mapped_column(String(100), default="general")
    trust_class: Mapped[str] = mapped_column(String(30), default="reputable")  # official/primary/reputable/community/aggregator
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)  # adapter-specific config

    # Gate 6: workbook linkage + stable identity (independent of display name).
    # stable_identity is a deterministic hash of (platform, normalized handle/URL)
    # so a source survives handle renames and duplicate display names.
    stable_identity: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    workbook_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    platform: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    inactive_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Health tracking (denormalized for quick queries)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    validation_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="untested", index=True
    )
    failure_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    no_cursor_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    health_status: Mapped[str] = mapped_column(String(30), default="configured")  # configured/healthy/degraded/unavailable

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    raw_items: Mapped[list["RawItem"]] = relationship(back_populates="source")
    cursors: Mapped[list["CollectionCursor"]] = relationship(back_populates="source")


class SourceCredential(Base):
    """References to external secrets — never stores actual values."""
    __tablename__ = "source_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(50), nullable=False)  # env_var, file_path, keyring
    credential_ref: Mapped[str] = mapped_column(String(500), nullable=False)  # e.g. "TELEGRAM_API_ID" or "/secrets/telegram"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollectionCursor(Base):
    """Incremental collection cursors per source."""
    __tablename__ = "collection_cursors"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    cursor_key: Mapped[str] = mapped_column(String(100), default="default")  # e.g. "last_message_id", "last_published"
    cursor_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    source: Mapped["Source"] = relationship(back_populates="cursors")
    __table_args__ = (UniqueConstraint("source_id", "cursor_key", name="uq_cursor_source_key"),)


# ── Collection & raw storage ──────────────────────────────────────

class CollectionRun(Base):
    """Record of a single collection run (one source, one invocation)."""
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running")  # running/ok/error
    items_collected: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawItem(Base):
    """Unprocessed item collected from a source."""
    __tablename__ = "raw_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False)  # structured JSON, not str(dict)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)  # pre-normalization hash for raw dedup
    # Gate 3: Telegram message identity for edit idempotency
    telegram_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    edit_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped["Source"] = relationship(back_populates="raw_items")
    normalized_item: Mapped["NormalizedItem | None"] = relationship(back_populates="raw_item", uselist=False)


# ── Normalized items ──────────────────────────────────────────────

class NormalizedItem(Base):
    """Processed item with standard fields."""
    __tablename__ = "normalized_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), unique=True, nullable=False)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    url_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("normalized_items.id"), nullable=True)

    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    raw_item: Mapped["RawItem"] = relationship(back_populates="normalized_item")
    duplicate_of: Mapped["NormalizedItem | None"] = relationship(remote_side=[id], foreign_keys=[duplicate_of_id])  # noqa: A003
    story_links: Mapped[list["StoryItem"]] = relationship(back_populates="item")


# ── Stories & evidence ─────────────────────────────────────────────

class Story(Base):
    """A clustered set of items about the same event."""
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    trust_status: Mapped[str] = mapped_column(String(30), default="unconfirmed")  # official/confirmed/likely/unconfirmed/rumor
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    novelty_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Cluster metadata
    cluster_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    source_count: Mapped[int] = mapped_column(Integer, default=1)

    # Material change tracking for /report new eligibility
    material_version: Mapped[int] = mapped_column(Integer, default=1)
    material_change_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list["StoryItem"]] = relationship(back_populates="story")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="story")


class StoryItem(Base):
    """Many-to-many between stories and normalized items."""
    __tablename__ = "story_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("normalized_items.id"), nullable=False)

    story: Mapped["Story"] = relationship(back_populates="items")
    item: Mapped["NormalizedItem"] = relationship(back_populates="story_links")
    __table_args__ = (UniqueConstraint("story_id", "item_id", name="uq_story_item"),)


class Evidence(Base):
    """Bounded evidence packet for editorial generation."""
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id"), nullable=False)
    packet: Mapped[dict] = mapped_column(JSONB, nullable=False)  # structured evidence: facts, sources, links, contradictions
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    story: Mapped["Story"] = relationship(back_populates="evidence")


# ── Reports & delivery ─────────────────────────────────────────────

class Report(Base):
    """Generated Persian report (renamed from Digest)."""
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    content_fa: Mapped[str] = mapped_column(Text, nullable=False)
    story_ids: Mapped[list] = mapped_column(JSONB, default=list)
    report_mode: Mapped[str] = mapped_column(String(30), default="scheduled")  # scheduled/manual_new/manual_comprehensive/latest
    generation_method: Mapped[str] = mapped_column(String(30), default="deterministic")  # llm/deterministic

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deliveries: Mapped[list["Delivery"]] = relationship(back_populates="report")


class Delivery(Base):
    """Telegram delivery tracking with chunk-level state."""
    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(50), nullable=False)  # hash for safety
    chat_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)  # safe label, no token
    total_chunks: Mapped[int] = mapped_column(Integer, default=1)
    delivered_chunks: Mapped[int] = mapped_column(Integer, default=0)
    message_ids: Mapped[list] = mapped_column(JSONB, default=list)  # Telegram message IDs per chunk
    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending/partial/delivered/failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parse_mode: Mapped[str] = mapped_column(String(10), default="HTML", nullable=False)
    last_send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    report: Mapped["Report"] = relationship(back_populates="deliveries")
    chunks: Mapped[list["DeliveryChunk"]] = relationship(
        back_populates="delivery", cascade="all, delete-orphan", order_by="DeliveryChunk.chunk_index"
    )

    __table_args__ = (
        UniqueConstraint("report_id", "chat_id", name="uq_delivery_report_chat"),
    )


# ── Jobs & operations ──────────────────────────────────────────────

class JobRun(Base):
    """Record of every pipeline execution."""
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)  # scheduled/manual
    job_id: Mapped[str] = mapped_column(String(100), nullable=False)  # correlation ID
    trigger: Mapped[str] = mapped_column(String(30), default="scheduled")  # scheduled/manual
    report_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    report_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stage: Mapped[str] = mapped_column(String(50), default="starting")
    status: Mapped[str] = mapped_column(String(30), default="running")  # running/ok/error

    source_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_item_count: Mapped[int] = mapped_column(Integer, default=0)
    normalized_item_count: Mapped[int] = mapped_column(Integer, default=0)
    story_count: Mapped[int] = mapped_column(Integer, default=0)
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    stages_log: Mapped[list] = mapped_column(JSONB, default=list)  # [{name, status, detail, ts}]


class ProcessingError(Base):
    """Persisted pipeline errors for diagnosis."""
    __tablename__ = "processing_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage: Mapped[str] = mapped_column(String(50), nullable=False)  # collect/normalize/dedupe/cluster/digest/deliver
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    recoverable: Mapped[bool] = mapped_column(Boolean, default=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ── Gate 2: Telegram delivery state ────────────────────────────────

class TelegramUpdate(Base):
    """Idempotency record for processed Telegram updates."""
    __tablename__ = "telegram_updates"

    id: Mapped[int] = mapped_column(primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    update_type: Mapped[str] = mapped_column(String(30), nullable=False)  # message/callback
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    command: Mapped[str | None] = mapped_column(String(100), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    result: Mapped[str | None] = mapped_column(String(50), nullable=True)  # ok/denied/error/busy


class DeliveryChunk(Base):
    """Per-chunk delivery state for partial recovery."""
    __tablename__ = "delivery_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/sent/failed
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    delivery: Mapped["Delivery"] = relationship(back_populates="chunks")
    __table_args__ = (UniqueConstraint("delivery_id", "chunk_index", name="uq_delivery_chunk_index"),)


class ReportCursor(Base):
    """Single-row cursor: last successfully delivered scheduled report."""
    __tablename__ = "report_cursors"

    id: Mapped[int] = mapped_column(primary_key=True)
    cursor_key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), nullable=True)
    delivery_id: Mapped[int | None] = mapped_column(ForeignKey("deliveries.id"), nullable=True)
    advanced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CommandRequest(Base):
    """Persistent idempotency for command/callback-driven pipeline runs."""
    __tablename__ = "command_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    command: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    job_run_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Gate 3: Telegram MTProto ingestion state ──────────────────────

class TelegramChannel(Base):
    """Extended Telegram channel metadata tied to sources.

    Stable numeric Telegram channel ID is the primary external identity.
    Usernames are mutable — username updates don't create duplicate sources.
    """
    __tablename__ = "telegram_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, unique=True)
    telegram_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    access_hash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    public_username: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    category: Mapped[str] = mapped_column(String(100), default="general")
    trust_class: Mapped[str] = mapped_column(String(30), default="unverified")
    trust_score: Mapped[float] = mapped_column(Float, default=0.0)
    collection_mode: Mapped[str] = mapped_column(String(30), default="history")
    source_state: Mapped[str] = mapped_column(String(30), default="candidate")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_observed_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reconciliation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    floodwait_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posting_frequency: Mapped[float] = mapped_column(Float, default=0.0)
    duplicate_rate: Mapped[float] = mapped_column(Float, default=0.0)
    spam_rate: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TelegramMessageGap(Base):
    """Detected message ID gaps for bounded reconciliation."""
    __tablename__ = "telegram_message_gaps"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    gap_start_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gap_end_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open")  # open/resolved/partial
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unresolved_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── Gate 4: AI editorial state ────────────────────────────────────

class EditorialAttempt(Base):
    """Audit record for every editorial generation attempt.

    No API keys stored. Enough metadata for replay and audit without
    duplicating the full evidence set (referenced by evidence_set_hash).
    """
    __tablename__ = "editorial_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    prompt_version: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    evidence_set_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    report_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="scheduled")

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ok")
    # ok/fallback/validation_failed/grounding_failed/provider_error
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)

    validation_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    grounding_result: Mapped[str | None] = mapped_column(Text, nullable=True)

    usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # token counts
    output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # structured output

    error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # redacted

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Idempotency: unique identity for cache reuse
    cache_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)


class EditorialHealth(Base):
    """Singleton editorial health state — updated after each attempt."""
    __tablename__ = "editorial_health"

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(50), default="deterministic")
    model: Mapped[str] = mapped_column(String(100), default="")

    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    validation_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    grounding_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, default=0)

    rate_limited: Mapped[bool] = mapped_column(Boolean, default=False)
    rate_limit_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    in_flight: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# Gate 6: multi-provider router reliability state.


class ProviderModelHealth(Base):
    """Safe validation and runtime health for one provider/model route."""

    __tablename__ = "provider_model_health"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(150), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unavailable")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    supported_capabilities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider", "model", name="uq_provider_model_health_route"),
        CheckConstraint("latency_ms >= 0", name="ck_provider_model_health_nonnegative_latency"),
        Index("ix_provider_model_health_validation", "validation_status", "enabled"),
    )


class ProviderKeyState(Base):
    """Per-key runtime state identified only by a one-way SHA-256 fingerprint."""

    __tablename__ = "provider_key_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_use_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("provider", "key_fingerprint", name="uq_provider_key_fingerprint"),
        CheckConstraint(
            "key_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_provider_key_fingerprint_sha256",
        ),
        CheckConstraint(
            "failure_count >= 0 AND success_count >= 0",
            name="ck_provider_key_nonnegative_counts",
        ),
        Index("ix_provider_key_state_cooldown", "cooldown_until"),
    )


class ProviderQuotaState(Base):
    """Durable project/model quota snapshot shared by every key in a scope."""

    __tablename__ = "provider_quota_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    scope_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rpm_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tpm_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rpd_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    day_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "provider", "model", "scope_fingerprint", name="uq_provider_model_quota_scope"
        ),
        CheckConstraint(
            "scope_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_provider_quota_scope_sha256",
        ),
        CheckConstraint(
            "rpm_used >= 0 AND tpm_used >= 0 AND rpd_used >= 0 AND reserved_tokens >= 0",
            name="ck_provider_quota_nonnegative_counts",
        ),
        Index("ix_provider_quota_state_cooldown", "cooldown_until"),
    )


class ProviderCircuitState(Base):
    """Provider-level circuit breaker state used across all model routes."""

    __tablename__ = "provider_circuit_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="closed")
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    half_open_probe_in_flight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('closed', 'open', 'half_open')",
            name="ck_provider_circuit_state",
        ),
        CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_provider_circuit_nonnegative_failures",
        ),
        Index("ix_provider_circuit_cooldown", "cooldown_until"),
    )


class ProviderRouteAttempt(Base):
    """One safe, idempotent provider-route attempt with editorial lineage."""

    __tablename__ = "provider_route_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    editorial_job_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shard_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    key_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    failure_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_after_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "key_fingerprint IS NULL OR key_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_provider_attempt_key_fingerprint_sha256",
        ),
        CheckConstraint(
            "latency_ms >= 0 AND estimated_input_tokens >= 0 "
            "AND actual_input_tokens >= 0 AND actual_output_tokens >= 0 "
            "AND (retry_after_seconds IS NULL OR retry_after_seconds >= 0)",
            name="ck_provider_attempt_nonnegative_usage",
        ),
        Index("ix_provider_route_attempt_event", "event_id", unique=True),
        Index("ix_provider_route_attempt_job", "editorial_job_id"),
        Index("ix_provider_route_attempt_shard", "shard_id"),
        Index("ix_provider_route_attempt_report", "report_id"),
        Index("ix_provider_route_attempt_artifact", "artifact_id"),
        Index("ix_provider_route_attempt_stage", "stage"),
        Index("ix_provider_route_attempt_provider", "provider"),
    )


# Gate 4 scalable: editorial jobs, shards, artifacts.


class EditorialJob(Base):
    """Top-level persistent job for a scalable editorial report.

    Tracks the full lifecycle of a hierarchical map/reduce report generation.
    No API keys stored — only provider name and model.
    """

    __tablename__ = "editorial_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    report_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    # pending/running/validated/failed_retryable/failed_permanent/fallback/completed/superseded

    candidate_story_ids: Mapped[list] = mapped_column(JSONB, default=list)
    excluded_as_delivered_count: Mapped[int] = mapped_column(Integer, default=0)
    materially_updated_count: Mapped[int] = mapped_column(Integer, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, default=0)
    omitted_count: Mapped[int] = mapped_column(Integer, default=0)

    shard_count: Mapped[int] = mapped_column(Integer, default=0)
    partition_version: Mapped[str] = mapped_column(String(30), nullable=False)
    reduction_depth: Mapped[int] = mapped_column(Integer, default=0)
    max_reduction_depth: Mapped[int] = mapped_column(Integer, default=3)

    total_model_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    max_input_token_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_token_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    map_call_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    reduction_call_budget: Mapped[int] = mapped_column(Integer, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    partial_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EditorialShard(Base):
    """Bounded partition of stories for one AI map call.

    Stable shard ID ensures deterministic partitioning for identical inputs.
    Processing lease prevents duplicate concurrent work.
    """

    __tablename__ = "editorial_shards"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_db_id: Mapped[int] = mapped_column(ForeignKey("editorial_jobs.id"), nullable=False, index=True)
    shard_id: Mapped[str] = mapped_column(String(100), nullable=False)
    shard_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    total_shards: Mapped[int] = mapped_column(Integer, nullable=False)

    story_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    evidence_ref_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    evidence_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    estimated_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_input_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_output_limit: Mapped[int] = mapped_column(Integer, nullable=False)

    prompt_version: Mapped[str] = mapped_column(String(30), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    partition_version: Mapped[str] = mapped_column(String(30), nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    # pending/running/validated/failed_retryable/failed_permanent/fallback/superseded/completed

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)

    lease_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)

    artifact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("job_db_id", "shard_id", name="uq_editorial_shard_id"),)


class EditorialArtifact(Base):
    """Validated output from a map or reduce stage.

    Stores structured conclusions, evidence mappings, and safe metadata.
    No chain-of-thought, prompts, or API keys stored.
    """

    __tablename__ = "editorial_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_db_id: Mapped[int] = mapped_column(ForeignKey("editorial_jobs.id"), nullable=False, index=True)
    shard_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # map/reduction_topic/reduction_final
    reduction_level: Mapped[int] = mapped_column(Integer, default=0)

    output_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    story_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    evidence_ref_ids: Mapped[list] = mapped_column(JSONB, nullable=False)

    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(30), nullable=False)
    validation_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    grounding_result: Mapped[str | None] = mapped_column(Text, nullable=True)

    cache_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="validated")
    # validated/failed/superseded

    child_artifact_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EditorialArtifactLineage(Base):
    """Evidence traceability from artifact to source.

    Every final claim traces through:
    final → reduction → map → story → evidence_ref → source_url
    """

    __tablename__ = "editorial_artifact_lineage"

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("editorial_artifacts.id"), nullable=False, index=True)
    story_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    evidence_ref_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "story_id",
            "evidence_ref_id",
            name="uq_editorial_artifact_lineage_identity",
        ),
    )


# ── Gate 5: Agent-Reach capability layer state ─────────────────────

class AgentReachBackendState(Base):
    """Per-channel Agent-Reach backend state — Newsroom-owned durability.

    Agent-Reach itself never writes to this table. Newsroom records the
    pinned version, selected backend, fallback backends, health, last
    success/failure, production approval, and the bounded real-read flag.

    No credentials, no cookies, no authorization headers stored here.
    """
    __tablename__ = "agent_reach_backend_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    pinned_version: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    selected_backend: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    fallback_backends: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    healthy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    production_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    production_approval: Mapped[str] = mapped_column(String(60), nullable=False, default="deferred")
    last_doctor_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AgentReachSourceState(Base):
    """Per-Source Agent-Reach adapter state.

    Extends the existing sources + collection_cursors tables with
    Agent-Reach-specific state: selected backend, backend version, durable
    cursor, pagination, rate-limit state, source-specific metadata, health,
    retry-after, and safe error category.

    No cookies, no local browser-profile paths, no complete authorization
    headers, no Agent-Reach config contents, no unrelated command output,
    no private messages.
    """
    __tablename__ = "agent_reach_source_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, unique=True, index=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    backend: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    backend_version: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    last_stable_item_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_original_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_publication_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_raw_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_edit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cursor: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    pagination_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rate_limit_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    health_status: Mapped[str] = mapped_column(String(30), nullable=False, default="configured")
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ── Gate 5X: X/Twitter account state for production timeline ingestion ──


class XAccountState(Base):
    """Per-account X/Twitter state for the production timeline collector.

    Tracks the stable numeric account ID (which never changes on handle
    rename), the configured handle, the last resolved handle, per-account
    health, rate-limit state, and the per-account cursor. Survives handle
    changes without breaking dedup.

    No cookies, tokens, or authorization headers stored here.
    """

    __tablename__ = "x_account_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, unique=True, index=True)
    account_id: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    configured_handle: Mapped[str] = mapped_column(String(20), nullable=False)
    last_resolved_handle: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_status: Mapped[str] = mapped_column(String(30), nullable=False, default="configured")
    cursor: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rate_limit_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_posts_collected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ── Gate 6: authoritative source workbook inventory ───────────────


class SourceInventory(Base):
    """Authoritative production source registry — one row per workbook row.

    Holds every reviewed workbook source (expected 1344) with all preserved
    workbook metadata, a stable normalized identity (independent of display
    name), validation result, operational state, and a link to the active
    collector row in ``sources`` when the source is activated.

    Repeated import is idempotent by ``stable_identity``: no duplicates, no
    silent row disappearance. Disabling a source never removes its historical
    raw items (the ``sources`` row is retained with ``enabled=False``).

    Existing source-state names are reused:
      operational_state: active | inactive | invalid
      (active rows link to ``sources`` via source_id; inactive rows carry a
      concise ``inactive_reason`` using the repository's existing inactive
      vocabulary: agent_reach_not_configured, x_auth_not_configured,
      access_required, not_a_repo, invalid_url, ...).

    No credentials, cookies, or session material stored here.
    """

    __tablename__ = "source_inventory"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Original workbook row ID (preserved verbatim) — idempotency key for import.
    workbook_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    # Platform + source type as recorded in the workbook (Type column).
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    workbook_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    public_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    topic: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(30), nullable=True)
    content_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    review_level: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Verification column
    verification: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovery_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)  # Core/Discovery/Community/Watchlist
    coverage_score: Mapped[int] = mapped_column(Integer, default=0)
    risk: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Numeric workbook scores preserved for ranking.
    speed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    informal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    noise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_community: Mapped[bool] = mapped_column(Boolean, default=False)
    is_opensource_api: Mapped[bool] = mapped_column(Boolean, default=False)

    # Stable normalized identity — independent of display name. Non-unique:
    # the same source may appear on multiple workbook rows; duplicates are
    # retained (operational_state='duplicate') so no row disappears silently.
    stable_identity: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Mapped Newsroom source type for collection (rss, github_releases,
    # telegram, reddit_subreddit, web_page, youtube_rss, x_timeline, ...).
    mapped_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    # validation_result: ok | invalid_url | invalid_handle | missing_url | duplicate
    validation_result: Mapped[str] = mapped_column(String(50), nullable=False, default="ok", index=True)
    validation_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # operational_state: active | inactive | invalid (reuses existing vocab)
    operational_state: Mapped[str] = mapped_column(String(30), nullable=False, default="inactive", index=True)
    inactive_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Link to the active collector row (sources.id) when activated.
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True, index=True)

    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

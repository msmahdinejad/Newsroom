"""SQLAlchemy database models — V2 schema authority.

All timestamps are timezone-aware UTC. JSON fields use JSONB for query efficiency.
No raw secrets stored — only references to external secret storage.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Timezone-aware UTC now — replaces deprecated datetime.utcnow."""
    return datetime.now(timezone.utc)


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

    # Health tracking (denormalized for quick queries)
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
    duplicate_of: Mapped["NormalizedItem | None"] = relationship(remote_side=[id], foreign_keys=[duplicate_of_id])
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
    total_chunks: Mapped[int] = mapped_column(Integer, default=1)
    delivered_chunks: Mapped[int] = mapped_column(Integer, default=0)
    message_ids: Mapped[list] = mapped_column(JSONB, default=list)  # Telegram message IDs per chunk
    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending/partial/delivered/failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    report: Mapped["Report"] = relationship(back_populates="deliveries")


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

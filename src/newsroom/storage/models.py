"""SQLAlchemy database models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Source(Base):
    """External feed or API source."""
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # rss, github_releases
    url: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en")
    priority: Mapped[str] = mapped_column(String(20), default="medium")  # high, medium, low
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Health tracking
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    raw_items: Mapped[list["RawItem"]] = relationship(back_populates="source")


class RawItem(Base):
    """Unprocessed item collected from a source."""
    __tablename__ = "raw_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    source: Mapped["Source"] = relationship(back_populates="raw_items")
    normalized_item: Mapped[Optional["NormalizedItem"]] = relationship(back_populates="raw_item", uselist=False)


class NormalizedItem(Base):
    """Processed item with standard fields."""
    __tablename__ = "normalized_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), unique=True, nullable=False)

    # Standard fields
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Deduplication fields
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("normalized_items.id"), nullable=True)

    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    raw_item: Mapped["RawItem"] = relationship(back_populates="normalized_item")
    duplicate_of: Mapped[Optional["NormalizedItem"]] = relationship(remote_side=[id])  # noqa: A003


class Story(Base):
    """A grouped set of items about the same event."""
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source tracking
    source_urls: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    item_ids: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of normalized_item IDs

    # Metadata
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Digest(Base):
    """Persian language digest output."""
    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(primary_key=True)
    content_fa: Mapped[str] = mapped_column(Text, nullable=False)
    story_ids: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array

    # Delivery tracking
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

"""Gate 3 — Telegram MTProto ingestion: channel registry, gaps, raw item identity.

Revision ID: 0004_gate3_mtproto
Revises: 0003_gate2_telegram
Create Date: 2026-07-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_gate3_mtproto"
down_revision: str | None = "0003_gate2_telegram"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Telegram channel metadata (tied to sources) ──
    op.create_table(
        "telegram_channels",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False, unique=True),
        # Stable numeric Telegram channel ID — primary external identity
        sa.Column("telegram_channel_id", sa.BigInteger, nullable=False, unique=True, index=True),
        # Internal use only — never in reports
        sa.Column("access_hash", sa.BigInteger, nullable=True),
        sa.Column("public_username", sa.String(255), nullable=True, index=True),
        sa.Column("public_url", sa.Text, nullable=True),
        sa.Column("display_name", sa.String(500), nullable=True),
        # Classification
        sa.Column("language", sa.String(10), server_default="en"),
        sa.Column("category", sa.String(100), server_default="general"),
        sa.Column("trust_class", sa.String(30), server_default="unverified"),
        sa.Column("trust_score", sa.Float, server_default="0"),
        sa.Column("collection_mode", sa.String(30), server_default="history"),
        # State — candidate/configured/enabled/healthy/degraded/auth_required/inaccessible/rate_limited/disabled/invalid
        sa.Column("source_state", sa.String(30), server_default="candidate"),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("false")),
        # Cursor / health
        sa.Column("last_message_id", sa.BigInteger, nullable=True),
        sa.Column("last_observed_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reconciliation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_error", sa.Text, nullable=True),
        sa.Column("error_category", sa.String(50), nullable=True),
        sa.Column("floodwait_until", sa.DateTime(timezone=True), nullable=True),
        # Stats
        sa.Column("posting_frequency", sa.Float, server_default="0"),
        sa.Column("duplicate_rate", sa.Float, server_default="0"),
        sa.Column("spam_rate", sa.Float, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── Gap tracking for reconciliation ──
    op.create_table(
        "telegram_message_gaps",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False, index=True),
        sa.Column("gap_start_id", sa.BigInteger, nullable=False),
        sa.Column("gap_end_id", sa.BigInteger, nullable=False),
        sa.Column("status", sa.String(30), server_default="open"),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unresolved_count", sa.Integer, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
    )

    # ── Extend raw_items for Telegram message identity ──
    op.add_column("raw_items", sa.Column("telegram_channel_id", sa.BigInteger, nullable=True))
    op.add_column("raw_items", sa.Column("telegram_message_id", sa.BigInteger, nullable=True))
    op.add_column("raw_items", sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")))
    op.add_column("raw_items", sa.Column("edit_ts", sa.DateTime(timezone=True), nullable=True))

    # Unique constraint: one raw item per (channel_id, message_id) — edit updates, not duplicates
    op.create_index(
        "uq_raw_items_telegram_identity",
        "raw_items",
        ["telegram_channel_id", "telegram_message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_raw_items_telegram_identity", table_name="raw_items")
    op.drop_column("raw_items", "edit_ts")
    op.drop_column("raw_items", "is_deleted")
    op.drop_column("raw_items", "telegram_message_id")
    op.drop_column("raw_items", "telegram_channel_id")
    op.drop_table("telegram_message_gaps")
    op.drop_table("telegram_channels")

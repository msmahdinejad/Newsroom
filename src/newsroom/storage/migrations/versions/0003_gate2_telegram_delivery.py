"""Delivery — Telegram delivery: idempotency, per-chunk state, delivery cursor.

Revision ID: 0003_gate2_telegram
Revises: 0002_v2_stories_reports
Create Date: 2026-07-16
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_gate2_telegram"
down_revision: str | None = "0002_v2_stories_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Telegram update idempotency ──
    op.create_table(
        "telegram_updates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("update_id", sa.BigInteger, nullable=False, unique=True, index=True),
        sa.Column("update_type", sa.String(30), nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=True),
        sa.Column("chat_id", sa.String(100), nullable=True),
        sa.Column("command", sa.String(100), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("result", sa.String(50), nullable=True),
    )

    # ── Delivery chunk records ──
    op.create_table(
        "delivery_chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("delivery_id", sa.Integer, sa.ForeignKey("deliveries.id"), nullable=False, index=True),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("total_chunks", sa.Integer, nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_category", sa.String(50), nullable=True),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("delivery_id", "chunk_index", name="uq_delivery_chunk_index"),
    )

    # ── Report delivery cursor ──
    op.create_table(
        "report_cursors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cursor_key", sa.String(50), nullable=False, unique=True),
        sa.Column("report_id", sa.Integer, sa.ForeignKey("reports.id"), nullable=True),
        sa.Column("delivery_id", sa.Integer, sa.ForeignKey("deliveries.id"), nullable=True),
        sa.Column("advanced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.execute(
        "INSERT INTO report_cursors (cursor_key, report_id, delivery_id) "
        "VALUES ('scheduled_delivery', NULL, NULL) "
        "ON CONFLICT (cursor_key) DO NOTHING"
    )

    # ── Enhance deliveries table ──
    op.add_column("deliveries", sa.Column("chat_ref", sa.String(100), nullable=True))
    op.add_column("deliveries", sa.Column("attempt_count", sa.Integer, server_default="0", nullable=False))
    op.add_column("deliveries", sa.Column("retry_count", sa.Integer, server_default="0", nullable=False))
    op.add_column("deliveries", sa.Column("error_category", sa.String(50), nullable=True))
    op.add_column("deliveries", sa.Column("parse_mode", sa.String(10), server_default="HTML", nullable=False))
    op.add_column("deliveries", sa.Column("last_send_at", sa.DateTime(timezone=True), nullable=True))

    # ── Command request idempotency ──
    op.create_table(
        "command_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("request_key", sa.String(200), nullable=False, unique=True, index=True),
        sa.Column("command", sa.String(100), nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=True),
        sa.Column("chat_id", sa.String(100), nullable=True),
        sa.Column("job_run_id", sa.String(100), nullable=True),
        sa.Column("report_id", sa.Integer, nullable=True),
        sa.Column("delivery_id", sa.Integer, nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("command_requests")
    op.drop_column("deliveries", "last_send_at")
    op.drop_column("deliveries", "parse_mode")
    op.drop_column("deliveries", "error_category")
    op.drop_column("deliveries", "retry_count")
    op.drop_column("deliveries", "attempt_count")
    op.drop_column("deliveries", "chat_ref")
    op.drop_table("report_cursors")
    op.drop_table("delivery_chunks")
    op.drop_table("telegram_updates")

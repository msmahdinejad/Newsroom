"""Gate 4 — AI editorial: editorial attempts, health, cache.

Revision ID: 0005_gate4_editorial
Revises: 0004_gate3_mtproto
Create Date: 2026-07-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005_gate4_editorial"
down_revision: str | None = "0004_gate3_mtproto"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Editorial attempt audit records ──
    op.create_table(
        "editorial_attempts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("report_id", sa.Integer, sa.ForeignKey("reports.id"), nullable=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False, server_default=""),
        sa.Column("prompt_version", sa.String(30), nullable=False, server_default=""),
        sa.Column("evidence_set_hash", sa.String(64), nullable=False, index=True),
        sa.Column("schema_version", sa.String(30), nullable=False, server_default=""),
        sa.Column("report_mode", sa.String(30), nullable=False, server_default="scheduled"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="ok"),
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("fallback_used", sa.Boolean, server_default=sa.text("false")),
        sa.Column("validation_result", sa.Text, nullable=True),
        sa.Column("grounding_result", sa.Text, nullable=True),
        sa.Column("usage", JSONB, nullable=True),
        sa.Column("output_json", JSONB, nullable=True),
        sa.Column("error_category", sa.String(50), nullable=True),
        sa.Column("error_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("cache_key", sa.String(128), nullable=True, unique=True, index=True),
    )

    # ── Editorial health singleton ──
    op.create_table(
        "editorial_health",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("false")),
        sa.Column("provider", sa.String(50), server_default="deterministic"),
        sa.Column("model", sa.String(100), server_default=""),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_latency_ms", sa.Integer, server_default="0"),
        sa.Column("validation_failure_count", sa.Integer, server_default="0"),
        sa.Column("grounding_failure_count", sa.Integer, server_default="0"),
        sa.Column("fallback_count", sa.Integer, server_default="0"),
        sa.Column("rate_limited", sa.Boolean, server_default=sa.text("false")),
        sa.Column("rate_limit_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("in_flight", sa.Integer, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    # Seed singleton row
    op.execute(
        "INSERT INTO editorial_health (id, enabled, provider) "
        "VALUES (1, false, 'deterministic') "
        "ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("editorial_health")
    op.drop_table("editorial_attempts")

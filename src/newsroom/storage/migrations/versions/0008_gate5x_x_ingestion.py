"""Gate 5X — X/Twitter account state for production timeline ingestion.

Adds the x_account_state table to persist stable account IDs, resolved
handles, and per-account health separately from the generic source state.
This survives handle changes (account renames) without breaking dedup.

Revision ID: 0008_gate5x_x_ingestion
Revises: 0007_gate5_agent_reach
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008_gate5x_x_ingestion"
down_revision: str | None = "0007_gate5_agent_reach"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── X account state ──
    # One row per configured X account. Tracks the stable numeric account ID
    # (which never changes even if the handle is renamed), the configured
    # handle, the last resolved handle, per-account health, rate-limit
    # state, and the per-account cursor. No cookies or tokens stored here.
    op.create_table(
        "x_account_state",
        sa.Column("id", sa.Integer, primary_key=True),
        # Link to the source row (sources.id). One row per x_timeline source.
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False, unique=True, index=True),
        # Stable numeric account ID (never changes on handle rename).
        sa.Column("account_id", sa.String(30), nullable=False, index=True),
        # The handle configured in source.config['handle'].
        sa.Column("configured_handle", sa.String(20), nullable=False),
        # The last resolved handle from twitter user --json. May differ from
        # configured_handle if the account was renamed.
        sa.Column("last_resolved_handle", sa.String(20), nullable=True),
        # When the account was last resolved (for periodic re-resolution).
        sa.Column("last_resolved_at", sa.DateTime(timezone=True), nullable=True),
        # Per-account health: healthy / degraded / unavailable / rate_limited.
        sa.Column("health_status", sa.String(30), nullable=False, server_default="configured"),
        # Per-account cursor (JSONB) — durable, bounded seen_item_ids set.
        sa.Column("cursor", JSONB, nullable=False, server_default="{}"),
        # Per-account rate-limit state (retry-after, remaining).
        sa.Column("rate_limit_state", JSONB, nullable=False, server_default="{}"),
        # Per-account retry-after timestamp.
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        # Safe error category for diagnosis (never raw command output).
        sa.Column("last_error_category", sa.String(50), nullable=True),
        # Counts for health/observability.
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_posts_collected", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Index for scheduled lookup: health_status + retry_after.
    op.create_index(
        "ix_x_account_state_health",
        "x_account_state",
        ["health_status", "retry_after"],
    )


def downgrade() -> None:
    op.drop_index("ix_x_account_state_health", table_name="x_account_state")
    op.drop_table("x_account_state")

"""Gate 5 — Agent-Reach capability layer: backend state, source extension.

Revision ID: 0007_gate5_agent_reach
Revises: 0006_gate4_scalable
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007_gate5_agent_reach"
down_revision: str | None = "0006_gate4_scalable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Agent-Reach backend state per channel ──
    # Newsroom owns durability of: pinned version, selected backend, fallback
    # backends, health, last success/failure, production approval, and the
    # bounded real-read flag. Agent-Reach itself never writes to this table.
    op.create_table(
        "agent_reach_backend_state",
        sa.Column("id", sa.Integer, primary_key=True),
        # Channel name is the stable platform identity (web, rss, github,
        # youtube, x, reddit, linkedin, instagram, facebook, tiktok, etc.).
        sa.Column("channel", sa.String(50), nullable=False, unique=True, index=True),
        # Pinned immutable Agent-Reach revision (release tag, package version,
        # or commit SHA). Never the mutable `main` branch.
        sa.Column("pinned_version", sa.String(100), nullable=False, server_default=""),
        # Selected upstream backend (e.g. yt-dlp, gh, feedparser).
        sa.Column("selected_backend", sa.String(100), nullable=False, server_default=""),
        # Fallback backends in priority order.
        sa.Column("fallback_backends", JSONB, nullable=False, server_default="[]"),
        # Health flag — true only after a bounded real read succeeds.
        sa.Column("healthy", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_category", sa.String(50), nullable=True),
        sa.Column("degraded", sa.Boolean, nullable=False, server_default="false"),
        # production_ready flips to true only after a bounded real read succeeds.
        # doctor detecting an executable is NOT sufficient.
        sa.Column("production_ready", sa.Boolean, nullable=False, server_default="false"),
        # production_approval is the final Gate 5 decision string from
        # ProductionApproval (approved / approved_with_auth /
        # manual_discovery_only / deferred / rejected).
        sa.Column("production_approval", sa.String(60), nullable=False, server_default="deferred"),
        sa.Column("last_doctor_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
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

    # ── Agent-Reach source state (per Source) ──
    # Extends the existing sources table for Agent-Reach-managed sources with
    # durable cursor, pagination, rate-limit, and health metadata. The existing
    # sources + collection_cursors tables remain the source of truth for source
    # config and basic cursors; this table carries Agent-Reach-specific state
    # that does not fit the generic cursor shape.
    op.create_table(
        "agent_reach_source_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False, unique=True, index=True),
        # Channel name (youtube, web, github_discovery, x, reddit, linkedin).
        sa.Column("channel", sa.String(50), nullable=False, index=True),
        # Selected upstream backend (yt-dlp, gh, jina, etc.).
        sa.Column("backend", sa.String(100), nullable=False, server_default=""),
        # Backend version string (yt-dlp version, gh version, etc.).
        sa.Column("backend_version", sa.String(100), nullable=False, server_default=""),
        # Stable platform-native item identifier (video_id, post_id, etc.).
        # Used together with raw_items.content_hash for dedup.
        sa.Column("last_stable_item_id", sa.String(200), nullable=True),
        # Original URL of the last collected item.
        sa.Column("last_original_url", sa.Text, nullable=True),
        # Platform-native publication timestamp of the last collected item.
        sa.Column("last_publication_ts", sa.DateTime(timezone=True), nullable=True),
        # Collection timestamp of the last successful collection.
        sa.Column("last_collected_at", sa.DateTime(timezone=True), nullable=True),
        # Raw content hash of the last collected item (for edit detection).
        sa.Column("last_raw_content_hash", sa.String(64), nullable=True),
        # Edit hash where applicable (when upstream exposes it).
        sa.Column("last_edit_hash", sa.String(64), nullable=True),
        # Cursor state (JSONB) — durable per-channel cursor. The generic
        # collection_cursors table remains the canonical cursor store; this
        # is a denormalized mirror for fast health queries.
        sa.Column("cursor", JSONB, nullable=False, server_default="{}"),
        # Pagination state (JSONB) — opaque to the core pipeline.
        sa.Column("pagination_state", JSONB, nullable=False, server_default="{}"),
        # Rate-limit state — retry-after, rate-limit-remaining, etc.
        sa.Column("rate_limit_state", JSONB, nullable=False, server_default="{}"),
        # Source-specific metadata — bounded adapter metadata, never credentials.
        sa.Column("source_metadata", JSONB, nullable=False, server_default="{}"),
        # Health status (healthy / degraded / unavailable).
        sa.Column("health_status", sa.String(30), nullable=False, server_default="configured"),
        # Retry-after timestamp for rate-limited sources.
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        # Safe error category for diagnosis (never raw command output).
        sa.Column("last_error_category", sa.String(50), nullable=True),
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

    # Index for scheduled source lookup: enabled + healthy + due for collection.
    op.create_index(
        "ix_agent_reach_source_state_health",
        "agent_reach_source_state",
        ["channel", "health_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_reach_source_state_health", table_name="agent_reach_source_state")
    op.drop_table("agent_reach_source_state")
    op.drop_table("agent_reach_backend_state")

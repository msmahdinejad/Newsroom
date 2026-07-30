"""Add grounded source discovery jobs and approval candidates.

Revision ID: 0014_source_discovery
Revises: 0013_digest_definitions
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_source_discovery"
down_revision: str | None = "0013_digest_definitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column(
            "requested_platforms",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("interaction_id", sa.String(length=255), nullable=True),
        sa.Column("failure_category", sa.String(length=50), nullable=True),
        sa.Column(
            "candidate_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mode IN ('quick', 'deep')",
            name="ck_discovery_job_mode",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "source_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column(
            "rationale",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "score",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "validation_status",
            sa.String(length=30),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("failure_category", sa.String(length=50), nullable=True),
        sa.Column(
            "approval_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected')",
            name="ck_source_candidate_approval",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["discovery_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "normalized_url",
            name="uq_source_candidate_job_url",
        ),
    )
    op.create_index(
        op.f("ix_source_candidates_job_id"),
        "source_candidates",
        ["job_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_source_candidates_job_id"),
        table_name="source_candidates",
    )
    op.drop_table("source_candidates")
    op.drop_table("discovery_jobs")

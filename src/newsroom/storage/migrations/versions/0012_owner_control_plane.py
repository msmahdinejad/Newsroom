"""Add non-secret owner control-plane preferences.

Revision ID: 0012_owner_control_plane
Revises: 0011_gate7_identity_privacy
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_owner_control_plane"
down_revision: str | None = "0011_gate7_identity_privacy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "newsroom_control_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "report_language",
            sa.String(length=10),
            nullable=False,
            server_default="fa",
        ),
        sa.Column(
            "report_source_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "report_story_count",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
        sa.Column(
            "schedule_times",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(
                """'["00:00","06:00","12:00","18:00"]'::jsonb"""
            ),
        ),
        sa.Column(
            "schedule_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="ck_newsroom_control_singleton"),
        sa.CheckConstraint(
            "report_story_count BETWEEN 1 AND 50",
            name="ck_newsroom_control_story_count",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO newsroom_control_settings "
            "(id, report_language, report_source_types, report_story_count, "
            "schedule_times, schedule_enabled) "
            "VALUES (1, 'fa', '[]'::jsonb, 15, "
            """'["00:00","06:00","12:00","18:00"]'::jsonb, true) """
            "ON CONFLICT (id) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.drop_table("newsroom_control_settings")

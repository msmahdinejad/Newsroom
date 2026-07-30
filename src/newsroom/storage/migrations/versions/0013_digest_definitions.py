"""Add named digest definitions and explicit source membership.

Revision ID: 0013_digest_definitions
Revises: 0012_owner_control_plane
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_digest_definitions"
down_revision: str | None = "0012_owner_control_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "digest_definitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("topic_brief", sa.Text(), nullable=False),
        sa.Column(
            "include_terms",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "exclude_terms",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "output_language",
            sa.String(length=10),
            nullable=False,
            server_default="fa",
        ),
        sa.Column(
            "timezone_name",
            sa.String(length=64),
            nullable=False,
            server_default="Asia/Tehran",
        ),
        sa.Column(
            "source_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "max_stories",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
        sa.Column(
            "minimum_telegram_stories",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "schedule_times",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("""'["00:00","06:00","12:00","18:00"]'::jsonb"""),
        ),
        sa.Column(
            "schedule_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "provider_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "delivery_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "max_stories BETWEEN 1 AND 50",
            name="ck_digest_max_stories",
        ),
        sa.CheckConstraint(
            "minimum_telegram_stories BETWEEN 0 AND max_stories",
            name="ck_digest_minimum_telegram_stories",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(
        op.f("ix_digest_definitions_slug"),
        "digest_definitions",
        ["slug"],
        unique=True,
    )
    op.create_table(
        "digest_sources",
        sa.Column("digest_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["digest_id"],
            ["digest_definitions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("digest_id", "source_id"),
    )
    op.add_column(
        "reports",
        sa.Column(
            "digest_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "reports",
        sa.Column(
            "digest_slug",
            sa.String(length=80),
            nullable=False,
            server_default="default",
        ),
    )
    op.create_foreign_key(
        "fk_reports_digest_id",
        "reports",
        "digest_definitions",
        ["digest_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "job_runs",
        sa.Column(
            "digest_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "job_runs",
        sa.Column(
            "digest_slug",
            sa.String(length=80),
            nullable=False,
            server_default="default",
        ),
    )
    op.create_foreign_key(
        "fk_job_runs_digest_id",
        "job_runs",
        "digest_definitions",
        ["digest_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Preserve the existing product exactly as the default digest. Operators
    # can generalize its topic after the migration without losing preferences.
    op.execute(
        sa.text(
            """
            INSERT INTO digest_definitions (
                slug,
                name,
                topic_brief,
                include_terms,
                exclude_terms,
                output_language,
                timezone_name,
                source_types,
                max_stories,
                minimum_telegram_stories,
                schedule_times,
                schedule_enabled,
                enabled,
                provider_policy,
                delivery_config
            )
            SELECT
                'default',
                'Default digest',
                'Software development, programming tools, developer services, '
                'libraries, frameworks, APIs, open-source projects and '
                'engineering practices.',
                '[]'::jsonb,
                '[]'::jsonb,
                report_language,
                'Asia/Tehran',
                report_source_types,
                report_story_count,
                2,
                schedule_times,
                schedule_enabled,
                true,
                '{}'::jsonb,
                '{}'::jsonb
            FROM newsroom_control_settings
            WHERE id = 1
            ON CONFLICT (slug) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_job_runs_digest_id",
        "job_runs",
        type_="foreignkey",
    )
    op.drop_column("job_runs", "digest_slug")
    op.drop_column("job_runs", "digest_id")
    op.drop_constraint(
        "fk_reports_digest_id",
        "reports",
        type_="foreignkey",
    )
    op.drop_column("reports", "digest_slug")
    op.drop_column("reports", "digest_id")
    op.drop_table("digest_sources")
    op.drop_index(
        op.f("ix_digest_definitions_slug"),
        table_name="digest_definitions",
    )
    op.drop_table("digest_definitions")

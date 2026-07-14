"""V2 schema part 2 — stories, evidence, reports, delivery, jobs.

Revision ID: 0002_v2_stories_reports
Revises: 0001_v2_schema
Create Date: 2026-07-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_v2_stories_reports"
down_revision: Union[str, None] = "0001_v2_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("stories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("headline", sa.Text, nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column("priority", sa.String(20), server_default="medium"),
        sa.Column("trust_status", sa.String(30), server_default="unconfirmed"),
        sa.Column("confidence", sa.Float, server_default="0"),
        sa.Column("importance_score", sa.Float, server_default="0"),
        sa.Column("novelty_score", sa.Float, server_default="0"),
        sa.Column("cluster_keywords", JSONB, server_default=sa.text("'[]'")),
        sa.Column("source_count", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table("story_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("story_id", sa.Integer, sa.ForeignKey("stories.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("normalized_items.id"), nullable=False),
        sa.UniqueConstraint("story_id", "item_id", name="uq_story_item"),
    )

    op.create_table("evidence",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("story_id", sa.Integer, sa.ForeignKey("stories.id"), nullable=False),
        sa.Column("packet", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table("reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("content_fa", sa.Text, nullable=False),
        sa.Column("story_ids", JSONB, server_default=sa.text("'[]'")),
        sa.Column("report_mode", sa.String(30), server_default="scheduled"),
        sa.Column("generation_method", sa.String(30), server_default="deterministic"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table("deliveries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("report_id", sa.Integer, sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("chat_id", sa.String(50), nullable=False),
        sa.Column("total_chunks", sa.Integer, server_default="1"),
        sa.Column("delivered_chunks", sa.Integer, server_default="0"),
        sa.Column("message_ids", JSONB, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(30), server_default="pending"),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
    )

    op.create_table("job_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_type", sa.String(30), nullable=False),
        sa.Column("job_id", sa.String(100), nullable=False),
        sa.Column("trigger", sa.String(30), server_default="scheduled"),
        sa.Column("report_window_start", sa.DateTime(timezone=True)),
        sa.Column("report_window_end", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("stage", sa.String(50), server_default="starting"),
        sa.Column("status", sa.String(30), server_default="running"),
        sa.Column("source_count", sa.Integer, server_default="0"),
        sa.Column("raw_item_count", sa.Integer, server_default="0"),
        sa.Column("normalized_item_count", sa.Integer, server_default="0"),
        sa.Column("story_count", sa.Integer, server_default="0"),
        sa.Column("report_id", sa.Integer),
        sa.Column("delivery_id", sa.Integer),
        sa.Column("error_category", sa.String(50)),
        sa.Column("error_detail", sa.Text),
        sa.Column("stages_log", JSONB, server_default=sa.text("'[]'")),
    )

    op.create_table("processing_errors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("source_id", sa.Integer),
        sa.Column("error_type", sa.String(100), nullable=False),
        sa.Column("error_message", sa.Text, nullable=False),
        sa.Column("recoverable", sa.Boolean, server_default=sa.text("true")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("processing_errors")
    op.drop_table("job_runs")
    op.drop_table("deliveries")
    op.drop_table("reports")
    op.drop_table("evidence")
    op.drop_table("story_items")
    op.drop_table("stories")

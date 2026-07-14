"""V2 initial schema — all tables.

Revision ID: 0001_v2_schema
Revises:
Create Date: 2026-07-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_v2_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sources
    op.create_table("sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("language", sa.String(10), server_default="en"),
        sa.Column("category", sa.String(100), server_default="general"),
        sa.Column("trust_class", sa.String(30), server_default="reputable"),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("true")),
        sa.Column("config", JSONB, server_default=sa.text("'{}'")),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("consecutive_failures", sa.Integer, server_default="0"),
        sa.Column("health_status", sa.String(30), server_default="configured"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table("source_credentials",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("credential_type", sa.String(50), nullable=False),
        sa.Column("credential_ref", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table("collection_cursors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("cursor_key", sa.String(100), server_default="default"),
        sa.Column("cursor_value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("source_id", "cursor_key", name="uq_cursor_source_key"),
    )

    op.create_table("collection_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), server_default="running"),
        sa.Column("items_collected", sa.Integer, server_default="0"),
        sa.Column("error", sa.Text),
    )

    op.create_table("raw_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("raw_data", JSONB, nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.create_index("ix_raw_items_content_hash", "raw_items", ["content_hash"])

    op.create_table("normalized_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("raw_item_id", sa.Integer, sa.ForeignKey("raw_items.id"), unique=True, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("canonical_url", sa.Text, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("language", sa.String(10)),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("url_hash", sa.String(64), server_default=""),
        sa.Column("is_duplicate", sa.Boolean, server_default=sa.text("false")),
        sa.Column("duplicate_of_id", sa.Integer, sa.ForeignKey("normalized_items.id")),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_normalized_items_content_hash", "normalized_items", ["content_hash"])
    op.create_index("ix_normalized_items_url_hash", "normalized_items", ["url_hash"])


def downgrade() -> None:
    op.drop_table("normalized_items")
    op.drop_index("ix_raw_items_content_hash", table_name="raw_items")
    op.drop_table("raw_items")
    op.drop_table("collection_runs")
    op.drop_table("collection_cursors")
    op.drop_table("source_credentials")
    op.drop_table("sources")

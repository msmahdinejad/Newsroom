"""Production — authoritative source workbook inventory + source identity linkage.

Adds the ``source_inventory`` table (one row per reviewed workbook source,
and extends ``sources`` with a stable normalized identity
that is independent of display name, plus workbook linkage columns.

The inventory is the reconciliation authority: every workbook row is
accounted for as active, inactive, or invalid. Disabling a source never
removes its historical raw items — the ``sources`` row is retained with
``enabled=False``.

Existing source-state vocabulary is reused (configured/healthy/degraded/
unavailable on ``sources``; active/inactive/invalid on the inventory).

Revision ID: 0009_gate6_source_inventory
Revises: 0008_gate5x_x_ingestion
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_gate6_source_inventory"
down_revision: str | None = "0008_gate5x_x_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Extend sources with stable identity + workbook linkage ──
    # stable_identity is a deterministic hash of (platform, normalized
    # handle/URL) — survives handle renames and duplicate display names.
    op.add_column("sources", sa.Column("stable_identity", sa.String(64), nullable=True))
    op.add_column("sources", sa.Column("workbook_id", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("platform", sa.String(50), nullable=True))
    op.add_column("sources", sa.Column("inactive_reason", sa.String(100), nullable=True))
    op.create_index("ix_sources_stable_identity", "sources", ["stable_identity"], unique=True)
    op.create_index("ix_sources_workbook_id", "sources", ["workbook_id"])
    op.create_index("ix_sources_platform", "sources", ["platform"])

    # ── Authoritative source inventory ──
    op.create_table(
        "source_inventory",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workbook_id", sa.Integer, nullable=False, unique=True, index=True),
        sa.Column("platform", sa.String(50), nullable=False, index=True),
        sa.Column("workbook_type", sa.String(50), nullable=False, server_default=""),
        sa.Column("name", sa.String(500), nullable=False, server_default=""),
        sa.Column("handle", sa.String(255), nullable=True),
        sa.Column("public_url", sa.Text, nullable=False, server_default=""),
        sa.Column("topic", sa.String(200), nullable=True),
        sa.Column("tags", sa.Text, nullable=True),
        sa.Column("language", sa.String(30), nullable=True),
        sa.Column("content_mode", sa.String(30), nullable=True),
        sa.Column("review_level", sa.String(50), nullable=True),
        sa.Column("verification", sa.Text, nullable=True),
        sa.Column("discovery_source", sa.Text, nullable=True),
        sa.Column("tier", sa.String(30), nullable=True, index=True),
        sa.Column("coverage_score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("risk", sa.String(30), nullable=True),
        sa.Column("speed", sa.Integer, nullable=True),
        sa.Column("informal", sa.Integer, nullable=True),
        sa.Column("noise", sa.Integer, nullable=True),
        sa.Column("is_community", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_opensource_api", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("stable_identity", sa.String(64), nullable=False),
        sa.Column("mapped_type", sa.String(50), nullable=False, server_default=""),
        sa.Column("validation_result", sa.String(50), nullable=False, server_default="ok"),
        sa.Column("validation_detail", sa.Text, nullable=True),
        sa.Column("operational_state", sa.String(30), nullable=False, server_default="inactive"),
        sa.Column("inactive_reason", sa.String(100), nullable=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=True, index=True),
        sa.Column(
            "imported_at",
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
    op.create_index(
        "ix_source_inventory_stable_identity",
        "source_inventory",
        ["stable_identity"],
    )
    op.create_index("ix_source_inventory_validation", "source_inventory", ["validation_result"])
    op.create_index("ix_source_inventory_state", "source_inventory", ["operational_state"])


def downgrade() -> None:
    op.drop_index("ix_source_inventory_state", table_name="source_inventory")
    op.drop_index("ix_source_inventory_validation", table_name="source_inventory")
    op.drop_index("ix_source_inventory_stable_identity", table_name="source_inventory")
    op.drop_table("source_inventory")
    op.drop_index("ix_sources_platform", table_name="sources")
    op.drop_index("ix_sources_workbook_id", table_name="sources")
    op.drop_index("ix_sources_stable_identity", table_name="sources")
    op.drop_column("sources", "inactive_reason")
    op.drop_column("sources", "platform")
    op.drop_column("sources", "workbook_id")
    op.drop_column("sources", "stable_identity")

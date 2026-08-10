"""Add non-secret per-digest editorial preferences.

Revision ID: 0015_digest_editorial_config
Revises: 0014_source_discovery
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_digest_editorial_config"
down_revision: str | None = "0014_source_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "digest_definitions",
        sa.Column(
            "editorial_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("digest_definitions", "editorial_config")

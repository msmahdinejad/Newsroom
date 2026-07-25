"""Remove raw Telegram identities from durable bot audit state.

Revision ID: 0011_gate7_identity_privacy
Revises: 0010_gate6_router_reliability
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_gate7_identity_privacy"
down_revision: str | None = "0010_gate6_router_reliability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("telegram_updates", "command_requests"):
        op.add_column(
            table_name,
            sa.Column("user_fingerprint", sa.String(64), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("chat_fingerprint", sa.String(64), nullable=True),
        )

    # Legacy request keys embedded raw identities. Replace them before the raw
    # columns are removed. Historical fingerprints intentionally remain NULL:
    # deriving them inside PostgreSQL would require retaining the raw values in
    # migration history or server-side configuration.
    op.execute(
        sa.text(
            "UPDATE command_requests "
            "SET request_key = 'legacy-' || id::text"
        )
    )

    for table_name in ("telegram_updates", "command_requests"):
        op.drop_column(table_name, "chat_id")
        op.drop_column(table_name, "user_id")


def downgrade() -> None:
    for table_name in ("telegram_updates", "command_requests"):
        op.add_column(table_name, sa.Column("user_id", sa.BigInteger(), nullable=True))
        op.add_column(table_name, sa.Column("chat_id", sa.String(100), nullable=True))
        op.drop_column(table_name, "chat_fingerprint")
        op.drop_column(table_name, "user_fingerprint")

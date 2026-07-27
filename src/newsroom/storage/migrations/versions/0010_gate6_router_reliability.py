"""Production multi-provider router reliability and source validation state.

Only safe operational metadata is stored. Provider access values, request
headers, prompts, responses, and raw provider errors have no columns here.

Revision ID: 0010_gate6_router_reliability
Revises: 0009_gate6_source_inventory
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010_gate6_router_reliability"
down_revision: str | None = "0009_gate6_source_inventory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("last_attempt_at", sa.DateTime(timezone=True)))
    op.add_column(
        "sources",
        sa.Column(
            "validation_status",
            sa.String(30),
            nullable=False,
            server_default="untested",
        ),
    )
    op.add_column("sources", sa.Column("failure_category", sa.String(50)))
    op.add_column("sources", sa.Column("no_cursor_reason", sa.String(100)))
    op.create_index("ix_sources_last_attempt_at", "sources", ["last_attempt_at"])
    op.create_index("ix_sources_validation_status", "sources", ["validation_status"])

    # Preserve the strongest available historical attempt evidence. Sources
    # with neither timestamp remain honestly untested.
    op.execute(
        """
        UPDATE sources
        SET last_attempt_at = CASE
                WHEN last_success_at IS NULL THEN last_error_at
                WHEN last_error_at IS NULL THEN last_success_at
                ELSE GREATEST(last_success_at, last_error_at)
            END,
            validation_status = CASE
                WHEN last_success_at IS NULL AND last_error_at IS NULL THEN 'untested'
                WHEN last_error_at IS NULL THEN 'valid'
                WHEN last_success_at IS NULL THEN 'failed'
                WHEN last_success_at >= last_error_at THEN 'valid'
                ELSE 'failed'
            END
        """
    )

    op.create_table(
        "provider_model_health",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(150), nullable=False),
        sa.Column("validation_status", sa.String(30), nullable=False, server_default="unavailable"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_category", sa.String(50)),
        sa.Column("supported_capabilities", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "model", name="uq_provider_model_health_route"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_provider_model_health_nonnegative_latency"),
    )
    op.create_index(
        "ix_provider_model_health_validation",
        "provider_model_health",
        ["validation_status", "enabled"],
    )

    op.create_table(
        "provider_key_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("key_fingerprint", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_use_at", sa.DateTime(timezone=True)),
        sa.Column("failure_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column("last_failure_category", sa.String(50)),
        sa.Column("success_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "key_fingerprint", name="uq_provider_key_fingerprint"),
        sa.CheckConstraint(
            "key_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_provider_key_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "failure_count >= 0 AND success_count >= 0",
            name="ck_provider_key_nonnegative_counts",
        ),
    )
    op.create_index("ix_provider_key_state_cooldown", "provider_key_state", ["cooldown_until"])

    op.create_table(
        "provider_quota_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(150), nullable=False, server_default=""),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("rpm_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tpm_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rpd_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reserved_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("window_started_at", sa.DateTime(timezone=True)),
        sa.Column("day_started_at", sa.DateTime(timezone=True)),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "provider", "model", "scope_fingerprint", name="uq_provider_model_quota_scope"
        ),
        sa.CheckConstraint(
            "scope_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_provider_quota_scope_sha256",
        ),
        sa.CheckConstraint(
            "rpm_used >= 0 AND tpm_used >= 0 AND rpd_used >= 0 AND reserved_tokens >= 0",
            name="ck_provider_quota_nonnegative_counts",
        ),
    )
    op.create_index("ix_provider_quota_state_cooldown", "provider_quota_state", ["cooldown_until"])

    op.create_table(
        "provider_circuit_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False, unique=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="closed"),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column("last_failure_category", sa.String(50)),
        sa.Column("half_open_probe_in_flight", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "state IN ('closed', 'open', 'half_open')",
            name="ck_provider_circuit_state",
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_provider_circuit_nonnegative_failures",
        ),
    )
    op.create_index("ix_provider_circuit_cooldown", "provider_circuit_state", ["cooldown_until"])

    op.create_table(
        "provider_route_attempts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.String(100), nullable=False),
        sa.Column("editorial_job_id", sa.String(100)),
        sa.Column("shard_id", sa.String(100)),
        sa.Column("report_id", sa.Integer),
        sa.Column("artifact_id", sa.Integer),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(150), nullable=False, server_default=""),
        sa.Column("key_fingerprint", sa.String(64)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("failure_category", sa.String(50)),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("estimated_input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("actual_input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("actual_output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("retry_after_seconds", sa.Float),
        sa.Column("accepted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "key_fingerprint IS NULL OR key_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_provider_attempt_key_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0 AND estimated_input_tokens >= 0 "
            "AND actual_input_tokens >= 0 AND actual_output_tokens >= 0 "
            "AND (retry_after_seconds IS NULL OR retry_after_seconds >= 0)",
            name="ck_provider_attempt_nonnegative_usage",
        ),
    )
    op.create_index("ix_provider_route_attempt_event", "provider_route_attempts", ["event_id"], unique=True)
    op.create_index("ix_provider_route_attempt_job", "provider_route_attempts", ["editorial_job_id"])
    op.create_index("ix_provider_route_attempt_shard", "provider_route_attempts", ["shard_id"])
    op.create_index("ix_provider_route_attempt_report", "provider_route_attempts", ["report_id"])
    op.create_index("ix_provider_route_attempt_artifact", "provider_route_attempts", ["artifact_id"])
    op.create_index("ix_provider_route_attempt_stage", "provider_route_attempts", ["stage"])
    op.create_index("ix_provider_route_attempt_provider", "provider_route_attempts", ["provider"])

    # These invariants close the last concurrent idempotency gaps. Abort rather
    # than silently deleting historical evidence if pre-existing duplicates
    # are ever found.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM deliveries
                GROUP BY report_id, chat_id HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'duplicate delivery identities require manual reconciliation';
            END IF;
            IF EXISTS (
                SELECT 1 FROM editorial_artifact_lineage
                GROUP BY artifact_id, story_id, evidence_ref_id HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'duplicate artifact lineage requires manual reconciliation';
            END IF;
        END $$
        """
    )
    op.create_unique_constraint(
        "uq_delivery_report_chat",
        "deliveries",
        ["report_id", "chat_id"],
    )
    op.create_unique_constraint(
        "uq_editorial_artifact_lineage_identity",
        "editorial_artifact_lineage",
        ["artifact_id", "story_id", "evidence_ref_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_editorial_artifact_lineage_identity",
        "editorial_artifact_lineage",
        type_="unique",
    )
    op.drop_constraint("uq_delivery_report_chat", "deliveries", type_="unique")

    op.drop_index("ix_provider_route_attempt_provider", table_name="provider_route_attempts")
    op.drop_index("ix_provider_route_attempt_stage", table_name="provider_route_attempts")
    op.drop_index("ix_provider_route_attempt_shard", table_name="provider_route_attempts")
    op.drop_index("ix_provider_route_attempt_job", table_name="provider_route_attempts")
    op.drop_index("ix_provider_route_attempt_artifact", table_name="provider_route_attempts")
    op.drop_index("ix_provider_route_attempt_report", table_name="provider_route_attempts")
    op.drop_index("ix_provider_route_attempt_event", table_name="provider_route_attempts")
    op.drop_table("provider_route_attempts")
    op.drop_index("ix_provider_circuit_cooldown", table_name="provider_circuit_state")
    op.drop_table("provider_circuit_state")
    op.drop_index("ix_provider_quota_state_cooldown", table_name="provider_quota_state")
    op.drop_table("provider_quota_state")
    op.drop_index("ix_provider_key_state_cooldown", table_name="provider_key_state")
    op.drop_table("provider_key_state")
    op.drop_index("ix_provider_model_health_validation", table_name="provider_model_health")
    op.drop_table("provider_model_health")

    op.drop_index("ix_sources_validation_status", table_name="sources")
    op.drop_index("ix_sources_last_attempt_at", table_name="sources")
    op.drop_column("sources", "no_cursor_reason")
    op.drop_column("sources", "failure_category")
    op.drop_column("sources", "validation_status")
    op.drop_column("sources", "last_attempt_at")

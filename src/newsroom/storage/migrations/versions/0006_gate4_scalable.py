"""Editorial scalable editorial: material version, jobs, shards, artifacts, lineage.

Revision ID: 0006_gate4_scalable
Revises: 0005_gate4_editorial
Create Date: 2026-07-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0006_gate4_scalable"
down_revision = "0005_gate4_editorial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add material_version to stories for delivered-story change tracking
    op.add_column(
        "stories",
        sa.Column("material_version", sa.Integer, nullable=False, server_default="1"),
    )
    op.add_column(
        "stories",
        sa.Column("material_change_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_stories_material_version", "stories", ["material_version"])
    op.create_index("ix_stories_material_change_at", "stories", ["material_change_at"])

    # 2. Editorial jobs — top-level persistent job for a report
    op.create_table(
        "editorial_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("report_mode", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        # pending/running/validated/failed_retryable/failed_permanent/fallback/completed/superseded
        sa.Column("candidate_story_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("excluded_as_delivered_count", sa.Integer, server_default="0"),
        sa.Column("materially_updated_count", sa.Integer, server_default="0"),
        sa.Column("selected_count", sa.Integer, server_default="0"),
        sa.Column("omitted_count", sa.Integer, server_default="0"),
        sa.Column("shard_count", sa.Integer, server_default="0"),
        sa.Column("partition_version", sa.String(30), nullable=False),
        sa.Column("reduction_depth", sa.Integer, server_default="0"),
        sa.Column("max_reduction_depth", sa.Integer, server_default="3"),
        sa.Column("total_model_calls", sa.Integer, server_default="0"),
        sa.Column("total_input_tokens", sa.Integer, server_default="0"),
        sa.Column("total_output_tokens", sa.Integer, server_default="0"),
        sa.Column("max_input_token_budget", sa.Integer, nullable=False),
        sa.Column("max_output_token_budget", sa.Integer, nullable=False),
        sa.Column("map_call_budget", sa.Integer, nullable=False),
        sa.Column("reduction_call_budget", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_id", sa.Integer, sa.ForeignKey("reports.id"), nullable=True),
        sa.Column("fallback_used", sa.Boolean, server_default="false"),
        sa.Column("partial_ai", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 3. Editorial shards — bounded partition for one AI call
    op.create_table(
        "editorial_shards",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_db_id", sa.Integer, sa.ForeignKey("editorial_jobs.id"), nullable=False, index=True),
        sa.Column("shard_id", sa.String(100), nullable=False),
        sa.Column("shard_sequence", sa.Integer, nullable=False),
        sa.Column("total_shards", sa.Integer, nullable=False),
        sa.Column("story_ids", JSONB, nullable=False),
        sa.Column("evidence_ref_ids", JSONB, nullable=False),
        sa.Column("evidence_set_hash", sa.String(64), nullable=False),
        sa.Column("estimated_input_tokens", sa.Integer, nullable=False),
        sa.Column("effective_input_limit", sa.Integer, nullable=False),
        sa.Column("effective_output_limit", sa.Integer, nullable=False),
        sa.Column("prompt_version", sa.String(30), nullable=False),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("partition_version", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        # pending/running/validated/failed_retryable/failed_permanent/fallback/superseded/completed
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("max_retries", sa.Integer, server_default="2"),
        sa.Column("lease_owner", sa.String(100), nullable=True),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("artifact_id", sa.Integer, nullable=True),
        sa.Column("error_category", sa.String(50), nullable=True),
        sa.Column("error_summary", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, server_default="0"),
        sa.Column("usage", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("job_db_id", "shard_id", name="uq_editorial_shard_id"),
    )

    # 4. Editorial artifacts — validated outputs from map or reduce stages
    op.create_table(
        "editorial_artifacts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_db_id", sa.Integer, sa.ForeignKey("editorial_jobs.id"), nullable=False, index=True),
        sa.Column("shard_id", sa.String(100), nullable=True),
        sa.Column("artifact_type", sa.String(30), nullable=False),
        # map/reduction_topic/reduction_final
        sa.Column("reduction_level", sa.Integer, server_default="0"),
        sa.Column("output_json", JSONB, nullable=False),
        sa.Column("story_ids", JSONB, nullable=False),
        sa.Column("evidence_ref_ids", JSONB, nullable=False),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("prompt_version", sa.String(30), nullable=False),
        sa.Column("validation_result", sa.Text, nullable=True),
        sa.Column("grounding_result", sa.Text, nullable=True),
        sa.Column("cache_key", sa.String(128), nullable=True, unique=True, index=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("usage", JSONB, nullable=True),
        sa.Column("latency_ms", sa.Integer, server_default="0"),
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="validated"),
        # validated/failed/superseded
        sa.Column("child_artifact_ids", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 5. Editorial artifact lineage — evidence traceability
    op.create_table(
        "editorial_artifact_lineage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("artifact_id", sa.Integer, sa.ForeignKey("editorial_artifacts.id"), nullable=False, index=True),
        sa.Column("story_id", sa.Integer, nullable=False, index=True),
        sa.Column("evidence_ref_id", sa.String(100), nullable=False),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 6. Index for delivery-status-based story lookup
    op.create_index(
        "ix_deliveries_status_report",
        "deliveries",
        ["status", "report_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_deliveries_status_report", table_name="deliveries")
    op.drop_table("editorial_artifact_lineage")
    op.drop_table("editorial_artifacts")
    op.drop_table("editorial_shards")
    op.drop_table("editorial_jobs")
    op.drop_index("ix_stories_material_change_at", table_name="stories")
    op.drop_index("ix_stories_material_version", table_name="stories")
    op.drop_column("stories", "material_change_at")
    op.drop_column("stories", "material_version")

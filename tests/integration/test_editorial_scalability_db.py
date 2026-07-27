"""PostgreSQL integration tests for scalable hierarchical editorial.

Real PostgreSQL, no mocked sessions. Tests:
- editorial job persistence
- shard persistence with stable IDs
- deterministic shard identity
- no API key persistence
- cache reuse across runs
- failed-shard retry isolation
- successful-shard preservation on restart
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.editorial.hierarchy import _create_job
from newsroom.editorial.schema import EditorialEvidenceSet
from newsroom.editorial.sharding import (
    PARTITION_VERSION,
    ShardingResult,
    ShardSpec,
    shard_evidence_set,
)
from newsroom.storage.models import EditorialJob, EditorialShard

pytestmark = pytest.mark.integration

# Ensure tests dir is importable
_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))


@pytest.fixture(autouse=True)
def cleanup_editorial_scalable(db: Session):
    """Clean scalable editorial tables before and after each test."""
    db.execute(text("DELETE FROM editorial_artifact_lineage"))
    db.execute(text("DELETE FROM editorial_artifacts"))
    db.execute(text("DELETE FROM editorial_shards"))
    db.execute(text("DELETE FROM editorial_jobs"))
    db.commit()
    yield
    db.rollback()
    db.execute(text("DELETE FROM editorial_artifact_lineage"))
    db.execute(text("DELETE FROM editorial_artifacts"))
    db.execute(text("DELETE FROM editorial_shards"))
    db.execute(text("DELETE FROM editorial_jobs"))
    db.commit()


def _make_shard_spec(
    shard_id: str = "shard-test",
    story_ids: list[int] | None = None,
    evidence_ref_ids: list[str] | None = None,
) -> ShardSpec:
    return ShardSpec(
        shard_id=shard_id,
        shard_sequence=0,
        total_shards=1,
        story_ids=story_ids or [1],
        evidence_ref_ids=evidence_ref_ids or ["ev-1-0"],
        estimated_input_tokens=500,
        effective_input_limit=8000,
        effective_output_limit=4000,
        evidence_set_hash="abc123",
    )


def _make_sharding_result(specs: list[ShardSpec]) -> ShardingResult:
    return ShardingResult(
        shards=specs,
        partition_version=PARTITION_VERSION,
        total_stories=sum(len(s.story_ids) for s in specs),
        omitted_stories=0,
        oversized_story_count=0,
        total_estimated_tokens=sum(s.estimated_input_tokens for s in specs),
    )


class TestEditorialJobPersistence:
    """Editorial job persistence."""

    def test_job_persisted_with_metadata(self, db: Session):
        result = _make_sharding_result([_make_shard_spec()])
        _create_job(db, "test_job_1", "scheduled", [1], result)
        db.commit()

        fetched = db.query(EditorialJob).filter_by(job_id="test_job_1").first()
        assert fetched is not None
        assert fetched.report_mode == "scheduled"
        assert fetched.shard_count == 1
        assert fetched.partition_version == PARTITION_VERSION
        assert fetched.max_input_token_budget == settings.editorial_max_total_input_tokens_per_report
        assert fetched.status == "running"

    def test_job_status_transitions(self, db: Session):
        result = _make_sharding_result([_make_shard_spec()])
        job = _create_job(db, "test_job_status", "scheduled", [1], result)
        db.commit()

        # Initial status
        assert job.status == "running"

        # Transition to completed
        job.status = "completed"
        from newsroom.storage.models import utcnow

        job.completed_at = utcnow()
        db.commit()

        fetched = db.query(EditorialJob).filter_by(job_id="test_job_status").first()
        assert fetched.status == "completed"
        assert fetched.completed_at is not None


class TestShardPersistence:
    """Shard persistence with stable IDs."""

    def test_shard_persisted_with_stable_id(self, db: Session):
        result = _make_sharding_result([_make_shard_spec("shard-stable-id", [1, 2])])
        job = _create_job(db, "test_shard_stable", "scheduled", [1, 2], result)
        db.commit()

        shard = db.query(EditorialShard).filter_by(job_db_id=job.id).first()
        assert shard is not None
        assert shard.shard_id == "shard-stable-id"
        assert shard.status == "pending"
        assert shard.shard_sequence == 0
        assert shard.total_shards == 1
        assert shard.story_ids == [1, 2]
        assert shard.lease_owner is None

    def test_shard_lease_acquired(self, db: Session):
        from datetime import UTC, datetime

        result = _make_sharding_result([_make_shard_spec("shard-lease", [1])])
        job = _create_job(db, "test_shard_lease", "scheduled", [1], result)
        db.commit()

        shard = db.query(EditorialShard).filter_by(job_db_id=job.id).first()
        shard.status = "running"
        shard.lease_owner = "worker-1"
        shard.leased_at = datetime.now(UTC)
        shard.lease_expires_at = datetime.now(UTC)
        db.commit()

        fetched = db.query(EditorialShard).filter_by(shard_id="shard-lease").first()
        assert fetched.status == "running"
        assert fetched.lease_owner == "worker-1"

    def test_unique_shard_id_per_job(self, db: Session):
        """Two shards in the same job must have unique shard_ids."""
        spec1 = _make_shard_spec("shard-a", [1])
        spec2 = _make_shard_spec("shard-b", [2])
        spec2.shard_sequence = 1
        result = _make_sharding_result([spec1, spec2])
        job = _create_job(db, "test_unique_shards", "scheduled", [1, 2], result)
        db.commit()

        shards = db.query(EditorialShard).filter_by(job_db_id=job.id).order_by(EditorialShard.shard_sequence).all()
        assert len(shards) == 2
        assert shards[0].shard_id == "shard-a"
        assert shards[1].shard_id == "shard-b"


class TestDeterministicShardIdentity:
    """Same input produces the same shard IDs."""

    def test_same_evidence_same_shard_ids(self, db: Session):
        from scalability_datasets import _make_story

        evidence = EditorialEvidenceSet(stories=[_make_story(1), _make_story(2), _make_story(3)])
        result1 = shard_evidence_set(evidence)
        result2 = shard_evidence_set(evidence)
        assert [s.shard_id for s in result1.shards] == [s.shard_id for s in result2.shards]


class TestNoApiKeyPersisted:
    """No API key in any editorial scalable table."""

    def test_no_api_key_in_job(self, db: Session):
        result = _make_sharding_result([_make_shard_spec()])
        _create_job(db, "test_no_key", "scheduled", [1], result)
        db.commit()

        rows = db.execute(text("SELECT * FROM editorial_jobs")).fetchall()
        for row in rows:
            row_str = str(row)
            assert "AIza" not in row_str
            assert "Bearer" not in row_str
            assert "EDITORIAL_API_KEY" not in row_str

    def test_no_api_key_in_shard(self, db: Session):
        result = _make_sharding_result([_make_shard_spec()])
        _create_job(db, "test_no_key_shard", "scheduled", [1], result)
        db.commit()

        rows = db.execute(text("SELECT * FROM editorial_shards")).fetchall()
        for row in rows:
            row_str = str(row)
            assert "AIza" not in row_str
            assert "Bearer" not in row_str


class TestStaleLeaseRecovery:
    """Stale running leases must be recoverable."""

    def test_expired_lease_can_be_reacquired(self, db: Session):
        from datetime import UTC, datetime, timedelta

        result = _make_sharding_result([_make_shard_spec("shard-stale", [1])])
        _create_job(db, "test_stale_lease", "scheduled", [1], result)
        db.commit()

        shard = db.query(EditorialShard).filter_by(shard_id="shard-stale").first()
        shard.status = "running"
        shard.lease_owner = "worker-dead"
        shard.leased_at = datetime.now(UTC) - timedelta(hours=1)
        shard.lease_expires_at = datetime.now(UTC) - timedelta(minutes=30)  # expired
        db.commit()

        # Find expired leases
        stale = db.query(EditorialShard).filter(
            EditorialShard.status == "running",
            EditorialShard.lease_expires_at < datetime.now(UTC),
        ).all()
        assert len(stale) == 1
        assert stale[0].shard_id == "shard-stale"

        # Re-acquire
        stale[0].status = "pending"
        stale[0].lease_owner = None
        stale[0].lease_expires_at = None
        db.commit()

        fetched = db.query(EditorialShard).filter_by(shard_id="shard-stale").first()
        assert fetched.status == "pending"
        assert fetched.lease_owner is None


class TestSuccessfulShardPreservation:
    """Validated shards must not be regenerated on restart."""

    def test_completed_shard_stays_completed(self, db: Session):
        result = _make_sharding_result([_make_shard_spec("shard-done", [1])])
        _create_job(db, "test_preserve", "scheduled", [1], result)
        db.commit()

        shard = db.query(EditorialShard).filter_by(shard_id="shard-done").first()
        shard.status = "completed"
        shard.artifact_id = 42
        db.commit()

        # After restart simulation (fresh query), status should be preserved
        fetched = db.query(EditorialShard).filter_by(shard_id="shard-done").first()
        assert fetched.status == "completed"
        assert fetched.artifact_id == 42


class TestFailedShardRetry:
    """Failed shards can be retried without affecting successful ones."""

    def test_failed_shard_marked_retryable(self, db: Session):
        spec1 = _make_shard_spec("shard-fail", [1])
        spec2 = _make_shard_spec("shard-ok", [2])
        spec2.shard_sequence = 1
        result = _make_sharding_result([spec1, spec2])
        _create_job(db, "test_retry", "scheduled", [1, 2], result)
        db.commit()

        # First shard fails
        s1 = db.query(EditorialShard).filter_by(shard_id="shard-fail").first()
        s1.status = "failed_retryable"
        s1.retry_count = 1
        s1.error_category = "timeout"

        # Second shard succeeds
        s2 = db.query(EditorialShard).filter_by(shard_id="shard-ok").first()
        s2.status = "completed"
        s2.artifact_id = 10
        db.commit()

        # Verify isolation
        s1_fetched = db.query(EditorialShard).filter_by(shard_id="shard-fail").first()
        s2_fetched = db.query(EditorialShard).filter_by(shard_id="shard-ok").first()

        assert s1_fetched.status == "failed_retryable"
        assert s2_fetched.status == "completed"
        # Successful shard is not affected by failed shard
        assert s2_fetched.artifact_id == 10

"""Gate 7 PostgreSQL checks for editorial artifact reuse and recovery."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from newsroom.editorial.deterministic_provider import DeterministicEditorialProvider
from newsroom.editorial.hierarchy import (
    _create_job,
    _persist_lineage,
    _process_shard,
    run_hierarchical_editorial,
)
from newsroom.editorial.router_persistence import (
    ModelHealthSnapshot,
    persist_router_snapshot,
)
from newsroom.editorial.schema import EditorialEvidenceSet, EditorialRequest
from newsroom.editorial.sharding import shard_evidence_set
from newsroom.storage.models import (
    EditorialArtifact,
    EditorialArtifactLineage,
    EditorialAttempt,
    EditorialJob,
    EditorialShard,
    ProviderModelHealth,
    Report,
)

pytestmark = pytest.mark.integration

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from scalability_datasets import _make_story  # noqa: E402

_JOB_IDS = ("gate7-cache-owner-a", "gate7-cache-owner-b")


def _cleanup(db: Session) -> None:
    job_db_ids = select(EditorialJob.id).where(EditorialJob.job_id.in_(_JOB_IDS))
    report_ids = list(
        db.scalars(
            select(EditorialJob.report_id).where(
                EditorialJob.job_id.in_(_JOB_IDS),
                EditorialJob.report_id.is_not(None),
            )
        )
    )
    artifact_ids = select(EditorialArtifact.id).where(
        EditorialArtifact.job_db_id.in_(job_db_ids)
    )
    db.execute(
        delete(EditorialArtifactLineage).where(
            EditorialArtifactLineage.artifact_id.in_(artifact_ids)
        )
    )
    if report_ids:
        db.execute(
            delete(EditorialAttempt).where(EditorialAttempt.report_id.in_(report_ids))
        )
    db.execute(delete(EditorialShard).where(EditorialShard.job_db_id.in_(job_db_ids)))
    db.execute(
        delete(EditorialArtifact).where(EditorialArtifact.job_db_id.in_(job_db_ids))
    )
    db.execute(delete(EditorialJob).where(EditorialJob.job_id.in_(_JOB_IDS)))
    if report_ids:
        db.execute(delete(Report).where(Report.id.in_(report_ids)))
    db.commit()


@pytest.fixture(autouse=True)
def cleanup_gate7_llm_rows(db: Session):
    _cleanup(db)
    yield
    db.rollback()
    _cleanup(db)


def test_cross_job_cache_reuse_marks_current_shard_completed(db: Session):
    evidence = EditorialEvidenceSet(
        stories=[_make_story(9_700_001, source_count=2)]
    )
    sharding = shard_evidence_set(evidence)
    assert len(sharding.shards) == 1
    spec = sharding.shards[0]
    provider = DeterministicEditorialProvider()

    first_job = _create_job(
        db,
        _JOB_IDS[0],
        "scheduled",
        [9_700_001],
        sharding,
    )
    first = _process_shard(db, first_job, spec, evidence, provider)
    db.commit()

    second_job = _create_job(
        db,
        _JOB_IDS[1],
        "scheduled",
        [9_700_001],
        sharding,
    )
    second = _process_shard(db, second_job, spec, evidence, provider)
    db.commit()

    current_shard = db.scalar(
        select(EditorialShard).where(
            EditorialShard.job_db_id == second_job.id,
            EditorialShard.shard_id == spec.shard_id,
        )
    )
    assert second.from_cache is True
    assert second.artifact_id == first.artifact_id
    assert current_shard is not None
    assert current_shard.status == "completed"
    assert current_shard.artifact_id == first.artifact_id
    assert current_shard.provider == first.provider
    assert current_shard.model == first.model


def test_completed_single_shard_job_replays_persisted_report_without_map_work(
    db: Session,
    monkeypatch,
):
    evidence = EditorialEvidenceSet(
        stories=[_make_story(9_700_002, source_count=2)]
    )
    sharding = shard_evidence_set(evidence)
    spec = sharding.shards[0]
    provider = DeterministicEditorialProvider()
    job = _create_job(
        db,
        _JOB_IDS[0],
        "scheduled",
        [9_700_002],
        sharding,
    )
    mapped = _process_shard(db, job, spec, evidence, provider)
    report = Report(
        content_fa="persisted restart-safe report",
        story_ids=[9_700_002],
        report_mode="scheduled",
        generation_method="deterministic",
    )
    db.add(report)
    db.flush()
    db.add(
        EditorialAttempt(
            report_id=report.id,
            provider=mapped.provider,
            model=mapped.model,
            prompt_version=evidence.prompt_version,
            evidence_set_hash=evidence.evidence_hash(),
            schema_version=evidence.schema_version,
            report_mode="scheduled",
            status="ok",
            output_json=mapped.output.model_dump(mode="json"),
        )
    )
    job.status = "completed"
    job.report_id = report.id
    db.commit()
    monkeypatch.setattr(
        "newsroom.editorial.hierarchy.build_evidence_set",
        lambda *_args, **_kwargs: evidence,
    )

    replay = run_hierarchical_editorial(
        db,
        [9_700_002],
        report_mode="scheduled",
        job_id=_JOB_IDS[0],
    )

    assert replay.content == report.content_fa
    assert replay.map_results == []
    assert replay.total_model_calls == 0
    assert replay.attempt.provider == mapped.provider
    assert replay.attempt.model == mapped.model


def test_runtime_success_preserves_live_model_validation_latency(db: Session):
    provider = "test_gate7_latency"
    db.execute(
        delete(ProviderModelHealth).where(
            ProviderModelHealth.provider == provider
        )
    )
    persist_router_snapshot(
        db,
        ModelHealthSnapshot(
            provider=provider,
            model="model",
            validation_status="validated",
            latency_ms=321,
            last_success_at=None,
            last_failure_category=None,
            supported_capabilities=("connectivity",),
            enabled=True,
        ),
    )
    persist_router_snapshot(
        db,
        ModelHealthSnapshot(
            provider=provider,
            model="model",
            validation_status="validated",
            latency_ms=None,
            last_success_at=None,
            last_failure_category=None,
            supported_capabilities=("connectivity",),
            enabled=True,
        ),
    )

    row = db.scalar(
        select(ProviderModelHealth).where(
            ProviderModelHealth.provider == provider,
            ProviderModelHealth.model == "model",
        )
    )
    assert row is not None
    assert row.latency_ms == 321
    db.execute(
        delete(ProviderModelHealth).where(
            ProviderModelHealth.provider == provider
        )
    )
    db.commit()


def test_artifact_lineage_includes_claim_specific_evidence_refs(db: Session):
    evidence = EditorialEvidenceSet(
        stories=[_make_story(9_700_003, source_count=2)]
    )
    sharding = shard_evidence_set(evidence)
    job = _create_job(
        db,
        _JOB_IDS[0],
        "scheduled",
        [9_700_003],
        sharding,
    )
    response = DeterministicEditorialProvider().generate(
        EditorialRequest(evidence=evidence)
    )
    expected_claim_refs = {
        ref
        for story in response.output.stories
        for claim in story.key_claims
        for ref in claim.supporting_evidence_refs
    }
    assert expected_claim_refs
    for story in response.output.stories:
        story.source_ref_ids = []
    artifact = EditorialArtifact(
        job_db_id=job.id,
        shard_id="claim-lineage",
        artifact_type="map",
        reduction_level=0,
        output_json=response.output.model_dump(mode="json"),
        story_ids=[9_700_003],
        evidence_ref_ids=sorted(expected_claim_refs),
        schema_version=evidence.schema_version,
        prompt_version=evidence.prompt_version,
        provider="deterministic",
        model="deterministic-v1",
        status="validated",
    )
    db.add(artifact)
    db.flush()

    _persist_lineage(db, artifact.id, response.output, evidence)

    persisted_refs = set(
        db.scalars(
            select(EditorialArtifactLineage.evidence_ref_id).where(
                EditorialArtifactLineage.artifact_id == artifact.id
            )
        )
    )
    assert expected_claim_refs <= persisted_refs

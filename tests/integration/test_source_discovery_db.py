"""PostgreSQL persistence for grounded, approval-gated source discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from newsroom.sources.discovery import GeminiSourceDiscovery
from newsroom.storage.models import DiscoveryJob, Source, SourceCandidate

pytestmark = pytest.mark.integration


def test_candidate_requires_approval_before_source_activation(db: Session) -> None:
    suffix = uuid4().hex[:10]
    url = f"https://example.com/{suffix}/feed.xml"
    job = DiscoveryJob(
        subject="Independent database engineering publications",
        requested_platforms=["web"],
        mode="quick",
        status="completed",
        provider="gemini",
        model="validated-model",
        candidate_count=1,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(job)
    db.flush()
    candidate = SourceCandidate(
        job_id=job.id,
        platform="web",
        source_type="rss",
        name=f"Database source {suffix}",
        url=url,
        normalized_url=url,
        rationale="A public engineering publication.",
        citations=[{"url": "https://example.com/about"}],
        score=0.8,
        validation_status="reachable",
        approval_status="pending",
    )
    db.add(candidate)
    db.flush()

    assert db.query(Source).filter(Source.url == url).first() is None

    approved = GeminiSourceDiscovery(db).approve(candidate.id)
    source = db.get(Source, approved.source_id)

    assert approved.approval_status == "approved"
    assert source is not None
    assert source.enabled is True
    assert source.type == "rss"


def test_discovery_schema_has_no_provider_access_fields() -> None:
    forbidden = {"api_key", "api_keys", "token", "secret", "credential"}
    job_columns = {column.key for column in inspect(DiscoveryJob).columns}
    candidate_columns = {column.key for column in inspect(SourceCandidate).columns}

    assert not forbidden.intersection(job_columns)
    assert not forbidden.intersection(candidate_columns)


def test_discovery_transaction_rolls_back(db: Session) -> None:
    subject = f"rollback-{uuid4().hex}"
    db.add(
        DiscoveryJob(
            subject=subject,
            requested_platforms=["web"],
            mode="quick",
            status="running",
            provider="gemini",
            model="validated-model",
        )
    )
    db.flush()
    db.rollback()

    assert db.query(DiscoveryJob).filter(DiscoveryJob.subject == subject).first() is None

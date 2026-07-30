"""PostgreSQL integration tests for Editorial editorial persistence.

Real PostgreSQL, no mocked sessions. Tests:
- editorial-attempt persistence
- prompt-version persistence
- evidence-set hash
- structured output persistence
- claim-to-evidence relationships
- unique/idempotent editorial identity
- cache reuse
- validation failure rollback
- fallback persistence
- report-delivery linkage
- no API key stored
- transaction rollback on failure
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from newsroom.editorial.orchestrator import EditorialAttempt
from newsroom.editorial.persistence import compute_cache_key, find_cached_attempt, persist_attempt
from newsroom.editorial.schema import (
    EVIDENCE_SCHEMA_VERSION,
    OUTPUT_SCHEMA_VERSION,
    SYSTEM_PROMPT_VERSION,
    ClaimStatus,
    EditorialEvidenceSet,
    EditorialOutput,
    EvidenceSourceItem,
    EvidenceStoryPacket,
    KeyClaim,
    ReportMetadata,
    StoryEditorialResult,
)
from newsroom.storage.models import EditorialAttempt as EditorialAttemptModel
from newsroom.storage.models import EditorialHealth, Report

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def cleanup_editorial_data(db: Session):
    """Clean editorial test data before and after each test."""
    db.query(EditorialAttemptModel).delete()
    db.commit()
    yield
    db.query(EditorialAttemptModel).delete()
    db.commit()


# ── Helpers ──────────────────────────────────────────────────────


def make_evidence_set(story_id: int = 1) -> EditorialEvidenceSet:
    return EditorialEvidenceSet(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        prompt_version=SYSTEM_PROMPT_VERSION,
        stories=[
            EvidenceStoryPacket(
                story_id=story_id,
                headline="Test Story",
                sources=[
                    EvidenceSourceItem(
                        ref_id=f"ev-{story_id}-0",
                        item_id=1,
                        source_name="Test",
                        source_type="rss",
                        original_url="https://example.com/test",
                    )
                ],
                facts=["Python 3.13 released"],
            )
        ],
    )


def make_output(evidence: EditorialEvidenceSet) -> EditorialOutput:
    return EditorialOutput(
        metadata=ReportMetadata(
            schema_version=OUTPUT_SCHEMA_VERSION,
            report_mode="scheduled",
            generated_at=datetime.now(UTC).isoformat(),
            model_name="test-model",
            provider="test",
            evidence_set_hash=evidence.evidence_hash(),
            prompt_version=SYSTEM_PROMPT_VERSION,
            editorial_status="ok",
        ),
        stories=[
            StoryEditorialResult(
                story_id=evidence.stories[0].story_id,
                headline_fa="\u0639\u0646\u0648\u0627\u0646 \u062a\u0633\u062a",
                summary_fa="\u062e\u0644\u0627\u0635\u0647",
                source_ref_ids=[evidence.stories[0].sources[0].ref_id],
                source_links=["https://example.com/test"],
                key_claims=[
                    KeyClaim(
                        claim_text="Python 3.13 released",
                        supporting_evidence_refs=[evidence.stories[0].sources[0].ref_id],
                        support_status=ClaimStatus.SUPPORTED,
                        confidence=0.9,
                    )
                ],
            )
        ],
    )


def make_attempt(status: str = "ok") -> EditorialAttempt:
    evidence = make_evidence_set()
    return EditorialAttempt(
        provider="test",
        model="test-model",
        prompt_version=SYSTEM_PROMPT_VERSION,
        evidence_set_hash=evidence.evidence_hash(),
        schema_version=EVIDENCE_SCHEMA_VERSION,
        status=status,
        output=make_output(evidence),
    )


# ── 1. Editorial attempt persistence ─────────────────────────────


def test_editorial_attempt_persisted(db: Session):
    """An editorial attempt is persisted with all metadata."""
    attempt = make_attempt()
    cache_key = compute_cache_key(
        "scheduled", attempt.evidence_set_hash, attempt.prompt_version, "test", "test-model"
    )

    record = persist_attempt(db, attempt, report_id=None, cache_key=cache_key)
    db.commit()

    assert record.id is not None
    assert record.provider == "test"
    assert record.model == "test-model"
    assert record.prompt_version == SYSTEM_PROMPT_VERSION
    assert record.evidence_set_hash == attempt.evidence_set_hash
    assert record.schema_version == EVIDENCE_SCHEMA_VERSION
    assert record.status == "ok"
    assert record.cache_key == cache_key


# ── 2. Prompt version persistence ─────────────────────────────────


def test_prompt_version_persisted(db: Session):
    """Prompt version is persisted in editorial attempt."""
    attempt = make_attempt()
    record = persist_attempt(db, attempt, report_id=None, cache_key="k1")
    db.commit()

    assert record.prompt_version == SYSTEM_PROMPT_VERSION


# ── 3. Evidence-set hash persistence ──────────────────────────────


def test_evidence_set_hash_persisted(db: Session):
    """Evidence set hash is persisted and indexed."""
    evidence = make_evidence_set()
    attempt = EditorialAttempt(
        provider="test",
        model="test-model",
        prompt_version=SYSTEM_PROMPT_VERSION,
        evidence_set_hash=evidence.evidence_hash(),
        schema_version=EVIDENCE_SCHEMA_VERSION,
    )
    record = persist_attempt(db, attempt, report_id=None, cache_key="k2")
    db.commit()

    # Query by hash and cache_key to get the exact record
    found = (
        db.query(EditorialAttemptModel)
        .filter_by(
            evidence_set_hash=evidence.evidence_hash(),
            cache_key="k2",
        )
        .first()
    )
    assert found is not None
    assert found.id == record.id


# ── 4. Structured output persistence ──────────────────────────────


def test_structured_output_persisted(db: Session):
    """The structured EditorialOutput is persisted as JSONB."""
    attempt = make_attempt()
    record = persist_attempt(db, attempt, report_id=None, cache_key="k3")
    db.commit()

    assert record.output_json is not None
    assert record.output_json["stories"][0]["story_id"] == 1
    assert (
        record.output_json["stories"][0]["headline"]
        == "\u0639\u0646\u0648\u0627\u0646 \u062a\u0633\u062a"
    )


# ── 5. Claim-to-evidence relationships ────────────────────────────


def test_claim_evidence_refs_persisted(db: Session):
    """Claim supporting_evidence_refs are persisted in the output JSON."""
    attempt = make_attempt()
    record = persist_attempt(db, attempt, report_id=None, cache_key="k4")
    db.commit()

    claims = record.output_json["stories"][0]["key_claims"]
    assert claims[0]["supporting_evidence_refs"] == ["ev-1-0"]


# ── 6. Unique/idempotent editorial identity ──────────────────────


def test_cache_key_unique(db: Session):
    """Cache key is unique — duplicate insert fails."""
    attempt = make_attempt()
    persist_attempt(db, attempt, report_id=None, cache_key="unique-key")
    db.commit()

    # Second attempt with same cache key should fail on unique constraint
    attempt2 = make_attempt()
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        persist_attempt(db, attempt2, report_id=None, cache_key="unique-key")
        db.commit()
    db.rollback()


# ── 7. Cache reuse ────────────────────────────────────────────────


def test_cache_reuse_finds_existing(db: Session):
    """find_cached_attempt returns existing accepted attempt."""
    attempt = make_attempt(status="ok")
    cache_key = "reuse-test-key"
    persist_attempt(db, attempt, report_id=None, cache_key=cache_key)
    db.commit()

    found = find_cached_attempt(db, cache_key)
    assert found is not None
    assert found.status == "ok"
    assert found.cache_key == cache_key


def test_cache_reuse_no_match(db: Session):
    """find_cached_attempt returns None for non-existent key."""
    found = find_cached_attempt(db, "nonexistent-key")
    assert found is None


# ── 8. Validation failure rollback ───────────────────────────────


def test_validation_failure_status_persisted(db: Session):
    """A validation failure status is persisted correctly."""
    attempt = make_attempt(status="validation_failed")
    attempt.error_category = "schema_validation"
    attempt.error_summary = "missing fields"
    record = persist_attempt(db, attempt, report_id=None, cache_key="val-fail")
    db.commit()

    assert record.status == "validation_failed"
    assert record.error_category == "schema_validation"


# ── 9. Fallback persistence ───────────────────────────────────────


def test_fallback_persisted(db: Session):
    """Fallback status and flag are persisted correctly."""
    attempt = make_attempt(status="fallback")
    attempt.fallback_used = True
    attempt.error_category = "provider_unavailable"
    attempt.error_summary = "outage"
    record = persist_attempt(db, attempt, report_id=None, cache_key="fb-key")
    db.commit()

    assert record.fallback_used is True
    assert record.status == "fallback"


# ── 10. Report-delivery linkage ───────────────────────────────────


def test_report_linkage(db: Session):
    """Editorial attempt is linked to the generated report."""
    # Create a report first
    report = Report(
        content_fa="test content",
        story_ids=[1],
        report_mode="scheduled",
        generation_method="deterministic",
    )
    db.add(report)
    db.flush()

    attempt = make_attempt()
    record = persist_attempt(db, attempt, report_id=report.id, cache_key="report-link")
    db.commit()

    assert record.report_id == report.id


# ── 11. No API key stored ─────────────────────────────────────────


def test_no_api_key_in_attempt(db: Session):
    """No API key field exists in editorial_attempts table."""
    from sqlalchemy import inspect as sa_inspect

    insp = sa_inspect(db.bind)
    columns = [c["name"] for c in insp.get_columns("editorial_attempts")]
    forbidden = {"api_key", "apikey", "secret", "token", "password", "credential"}
    for col in columns:
        col_lower = col.lower()
        for word in forbidden:
            assert word not in col_lower, f"Column '{col}' contains forbidden word '{word}'"


def test_no_api_key_in_output_json(db: Session):
    """The output JSON does not contain any API key or secret."""
    attempt = make_attempt()
    record = persist_attempt(db, attempt, report_id=None, cache_key="no-key")
    db.commit()

    import json

    output_str = json.dumps(record.output_json)
    assert "api_key" not in output_str.lower()
    assert "apikey" not in output_str.lower()
    assert "secret" not in output_str.lower()
    assert "bearer" not in output_str.lower()


# ── 12. Transaction rollback on failure ──────────────────────────


def test_transaction_rollback(db: Session):
    """Failed transaction rolls back editorial attempt."""
    attempt = make_attempt()
    try:
        persist_attempt(db, attempt, report_id=None, cache_key="rollback-test")
        # Force a failure
        db.execute(text("SELECT 1 / 0"))
        db.commit()
    except Exception:
        db.rollback()

    # The attempt should not be persisted
    found = db.query(EditorialAttemptModel).filter_by(cache_key="rollback-test").first()
    assert found is None


# ── 13. Editorial health table ────────────────────────────────────


def test_editorial_health_singleton(db: Session):
    """Editorial health table has a singleton row."""
    health = db.query(EditorialHealth).filter_by(id=1).first()
    assert health is not None


def test_editorial_health_updated(db: Session):
    """Health is updated after an attempt."""
    attempt = make_attempt(status="ok")
    persist_attempt(db, attempt, report_id=None, cache_key="health-update")
    db.commit()

    health = db.query(EditorialHealth).filter_by(id=1).first()
    assert health.last_success_at is not None
    assert health.last_latency_ms >= 0


# ── 14. Scheduled and manual report separation ───────────────────


def test_report_mode_persisted(db: Session):
    """Report mode is persisted in the editorial attempt."""
    # The report_mode field is on the model — but currently set by caller
    # We set it via the model after persist
    attempt = make_attempt()
    record = persist_attempt(db, attempt, report_id=None, cache_key="mode-test")
    record.report_mode = "manual"
    db.commit()

    found = db.query(EditorialAttemptModel).filter_by(cache_key="mode-test").first()
    assert found.report_mode == "manual"


# ── 15. (cleanup handled by fixture) ─────────────────────────────

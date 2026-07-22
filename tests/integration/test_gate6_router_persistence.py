"""Real PostgreSQL coverage for Gate 6 router reliability state."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, sessionmaker

from newsroom.editorial.router_persistence import (
    CircuitStateSnapshot,
    KeyStateSnapshot,
    ModelHealthSnapshot,
    PostgresRouterStateSink,
    QuotaStateSnapshot,
    RouteAttemptEvent,
    load_router_snapshots,
    persist_route_attempt,
    persist_router_snapshot,
)
from newsroom.storage.models import (
    Delivery,
    EditorialArtifact,
    EditorialArtifactLineage,
    EditorialJob,
    ProviderCircuitState,
    ProviderKeyState,
    ProviderModelHealth,
    ProviderQuotaState,
    ProviderRouteAttempt,
    Report,
    Source,
)

pytestmark = pytest.mark.integration

KEY_FP = "1" * 64
SECOND_KEY_FP = "2" * 64
SCOPE_FP = "a" * 64
RAW_PROVIDER_VALUE = "provider-value-must-never-persist"


@pytest.fixture(autouse=True)
def cleanup_router_test_rows(db: Session):
    _cleanup_router_rows(db)
    yield
    db.rollback()
    _cleanup_router_rows(db)


def _cleanup_router_rows(db: Session) -> None:
    db.execute(text("DELETE FROM provider_route_attempts WHERE provider LIKE 'test_%'"))
    db.execute(text("DELETE FROM provider_circuit_state WHERE provider LIKE 'test_%'"))
    db.execute(text("DELETE FROM provider_quota_state WHERE provider LIKE 'test_%'"))
    db.execute(text("DELETE FROM provider_key_state WHERE provider LIKE 'test_%'"))
    db.execute(text("DELETE FROM provider_model_health WHERE provider LIKE 'test_%'"))
    db.commit()


def test_migration_tables_and_source_attempt_columns_exist(engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "provider_model_health",
        "provider_key_state",
        "provider_quota_state",
        "provider_circuit_state",
        "provider_route_attempts",
    } <= tables
    source_columns = {column["name"] for column in inspector.get_columns("sources")}
    assert {
        "last_attempt_at",
        "validation_status",
        "failure_category",
        "no_cursor_reason",
    } <= source_columns


def test_model_health_and_key_cooldown_upsert(db: Session) -> None:
    now = datetime.now(UTC)
    persist_router_snapshot(
        db,
        ModelHealthSnapshot(
            provider="test_gemini",
            model="gemini-3.6-flash",
            validation_status="validated",
            latency_ms=125,
            last_success_at=now,
            last_failure_category=None,
            supported_capabilities=("persian", "structured", "grounding"),
            enabled=True,
        ),
    )
    persist_router_snapshot(
        db,
        KeyStateSnapshot(
            provider="test_gemini",
            key_fingerprint=KEY_FP,
            enabled=True,
            last_use_at=now,
            failure_count=1,
            cooldown_until=now + timedelta(seconds=60),
            last_failure_category="rate_limit",
            success_count=9,
        ),
    )
    db.commit()

    health = db.query(ProviderModelHealth).filter_by(provider="test_gemini").one()
    key = db.query(ProviderKeyState).filter_by(provider="test_gemini").one()
    assert health.validation_status == "validated"
    assert health.supported_capabilities == ["grounding", "persian", "structured"]
    assert key.key_fingerprint == KEY_FP
    assert key.cooldown_until is not None
    assert key.success_count == 9

    persist_router_snapshot(
        db,
        replace(
            KeyStateSnapshot(
                provider="test_gemini",
                key_fingerprint=KEY_FP,
                enabled=True,
                last_use_at=now,
                failure_count=1,
                cooldown_until=now + timedelta(seconds=60),
                last_failure_category="rate_limit",
                success_count=9,
            ),
            failure_count=0,
            cooldown_until=None,
            last_failure_category=None,
            success_count=10,
        ),
    )
    db.commit()
    assert db.query(ProviderKeyState).filter_by(provider="test_gemini").count() == 1
    assert db.query(ProviderKeyState).filter_by(provider="test_gemini").one().success_count == 10


def test_project_scope_quota_usage_reconciles_without_key_multiplication(db: Session) -> None:
    now = datetime.now(UTC)
    initial = QuotaStateSnapshot(
        provider="test_gemini",
        model="gemini-3.6-flash",
        scope_fingerprint=SCOPE_FP,
        rpm_used=2,
        tpm_used=10_000,
        rpd_used=20,
        reserved_tokens=2_000,
        window_started_at=now,
        day_started_at=now.replace(hour=0, minute=0, second=0, microsecond=0),
        cooldown_until=None,
    )
    persist_router_snapshot(db, initial)
    persist_router_snapshot(
        db,
        replace(initial, rpm_used=3, tpm_used=11_250, rpd_used=21, reserved_tokens=0),
    )
    db.commit()

    rows = db.query(ProviderQuotaState).filter_by(provider="test_gemini").all()
    assert len(rows) == 1
    assert (rows[0].rpm_used, rows[0].tpm_used, rows[0].rpd_used) == (3, 11_250, 21)
    assert rows[0].reserved_tokens == 0


def test_cooldowns_and_quota_survive_fresh_session(db: Session, engine) -> None:
    now = datetime.now(UTC)
    cooldown = now + timedelta(minutes=5)
    persist_router_snapshot(
        db,
        CircuitStateSnapshot(
            provider="test_mistral",
            state="open",
            consecutive_failures=3,
            cooldown_until=cooldown,
            last_failure_category="server_error",
            half_open_probe_in_flight=False,
        ),
    )
    persist_router_snapshot(
        db,
        QuotaStateSnapshot(
            provider="test_mistral",
            model="mistral-large-2512",
            scope_fingerprint=SCOPE_FP,
            rpm_used=7,
            tpm_used=50_000,
            rpd_used=80,
            reserved_tokens=500,
            window_started_at=now,
            day_started_at=now,
            cooldown_until=cooldown,
        ),
    )
    db.commit()

    fresh = sessionmaker(bind=engine)()
    try:
        restored = load_router_snapshots(fresh)
        circuit = next(row for row in restored.circuits if row.provider == "test_mistral")
        quota = next(row for row in restored.quotas if row.provider == "test_mistral")
        assert circuit.state == "open"
        assert circuit.cooldown_until == cooldown
        assert quota.tpm_used == 50_000
        assert quota.reserved_tokens == 500
    finally:
        fresh.close()


def test_route_attempt_is_idempotent_and_lineage_is_immutable(db: Session) -> None:
    now = datetime.now(UTC)
    started = RouteAttemptEvent(
        event_id="test-event-1",
        editorial_job_id="test-job-1",
        shard_id="test-shard-1",
        report_id=101,
        artifact_id=201,
        stage="map",
        provider="test_gemini",
        model="gemini-3.6-flash",
        key_fingerprint=KEY_FP,
        status="running",
        estimated_input_tokens=4_000,
        created_at=now,
    )
    persist_route_attempt(db, started)
    persist_route_attempt(
        db,
        replace(
            started,
            status="ok",
            latency_ms=350,
            actual_input_tokens=3_800,
            actual_output_tokens=900,
            accepted=True,
            completed_at=now + timedelta(seconds=1),
        ),
    )
    db.commit()

    row = db.query(ProviderRouteAttempt).filter_by(event_id="test-event-1").one()
    assert row.editorial_job_id == "test-job-1"
    assert row.shard_id == "test-shard-1"
    assert row.report_id == 101
    assert row.artifact_id == 201
    assert row.status == "ok"
    assert (row.actual_input_tokens, row.actual_output_tokens) == (3_800, 900)
    assert db.query(ProviderRouteAttempt).filter_by(event_id="test-event-1").count() == 1

    with pytest.raises(ValueError, match="immutable lineage"):
        persist_route_attempt(db, replace(started, model="gemini-2.5-flash"))
    db.rollback()
    assert db.query(ProviderRouteAttempt).filter_by(event_id="test-event-1").one().model == "gemini-3.6-flash"


def test_production_sink_bridge_commits_core_events_and_loads_validated_models(engine) -> None:
    from newsroom.editorial.router.types import KeyStateSnapshot as CoreKeyStateSnapshot
    from newsroom.editorial.router.types import ModelHealthSnapshot as CoreModelHealthSnapshot
    from newsroom.editorial.router.types import RouteAttemptEvent as CoreRouteAttemptEvent

    factory = sessionmaker(bind=engine)
    sink = PostgresRouterStateSink(factory)
    now = datetime.now(UTC)
    sink.record_snapshot(
        CoreModelHealthSnapshot(
            provider="test_nvidia",
            model="nvidia/nemotron-3-ultra-550b-a55b",
            validation_status="validated",
            latency_ms=210,
            last_success_at=now,
            last_failure_category=None,
            supported_capabilities=("persian", "structured"),
            enabled=True,
        )
    )
    sink.record_snapshot(
        CoreKeyStateSnapshot(
            provider="test_nvidia",
            key_fingerprint=SECOND_KEY_FP,
            safe_id="test-safe-id",
            enabled=True,
            last_use_at=now,
            failure_count=0,
            cooldown_until=None,
            last_failure_category=None,
            successful_request_count=1,
        )
    )
    sink.record_attempt(
        CoreRouteAttemptEvent(
            event_id="test-sink-event",
            job_id="test-job-sink",
            shard_id="test-shard-sink",
            stage="reduction",
            report_id=301,
            artifact_id=401,
            provider="test_nvidia",
            model="nvidia/nemotron-3-ultra-550b-a55b",
            key_fingerprint=SECOND_KEY_FP,
            status="ok",
            failure_category=None,
            latency_ms=210,
            estimated_input_tokens=1_000,
            actual_input_tokens=900,
            actual_output_tokens=300,
            retry_after_seconds=None,
            created_at=now,
        )
    )

    restored = sink.load()
    assert restored.validated_model_ids["test_nvidia"] == (
        "nvidia/nemotron-3-ultra-550b-a55b",
    )
    check = factory()
    try:
        assert check.query(ProviderRouteAttempt).filter_by(event_id="test-sink-event").count() == 1
    finally:
        check.close()


def test_persistence_flush_respects_caller_transaction_rollback(db: Session) -> None:
    persist_router_snapshot(
        db,
        CircuitStateSnapshot(
            provider="test_rollback",
            state="open",
            consecutive_failures=3,
            cooldown_until=datetime.now(UTC) + timedelta(minutes=5),
            last_failure_category="timeout",
            half_open_probe_in_flight=False,
        ),
    )
    db.rollback()
    assert db.query(ProviderCircuitState).filter_by(provider="test_rollback").first() is None


def test_provider_access_value_cannot_enter_fingerprint_state(db: Session) -> None:
    with pytest.raises(ValueError, match="SHA-256 fingerprint"):
        persist_router_snapshot(
            db,
            KeyStateSnapshot(
                provider="test_groq",
                key_fingerprint=RAW_PROVIDER_VALUE,
                enabled=True,
                last_use_at=None,
                failure_count=0,
                cooldown_until=None,
                last_failure_category=None,
                success_count=0,
            ),
        )
    db.rollback()
    forbidden_columns = db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name LIKE 'provider_%' "
            "AND column_name IN ('api_key', 'key_value', 'access_value', 'token', 'secret')"
        )
    ).scalars().all()
    assert forbidden_columns == []
    serialized = db.execute(
        text(
            "SELECT COALESCE(string_agg(row_to_json(rows)::text, ''), '') "
            "FROM (SELECT * FROM provider_key_state WHERE provider LIKE 'test_%') rows"
        )
    ).scalar_one()
    assert RAW_PROVIDER_VALUE not in serialized


def test_source_attempt_metadata_roundtrip(db: Session) -> None:
    name = "__gate6_router_source_attempt__"
    db.query(Source).filter_by(name=name).delete()
    db.commit()
    attempted_at = datetime.now(UTC)
    source = Source(
        name=name,
        type="rss",
        url="https://example.com/router-source.xml",
        last_attempt_at=attempted_at,
        validation_status="degraded",
        failure_category="timeout",
        no_cursor_reason="attempt_failed_before_cursor",
    )
    db.add(source)
    db.commit()
    db.expire_all()
    found = db.query(Source).filter_by(name=name).one()
    assert found.last_attempt_at == attempted_at
    assert found.validation_status == "degraded"
    assert found.failure_category == "timeout"
    assert found.no_cursor_reason == "attempt_failed_before_cursor"
    db.delete(found)
    db.commit()


def test_delivery_and_artifact_lineage_uniqueness(db: Session) -> None:
    report = Report(content_fa="test", story_ids=[], report_mode="manual")
    db.add(report)
    db.flush()
    delivery = Delivery(report_id=report.id, chat_id="test-chat", status="pending")
    db.add(delivery)
    db.commit()
    db.add(Delivery(report_id=report.id, chat_id="test-chat", status="pending"))
    with pytest.raises(Exception):  # noqa: B017 - database uniqueness is the behavior
        db.commit()
    db.rollback()

    job = EditorialJob(
        job_id="test-lineage-job",
        report_mode="manual",
        partition_version="test-v1",
        max_input_token_budget=10_000,
        max_output_token_budget=2_000,
        map_call_budget=2,
        reduction_call_budget=1,
    )
    db.add(job)
    db.flush()
    artifact = EditorialArtifact(
        job_db_id=job.id,
        shard_id="test-lineage-shard",
        artifact_type="map",
        output_json={"stories": []},
        story_ids=[501],
        evidence_ref_ids=["test-evidence"],
        schema_version="test-v1",
        prompt_version="test-v1",
        provider="test_gemini",
        model="gemini-3.6-flash",
    )
    db.add(artifact)
    db.flush()
    lineage = EditorialArtifactLineage(
        artifact_id=artifact.id,
        story_id=501,
        evidence_ref_id="test-evidence",
        source_url="https://example.com/source",
    )
    db.add(lineage)
    db.commit()
    db.add(
        EditorialArtifactLineage(
            artifact_id=artifact.id,
            story_id=501,
            evidence_ref_id="test-evidence",
            source_url="https://example.com/source",
        )
    )
    with pytest.raises(Exception):  # noqa: B017 - database uniqueness is the behavior
        db.commit()
    db.rollback()

    db.query(EditorialArtifactLineage).filter_by(artifact_id=artifact.id).delete()
    db.query(EditorialArtifact).filter_by(id=artifact.id).delete()
    db.query(EditorialJob).filter_by(id=job.id).delete()
    db.query(Delivery).filter_by(report_id=report.id).delete()
    db.query(Report).filter_by(id=report.id).delete()
    db.commit()


def test_mixed_provider_artifact_attempt_lineage(db: Session) -> None:
    job_id = "test-mixed-provider-job"
    now = datetime.now(UTC)
    job = EditorialJob(
        job_id=job_id,
        report_mode="scheduled",
        partition_version="test-v1",
        max_input_token_budget=20_000,
        max_output_token_budget=4_000,
        map_call_budget=2,
        reduction_call_budget=1,
    )
    db.add(job)
    db.flush()
    gemini_artifact = EditorialArtifact(
        job_db_id=job.id,
        shard_id="test-map-0",
        artifact_type="map",
        output_json={"stories": []},
        story_ids=[601],
        evidence_ref_ids=["test-evidence-601"],
        schema_version="test-v1",
        prompt_version="test-v1",
        provider="test_gemini",
        model="gemini-3.6-flash",
    )
    mistral_artifact = EditorialArtifact(
        job_db_id=job.id,
        shard_id="test-map-1",
        artifact_type="map",
        output_json={"stories": []},
        story_ids=[602],
        evidence_ref_ids=["test-evidence-602"],
        schema_version="test-v1",
        prompt_version="test-v1",
        provider="test_mistral",
        model="mistral-large-2512",
    )
    db.add_all([gemini_artifact, mistral_artifact])
    db.flush()
    db.add_all(
        [
            EditorialArtifactLineage(
                artifact_id=gemini_artifact.id,
                story_id=601,
                evidence_ref_id="test-evidence-601",
                source_url="https://example.com/gemini-source",
            ),
            EditorialArtifactLineage(
                artifact_id=mistral_artifact.id,
                story_id=602,
                evidence_ref_id="test-evidence-602",
                source_url="https://example.com/mistral-source",
            ),
        ]
    )
    persist_route_attempt(
        db,
        RouteAttemptEvent(
            event_id="test-mixed-gemini",
            editorial_job_id=job_id,
            shard_id="test-map-0",
            stage="map",
            provider="test_gemini",
            model="gemini-3.6-flash",
            artifact_id=gemini_artifact.id,
            key_fingerprint=KEY_FP,
            status="ok",
            accepted=True,
            created_at=now,
        ),
    )
    persist_route_attempt(
        db,
        RouteAttemptEvent(
            event_id="test-mixed-mistral",
            editorial_job_id=job_id,
            shard_id="test-map-1",
            stage="map",
            provider="test_mistral",
            model="mistral-large-2512",
            artifact_id=mistral_artifact.id,
            key_fingerprint=SECOND_KEY_FP,
            status="ok",
            accepted=True,
            created_at=now,
        ),
    )
    db.commit()
    rows = db.query(ProviderRouteAttempt).filter_by(editorial_job_id=job_id).all()
    artifacts = db.query(EditorialArtifact).filter_by(job_db_id=job.id).all()
    assert {(row.provider, row.model, row.shard_id, row.artifact_id) for row in rows} == {
        ("test_gemini", "gemini-3.6-flash", "test-map-0", gemini_artifact.id),
        ("test_mistral", "mistral-large-2512", "test-map-1", mistral_artifact.id),
    }
    assert {(artifact.provider, artifact.model) for artifact in artifacts} == {
        ("test_gemini", "gemini-3.6-flash"),
        ("test_mistral", "mistral-large-2512"),
    }
    assert db.query(EditorialArtifactLineage).filter(
        EditorialArtifactLineage.artifact_id.in_([gemini_artifact.id, mistral_artifact.id])
    ).count() == 2

    db.query(ProviderRouteAttempt).filter_by(editorial_job_id=job_id).delete()
    db.query(EditorialArtifactLineage).filter(
        EditorialArtifactLineage.artifact_id.in_([gemini_artifact.id, mistral_artifact.id])
    ).delete(synchronize_session=False)
    db.query(EditorialArtifact).filter_by(job_db_id=job.id).delete()
    db.delete(job)
    db.commit()

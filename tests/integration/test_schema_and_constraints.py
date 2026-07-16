"""Real PostgreSQL: migrations, tables, constraints, JSONB, rollback."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "sources",
    "source_credentials",
    "collection_cursors",
    "collection_runs",
    "raw_items",
    "normalized_items",
    "stories",
    "story_items",
    "evidence",
    "reports",
    "deliveries",
    "job_runs",
    "processing_errors",
    "alembic_version",
}

ROOT = Path(__file__).resolve().parents[2]


def test_alembic_current_is_head(engine: Engine) -> None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert row is not None
    # heads file
    heads = subprocess.run(
        ["uv", "run", "alembic", "heads"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert heads.returncode == 0
    assert row in heads.stdout


def test_expected_tables_exist(engine: Engine) -> None:
    insp = inspect(engine)
    names = set(insp.get_table_names())
    missing = EXPECTED_TABLES - names
    assert not missing, f"missing tables: {missing}"


def test_source_name_unique(db: Session) -> None:
    from newsroom.storage.models import Source

    name = "__gate1_unique_source__"
    db.query(Source).filter_by(name=name).delete()
    db.commit()
    db.add(Source(name=name, type="rss", url="https://example.com/a.xml"))
    db.commit()
    db.add(Source(name=name, type="rss", url="https://example.com/b.xml"))
    with pytest.raises(Exception):  # noqa: B017
        db.commit()
    db.rollback()
    db.query(Source).filter_by(name=name).delete()
    db.commit()


def test_transaction_rollback(db: Session) -> None:
    from newsroom.storage.models import Source

    name = "__gate1_rollback_source__"
    db.query(Source).filter_by(name=name).delete()
    db.commit()
    db.add(Source(name=name, type="rss", url="https://example.com/r.xml"))
    db.flush()
    db.rollback()
    assert db.query(Source).filter_by(name=name).first() is None


def test_jsonb_raw_item_roundtrip(db: Session) -> None:
    from newsroom.storage.models import RawItem, Source

    name = "__gate1_jsonb_source__"
    src = db.query(Source).filter_by(name=name).first()
    if not src:
        src = Source(name=name, type="rss", url="https://example.com/j.xml")
        db.add(src)
        db.flush()
    payload = {"title": "t", "nested": {"a": 1}, "list": [1, 2]}
    raw = RawItem(source_id=src.id, raw_data=payload, content_hash="abc" * 10 + "ab")
    db.add(raw)
    db.commit()
    got = db.query(RawItem).filter_by(id=raw.id).first()
    assert got is not None
    assert got.raw_data["nested"]["a"] == 1
    db.delete(got)
    db.query(Source).filter_by(name=name).delete()
    db.commit()


def test_normalized_item_fk_and_unique_raw(db: Session) -> None:
    from newsroom.storage.models import NormalizedItem, RawItem, Source

    name = "__gate1_norm_source__"
    src = db.query(Source).filter_by(name=name).first()
    if not src:
        src = Source(name=name, type="rss", url="https://example.com/n.xml")
        db.add(src)
        db.flush()
    raw = RawItem(source_id=src.id, raw_data={"title": "x"}, content_hash="d" * 64)
    db.add(raw)
    db.flush()
    n1 = NormalizedItem(
        raw_item_id=raw.id,
        title="x",
        source_url="https://example.com/x",
        content_hash="e" * 64,
    )
    db.add(n1)
    db.commit()
    n2 = NormalizedItem(
        raw_item_id=raw.id,
        title="y",
        source_url="https://example.com/y",
        content_hash="f" * 64,
    )
    db.add(n2)
    with pytest.raises(Exception):  # noqa: B017
        db.commit()
    db.rollback()
    db.query(NormalizedItem).filter_by(raw_item_id=raw.id).delete()
    db.query(RawItem).filter_by(id=raw.id).delete()
    db.query(Source).filter_by(name=name).delete()
    db.commit()


def test_job_run_persistence(db: Session) -> None:
    from newsroom.storage.models import JobRun

    jr = JobRun(job_type="manual", job_id="gate1_job_test", trigger="manual", status="running")
    db.add(jr)
    db.commit()
    got = db.query(JobRun).filter_by(job_id="gate1_job_test").first()
    assert got is not None
    assert got.status == "running"
    db.delete(got)
    db.commit()


def test_delivery_idempotency_record(db: Session) -> None:
    from newsroom.storage.models import Delivery, Report

    report = Report(content_fa="تست", story_ids=[], report_mode="manual")
    db.add(report)
    db.flush()
    d = Delivery(
        report_id=report.id,
        chat_id="deadbeefdeadbeef",
        total_chunks=1,
        delivered_chunks=1,
        message_ids=[1],
        status="delivered",
    )
    db.add(d)
    db.commit()
    again = (
        db.query(Delivery)
        .filter_by(report_id=report.id, chat_id="deadbeefdeadbeef")
        .first()
    )
    assert again is not None
    assert again.status == "delivered"
    db.delete(again)
    db.delete(report)
    db.commit()

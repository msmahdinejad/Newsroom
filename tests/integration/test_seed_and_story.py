"""Source seed idempotency + story relationship smoke on real DB."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from newsroom.storage.models import NormalizedItem, RawItem, Source, Story, StoryItem

pytestmark = pytest.mark.integration


def test_seed_sources_idempotent(db: Session) -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "seed_sources.py"
    spec = importlib.util.spec_from_file_location("seed_sources", path)
    assert spec and spec.loader
    seed_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_mod)

    before = db.query(Source).count()
    seed_mod.seed()
    mid = db.query(Source).count()
    seed_mod.seed()
    after = db.query(Source).count()
    assert after == mid
    assert after >= before
    assert after >= 30


def test_story_item_relationship(db: Session) -> None:
    name = "__gate1_story_src__"
    src = db.query(Source).filter_by(name=name).first()
    if not src:
        src = Source(name=name, type="rss", url="https://example.com/s.xml")
        db.add(src)
        db.flush()
    raw = RawItem(source_id=src.id, raw_data={"title": "s"}, content_hash="1" * 64)
    db.add(raw)
    db.flush()
    norm = NormalizedItem(
        raw_item_id=raw.id,
        title="story item",
        source_url="https://example.com/s",
        content_hash="2" * 64,
    )
    db.add(norm)
    db.flush()
    story = Story(headline="h", cluster_keywords=["k"], source_count=1)
    db.add(story)
    db.flush()
    db.add(StoryItem(story_id=story.id, item_id=norm.id))
    db.commit()
    links = db.query(StoryItem).filter_by(story_id=story.id).all()
    assert len(links) == 1
    # cleanup
    db.query(StoryItem).filter_by(story_id=story.id).delete()
    db.delete(story)
    db.delete(norm)
    db.delete(raw)
    db.query(Source).filter_by(name=name).delete()
    db.commit()

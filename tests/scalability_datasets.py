"""Synthetic dataset generators for scalability tests.

Generates realistic synthetic data without touching production sources.
Dataset S: 100 sources, 1,000 raw items
Dataset M: 500 sources, 10,000 raw items
Dataset L: 1,300+ sources, 50,000+ raw items

These do NOT need to be inserted permanently into the normal development DB.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from newsroom.editorial.schema import (
    EVIDENCE_SCHEMA_VERSION,
    SYSTEM_PROMPT_VERSION,
    EditorialEvidenceSet,
    EvidenceSourceItem,
    EvidenceStoryPacket,
)


@dataclass
class SyntheticDataset:
    """In-memory synthetic dataset for scalability testing."""

    name: str
    source_count: int
    raw_item_count: int
    story_count: int
    evidence: EditorialEvidenceSet
    languages: list[str]
    has_duplicates: bool
    has_conflicts: bool
    has_oversized: bool


def _make_source(
    story_id: int,
    seq: int,
    trust: str = "reputable",
    trust_score: float = 0.8,
    excerpt_size: int = 200,
    language: str = "en",
) -> EvidenceSourceItem:
    return EvidenceSourceItem(
        ref_id=f"ev-{story_id}-{seq}",
        item_id=story_id * 1000 + seq,
        source_name=f"Source{seq}",
        source_type="rss" if seq % 3 != 0 else "github_releases",
        source_trust=trust,
        source_trust_score=trust_score,
        published_at="2026-07-18T10:00:00+00:00",
        original_title=f"Title for story {story_id} source {seq}",
        excerpt="x" * excerpt_size,
        original_url=f"https://example.com/{story_id}/{seq}",
        detected_language=language,
    )


def _make_story(
    story_id: int,
    source_count: int = 3,
    excerpt_size: int = 200,
    importance: float = 0.5,
    trust: str = "confirmed",
    language: str = "en",
    conflicts: bool = False,
) -> EvidenceStoryPacket:
    sources = [
        _make_source(
            story_id,
            i,
            trust="official" if i == 0 else "reputable",
            trust_score=0.95 if i == 0 else 0.75,
            excerpt_size=excerpt_size,
            language=language,
        )
        for i in range(source_count)
    ]
    return EvidenceStoryPacket(
        story_id=story_id,
        headline=f"Story {story_id}",
        keywords=["ai", "test"],
        trust_status=trust,
        confidence=0.8,
        importance_score=importance,
        source_count=source_count,
        item_count=source_count,
        sources=sources,
        facts=[f"Fact {story_id}.1", f"Fact {story_id}.2"],
        contradictions=[{"issue": "conflict"}] if conflicts else [],
    )


def generate_dataset_s() -> SyntheticDataset:
    """Dataset S: 100 sources, 1,000 raw items.

    ~200 stories (after dedup/cluster simulation), duplicates, multiple languages.
    """
    rng = random.Random(42)  # deterministic
    stories: list[EvidenceStoryPacket] = []
    languages = ["en", "fa", "en", "en"]  # mostly English, some Persian

    for i in range(200):
        lang = rng.choice(languages)
        source_count = rng.randint(2, 5)
        importance = rng.uniform(0.3, 0.95)
        conflicts = i % 20 == 0  # 5% conflicting
        stories.append(_make_story(
            story_id=i + 1,
            source_count=source_count,
            importance=importance,
            language=lang,
            conflicts=conflicts,
        ))

    evidence = EditorialEvidenceSet(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        prompt_version=SYSTEM_PROMPT_VERSION,
        report_mode="scheduled",
        stories=stories,
    )

    return SyntheticDataset(
        name="S",
        source_count=100,
        raw_item_count=1000,
        story_count=200,
        evidence=evidence,
        languages=["en", "fa"],
        has_duplicates=True,
        has_conflicts=True,
        has_oversized=False,
    )


def generate_dataset_m() -> SyntheticDataset:
    """Dataset M: 500 sources, 10,000 raw items.

    ~1,500 stories, duplicate bursts, conflicting stories, oversized evidence.
    """
    rng = random.Random(123)
    stories: list[EvidenceStoryPacket] = []

    for i in range(1500):
        source_count = rng.randint(2, 8)
        excerpt_size = rng.randint(100, 800)  # some oversized
        importance = rng.uniform(0.2, 0.98)
        conflicts = i % 15 == 0  # ~7% conflicting
        trust = rng.choice(["confirmed", "likely", "rumor"])
        stories.append(_make_story(
            story_id=i + 1,
            source_count=source_count,
            excerpt_size=excerpt_size,
            importance=importance,
            trust=trust,
            conflicts=conflicts,
        ))

    evidence = EditorialEvidenceSet(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        prompt_version=SYSTEM_PROMPT_VERSION,
        report_mode="scheduled",
        stories=stories,
    )

    return SyntheticDataset(
        name="M",
        source_count=500,
        raw_item_count=10000,
        story_count=1500,
        evidence=evidence,
        languages=["en", "fa"],
        has_duplicates=True,
        has_conflicts=True,
        has_oversized=True,
    )


def generate_dataset_l() -> SyntheticDataset:
    """Dataset L: 1,300+ sources, 50,000+ raw items.

    ~8,000 stories, realistic duplicate/clustering ratios, mixed source types.
    """
    rng = random.Random(456)
    stories: list[EvidenceStoryPacket] = []

    for i in range(8000):
        source_count = rng.randint(2, 10)
        excerpt_size = rng.randint(50, 600)
        importance = rng.uniform(0.1, 0.99)
        conflicts = i % 25 == 0  # 4% conflicting
        trust = rng.choice(["confirmed", "likely", "rumor", "official"])
        lang = rng.choice(["en", "en", "en", "fa"])
        stories.append(_make_story(
            story_id=i + 1,
            source_count=source_count,
            excerpt_size=excerpt_size,
            importance=importance,
            trust=trust,
            language=lang,
            conflicts=conflicts,
        ))

    evidence = EditorialEvidenceSet(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        prompt_version=SYSTEM_PROMPT_VERSION,
        report_mode="scheduled",
        stories=stories,
    )

    return SyntheticDataset(
        name="L",
        source_count=1300,
        raw_item_count=50000,
        story_count=8000,
        evidence=evidence,
        languages=["en", "fa"],
        has_duplicates=True,
        has_conflicts=True,
        has_oversized=True,
    )

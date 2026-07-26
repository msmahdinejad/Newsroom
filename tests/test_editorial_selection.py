"""Unit tests for /report new delivered-story semantics (no DB required).

Tests detect_material_change logic. Integration tests with real PostgreSQL
are in tests/integration/test_gate4_report_new.py.
"""

from __future__ import annotations

from newsroom.editorial.selection import detect_material_change, reserve_telegram_story_ids
from newsroom.storage.models import Story


class TestDetectMaterialChange:
    """Unit tests for detect_material_change (no DB needed)."""

    def test_new_story_is_material(self):
        """A story with no old evidence packet is always material."""
        story = Story(headline="test", source_count=1)
        assert detect_material_change(story, {"facts": ["new fact"]}, None) is True

    def test_new_source_is_material(self):
        """Increased source_count is a material change."""
        story = Story(headline="test", source_count=3)
        old = {"source_count": 2, "facts": ["fact1"]}
        new = {"source_count": 3, "facts": ["fact1"]}
        assert detect_material_change(story, new, old) is True

    def test_new_fact_is_material(self):
        """A new fact is a material change."""
        story = Story(headline="test", source_count=1)
        old = {"source_count": 1, "facts": ["fact1"]}
        new = {"source_count": 1, "facts": ["fact1", "fact2 new"]}
        assert detect_material_change(story, new, old) is True

    def test_duplicate_coverage_not_material(self):
        """Same facts and source count is not a material change."""
        story = Story(headline="test", source_count=2)
        old = {"source_count": 2, "facts": ["fact1"], "contradictions": []}
        new = {"source_count": 2, "facts": ["fact1"], "contradictions": []}
        assert detect_material_change(story, new, old) is False

    def test_new_contradiction_is_material(self):
        """A new contradiction is a material change."""
        story = Story(headline="test", source_count=1)
        old = {"source_count": 1, "facts": ["fact1"], "contradictions": []}
        new = {"source_count": 1, "facts": ["fact1"], "contradictions": [{"issue": "conflict"}]}
        assert detect_material_change(story, new, old) is True

    def test_formatting_edit_not_material(self):
        """Rephrased same fact is not a material change."""
        story = Story(headline="test", source_count=1)
        old = {"source_count": 1, "facts": ["the model was released"]}
        new = {"source_count": 1, "facts": ["the model was released"]}  # same
        assert detect_material_change(story, new, old) is False


def test_selection_reserves_space_for_recent_telegram_stories() -> None:
    selected = [10, 11, 12, 13]
    candidates = [10, 11, 12, 13, 20, 21]

    result = reserve_telegram_story_ids(
        selected,
        candidates,
        telegram_story_ids={20, 21},
        max_stories=4,
        minimum_telegram_stories=2,
    )

    assert result == [10, 11, 20, 21]

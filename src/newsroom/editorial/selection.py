"""Story selection with delivered-story awareness for /report new.

Implements the authoritative semantics:
- /report new excludes stories from successfully delivered reports
- Only complete deliveries count (status='delivered')
- Material changes can re-qualify a delivered story
- /report and /report comprehensive include all recent stories
- /latest performs no selection and no provider call

Uses set-based SQL — no per-story queries, no loading all delivery history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from newsroom.logging import get_logger
from newsroom.storage.models import Story

logger = get_logger(__name__)

# Maximum stories to consider as candidates (before mode-based filtering)
MAX_CANDIDATE_STORIES = 100


@dataclass
class SelectionResult:
    """Result of story selection for a report."""

    story_ids: list[int]
    excluded_as_delivered: int
    materially_updated: int
    total_candidates: int
    selected_count: int
    omitted_count: int
    report_mode: str
    no_new_items: bool


def get_delivered_story_ids(db: Session) -> set[int]:
    """Get story IDs from all successfully delivered reports.

    Uses a single set-based SQL query with JSONB expansion.
    Does NOT count failed or partial deliveries.
    """
    result = db.execute(
        text(
            """
            SELECT DISTINCT (story_id::text)::int AS story_id
            FROM (
                SELECT jsonb_array_elements_text(r.story_ids) AS story_id
                FROM reports r
                JOIN deliveries d ON d.report_id = r.id
                WHERE d.status = 'delivered'
            ) sub
            WHERE story_id IS NOT NULL AND story_id != ''
            """
        )
    )
    return {row[0] for row in result}


def get_delivered_story_versions(db: Session) -> dict[int, int]:
    """Map delivered story IDs to their material_version at delivery time.

    We approximate by joining to the current story material_version.
    A story is excluded if it was delivered AND its material_version hasn't
    changed since the most recent delivery that included it.
    """
    # Get the most recent delivered report per story
    result = db.execute(
        text(
            """
            SELECT (story_id::text)::int AS sid, MAX(delivered_at) AS delivered_at
            FROM (
                SELECT
                    jsonb_array_elements_text(r.story_ids) AS story_id,
                    COALESCE(d.delivered_at, r.created_at) AS delivered_at
                FROM reports r
                JOIN deliveries d ON d.report_id = r.id
                WHERE d.status = 'delivered'
            ) sub
            WHERE story_id IS NOT NULL AND story_id != ''
            GROUP BY sid
            """
        )
    )
    delivered_at_map: dict[int, Any] = {row[0]: row[1] for row in result}

    # A story is materially updated if material_change_at > most_recent_delivery
    updated: dict[int, int] = {}
    if delivered_at_map:
        story_ids = list(delivered_at_map.keys())
        stories = (
            db.query(Story)
            .filter(Story.id.in_(story_ids))
            .all()
        )
        for story in stories:
            delivered_at = delivered_at_map.get(story.id)
            if (
                delivered_at
                and isinstance(delivered_at, datetime)
                and story.material_change_at
                and story.material_change_at > delivered_at
            ):
                updated[story.id] = story.material_version
    return updated


def select_stories_for_report(
    db: Session,
    report_mode: str,
    max_stories: int = 30,
) -> SelectionResult:
    """Select stories for a report based on the report mode.

    - manual_new: exclude delivered stories (unless materially updated)
    - manual / manual_comprehensive / scheduled: include all recent stories
    - latest: no selection (handled by bot directly)

    Returns a SelectionResult with counts and no_new_items flag.
    """
    # Get candidates: most recent non-duplicate stories, ordered by importance
    candidates = (
        db.query(Story)
        .order_by(Story.importance_score.desc(), Story.created_at.desc())
        .limit(MAX_CANDIDATE_STORIES)
        .all()
    )

    candidate_ids = [s.id for s in candidates]
    total_candidates = len(candidate_ids)

    if report_mode == "manual_new":
        delivered_ids = get_delivered_story_ids(db)
        updated_ids = get_delivered_story_versions(db)

        # Exclude delivered unless materially updated
        excluded = delivered_ids - set(updated_ids.keys())
        materially_updated = len(updated_ids)

        selected = [sid for sid in candidate_ids if sid not in excluded]
        excluded_count = len(candidate_ids) - len(selected)

        if not selected:
            return SelectionResult(
                story_ids=[],
                excluded_as_delivered=excluded_count,
                materially_updated=materially_updated,
                total_candidates=total_candidates,
                selected_count=0,
                omitted_count=0,
                report_mode=report_mode,
                no_new_items=True,
            )

        # Limit to max_stories
        selected = selected[:max_stories]
        omitted = max(0, len(candidate_ids) - len(selected))

        return SelectionResult(
            story_ids=selected,
            excluded_as_delivered=excluded_count,
            materially_updated=materially_updated,
            total_candidates=total_candidates,
            selected_count=len(selected),
            omitted_count=omitted,
            report_mode=report_mode,
            no_new_items=False,
        )

    # All other modes: include all candidates (up to max_stories)
    selected = candidate_ids[:max_stories]
    omitted = max(0, len(candidate_ids) - len(selected))

    return SelectionResult(
        story_ids=selected,
        excluded_as_delivered=0,
        materially_updated=0,
        total_candidates=total_candidates,
        selected_count=len(selected),
        omitted_count=omitted,
        report_mode=report_mode,
        no_new_items=not selected,
    )


def detect_material_change(
    story: Story,
    new_evidence_packet: dict,
    old_evidence_packet: dict | None,
) -> bool:
    """Determine if a story has a material change warranting re-reporting.

    Material changes:
    - New official source added (source_count increased with higher trust)
    - Materially new facts in evidence packet
    - Telegram post edited after delivery (edit_ts changes)

    NOT material changes:
    - Duplicate coverage (same story from different sources)
    - Formatting edits only
    - Same facts rephrased
    """
    if not old_evidence_packet:
        return True  # New story — always material

    # New official source: source_count increased
    old_source_count = old_evidence_packet.get("source_count", 0)
    new_source_count = new_evidence_packet.get("source_count", story.source_count)
    if new_source_count > old_source_count:
        return True

    # New facts added
    old_facts = set(old_evidence_packet.get("facts", []))
    new_facts = set(new_evidence_packet.get("facts", []))
    if new_facts - old_facts:
        return True

    # New contradictions
    old_contra = len(old_evidence_packet.get("contradictions", []))
    new_contra = len(new_evidence_packet.get("contradictions", []))
    return new_contra > old_contra


def bump_material_version(db: Session, story_id: int) -> None:
    """Increment material_version for a story that has materially changed."""
    story = db.get(Story, story_id)
    if story:
        story.material_version += 1
        from newsroom.storage.models import utcnow

        story.material_change_at = utcnow()

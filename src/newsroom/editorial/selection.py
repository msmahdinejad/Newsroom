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

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from newsroom.editorial.report_profiles import (
    ReportProfile,
    is_programming_material,
    is_usable_editorial_material,
    resolve_report_profile,
)
from newsroom.logging import get_logger
from newsroom.storage.models import NormalizedItem, RawItem, Source, Story, StoryItem

logger = get_logger(__name__)

# Maximum stories to consider as candidates (before mode-based filtering)
MAX_CANDIDATE_STORIES = 500


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


def reserve_telegram_story_ids(
    selected: list[int],
    candidates: list[int],
    *,
    telegram_story_ids: set[int],
    max_stories: int,
    minimum_telegram_stories: int,
) -> list[int]:
    """Reserve a small bounded share for Telegram without expanding a report."""
    minimum = max(0, min(minimum_telegram_stories, max_stories))
    if not minimum or not telegram_story_ids:
        return selected[:max_stories]

    included = [story_id for story_id in selected if story_id in telegram_story_ids]
    missing = [
        story_id
        for story_id in candidates
        if story_id in telegram_story_ids and story_id not in included
    ][: max(0, minimum - len(included))]
    if not missing:
        return selected[:max_stories]

    retained = [story_id for story_id in selected if story_id not in missing]
    retained = retained[: max(0, max_stories - len(missing))]
    return retained + missing


def _story_material(
    db: Session,
    story_ids: list[int],
) -> dict[int, list[tuple[str, str, str, str, bool]]]:
    """Load bounded selection metadata in one query."""
    material: dict[int, list[tuple[str, str, str, str, bool]]] = {
        story_id: [] for story_id in story_ids
    }
    if not story_ids:
        return material
    rows = (
        db.query(
            StoryItem.story_id,
            Source.type,
            Source.category,
            NormalizedItem.title,
            NormalizedItem.description,
            Source.enabled,
        )
        .join(NormalizedItem, StoryItem.item_id == NormalizedItem.id)
        .join(RawItem, NormalizedItem.raw_item_id == RawItem.id)
        .join(Source, RawItem.source_id == Source.id)
        .filter(StoryItem.story_id.in_(story_ids))
        .all()
    )
    for story_id, source_type, category, title, description, source_enabled in rows:
        material[story_id].append(
            (
                source_type,
                category or "",
                title or "",
                description or "",
                bool(source_enabled),
            )
        )
    return material


def _eligible_story_ids(
    db: Session,
    story_ids: list[int],
    profile: ReportProfile,
) -> list[int]:
    """Apply source exclusivity and high-recall programming relevance."""
    material = _story_material(db, story_ids)
    eligible: list[int] = []
    for story_id in story_ids:
        entries = material[story_id]
        # Preserve legacy/test stories that predate source linkage.
        if not entries:
            if profile.source_types is None:
                eligible.append(story_id)
            continue
        scoped = [
            entry
            for entry in entries
            if entry[4]
            and (profile.source_types is None or entry[0] in profile.source_types)
        ]
        if not scoped:
            continue
        scoped = [
            entry
            for entry in scoped
            if is_usable_editorial_material(
                title=entry[2],
                description=entry[3],
            )
        ]
        if not scoped:
            continue
        if profile.programming_only and not any(
            is_programming_material(
                source_type=source_type,
                category=category,
                title=title,
                description=description,
            )
            for source_type, category, title, description, _enabled in scoped
        ):
            continue
        eligible.append(story_id)
    return eligible


def _candidate_query(db: Session, profile: ReportProfile):
    """Start an importance-ranked query, scoped before the candidate limit."""
    query = db.query(Story)
    if profile.source_types is not None:
        query = (
            query.join(StoryItem, StoryItem.story_id == Story.id)
            .join(NormalizedItem, StoryItem.item_id == NormalizedItem.id)
            .join(RawItem, NormalizedItem.raw_item_id == RawItem.id)
            .join(Source, RawItem.source_id == Source.id)
            .filter(
                Source.type.in_(profile.source_types),
                Source.enabled.is_(True),
            )
            .distinct()
        )
    return query


def _with_telegram_reserve(
    db: Session,
    story_ids: list[int],
    max_stories: int,
    minimum_telegram_stories: int,
) -> list[int]:
    """Give eligible Telegram programming stories a bounded seat."""
    if not story_ids:
        return []
    material = _story_material(db, story_ids)
    telegram_story_ids = {
        story_id
        for story_id, entries in material.items()
        if any(
            source_type == "telegram"
            and is_usable_editorial_material(
                title=title,
                description=description,
            )
            and is_programming_material(
                source_type=source_type,
                category=category,
                title=title,
                description=description,
            )
            for source_type, category, title, description, enabled in entries
            if enabled
        )
    }
    return reserve_telegram_story_ids(
        story_ids[:max_stories],
        story_ids,
        telegram_story_ids=telegram_story_ids,
        max_stories=max_stories,
        minimum_telegram_stories=minimum_telegram_stories,
    )


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


def get_scheduled_boundary(db: Session) -> datetime | None:
    """Return the advanced_at of the last completely delivered scheduled report.

    Used as the 'since the last completely delivered scheduled report' window
    boundary for scheduled report selection. None when no scheduled report
    has been delivered yet (first run selects all recent material).
    """
    row = db.execute(
        text(
            "SELECT advanced_at FROM report_cursors "
            "WHERE cursor_key = 'scheduled_delivery' AND advanced_at IS NOT NULL"
        )
    ).first()
    return row[0] if row else None


def select_stories_for_report(
    db: Session,
    report_mode: str,
    max_stories: int | None = None,
    *,
    source_types: tuple[str, ...] | None = None,
) -> SelectionResult:
    """Select stories for a report based on the report mode.

    - manual_new: exclude delivered stories (unless materially updated)
    - scheduled: select material since the last delivered scheduled report
      boundary (created or materially changed after it), excluding delivered
      unchanged stories. With no new material since the boundary → no_new_items
      (the no-news path makes zero editorial provider calls).
    - manual / manual_comprehensive: include all recent stories
    - latest: no selection (handled by bot directly)

    Returns a SelectionResult with counts and no_new_items flag.
    """
    profile = resolve_report_profile(report_mode)
    if source_types is not None:
        normalized_types = frozenset(source_types)
        profile = replace(
            profile,
            source_types=normalized_types or None,
            minimum_telegram_stories=(
                profile.minimum_telegram_stories
                if "telegram" in normalized_types or not normalized_types
                else 0
            ),
        )
    max_stories = max_stories or profile.max_stories
    delivered_ids = get_delivered_story_ids(db)
    updated_ids = get_delivered_story_versions(db)
    excluded_delivered = delivered_ids - set(updated_ids.keys())
    materially_updated = len(updated_ids)

    if report_mode == "scheduled":
        boundary = get_scheduled_boundary(db)
        if boundary is None:
            # First scheduled run — all recent candidates are new material.
            candidates = (
                _candidate_query(db, profile)
                .order_by(Story.importance_score.desc(), Story.created_at.desc())
                .limit(MAX_CANDIDATE_STORIES)
                .all()
            )
            candidate_ids = _eligible_story_ids(
                db, [s.id for s in candidates], profile
            )
        else:
            # New material since the boundary: created or materially changed after.
            candidates = (
                _candidate_query(db, profile)
                .filter(
                    (Story.created_at > boundary)
                    | (Story.material_change_at.is_not(None) & (Story.material_change_at > boundary))
                )
                .order_by(Story.importance_score.desc(), Story.created_at.desc())
                .limit(MAX_CANDIDATE_STORIES)
                .all()
            )
            candidate_ids = _eligible_story_ids(
                db, [s.id for s in candidates], profile
            )
        total_candidates = len(candidate_ids)
        # Exclude delivered unchanged stories (already delivered, no change).
        selected = [sid for sid in candidate_ids if sid not in excluded_delivered]
        excluded_count = total_candidates - len(selected)
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
        selected = _with_telegram_reserve(
            db,
            selected,
            max_stories,
            profile.minimum_telegram_stories,
        )
        omitted = max(0, total_candidates - len(selected))
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

    if report_mode == "manual_new":
        candidate_ids = _eligible_story_ids(
            db,
            [
                s.id
                for s in _candidate_query(db, profile)
                .order_by(Story.importance_score.desc(), Story.created_at.desc())
                .limit(MAX_CANDIDATE_STORIES)
                .all()
            ],
            profile,
        )
        total_candidates = len(candidate_ids)
        selected = [sid for sid in candidate_ids if sid not in excluded_delivered]
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
        selected = _with_telegram_reserve(
            db,
            selected,
            max_stories,
            profile.minimum_telegram_stories,
        )
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

    # manual / manual_comprehensive: include all candidates (up to max_stories)
    candidates = (
        _candidate_query(db, profile)
        .order_by(Story.importance_score.desc(), Story.created_at.desc())
        .limit(MAX_CANDIDATE_STORIES)
        .all()
    )
    candidate_ids = _eligible_story_ids(db, [s.id for s in candidates], profile)
    total_candidates = len(candidate_ids)
    selected = _with_telegram_reserve(
        db,
        candidate_ids,
        max_stories,
        profile.minimum_telegram_stories,
    )
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

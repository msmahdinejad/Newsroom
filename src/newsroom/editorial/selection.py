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
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.control.digests import InterestPolicy
from newsroom.editorial.report_profiles import (
    DEFAULT_INTEREST_POLICY,
    ReportProfile,
    is_interest_material,
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


@dataclass(frozen=True)
class StoryMaterial:
    """Source-backed material used for deterministic report selection."""

    source_id: int
    source_type: str
    category: str
    title: str
    description: str
    enabled: bool
    published_at: datetime | None


def retain_recent_stories(
    story_ids: list[int],
    material: dict[int, list[StoryMaterial]],
    *,
    max_age_hours: int,
    now: datetime | None = None,
) -> list[int]:
    """Drop explicitly stale stories while preserving undated/legacy material."""
    if max_age_hours <= 0:
        return story_ids
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=max_age_hours)
    return [
        story_id
        for story_id in story_ids
        if not material.get(story_id)
        or any(
            entry.published_at is None or entry.published_at >= cutoff
            for entry in material[story_id]
        )
    ]


def balance_story_sources(
    story_ids: list[int],
    material: dict[int, list[StoryMaterial]],
    *,
    max_stories: int,
    max_per_source: int,
) -> list[int]:
    """Keep one feed from monopolizing the default digest."""
    if max_per_source <= 0:
        return story_ids[:max_stories]
    source_counts: dict[int, int] = {}
    selected: list[int] = []
    for story_id in story_ids:
        source_ids = sorted(
            {entry.source_id for entry in material.get(story_id, []) if entry.enabled}
        )
        if not source_ids:
            selected.append(story_id)
        else:
            available = [
                source_id
                for source_id in source_ids
                if source_counts.get(source_id, 0) < max_per_source
            ]
            if not available:
                continue
            attributed_source = min(
                available,
                key=lambda source_id: (source_counts.get(source_id, 0), source_id),
            )
            source_counts[attributed_source] = source_counts.get(attributed_source, 0) + 1
            selected.append(story_id)
        if len(selected) >= max_stories:
            break
    return selected


def reserve_telegram_story_ids(
    selected: list[int],
    candidates: list[int],
    *,
    telegram_story_ids: set[int],
    telegram_source_ids_by_story: dict[int, set[int]] | None = None,
    max_stories: int,
    minimum_telegram_stories: int,
) -> list[int]:
    """Reserve a small bounded share for Telegram without expanding a report."""
    minimum = max(0, min(minimum_telegram_stories, max_stories))
    if not minimum or not telegram_story_ids:
        return selected[:max_stories]

    if telegram_source_ids_by_story:
        reserved: list[int] = []
        used_sources: set[int] = set()
        telegram_candidates = [
            story_id for story_id in candidates if story_id in telegram_story_ids
        ]
        for story_id in telegram_candidates:
            story_sources = telegram_source_ids_by_story.get(story_id, set())
            if story_sources - used_sources:
                reserved.append(story_id)
                used_sources.update(story_sources)
                if len(reserved) >= minimum:
                    break
        for story_id in telegram_candidates:
            if len(reserved) >= minimum:
                break
            if story_id not in reserved:
                reserved.append(story_id)
        retained = [
            story_id
            for story_id in selected
            if story_id not in telegram_story_ids or story_id in reserved
        ]
        missing = [story_id for story_id in reserved if story_id not in retained]
        retained = retained[: max(0, max_stories - len(missing))]
        result = retained + missing
        for story_id in candidates:
            if len(result) >= max_stories:
                break
            if story_id not in result:
                result.append(story_id)
        return result

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
) -> dict[int, list[StoryMaterial]]:
    """Load bounded selection metadata in one query."""
    material: dict[int, list[StoryMaterial]] = {story_id: [] for story_id in story_ids}
    if not story_ids:
        return material
    rows = (
        db.query(
            StoryItem.story_id,
            Source.id,
            Source.type,
            Source.category,
            NormalizedItem.title,
            NormalizedItem.description,
            Source.enabled,
            NormalizedItem.published_at,
        )
        .join(NormalizedItem, StoryItem.item_id == NormalizedItem.id)
        .join(RawItem, NormalizedItem.raw_item_id == RawItem.id)
        .join(Source, RawItem.source_id == Source.id)
        .filter(StoryItem.story_id.in_(story_ids))
        .all()
    )
    for (
        story_id,
        source_id,
        source_type,
        category,
        title,
        description,
        source_enabled,
        published_at,
    ) in rows:
        material[story_id].append(
            StoryMaterial(
                source_id=source_id,
                source_type=source_type,
                category=category or "",
                title=title or "",
                description=description or "",
                enabled=bool(source_enabled),
                published_at=published_at,
            )
        )
    return material


def _scoped_material(
    material: dict[int, list[StoryMaterial]],
    profile: ReportProfile,
    source_ids: frozenset[int] | None,
) -> dict[int, list[StoryMaterial]]:
    return {
        story_id: [
            entry
            for entry in entries
            if entry.enabled
            and (source_ids is None or entry.source_id in source_ids)
            and (profile.source_types is None or entry.source_type in profile.source_types)
        ]
        for story_id, entries in material.items()
    }


def _eligible_story_ids(
    db: Session,
    story_ids: list[int],
    profile: ReportProfile,
    interest: InterestPolicy,
    source_ids: frozenset[int] | None,
) -> list[int]:
    """Apply source exclusivity and high-recall subject relevance."""
    material = _story_material(db, story_ids)
    scoped_material = _scoped_material(material, profile, source_ids)
    eligible: list[int] = []
    for story_id in story_ids:
        entries = material[story_id]
        # Preserve legacy/test stories that predate source linkage.
        if not entries:
            if profile.source_types is None:
                eligible.append(story_id)
            continue
        scoped = scoped_material[story_id]
        if not scoped:
            continue
        scoped = [
            entry
            for entry in scoped
            if is_usable_editorial_material(
                title=entry.title,
                description=entry.description,
            )
        ]
        if not scoped:
            continue
        if not any(
            is_interest_material(
                interest=interest,
                source_type=entry.source_type,
                category=entry.category,
                title=entry.title,
                description=entry.description,
            )
            for entry in scoped
        ):
            continue
        eligible.append(story_id)
    return eligible


def _candidate_query(
    db: Session,
    profile: ReportProfile,
    source_ids: frozenset[int] | None,
):
    """Start an importance-ranked query, scoped before the candidate limit."""
    query = db.query(Story)
    if profile.source_types is not None or source_ids is not None:
        query = (
            query.join(StoryItem, StoryItem.story_id == Story.id)
            .join(NormalizedItem, StoryItem.item_id == NormalizedItem.id)
            .join(RawItem, NormalizedItem.raw_item_id == RawItem.id)
            .join(Source, RawItem.source_id == Source.id)
            .filter(
                Source.enabled.is_(True),
            )
            .distinct()
        )
        if profile.source_types is not None:
            query = query.filter(Source.type.in_(profile.source_types))
        if source_ids is not None:
            query = query.filter(Source.id.in_(source_ids))
    return query


def _with_telegram_reserve(
    db: Session,
    selected: list[int],
    candidates: list[int],
    max_stories: int,
    minimum_telegram_stories: int,
    interest: InterestPolicy,
    source_ids: frozenset[int] | None,
) -> list[int]:
    """Give eligible Telegram stories a bounded seat."""
    if not candidates:
        return []
    material = _story_material(db, candidates)
    telegram_story_ids = {
        story_id
        for story_id, entries in material.items()
        if any(
            entry.source_type == "telegram"
            and (source_ids is None or entry.source_id in source_ids)
            and is_usable_editorial_material(
                title=entry.title,
                description=entry.description,
            )
            and is_interest_material(
                interest=interest,
                source_type=entry.source_type,
                category=entry.category,
                title=entry.title,
                description=entry.description,
            )
            for entry in entries
            if entry.enabled
        )
    }
    telegram_source_ids_by_story = {
        story_id: {
            entry.source_id
            for entry in entries
            if entry.enabled
            and entry.source_type == "telegram"
            and (source_ids is None or entry.source_id in source_ids)
        }
        for story_id, entries in material.items()
    }
    return reserve_telegram_story_ids(
        selected,
        candidates,
        telegram_story_ids=telegram_story_ids,
        telegram_source_ids_by_story=telegram_source_ids_by_story,
        max_stories=max_stories,
        minimum_telegram_stories=minimum_telegram_stories,
    )


def _recent_scoped_story_ids(
    db: Session,
    story_ids: list[int],
    profile: ReportProfile,
    source_ids: frozenset[int] | None,
) -> list[int]:
    """Apply the configured freshness window to in-scope material."""
    material = _story_material(db, story_ids)
    scoped = _scoped_material(material, profile, source_ids)
    return retain_recent_stories(
        story_ids,
        scoped,
        max_age_hours=settings.editorial_max_item_age_hours,
    )


def _balanced_story_ids(
    db: Session,
    story_ids: list[int],
    profile: ReportProfile,
    source_ids: frozenset[int] | None,
    *,
    max_stories: int,
) -> list[int]:
    """Apply the per-source cap to non-comprehensive digests."""
    material = _scoped_material(_story_material(db, story_ids), profile, source_ids)
    return balance_story_sources(
        story_ids,
        material,
        max_stories=max_stories,
        max_per_source=(0 if profile.comprehensive else settings.editorial_max_stories_per_source),
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
        stories = db.query(Story).filter(Story.id.in_(story_ids)).all()
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


def get_scheduled_boundary(
    db: Session,
    digest_slug: str = "default",
) -> datetime | None:
    """Return the advanced_at of the last completely delivered scheduled report.

    Used as the 'since the last completely delivered scheduled report' window
    boundary for scheduled report selection. None when no scheduled report
    has been delivered yet (first run selects all recent material).
    """
    cursor_key = (
        "scheduled_delivery" if digest_slug == "default" else f"scheduled_delivery:{digest_slug}"
    )
    row = db.execute(
        text(
            "SELECT advanced_at FROM report_cursors "
            "WHERE cursor_key = :cursor_key AND advanced_at IS NOT NULL"
        ),
        {"cursor_key": cursor_key},
    ).first()
    return row[0] if row else None


def select_stories_for_report(
    db: Session,
    report_mode: str,
    max_stories: int | None = None,
    *,
    source_types: tuple[str, ...] | None = None,
    source_ids: tuple[int, ...] | None = None,
    interest: InterestPolicy = DEFAULT_INTEREST_POLICY,
    minimum_telegram_stories: int | None = None,
    digest_slug: str = "default",
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
        effective_types = (
            profile.source_types
            if not normalized_types
            else normalized_types
            if profile.source_types is None
            else normalized_types.intersection(profile.source_types)
        )
        profile = replace(
            profile,
            source_types=effective_types,
            minimum_telegram_stories=(
                profile.minimum_telegram_stories
                if effective_types is None or "telegram" in effective_types
                else 0
            ),
        )
    if minimum_telegram_stories is not None:
        profile = replace(
            profile,
            minimum_telegram_stories=max(0, int(minimum_telegram_stories)),
        )
    normalized_source_ids = (
        frozenset(int(source_id) for source_id in source_ids) if source_ids else None
    )
    max_stories = max_stories or profile.max_stories
    delivered_ids = get_delivered_story_ids(db)
    updated_ids = get_delivered_story_versions(db)
    excluded_delivered = delivered_ids - set(updated_ids.keys())
    materially_updated = len(updated_ids)

    if report_mode == "scheduled":
        boundary = get_scheduled_boundary(db, digest_slug)
        if boundary is None:
            # First scheduled run — all recent candidates are new material.
            candidates = (
                _candidate_query(db, profile, normalized_source_ids)
                .order_by(Story.importance_score.desc(), Story.created_at.desc())
                .limit(MAX_CANDIDATE_STORIES)
                .all()
            )
            candidate_ids = _eligible_story_ids(
                db,
                [s.id for s in candidates],
                profile,
                interest,
                normalized_source_ids,
            )
        else:
            # New material since the boundary: created or materially changed after.
            candidates = (
                _candidate_query(db, profile, normalized_source_ids)
                .filter(
                    (Story.created_at > boundary)
                    | (
                        Story.material_change_at.is_not(None)
                        & (Story.material_change_at > boundary)
                    )
                )
                .order_by(Story.importance_score.desc(), Story.created_at.desc())
                .limit(MAX_CANDIDATE_STORIES)
                .all()
            )
            candidate_ids = _eligible_story_ids(
                db,
                [s.id for s in candidates],
                profile,
                interest,
                normalized_source_ids,
            )
        candidate_ids = _recent_scoped_story_ids(
            db,
            candidate_ids,
            profile,
            normalized_source_ids,
        )
        total_candidates = len(candidate_ids)
        # Exclude delivered unchanged stories (already delivered, no change).
        undelivered = [sid for sid in candidate_ids if sid not in excluded_delivered]
        excluded_count = total_candidates - len(undelivered)
        if not undelivered:
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
        selected = _balanced_story_ids(
            db,
            undelivered,
            profile,
            normalized_source_ids,
            max_stories=max_stories,
        )
        selected = _with_telegram_reserve(
            db,
            selected,
            undelivered,
            max_stories,
            profile.minimum_telegram_stories,
            interest,
            normalized_source_ids,
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
                for s in _candidate_query(db, profile, normalized_source_ids)
                .order_by(Story.importance_score.desc(), Story.created_at.desc())
                .limit(MAX_CANDIDATE_STORIES)
                .all()
            ],
            profile,
            interest,
            normalized_source_ids,
        )
        candidate_ids = _recent_scoped_story_ids(
            db,
            candidate_ids,
            profile,
            normalized_source_ids,
        )
        total_candidates = len(candidate_ids)
        undelivered = [sid for sid in candidate_ids if sid not in excluded_delivered]
        excluded_count = len(candidate_ids) - len(undelivered)
        if not undelivered:
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
        selected = _balanced_story_ids(
            db,
            undelivered,
            profile,
            normalized_source_ids,
            max_stories=max_stories,
        )
        selected = _with_telegram_reserve(
            db,
            selected,
            undelivered,
            max_stories,
            profile.minimum_telegram_stories,
            interest,
            normalized_source_ids,
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
        _candidate_query(db, profile, normalized_source_ids)
        .order_by(Story.importance_score.desc(), Story.created_at.desc())
        .limit(MAX_CANDIDATE_STORIES)
        .all()
    )
    candidate_ids = _eligible_story_ids(
        db,
        [s.id for s in candidates],
        profile,
        interest,
        normalized_source_ids,
    )
    candidate_ids = _recent_scoped_story_ids(
        db,
        candidate_ids,
        profile,
        normalized_source_ids,
    )
    total_candidates = len(candidate_ids)
    selected = _balanced_story_ids(
        db,
        candidate_ids,
        profile,
        normalized_source_ids,
        max_stories=max_stories,
    )
    selected = _with_telegram_reserve(
        db,
        selected,
        candidate_ids,
        max_stories,
        profile.minimum_telegram_stories,
        interest,
        normalized_source_ids,
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

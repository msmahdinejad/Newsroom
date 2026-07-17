"""Grounding validator — verifies claims against evidence.

For every factual claim:
- supporting evidence IDs must exist
- evidence must belong to the same story or explicitly linked story
- links must come from persisted source records
- dates and version numbers must appear in evidence
- unsupported claims are removed or cause fallback
- disagreement between sources remains visible

Do not treat model confidence as proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from newsroom.editorial.schema import (
    GROUNDING_VALIDATOR_VERSION,
    ClaimStatus,
    EditorialEvidenceSet,
    EditorialOutput,
    KeyClaim,
    StoryEditorialResult,
)


@dataclass
class GroundingResult:
    """Result of grounding validation."""

    version: str = GROUNDING_VALIDATOR_VERSION
    valid: bool = True
    removed_claims: list[str] = field(default_factory=list)
    removed_stories: list[int] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def add_issue(self, msg: str) -> None:
        self.issues.append(msg)
        self.valid = False


def validate_grounding(
    evidence: EditorialEvidenceSet,
    output: EditorialOutput,
) -> tuple[EditorialOutput, GroundingResult]:
    """Validate and repair editorial output against evidence.

    Returns (cleaned_output, grounding_result).
    Unsupported claims are removed. Stories with no remaining claims are flagged.
    """
    result = GroundingResult()
    valid_ref_ids = evidence.all_ref_ids()
    refs_by_story = evidence.refs_by_story()
    valid_story_ids = evidence.story_ids()
    valid_urls = evidence.all_urls()

    cleaned_stories: list[StoryEditorialResult] = []

    for story_result in output.stories:
        # Check story ID exists in evidence
        if story_result.story_id not in valid_story_ids:
            result.add_issue(
                f"story {story_result.story_id} not in evidence set"
            )
            result.removed_stories.append(story_result.story_id)
            continue

        story_refs = refs_by_story.get(story_result.story_id, set())

        # Check source_ref_ids
        bad_refs = [r for r in story_result.source_ref_ids if r not in valid_ref_ids]
        if bad_refs:
            result.add_issue(
                f"story {story_result.story_id}: invented ref_ids {bad_refs}"
            )
            story_result.source_ref_ids = [
                r for r in story_result.source_ref_ids if r in valid_ref_ids
            ]

        # Check source_links
        bad_links = [lnk for lnk in story_result.source_links if lnk not in valid_urls]
        if bad_links:
            result.add_issue(
                f"story {story_result.story_id}: invented links {bad_links}"
            )
            story_result.source_links = [
                lnk for lnk in story_result.source_links if lnk in valid_urls
            ]

        # Validate each claim
        cleaned_claims: list[KeyClaim] = []
        for claim in story_result.key_claims:
            # Check supporting refs exist
            bad_support = [
                r for r in claim.supporting_evidence_refs if r not in valid_ref_ids
            ]
            if bad_support:
                result.add_issue(
                    f"story {story_result.story_id}: claim '{claim.claim_text[:50]}...' "
                    f"has invented refs {bad_support}"
                )
                claim.supporting_evidence_refs = [
                    r for r in claim.supporting_evidence_refs if r in valid_ref_ids
                ]

            # Check refs belong to this story
            wrong_story_refs = [
                r for r in claim.supporting_evidence_refs if r not in story_refs
            ]
            if wrong_story_refs:
                result.add_issue(
                    f"story {story_result.story_id}: claim refs {wrong_story_refs} "
                    f"belong to different story"
                )
                claim.supporting_evidence_refs = [
                    r for r in claim.supporting_evidence_refs if r in story_refs
                ]

            # Check conflicting refs exist
            bad_conflict = [
                r for r in claim.conflicting_evidence_refs if r not in valid_ref_ids
            ]
            if bad_conflict:
                result.add_issue(
                    f"story {story_result.story_id}: claim '{claim.claim_text[:50]}...' "
                    f"has invented conflicting refs {bad_conflict}"
                )
                claim.conflicting_evidence_refs = [
                    r for r in claim.conflicting_evidence_refs if r in valid_ref_ids
                ]

            # If claim has no supporting refs, mark unsupported
            if not claim.supporting_evidence_refs:
                if claim.support_status == ClaimStatus.SUPPORTED:
                    result.add_issue(
                        f"story {story_result.story_id}: claim '{claim.claim_text[:50]}...' "
                        f"marked supported but has no valid refs — removing"
                    )
                    result.removed_claims.append(claim.claim_text[:80])
                    continue  # remove this claim
                else:
                    # Keep unverified/conflicting claims but note
                    pass

            # Check for unsupported numbers/dates/versions
            if _has_unsupported_numbers(claim.claim_text, evidence, story_result.story_id):
                result.add_issue(
                    f"story {story_result.story_id}: claim contains unsupported numbers/dates/versions"
                )
                result.removed_claims.append(claim.claim_text[:80])
                continue

            cleaned_claims.append(claim)

        story_result.key_claims = cleaned_claims

        # If no claims remain, downgrade confidence
        if not cleaned_claims:
            story_result.confidence_level = min(story_result.confidence_level, 0.1)
            result.add_issue(
                f"story {story_result.story_id}: all claims removed — confidence downgraded"
            )

        cleaned_stories.append(story_result)

    cleaned_output = EditorialOutput(
        metadata=output.metadata,
        stories=cleaned_stories,
    )

    return cleaned_output, result


def _has_unsupported_numbers(
    claim_text: str,
    evidence: EditorialEvidenceSet,
    story_id: int,
) -> bool:
    """Check if claim contains numbers/dates/versions not in evidence.

    This is a conservative heuristic — false positives are better than
    letting unsupported claims through.
    Handles both Latin (0-9) and Persian-Indic (۰-۹) digit variants.
    """
    import re

    # Normalize Persian-Indic digits to Latin for comparison
    persian_map = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

    def normalize_num(s: str) -> str:
        return s.translate(persian_map)

    def extract_numbers(text: str) -> set[str]:
        raw = re.findall(r"\b\d+(?:\.\d+)?\b", text)
        return {normalize_num(n) for n in raw}

    # Extract all numbers from claim (normalized)
    numbers = extract_numbers(claim_text)
    if not numbers:
        return False

    # Collect all numbers from evidence for this story (normalized)
    evidence_numbers: set[str] = set()
    for story in evidence.stories:
        if story.story_id != story_id:
            continue
        # From headlines, facts, excerpts, titles
        texts = [story.headline] + story.facts
        for src in story.sources:
            texts.append(src.original_title)
            texts.append(src.excerpt)
            if src.release_version:
                evidence_numbers.update(extract_numbers(src.release_version))
        for text in texts:
            evidence_numbers.update(extract_numbers(text))

    # Check each number in claim against evidence
    for num in numbers:
        if num not in evidence_numbers:
            # Allow small common numbers that might be in dates/percentages
            if num in {"0", "1", "2", "3", "100"}:
                continue
            return True

    return False

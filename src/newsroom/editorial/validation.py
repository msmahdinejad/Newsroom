"""Schema validation for editorial output.

Rejects or repairs:
- malformed JSON
- missing required fields
- unknown story IDs
- unknown evidence IDs
- invented links
- prose outside schema
- claim references that don't exist
- output exceeding limits
- wrong language
- duplicate story entries
- invalid confidence
- unsupported enum values

Uses bounded repair attempts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from newsroom.editorial.schema import (
    EditorialError,
    EditorialErrorCategory,
    EditorialEvidenceSet,
    EditorialOutput,
)

_PERSIAN_RE = re.compile(r"[\u0600-\u06ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)


@dataclass
class ValidationResult:
    valid: bool = True
    issues: list[str] = field(default_factory=list)
    repaired: bool = False


def parse_and_validate(
    raw_content: str,
    evidence: EditorialEvidenceSet,
    max_output_tokens: int = 4000,
) -> tuple[EditorialOutput | None, ValidationResult]:
    """Parse raw model output and validate against schema.

    Returns (output, result). output is None if validation fails.
    """
    result = ValidationResult()

    # Step 1: Parse JSON — try direct, then extract from markdown code block
    output_dict: dict | None = None
    try:
        output_dict = json.loads(raw_content)
    except json.JSONDecodeError:
        # Try extracting from markdown code block
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw_content, re.DOTALL)
        if match:
            try:
                output_dict = json.loads(match.group(1))
                result.repaired = True
                result.issues.append("extracted from markdown code block")
            except json.JSONDecodeError:
                pass

    if output_dict is None:
        result.valid = False
        result.issues.append("malformed JSON — cannot parse")
        return (None, result)

    # Step 2: Check required top-level fields
    if "stories" not in output_dict:
        result.valid = False
        result.issues.append("missing 'stories' field")
        return (None, result)

    if "metadata" not in output_dict:
        result.valid = False
        result.issues.append("missing 'metadata' field")
        return (None, result)

    # Step 3: Check for duplicate story IDs
    stories = output_dict.get("stories", [])
    story_ids = [s.get("story_id") for s in stories if isinstance(s, dict)]

    # If evidence has stories but output has none, that's a schema failure
    if not stories and evidence.stories:
        result.valid = False
        result.issues.append("no stories in output despite evidence having stories")
        return (None, result)

    seen_ids: set[int] = set()
    for sid in story_ids:
        if sid is None:
            continue
        if sid in seen_ids:
            result.valid = False
            result.issues.append(f"duplicate story ID: {sid}")
            return (None, result)
        seen_ids.add(sid)

    # Step 4: Check unknown story IDs
    valid_story_ids = evidence.story_ids()
    for sid in story_ids:
        if sid not in valid_story_ids:
            result.valid = False
            result.issues.append(f"unknown story ID: {sid}")
            return (None, result)
    missing_story_ids = valid_story_ids - seen_ids
    if missing_story_ids:
        result.valid = False
        result.issues.append(f"missing story IDs: {sorted(missing_story_ids)}")
        return (None, result)

    # Step 5: Check output size (approximate token count via char/4)
    approx_tokens = len(raw_content) // 4
    if approx_tokens > max_output_tokens * 1.5:
        result.valid = False
        result.issues.append(f"output exceeds limit: ~{approx_tokens} tokens > {max_output_tokens}")
        return (None, result)

    # Step 6: Validate enum values and confidence ranges
    valid_classifications = {
        "official", "corroborated", "single_reputable", "community",
        "conflicting", "unverified", "unavailable",
    }
    valid_claim_status = {"supported", "conflicting", "unsupported", "unverified"}
    valid_priorities = {"high", "medium", "low"}

    for story in stories:
        sid = story.get("story_id", "?")
        copy_issue = _reader_facing_copy_issue(
            story,
            report_language=evidence.report_language,
        )
        if copy_issue:
            result.valid = False
            result.issues.append(f"story {sid}: reader-facing copy {copy_issue}")
            return (None, result)

        cls = story.get("classification", "")
        if cls and cls not in valid_classifications:
            result.valid = False
            result.issues.append(f"story {sid}: invalid classification '{cls}'")
            return (None, result)

        conf = story.get("confidence_level", 0)
        if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
            result.valid = False
            result.issues.append(f"story {sid}: invalid confidence {conf}")
            return (None, result)

        priority = story.get("suggested_priority", "medium")
        if priority not in valid_priorities:
            story["suggested_priority"] = "medium"
            result.repaired = True
            result.issues.append(f"story {sid}: repaired priority to 'medium'")

        # Check claims
        claims = story.get("key_claims", [])
        for ci, claim in enumerate(claims):
            cs = claim.get("support_status", "unverified")
            if cs not in valid_claim_status:
                claim["support_status"] = "unverified"
                result.repaired = True
                result.issues.append(f"story {sid} claim {ci}: repaired status to 'unverified'")

            cc = claim.get("confidence", 0)
            if not isinstance(cc, (int, float)) or cc < 0 or cc > 1:
                claim["confidence"] = 0.0
                result.repaired = True
                result.issues.append(f"story {sid} claim {ci}: repaired confidence to 0.0")

    # Step 7: Try Pydantic validation
    try:
        output = EditorialOutput.model_validate(output_dict)
    except Exception as e:
        result.valid = False
        result.issues.append(f"schema validation failed: {e}")
        return (None, result)

    # Step 8: Check evidence refs exist
    valid_refs = evidence.all_ref_ids()
    all_claim_refs = output.all_claim_refs()
    unknown_refs = all_claim_refs - valid_refs
    if unknown_refs:
        result.valid = False
        result.issues.append(f"unknown evidence refs in claims: {unknown_refs}")
        return (None, result)

    if not result.valid:
        return (None, result)
    return (output, result)


def _reader_facing_copy_issue(
    story: dict,
    *,
    report_language: str,
) -> str | None:
    """Reject source-shaped output before it can reach the public renderer."""
    headline = story.get("headline_fa")
    summary = story.get("summary_fa")
    if not isinstance(headline, str) or not headline.strip():
        return "has an empty headline"
    if not isinstance(summary, str) or not summary.strip():
        return "has an empty summary"
    if len(headline) > 180 or len(summary) > 600:
        return "exceeds the compact-copy limit"
    if _URL_RE.search(headline):
        return "has a URL-shaped headline"
    language = report_language.casefold().split("-", maxsplit=1)[0]
    if language == "fa" and (
        not _PERSIAN_RE.search(headline) or not _PERSIAN_RE.search(summary)
    ):
        return "is not Persian"
    if language == "en" and (
        not _LATIN_RE.search(headline) or not _LATIN_RE.search(summary)
    ):
        return "is not English"
    return None


def create_validation_error(
    result: ValidationResult,
) -> EditorialError:
    """Create an EditorialError from validation failure."""
    detail = "; ".join(result.issues[:5])
    return EditorialError(
        EditorialErrorCategory.SCHEMA_VALIDATION,
        detail,
        retryable=False,
    )

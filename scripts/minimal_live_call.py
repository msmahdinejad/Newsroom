"""Phase 6: Minimal live provider call — tiny synthetic evidence, no delivery.

Records only safe metadata: provider, model (name only), endpoint type,
latency, validation status, grounding status, usage, retry count,
redacted error category if failed.

Never records: API key, authorization headers, raw environment, reasoning.
"""

from __future__ import annotations

import json
import sys
import time

from newsroom.editorial.grounding import validate_grounding
from newsroom.editorial.openai_provider import OpenAICompatibleEditorialProvider
from newsroom.editorial.schema import (
    EditorialEvidenceSet,
    EditorialRequest,
    EvidenceSourceItem,
    EvidenceStoryPacket,
)
from newsroom.editorial.validation import parse_and_validate


def build_tiny_evidence() -> EditorialEvidenceSet:
    """Build a tiny synthetic public evidence packet: 1 story, 2 sources."""
    return EditorialEvidenceSet(
        stories=[
            EvidenceStoryPacket(
                story_id=1,
                headline="Python 3.13.1 released",
                keywords=["python", "release"],
                trust_status="official",
                confidence=0.95,
                importance_score=0.75,
                source_count=2,
                item_count=2,
                sources=[
                    EvidenceSourceItem(
                        ref_id="ev-1-0",
                        item_id=1,
                        source_name="Python.org RSS",
                        source_type="rss",
                        source_trust="official",
                        source_trust_score=0.95,
                        published_at="2026-07-17T08:00:00+00:00",
                        original_title="Python 3.13.1",
                        excerpt="Python 3.13.1 is the first maintenance release of the 3.13 series.",
                        original_url="https://www.python.org/downloads/release/python-1311/",
                    ),
                    EvidenceSourceItem(
                        ref_id="ev-1-1",
                        item_id=2,
                        source_name="GitHub Releases",
                        source_type="github_releases",
                        source_trust="official",
                        source_trust_score=0.9,
                        published_at="2026-07-17T09:00:00+00:00",
                        original_title="python/cpython 3.13.1",
                        excerpt="Maintenance release with bug fixes.",
                        original_url="https://github.com/python/cpython/releases/tag/v3.13.1",
                    ),
                ],
                facts=[
                    "Python 3.13.1 is a maintenance release",
                    "It includes bug fixes for the 3.13 series",
                ],
                contradictions=[],
                evidence_freshness="2026-07-17T09:00:00+00:00",
            )
        ]
    )


def run_minimal_call() -> dict:
    """Run one minimal provider call. Returns safe metadata only."""
    from newsroom.config import settings

    if not settings.editorial_ready():
        return {
            "status": "skipped",
            "reason": "editorial not ready — no credentials configured",
        }

    result: dict = {
        "provider": settings.editorial_provider,
        "configured_model": settings.editorial_model,
        "endpoint_type": "openai_compatible /chat/completions",
        "api_base": settings.editorial_api_base,
        "configured_max_output_tokens": settings.editorial_max_output_tokens,
    }

    provider = OpenAICompatibleEditorialProvider(
        api_base=settings.editorial_api_base,
        api_key=settings.editorial_api_key,
        model=settings.editorial_model,
        timeout_seconds=30,
        max_retries=1,
        max_output_tokens=2000,  # small limit for minimal call
    )

    result["effective_max_output_tokens"] = provider.effective_max_output_tokens

    evidence = build_tiny_evidence()
    request = EditorialRequest(
        evidence=evidence,
        model=settings.editorial_model,
        max_output_tokens=2000,
        timeout_seconds=30,
    )

    start = time.monotonic()
    try:
        response = provider.generate(request)
        result["status"] = "success"
        result["latency_ms"] = response.latency_ms
        result["retry_count"] = response.retry_count
        result["finish_status"] = response.finish_status
        result["usage"] = response.usage
        result["output_stories"] = len(response.output.stories)
        result["schema_version"] = response.output.metadata.schema_version
        result["prompt_version"] = response.output.metadata.prompt_version

        # Validate output
        raw = response.output.model_dump_json(indent=2)
        parsed, val_result = parse_and_validate(raw, evidence, 2000)
        result["validation_status"] = "valid" if val_result.valid else f"invalid: {val_result.issues}"

        # Grounding check
        grounded, grounding_result = validate_grounding(evidence, response.output)
        result["grounding_status"] = "valid" if grounding_result.valid else f"issues: {grounding_result.issues}"
        result["grounding_removed_claims"] = grounding_result.removed_claims

        # Safe output summary
        if response.output.stories:
            s = response.output.stories[0]
            result["story_headline_fa"] = s.headline_fa
            result["story_claims_count"] = len(s.key_claims)
            result["story_source_links"] = s.source_links
            result["story_classification"] = s.classification
            result["story_confidence"] = s.confidence_level

    except Exception as e:
        result["status"] = "failed"
        result["latency_ms"] = int((time.monotonic() - start) * 1000)
        result["error_type"] = type(e).__name__
        # Only record error category, not full detail that might contain headers
        if hasattr(e, "category"):
            result["error_category"] = str(e.category)
        result["error_summary"] = str(e)[:200]  # truncated, no headers

    return result


if __name__ == "__main__":
    print("Phase 6: Minimal live provider call", file=sys.stderr)
    result = run_minimal_call()
    # Print only the safe result as JSON
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

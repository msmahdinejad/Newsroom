"""Deterministic editorial provider — no network, always available.

This is the terminal structured fallback when every validated AI route is
unavailable. Public rendering is centralized in ``editorial.presentation``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from newsroom.editorial.provider import EditorialProvider
from newsroom.editorial.schema import (
    OUTPUT_SCHEMA_VERSION,
    SYSTEM_PROMPT_VERSION,
    ClaimStatus,
    EditorialClassification,
    EditorialOutput,
    EditorialRequest,
    EditorialResponse,
    EvidenceStoryPacket,
    KeyClaim,
    ReportMetadata,
    StoryEditorialResult,
)

TRUST_FA = {
    "official": "\u0631\u0633\u0645\u06cc",
    "confirmed": "\u062a\u0623\u06cc\u06cc\u062f\u0634\u062f\u0647",
    "likely": "\u0645\u062d\u062a\u0645\u0644",
    "unconfirmed": "\u062a\u0623\u06cc\u06cc\u062f\u0646\u0634\u062f\u0647",
    "rumor": "\u0634\u0627\u06cc\u0639\u0647",
    "promotional": "\u062a\u0628\u0644\u06cc\u063a\u0627\u062a\u06cc",
    "suspicious": "\u0645\u0634\u06a9\u0648\u06a9",
}


class DeterministicEditorialProvider(EditorialProvider):
    """Non-AI fallback — always available, no network dependency."""

    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "deterministic"

    @property
    def model_name(self) -> str:
        return "deterministic-v1"

    def generate(self, request: EditorialRequest) -> EditorialResponse:
        """Generate a deterministic editorial response from evidence."""
        import time

        start = time.monotonic()
        evidence = request.evidence

        story_results: list[StoryEditorialResult] = []
        for story_pkt in evidence.stories:
            # Map trust status to classification — contradictions take priority
            trust = story_pkt.trust_status
            if story_pkt.contradictions:
                classification = EditorialClassification.CONFLICTING
            elif trust == "official":
                classification = EditorialClassification.OFFICIAL
            elif story_pkt.source_count >= 2 and trust in ("confirmed", "likely"):
                classification = EditorialClassification.CORROBORATED
            elif trust == "rumor":
                classification = EditorialClassification.COMMUNITY
            elif trust in ("confirmed", "likely"):
                classification = EditorialClassification.SINGLE_REPUTABLE
            else:
                classification = EditorialClassification.UNVERIFIED

            # Build claims from facts — each mapped to source refs
            ref_ids = [s.ref_id for s in story_pkt.sources[: request_max_refs(request)]]
            key_claims: list[KeyClaim] = []
            for i, fact in enumerate(story_pkt.facts[:5]):
                # Assign refs round-robin
                supporting = [ref_ids[i % len(ref_ids)]] if ref_ids else []
                key_claims.append(
                    KeyClaim(
                        claim_text=fact,
                        supporting_evidence_refs=supporting,
                        support_status=ClaimStatus.SUPPORTED
                        if supporting
                        else ClaimStatus.UNVERIFIED,
                        confidence=story_pkt.confidence,
                    )
                )

            # Persian headline — use story headline if Persian, else render from sources
            headline_fa = (
                story_pkt.headline
                if _is_persian(story_pkt.headline)
                else _render_fa_headline(story_pkt)
            )

            summary_fa = _render_fa_summary(story_pkt)
            why_it_matters = _render_why_it_matters(story_pkt)
            practical_impact = _render_practical_impact(story_pkt)

            source_links = [s.original_url for s in story_pkt.sources if s.original_url][:5]

            story_results.append(
                StoryEditorialResult(
                    story_id=story_pkt.story_id,
                    headline=headline_fa,
                    summary=summary_fa,
                    why_it_matters_fa=why_it_matters,
                    practical_impact_fa=practical_impact,
                    target_audience="developers",
                    confidence_level=story_pkt.confidence,
                    verification_status=trust,
                    classification=classification,
                    source_ref_ids=ref_ids,
                    source_links=source_links,
                    key_claims=key_claims,
                    uncertainty_notes=_render_uncertainty(story_pkt),
                    suggested_priority="high" if story_pkt.importance_score >= 0.7 else "medium",
                    watch_next_note=None,
                )
            )

        now_iso = datetime.now(UTC).isoformat()
        metadata = ReportMetadata(
            schema_version=OUTPUT_SCHEMA_VERSION,
            report_mode=evidence.report_mode,
            generated_at=now_iso,
            model_name=self.model_name,
            provider=self.name,
            evidence_set_hash=evidence.evidence_hash(),
            prompt_version=SYSTEM_PROMPT_VERSION,
            editorial_status="ok",
        )

        output = EditorialOutput(metadata=metadata, stories=story_results)

        from newsroom.editorial.provider import time_ms

        return EditorialResponse(
            output=output,
            model=self.model_name,
            provider=self.name,
            latency_ms=time_ms(start),
            finish_status="stop",
            usage=None,
            retry_count=0,
            fallback_used=False,
        )


def request_max_refs(request: EditorialRequest) -> int:
    """Max evidence refs per story from request constraints."""
    # ponytail: simpler to cap at evidence count than track separate limit
    return max(
        1, min(10, len(request.evidence.stories[0].sources) if request.evidence.stories else 0)
    )


def _is_persian(text: str) -> bool:
    if not text:
        return False
    persian_chars = sum(1 for c in text if "\u0600" <= c <= "\u06ff")
    return persian_chars > len(text) * 0.15


def _render_fa_headline(story: EvidenceStoryPacket) -> str:
    if story.headline:
        return str(story.headline)
    if story.sources:
        return str(
            story.sources[0].original_title
            or "\u062e\u0628\u0631 \u0641\u0646\u0627\u0648\u0631\u06cc"
        )
    return "\u062e\u0628\u0631 \u0641\u0646\u0627\u0648\u0631\u06cc"


def _render_fa_summary(story: EvidenceStoryPacket) -> str:
    parts = []
    if story.facts:
        parts.append(story.facts[0])
    if story.source_count > 1:
        parts.append(
            f"\u0627\u06cc\u0646 \u062e\u0628\u0631 \u0627\u0632 {story.source_count} \u0645\u0646\u0628\u0639 \u0645\u0633\u062a\u0642\u0644 \u06af\u0632\u0627\u0631\u0634 \u0634\u062f\u0647 \u0627\u0633\u062a."
        )
    return (
        " ".join(parts)
        if parts
        else "\u062c\u0632\u0626\u06cc\u0627\u062a \u0628\u06cc\u0634\u062a\u0631 \u062f\u0631 \u0645\u0646\u0627\u0628\u0639."
    )


def _render_why_it_matters(story: EvidenceStoryPacket) -> str:
    importance = story.importance_score
    if importance >= 0.7:
        return "\u0627\u06cc\u0646 \u062e\u0628\u0631 \u0628\u0631\u0627\u06cc \u062a\u0648\u0633\u0639\u0647‌\u062f\u0647\u0646\u062f\u06af\u0627\u0646 \u0648 \u0641\u0639\u0627\u0644\u0627\u0646 \u062d\u0648\u0632\u0647 \u0641\u0646\u0627\u0648\u0631\u06cc \u0627\u0647\u0645\u06cc\u062a \u0628\u0627\u0644\u0627\u06cc\u06cc \u062f\u0627\u0631\u062f."
    if importance >= 0.3:
        return "\u0627\u06cc\u0646 \u062e\u0628\u0631 \u0645\u0645\u06a9\u0646 \u0627\u0633\u062a \u0628\u0631\u0627\u06cc \u067e\u0631\u0648\u0698\u0647‌\u0647\u0627\u06cc \u0645\u0631\u062a\u0628\u0637 \u0642\u0627\u0628\u0644 \u062a\u0648\u062c\u0647 \u0628\u0627\u0634\u062f."
    return "\u0627\u06cc\u0646 \u062e\u0628\u0631 \u062f\u0631 \u062f\u0633\u062a\u0647 \u0627\u062e\u0628\u0627\u0631 \u0645\u062a\u062f\u0627\u0648\u0644 \u0642\u0631\u0627\u0631 \u0645\u06cc‌\u06af\u06cc\u0631\u062f."


def _render_practical_impact(story: EvidenceStoryPacket) -> str:
    if story.keywords:
        kws = "\u060c ".join(story.keywords[:3])
        return f"\u0645\u0631\u062a\u0628\u0637 \u0628\u0627 \u0645\u0648\u0636\u0648\u0639\u0627\u062a: {kws}. \u0628\u0631\u0627\u06cc \u062a\u0648\u0633\u0639\u0647‌\u062f\u0647\u0646\u062f\u06af\u0627\u0646 \u0645\u0631\u062a\u0628\u0637 \u0628\u0627 \u0627\u06cc\u0646 \u062d\u0648\u0632\u0647 \u0642\u0627\u0628\u0644 \u062a\u0648\u062c\u0647 \u0627\u0633\u062a."
    return "\u0628\u0631\u0627\u06cc \u0627\u0631\u0632\u06cc\u0627\u0628\u06cc \u06a9\u0627\u0631\u0628\u0631\u062f \u0639\u0645\u0644\u06cc\u060c \u0645\u0646\u0627\u0628\u0639 \u0627\u0635\u0644\u06cc \u0631\u0627 \u0628\u0631\u0631\u0633\u06cc \u06a9\u0646\u06cc\u062f."


def _render_uncertainty(story: EvidenceStoryPacket) -> str:
    if story.contradictions:
        return "\u0645\u0646\u0627\u0628\u0639 \u062f\u0631 \u0628\u0631\u062e\u06cc \u062c\u0632\u0626\u06cc\u0627\u062a \u0627\u062e\u062a\u0644\u0627\u0641 \u0646\u0638\u0631 \u062f\u0627\u0631\u0646\u062f."
    trust_fa = TRUST_FA.get(story.trust_status, story.trust_status)
    if story.trust_status in ("rumor", "unconfirmed"):
        return f"\u0648\u0636\u0639\u06cc\u062a: {trust_fa} — \u0646\u06cc\u0627\u0632 \u0628\u0647 \u062a\u0623\u06cc\u06cc\u062f \u0628\u06cc\u0634\u062a\u0631."
    return ""

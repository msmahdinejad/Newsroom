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
    "official": "رسمی",
    "confirmed": "تأییدشده",
    "likely": "محتمل",
    "unconfirmed": "تأییدنشده",
    "rumor": "شایعه",
    "promotional": "تبلیغاتی",
    "suspicious": "مشکوک",
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
                        support_status=ClaimStatus.SUPPORTED if supporting else ClaimStatus.UNVERIFIED,
                        confidence=story_pkt.confidence,
                    )
                )

            # Persian headline — use story headline if Persian, else render from sources
            headline_fa = story_pkt.headline if _is_persian(story_pkt.headline) else _render_fa_headline(story_pkt)

            summary_fa = _render_fa_summary(story_pkt)
            why_it_matters = _render_why_it_matters(story_pkt)
            practical_impact = _render_practical_impact(story_pkt)

            source_links = [s.original_url for s in story_pkt.sources if s.original_url][:5]

            story_results.append(
                StoryEditorialResult(
                    story_id=story_pkt.story_id,
                    headline_fa=headline_fa,
                    summary_fa=summary_fa,
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
    return max(1, min(10, len(request.evidence.stories[0].sources) if request.evidence.stories else 0))


def _is_persian(text: str) -> bool:
    if not text:
        return False
    persian_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    return persian_chars > len(text) * 0.15


def _render_fa_headline(story: EvidenceStoryPacket) -> str:
    if story.headline:
        return str(story.headline)
    if story.sources:
        return str(story.sources[0].original_title or "خبر فناوری")
    return "خبر فناوری"


def _render_fa_summary(story: EvidenceStoryPacket) -> str:
    parts = []
    if story.facts:
        parts.append(story.facts[0])
    if story.source_count > 1:
        parts.append(f"این خبر از {story.source_count} منبع مستقل گزارش شده است.")
    return " ".join(parts) if parts else "جزئیات بیشتر در منابع."


def _render_why_it_matters(story: EvidenceStoryPacket) -> str:
    importance = story.importance_score
    if importance >= 0.7:
        return "این خبر برای توسعه‌دهندگان و فعالان حوزه فناوری اهمیت بالایی دارد."
    if importance >= 0.3:
        return "این خبر ممکن است برای پروژه‌های مرتبط قابل توجه باشد."
    return "این خبر در دسته اخبار متداول قرار می‌گیرد."


def _render_practical_impact(story: EvidenceStoryPacket) -> str:
    if story.keywords:
        kws = "، ".join(story.keywords[:3])
        return f"مرتبط با موضوعات: {kws}. برای توسعه‌دهندگان مرتبط با این حوزه قابل توجه است."
    return "برای ارزیابی کاربرد عملی، منابع اصلی را بررسی کنید."


def _render_uncertainty(story: EvidenceStoryPacket) -> str:
    if story.contradictions:
        return "منابع در برخی جزئیات اختلاف نظر دارند."
    trust_fa = TRUST_FA.get(story.trust_status, story.trust_status)
    if story.trust_status in ("rumor", "unconfirmed"):
        return f"وضعیت: {trust_fa} — نیاز به تأیید بیشتر."
    return ""

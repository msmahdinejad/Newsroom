"""Deterministic fake provider for scalability tests.

Simulates realistic token usage and latency without real API calls.
Returns valid structured editorial output for any evidence set.
"""

from __future__ import annotations

import time
from typing import Any

from newsroom.editorial.provider import EditorialProvider
from newsroom.editorial.schema import (
    OUTPUT_SCHEMA_VERSION,
    SYSTEM_PROMPT_VERSION,
    ClaimStatus,
    EditorialClassification,
    EditorialOutput,
    EditorialRequest,
    EditorialResponse,
    KeyClaim,
    ReportMetadata,
    StoryEditorialResult,
)


class FakeScalableProvider(EditorialProvider):
    """Deterministic fake provider for scalability testing.

    Simulates:
    - realistic token usage based on evidence size
    - configurable latency
    - bounded concurrency tracking
    - optional failure injection for fault-isolation tests

    Never makes real network calls. Safe for large-scale testing.
    """

    def __init__(
        self,
        name: str = "fake_scalable",
        model: str = "fake-model",
        latency_ms: int = 100,
        fail_shard_ids: set[str] | None = None,
        fail_after_n_calls: int | None = None,
    ) -> None:
        self._name = name
        self._model = model
        self._latency_ms = latency_ms
        self._fail_shard_ids = fail_shard_ids or set()
        self._fail_after_n_calls = fail_after_n_calls
        self.call_count = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.concurrency_high_water_mark = 0
        self._in_flight = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_name(self) -> str:
        return self._model

    def generate(self, request: EditorialRequest) -> EditorialResponse:
        self._in_flight += 1
        self.concurrency_high_water_mark = max(
            self.concurrency_high_water_mark, self._in_flight
        )
        try:
            self.call_count += 1

            if self._fail_after_n_calls and self.call_count > self._fail_after_n_calls:
                from newsroom.editorial.schema import EditorialError, EditorialErrorCategory

                raise EditorialError(
                    EditorialErrorCategory.PROVIDER_UNAVAILABLE,
                    f"injected failure at call {self.call_count}",
                    retryable=True,
                )

            # Simulate latency
            time.sleep(self._latency_ms / 1000.0)

            # Estimate token usage
            evidence_json = request.evidence.model_dump_json()
            prompt_tokens = max(1, len(evidence_json) // 4)
            completion_tokens = max(1, len(evidence_json) // 8)

            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens

            # Build deterministic output
            output = self._build_output(request.evidence)

            return EditorialResponse(
                output=output,
                model=self._model,
                provider=self._name,
                latency_ms=self._latency_ms,
                finish_status="stop",
                usage={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
                retry_count=0,
                fallback_used=False,
            )
        finally:
            self._in_flight -= 1

    def _build_output(self, evidence: Any) -> EditorialOutput:
        """Build a valid deterministic output from the evidence set."""
        stories: list[StoryEditorialResult] = []
        for sp in evidence.stories:
            refs = [s.ref_id for s in sp.sources]
            links = [s.original_url for s in sp.sources if s.original_url]

            # Build claims from facts
            claims: list[KeyClaim] = []
            for _i, fact in enumerate(sp.facts[:3]):
                claims.append(KeyClaim(
                    claim_text=fact,
                    supporting_evidence_refs=refs[:1] if refs else [],
                    support_status=ClaimStatus.SUPPORTED if refs else ClaimStatus.UNVERIFIED,
                    confidence=sp.confidence,
                ))

            # Persian headline
            headline_fa = f"\u062e\u0628\u0631 {sp.story_id}"
            summary_fa = f"\u062e\u0644\u0627\u0635\u0647 \u062e\u0628\u0631 {sp.story_id}"
            why_fa = "\u0627\u06cc\u0646 \u062e\u0628\u0631 \u0645\u0647\u0645 \u0627\u0633\u062a"

            stories.append(StoryEditorialResult(
                story_id=sp.story_id,
                headline_fa=headline_fa,
                summary_fa=summary_fa,
                why_it_matters_fa=why_fa,
                practical_impact_fa="\u06a9\u0627\u0631\u0628\u0631\u062f \u0639\u0645\u0644\u06cc",
                target_audience="developers",
                confidence_level=sp.confidence,
                verification_status=sp.trust_status,
                classification=EditorialClassification.CORROBORATED,
                source_ref_ids=refs,
                source_links=links,
                key_claims=claims,
                uncertainty_notes="",
                suggested_priority="high" if sp.importance_score >= 0.7 else "medium",
            ))

        return EditorialOutput(
            metadata=ReportMetadata(
                schema_version=OUTPUT_SCHEMA_VERSION,
                prompt_version=SYSTEM_PROMPT_VERSION,
                report_mode=evidence.report_mode,
                model_name=self._model,
                provider=self._name,
                evidence_set_hash=evidence.evidence_hash(),
                editorial_status="ok",
            ),
            stories=stories,
        )

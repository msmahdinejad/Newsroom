"""Versioned schemas for Editorial editorial layer.

Evidence schema: bounded structured input sent to the AI provider.
Output schema: versioned structured editorial response.

All content is untrusted — serialized as data, not executable instructions.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ── Version constants ─────────────────────────────────────────────

SYSTEM_PROMPT_VERSION = "g7sp-v4"
EVIDENCE_SCHEMA_VERSION = "g7ev-v2"
OUTPUT_SCHEMA_VERSION = "g7out-v3"
TERMINOLOGY_POLICY_VERSION = "g5tp-v2"
GROUNDING_VALIDATOR_VERSION = "g4gv-v1"
EDITORIAL_PROVIDER_VERSION = "g4pv-v1"

# ── Evidence packet (input) ───────────────────────────────────────


class EvidenceSourceItem(BaseModel):
    """A single source item within an evidence packet."""

    ref_id: str = Field(description="Stable reference ID like 'ev-<story>-<seq>'")
    item_id: int = Field(description="Internal normalized item ID")
    source_name: str = ""
    source_type: str = "unknown"
    source_trust: str = "unverified"  # official/community/unverified/reputable
    source_trust_score: float = 0.0
    published_at: str | None = None
    original_title: str = ""
    excerpt: str = ""
    original_url: str = ""
    telegram_permalink: str | None = None
    repo_name: str | None = None
    release_version: str | None = None
    detected_language: str = "en"


class EvidenceStoryPacket(BaseModel):
    """A bounded evidence packet for one story."""

    story_id: int
    headline: str = ""
    keywords: list[str] = Field(default_factory=list)
    trust_status: str = "unconfirmed"
    confidence: float = 0.0
    importance_score: float = 0.0
    source_count: int = 1
    item_count: int = 0
    sources: list[EvidenceSourceItem] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    evidence_freshness: str = ""  # ISO timestamp of most recent source
    duplicate_cluster_info: dict[str, Any] | None = None


class EditorialEvidenceSet(BaseModel):
    """The complete evidence set sent to a provider for one editorial call."""

    schema_version: str = EVIDENCE_SCHEMA_VERSION
    prompt_version: str = SYSTEM_PROMPT_VERSION
    report_mode: str = "scheduled"
    report_language: str = "fa"
    stories: list[EvidenceStoryPacket] = Field(default_factory=list)

    def evidence_hash(self) -> str:
        """Deterministic hash of evidence set for caching and audit."""
        import hashlib
        import json

        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def all_ref_ids(self) -> set[str]:
        ids: set[str] = set()
        for s in self.stories:
            for src in s.sources:
                ids.add(src.ref_id)
        return ids

    def story_ids(self) -> set[int]:
        return {s.story_id for s in self.stories}

    def refs_by_story(self) -> dict[int, set[str]]:
        result: dict[int, set[str]] = {}
        for s in self.stories:
            result[s.story_id] = {src.ref_id for src in s.sources}
        return result

    def all_urls(self) -> set[str]:
        urls: set[str] = set()
        for s in self.stories:
            for src in s.sources:
                if src.original_url:
                    urls.add(src.original_url)
                if src.telegram_permalink:
                    urls.add(src.telegram_permalink)
        return urls


# ── Structured editorial output ──────────────────────────────────


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    CONFLICTING = "conflicting"
    UNSUPPORTED = "unsupported"
    UNVERIFIED = "unverified"


class EditorialClassification(StrEnum):
    OFFICIAL = "official"
    CORROBORATED = "corroborated"
    SINGLE_REPUTABLE = "single_reputable"
    COMMUNITY = "community"
    CONFLICTING = "conflicting"
    UNVERIFIED = "unverified"
    UNAVAILABLE = "unavailable"


class KeyClaim(BaseModel):
    """A factual claim with supporting evidence references."""

    claim_text: str
    supporting_evidence_refs: list[str] = Field(default_factory=list)
    support_status: ClaimStatus = ClaimStatus.UNVERIFIED
    confidence: float = 0.0
    conflicting_evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def valid_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class StoryEditorialResult(BaseModel):
    """Per-story editorial result from the AI provider."""

    story_id: int
    headline_fa: str = ""
    summary_fa: str = ""
    why_it_matters_fa: str = ""
    practical_impact_fa: str = ""
    target_audience: str = ""
    confidence_level: float = 0.0
    verification_status: str = "unverified"
    classification: EditorialClassification = EditorialClassification.UNVERIFIED
    source_ref_ids: list[str] = Field(default_factory=list)
    source_links: list[str] = Field(default_factory=list)
    key_claims: list[KeyClaim] = Field(default_factory=list)
    uncertainty_notes: str = ""
    suggested_priority: str = "medium"
    watch_next_note: str | None = None

    @field_validator("confidence_level")
    @classmethod
    def valid_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class ReportMetadata(BaseModel):
    """Metadata about the editorial generation."""

    schema_version: str = OUTPUT_SCHEMA_VERSION
    report_mode: str = "scheduled"
    report_language: str = "fa"
    generated_at: str = ""
    model_name: str = ""
    provider: str = "deterministic"
    evidence_set_hash: str = ""
    prompt_version: str = SYSTEM_PROMPT_VERSION
    editorial_status: str = "ok"  # ok/fallback/validation_failed


class EditorialOutput(BaseModel):
    """Complete structured editorial output from a provider."""

    metadata: ReportMetadata
    stories: list[StoryEditorialResult] = Field(default_factory=list)

    def story_ids(self) -> set[int]:
        return {s.story_id for s in self.stories}

    def all_claim_refs(self) -> set[str]:
        refs: set[str] = set()
        for s in self.stories:
            for c in s.key_claims:
                refs.update(c.supporting_evidence_refs)
                refs.update(c.conflicting_evidence_refs)
            refs.update(s.source_ref_ids)
        return refs


# ── Editorial error categories ────────────────────────────────────


class EditorialErrorCategory(StrEnum):
    INVALID_API_KEY = "invalid_api_key"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    MALFORMED_RESPONSE = "malformed_response"
    SCHEMA_VALIDATION = "schema_validation"
    UNSUPPORTED_CLAIMS = "unsupported_claims"
    CONTEXT_LENGTH = "context_length"
    PARTIAL_RESPONSE = "partial_response"
    SAFETY_REFUSAL = "safety_refusal"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


class EditorialError(Exception):
    """Typed editorial error with category."""

    def __init__(
        self,
        category: EditorialErrorCategory,
        detail: str,
        retryable: bool = False,
    ) -> None:
        self.category = category
        self.detail = detail[:500]
        self.retryable = retryable
        super().__init__(f"[{category.value}] {detail}")


# ── Provider interface ────────────────────────────────────────────


class EditorialRequest(BaseModel):
    """Structured request to an editorial provider."""

    evidence: EditorialEvidenceSet
    model: str = ""
    temperature: float = 0.3
    max_input_tokens: int = 12000
    max_output_tokens: int = 4000
    timeout_seconds: int = 60
    # Safe routing/audit context. These identifiers never contain access
    # values and let the multi-provider router preserve stage lineage.
    stage: str = "editorial"
    job_id: str = ""
    shard_id: str = ""


class EditorialResponse(BaseModel):
    """Structured response from an editorial provider."""

    output: EditorialOutput
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
    finish_status: str = "stop"  # stop/length/refusal
    usage: dict[str, int] | None = None
    retry_count: int = 0
    fallback_used: bool = False

"""Editorial orchestrator — coordinates provider, validation, grounding, fallback.

This is the single entry point for the pipeline runner. It:
1. Builds bounded evidence set from persisted stories
2. Selects the configured provider (deterministic or AI)
3. Calls the provider
4. Validates the output schema
5. Grounds claims against evidence
6. Falls back to deterministic on failure
7. Renders the final Persian report text
8. Returns report content + metadata for persistence
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.editorial.deterministic_provider import DeterministicEditorialProvider
from newsroom.editorial.evidence_builder import build_evidence_set
from newsroom.editorial.grounding import validate_grounding
from newsroom.editorial.provider import (
    EditorialError,
    EditorialProvider,
    EditorialRequest,
    EditorialResponse,
)
from newsroom.editorial.schema import (
    EditorialErrorCategory,
    EditorialEvidenceSet,
    EditorialOutput,
    StoryEditorialResult,
)
from newsroom.editorial.validation import create_validation_error, parse_and_validate
from newsroom.logging import get_logger

logger = get_logger(__name__)


@dataclass
class EditorialAttempt:
    """Record of one editorial attempt for persistence."""

    provider: str = "deterministic"
    model: str = ""
    prompt_version: str = ""
    evidence_set_hash: str = ""
    schema_version: str = ""
    report_mode: str = "scheduled"
    started_at: str = ""
    completed_at: str = ""
    latency_ms: int = 0
    status: str = "ok"  # ok/fallback/validation_failed/grounding_failed/provider_error
    retry_count: int = 0
    fallback_used: bool = False
    validation_result: str = ""  # issues joined
    grounding_result: str = ""
    usage: dict[str, int] | None = None
    error_category: str = ""
    error_summary: str = ""
    output: EditorialOutput | None = None


@lru_cache(maxsize=1)
def _production_router() -> EditorialProvider:
    """Build one shared process-wide router from its canonical local file.

    Provider access values are deliberately absent from ``settings`` and the
    process environment. PostgreSQL contributes safe validated-route, quota,
    cooldown, and circuit state only.
    """
    from newsroom.editorial.router.factory import create_router_from_local_env
    from newsroom.editorial.router_persistence import PostgresRouterStateSink

    provider_file = os.environ.get("LLM_PROVIDER_ENV_FILE", ".env.providers.local")
    sink = PostgresRouterStateSink()
    restored = sink.load()
    router = create_router_from_local_env(
        provider_file,
        state_sink=sink,
        fallback=DeterministicEditorialProvider(),
        validated_models=restored.validated_model_ids,
        restored_snapshot=restored.snapshots,
        timeout_seconds=float(settings.editorial_timeout_seconds),
    )
    if not router.config.enabled:
        logger.warning("Editorial router disabled — using deterministic")
        return DeterministicEditorialProvider()
    if not any(provider.keys for provider in router.config.providers):
        logger.warning("Editorial router has no configured provider access — using deterministic")
        return DeterministicEditorialProvider()
    if not any(route.enabled and route.validation_status == "validated" for route in router.routes):
        logger.warning("Editorial router has no validated model route — using deterministic")
        return DeterministicEditorialProvider()
    return router


def select_provider() -> EditorialProvider:
    """Select the persistent multi-provider router or deterministic fallback."""
    if not settings.editorial_enabled:
        return DeterministicEditorialProvider()
    try:
        return _production_router()
    except Exception as exc:
        logger.warning(
            "Editorial router initialization failed (%s) — using deterministic",
            type(exc).__name__,
        )
        return DeterministicEditorialProvider()


def generate_editorial(
    db: Session,
    story_ids: list[int],
    report_mode: str = "scheduled",
    *,
    cache_check: bool = True,
    job_id: str | None = None,
) -> tuple[str, EditorialAttempt]:
    """Generate an editorial report from persisted stories.

    Returns (report_content_text, attempt_metadata).
    The caller persists the report and the attempt.
    """
    import time

    start = time.monotonic()
    attempt = EditorialAttempt()
    attempt.started_at = datetime.now(UTC).isoformat()

    # 1. Build evidence set
    evidence = build_evidence_set(db, story_ids, report_mode)
    attempt.evidence_set_hash = evidence.evidence_hash()
    attempt.prompt_version = evidence.prompt_version
    attempt.schema_version = evidence.schema_version
    attempt.report_mode = report_mode

    if not evidence.stories:
        # Empty report
        attempt.provider = "deterministic"
        attempt.model = "deterministic-v1"
        attempt.status = "ok"
        attempt.completed_at = datetime.now(UTC).isoformat()
        attempt.latency_ms = int((time.monotonic() - start) * 1000)
        empty_content = _empty_report(report_mode)
        return empty_content, attempt

    # 2. Select provider (needed for cache key identity)
    provider = select_provider()
    attempt.provider = provider.name
    attempt.model = provider.model_name

    # 3. Check cache
    if cache_check:
        cached = _check_cache(db, evidence, report_mode, provider.name, provider.model_name)
        if cached:
            attempt.provider = cached.provider or provider.name
            attempt.model = cached.model or provider.model_name
            attempt.usage = cached.usage
            attempt.output = cached.output
            attempt.status = "ok"
            attempt.fallback_used = False
            attempt.completed_at = datetime.now(UTC).isoformat()
            attempt.latency_ms = int((time.monotonic() - start) * 1000)
            content = _render_persian_report(cached.output, report_mode)
            return content, attempt

    request = EditorialRequest(
        evidence=evidence,
        model=provider.model_name,
        temperature=settings.editorial_temperature,
        max_input_tokens=settings.editorial_max_input_tokens,
        max_output_tokens=settings.editorial_max_output_tokens,
        timeout_seconds=settings.editorial_timeout_seconds,
        stage="editorial",
        job_id=job_id or "",
    )

    try:
        response = provider.generate(request)
        attempt.provider = response.provider or provider.name
        attempt.model = response.model or provider.model_name
        attempt.fallback_used = bool(
            response.fallback_used
            or (attempt.provider == "deterministic" and provider.name != "deterministic")
        )
        if attempt.fallback_used:
            attempt.status = "fallback"
    except EditorialError as e:
        attempt.error_category = e.category.value
        attempt.error_summary = e.detail
        attempt.status = "provider_error"

        if settings.editorial_fallback_enabled:
            logger.warning(
                f"Editorial provider failed ({e.category.value}) — falling back to deterministic"
            )
            det_provider = DeterministicEditorialProvider()
            response = det_provider.generate(request)
            attempt.provider = response.provider or det_provider.name
            attempt.model = response.model or det_provider.model_name
            attempt.fallback_used = True
            attempt.status = "fallback"
        else:
            attempt.completed_at = datetime.now(UTC).isoformat()
            attempt.latency_ms = int((time.monotonic() - start) * 1000)
            raise

    attempt.retry_count = response.retry_count
    attempt.usage = response.usage

    # 4. Validate output (for AI providers; deterministic is already structured)
    output = response.output
    if attempt.provider != "deterministic":
        # Re-validate the structured output
        try:
            output = _validate_output(output, evidence, settings.editorial_max_output_tokens)
        except EditorialError as e:
            attempt.error_category = e.category.value
            attempt.error_summary = e.detail
            attempt.status = "validation_failed"

            if settings.editorial_fallback_enabled:
                logger.warning("Editorial validation failed — falling back to deterministic")
                det_provider = DeterministicEditorialProvider()
                response = det_provider.generate(request)
                output = response.output
                attempt.provider = response.provider or det_provider.name
                attempt.model = response.model or det_provider.model_name
                attempt.fallback_used = True
                attempt.status = "fallback"
            else:
                attempt.completed_at = datetime.now(UTC).isoformat()
                attempt.latency_ms = int((time.monotonic() - start) * 1000)
                raise

    # 5. Grounding validation (for AI providers)
    if attempt.provider != "deterministic":
        grounded_output, grounding_result = validate_grounding(evidence, output)
        attempt.grounding_result = "; ".join(grounding_result.issues) if grounding_result.issues else "ok"

        if not grounding_result.valid and settings.editorial_fallback_enabled:
            logger.warning("Grounding validation failed — falling back to deterministic")
            det_provider = DeterministicEditorialProvider()
            response = det_provider.generate(request)
            grounded_output, grounding_result = validate_grounding(evidence, response.output)
            attempt.provider = response.provider or det_provider.name
            attempt.model = response.model or det_provider.model_name
            attempt.fallback_used = True
            attempt.status = "fallback"
            attempt.grounding_result = "; ".join(grounding_result.issues) if grounding_result.issues else "ok"
        elif not grounding_result.valid:
            attempt.status = "grounding_failed"
            attempt.completed_at = datetime.now(UTC).isoformat()
            attempt.latency_ms = int((time.monotonic() - start) * 1000)
            raise EditorialError(
                EditorialErrorCategory.UNSUPPORTED_CLAIMS,
                "grounding validation failed and fallback disabled",
                retryable=False,
            )
        output = grounded_output
    else:
        attempt.grounding_result = "ok"

    # 6. Render Persian report
    content = _render_persian_report(output, report_mode)

    attempt.output = output
    attempt.completed_at = datetime.now(UTC).isoformat()
    attempt.latency_ms = int((time.monotonic() - start) * 1000)

    if attempt.status != "fallback":
        attempt.status = "ok"

    return content, attempt


def _validate_output(
    output: EditorialOutput,
    evidence: EditorialEvidenceSet,
    max_tokens: int,
) -> EditorialOutput:
    """Re-validate a structured EditorialOutput against evidence."""

    raw = output.model_dump_json(indent=2)
    parsed, result = parse_and_validate(raw, evidence, max_tokens)
    if parsed is None or not result.valid:
        raise create_validation_error(result)
    return parsed


def _check_cache(
    db: Session,
    evidence: EditorialEvidenceSet,
    report_mode: str,
    provider: str,
    model: str,
) -> EditorialResponse | None:
    """Check for cached editorial result by cache key. Returns None if no hit."""
    from newsroom.editorial.persistence import (
        cache_route_identity,
        compute_cache_key,
        find_cached_attempt,
    )

    provider, model = cache_route_identity(provider, model)

    cache_key = compute_cache_key(
        report_mode,
        evidence.evidence_hash(),
        evidence.prompt_version,
        provider,
        model,
        temperature=settings.editorial_temperature,
        max_input_tokens=settings.editorial_max_input_tokens,
        max_output_tokens=settings.editorial_max_output_tokens,
    )
    record = find_cached_attempt(db, cache_key)
    if record and record.output_json:
        try:
            output = EditorialOutput.model_validate(record.output_json)
            return EditorialResponse(
                output=output,
                model=record.model,
                provider=record.provider,
                latency_ms=0,
                finish_status="stop",
                usage=record.usage if isinstance(record.usage, dict) else None,
                retry_count=0,
                fallback_used=False,
            )
        except Exception:
            logger.debug("cached editorial output failed to validate — skipping cache")
            return None
    return None


def _render_persian_report(output: EditorialOutput, report_mode: str) -> str:
    """Render the structured editorial output as a Persian report text."""
    now = datetime.now(UTC)
    mode_fa = {
        "scheduled": "زمان‌بندی‌شده",
        "manual": "فوری",
        "manual_new": "اخبار جدید",
        "manual_comprehensive": "جامع",
    }.get(report_mode, "")

    lines = [
        "📰 گزارش خبری هوش مصنوعی و فناوری",
        f"تاریخ: {now.strftime('%Y-%m-%d')}",
        f"نوع گزارش: {mode_fa}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    # Layer A: high priority
    high = [s for s in output.stories if s.suggested_priority == "high"]
    medium = [s for s in output.stories if s.suggested_priority == "medium"]
    low = [s for s in output.stories if s.suggested_priority == "low"]

    if high:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🔥 مهم‌ترین خبرها")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        for story in high:
            lines.append(_render_story_major(story))

    if medium:
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📋 اخبار مهم")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        for story in medium[:8]:
            lines.append(_render_story_medium(story))

    if low:
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📰 ریزخبرها")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        for story in low[:15]:
            lines.append(_render_story_brief(story))

    gen_label = "تولید شده توسط هوش مصنوعی" if output.metadata.provider != "deterministic" else "تولید شده توسط سیستم خبرخوان"
    if output.metadata.editorial_status == "fallback":
        gen_label = "تولید شده توسط سیستم خبرخوان (حالت پشتیبان)"

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 این گزارش شامل {len(output.stories)} خبر از منابع مختلف است")
    lines.append(f"🤖 {gen_label}")
    lines.append(f"⏰ {now.strftime('%H:%M UTC')}")

    return "\n\n".join(lines)


def _render_story_major(story: StoryEditorialResult) -> str:
    lines = [f"🔹 {story.headline_fa}"]
    lines.append(f"وضعیت: {story.verification_status} | اطمینان: {int(story.confidence_level * 100)}%")

    if story.summary_fa:
        lines.append(f"چه اتفاقی افتاد: {story.summary_fa}")
    if story.why_it_matters_fa:
        lines.append(f"چرا مهم است: {story.why_it_matters_fa}")
    if story.practical_impact_fa:
        lines.append(f"کاربرد عملی: {story.practical_impact_fa}")
    if story.uncertainty_notes:
        lines.append(f"⚠️ {story.uncertainty_notes}")

    for link in story.source_links[:3]:
        if link:
            lines.append(f"🔗 {link}")

    if len(story.source_links) > 3:
        lines.append(f"... و {len(story.source_links) - 3} منبع دیگر")

    return "\n".join(lines)


def _render_story_medium(story: StoryEditorialResult) -> str:
    lines = [f"▸ {story.headline_fa}"]
    lines.append(f"  وضعیت: {story.verification_status}")
    if story.source_links:
        lines.append(f"  🔗 {story.source_links[0]}")
    return "\n".join(lines)


def _render_story_brief(story: StoryEditorialResult) -> str:
    link = f" | 🔗 {story.source_links[0]}" if story.source_links else ""
    return f"• {story.headline_fa}{link}"


def _empty_report(report_mode: str) -> str:
    now = datetime.now(UTC)
    return f"""📰 گزارش خبری هوش مصنوعی و فناوری
تاریخ: {now.strftime('%Y-%m-%d')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

خبر جدیدی در این دوره یافت نشد.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

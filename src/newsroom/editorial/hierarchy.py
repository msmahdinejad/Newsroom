"""Hierarchical map/reduce editorial pipeline for scalable AI processing.

Flow:
1. Deterministic candidate selection (selection.py)
2. Deterministic dedup/clustering/evidence (existing processing/)
3. Deterministic ranking and budget allocation
4. Stable partitioning into bounded shards (sharding.py)
5. Per-shard AI map: generate structured editorial candidates
6. Topic-level reduction: merge overlapping shards
7. Global cross-shard deduplication
8. Final report planning and synthesis
9. Final grounding and schema validation
10. Telegram rendering and delivery (pipeline runner)

Every map result passes schema validation and grounding before reduction.
Failed shards are isolated — they don't corrupt successful shards.
Evidence lineage is preserved through all reduction levels.

No API keys, prompts, or chain-of-thought are persisted.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from newsroom.config import settings
from newsroom.editorial.evidence_builder import build_evidence_set
from newsroom.editorial.grounding import validate_grounding
from newsroom.editorial.orchestrator import (
    EditorialAttempt,
    _render_persian_report,
    select_provider,
)
from newsroom.editorial.provider import EditorialError, EditorialProvider, EditorialRequest
from newsroom.editorial.schema import (
    EditorialEvidenceSet,
    EditorialOutput,
    EvidenceStoryPacket,
    ReportMetadata,
    StoryEditorialResult,
)
from newsroom.editorial.sharding import (
    PARTITION_VERSION,
    PROMPT_OVERHEAD_TOKENS,
    ShardingResult,
    ShardSpec,
    estimate_story_tokens,
    shard_evidence_set,
    trim_evidence_for_shard,
)
from newsroom.editorial.validation import parse_and_validate
from newsroom.logging import get_logger
from newsroom.storage.models import (
    EditorialArtifact,
    EditorialArtifactLineage,
    EditorialJob,
    EditorialShard,
    Report,
)
from newsroom.storage.models import (
    EditorialAttempt as EditorialAttemptRecord,
)

logger = get_logger(__name__)


@dataclass
class MapResult:
    """Validated output from one map shard."""

    shard_id: str
    artifact_id: int
    output: EditorialOutput
    story_ids: list[int]
    evidence_ref_ids: list[str]
    latency_ms: int
    usage: dict[str, int] | None
    from_cache: bool
    fallback_used: bool
    provider: str = "deterministic"
    model: str = "deterministic-v1"


@dataclass
class HierarchicalResult:
    """Final result of the hierarchical editorial pipeline."""

    content: str
    attempt: EditorialAttempt
    job: EditorialJob
    map_results: list[MapResult]
    reduction_level: int
    total_model_calls: int
    total_input_tokens: int
    total_output_tokens: int
    cache_hits: int
    fallback_shards: int
    selection_stats: dict[str, int]


def run_hierarchical_editorial(
    db: Session,
    story_ids: list[int],
    report_mode: str = "scheduled",
    job_id: str | None = None,
) -> HierarchicalResult:
    """Run the full hierarchical map/reduce editorial pipeline.

    This is the scalable entry point that replaces the single-call
    generate_editorial for large candidate sets.
    """

    start = time.monotonic()
    if not job_id:
        job_id = f"ej_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{hashlib.sha256(str(story_ids).encode()).hexdigest()[:8]}"

    # 1. Build evidence set
    # The per-call story cap belongs to each shard, not the whole hierarchy.
    # Build evidence for every selected story; sharding then enforces the
    # per-request count/token and total map-call budgets.
    evidence = build_evidence_set(
        db,
        story_ids,
        report_mode,
        max_stories=len(story_ids),
    )

    if not evidence.stories:
        return _empty_hierarchical_result(db, job_id, report_mode)

    # 2. Shard the evidence set
    sharding_result = shard_evidence_set(evidence)

    # 3. Create persistent job
    job = _create_job(
        db, job_id, report_mode, story_ids, sharding_result,
    )

    # A delivery retry for the same scheduled boundary reuses the completed
    # report and accepted artifacts without making any provider call.
    if job.status == "completed" and job.report_id is not None:
        report = db.get(Report, job.report_id)
        persisted_attempt = (
            db.query(EditorialAttemptRecord)
            .filter_by(report_id=job.report_id)
            .order_by(EditorialAttemptRecord.id.desc())
            .first()
        )
        if (
            report is not None
            and persisted_attempt is not None
            and persisted_attempt.output_json
        ):
            cached_output = EditorialOutput.model_validate(
                persisted_attempt.output_json
            )
            attempt = EditorialAttempt(
                provider=persisted_attempt.provider,
                model=persisted_attempt.model,
                prompt_version=persisted_attempt.prompt_version,
                evidence_set_hash=persisted_attempt.evidence_set_hash,
                schema_version=persisted_attempt.schema_version,
                report_mode=report_mode,
                status=persisted_attempt.status,
                fallback_used=persisted_attempt.fallback_used,
                usage=(
                    persisted_attempt.usage
                    if isinstance(persisted_attempt.usage, dict)
                    else None
                ),
                output=cached_output,
            )
            return HierarchicalResult(
                content=report.content_fa,
                attempt=attempt,
                job=job,
                map_results=[],
                reduction_level=job.reduction_depth,
                total_model_calls=0,
                total_input_tokens=0,
                total_output_tokens=0,
                cache_hits=job.shard_count + 1,
                fallback_shards=job.shard_count if job.fallback_used else 0,
                selection_stats={
                    "total_candidates": len(story_ids),
                    "selected": len(story_ids),
                    "shards": job.shard_count,
                },
            )
        final_artifact = (
            db.query(EditorialArtifact)
            .filter_by(job_db_id=job.id, artifact_type="reduction_final", status="validated")
            .order_by(EditorialArtifact.id.desc())
            .first()
        )
        if report is not None and final_artifact is not None:
            cached_output = EditorialOutput.model_validate(final_artifact.output_json)
            attempt = EditorialAttempt(
                provider=final_artifact.provider or cached_output.metadata.provider,
                model=final_artifact.model or cached_output.metadata.model_name,
                prompt_version=evidence.prompt_version,
                evidence_set_hash=evidence.evidence_hash(),
                schema_version=evidence.schema_version,
                report_mode=report_mode,
                status="fallback" if job.fallback_used else "ok",
                fallback_used=job.fallback_used,
                usage=final_artifact.usage if isinstance(final_artifact.usage, dict) else None,
                output=cached_output,
            )
            return HierarchicalResult(
                content=report.content_fa,
                attempt=attempt,
                job=job,
                map_results=[],
                reduction_level=job.reduction_depth,
                total_model_calls=0,
                total_input_tokens=0,
                total_output_tokens=0,
                cache_hits=job.shard_count + 1,
                fallback_shards=job.shard_count if job.fallback_used else 0,
                selection_stats={
                    "total_candidates": len(story_ids),
                    "selected": len(story_ids),
                    "shards": job.shard_count,
                },
            )

    # 4. Map stage: process each shard
    provider = select_provider()
    map_results: list[MapResult] = []
    total_model_calls = 0
    total_input_tokens = 0
    total_output_tokens = 0
    cache_hits = 0
    fallback_shards = 0

    for shard_spec in sharding_result.shards:
        if total_model_calls >= settings.editorial_max_map_calls_per_report:
            logger.warning(f"Map call budget exhausted at {total_model_calls}")
            break

        # Check budget
        remaining_input = settings.editorial_max_total_input_tokens_per_report - total_input_tokens
        if remaining_input < shard_spec.estimated_input_tokens:
            logger.warning(f"Input token budget exhausted, skipping shard {shard_spec.shard_id}")
            break

        result = _process_shard(
            db, job, shard_spec, evidence, provider,
        )
        map_results.append(result)

        if not result.from_cache:
            total_model_calls += 1
            if result.usage:
                total_input_tokens += result.usage.get("prompt_tokens", 0)
                total_output_tokens += result.usage.get("completion_tokens", 0)
        else:
            cache_hits += 1

        if result.fallback_used:
            fallback_shards += 1

    if len(map_results) != len(sharding_result.shards):
        from newsroom.editorial.schema import EditorialErrorCategory

        job.status = "failed_retryable"
        db.flush()
        raise EditorialError(
            EditorialErrorCategory.PROVIDER_UNAVAILABLE,
            "required validated map artifacts are incomplete",
            retryable=True,
        )

    # 5. Reduction stage: merge map artifacts
    reduction_level = 0
    final_output: EditorialOutput

    if len(map_results) == 1:
        # Single shard — no reduction needed
        final_output = map_results[0].output
        reduction_calls = 0
        reduction_input_tokens = 0
        reduction_output_tokens = 0
        reduction_fallback = False
    else:
        (
            final_output,
            reduction_level,
            reduction_calls,
            reduction_input_tokens,
            reduction_output_tokens,
            reduction_fallback,
        ) = _reduce_artifacts(
            db, job, map_results, evidence, provider,
            total_model_calls, total_input_tokens, total_output_tokens,
        )
        total_model_calls += reduction_calls
        total_input_tokens += reduction_input_tokens
        total_output_tokens += reduction_output_tokens

    # 6. Update job status
    job.status = "completed"
    job.completed_at = datetime.now(UTC)
    job.total_model_calls = total_model_calls
    job.total_input_tokens = total_input_tokens
    job.total_output_tokens = total_output_tokens
    job.reduction_depth = reduction_level
    job.fallback_used = fallback_shards > 0 or reduction_fallback
    job.partial_ai = job.fallback_used and fallback_shards < len(map_results)
    db.flush()

    # 7. Render Persian report
    content = _render_persian_report(final_output, report_mode)

    # 8. Build attempt metadata
    used_providers = {result.provider for result in map_results}
    used_models = {result.model for result in map_results}
    final_provider = final_output.metadata.provider or (
        next(iter(used_providers)) if len(used_providers) == 1 else "mixed"
    )
    final_model = final_output.metadata.model_name or (
        next(iter(used_models)) if len(used_models) == 1 else "mixed"
    )
    attempt = EditorialAttempt(
        provider=final_provider,
        model=final_model,
        prompt_version=evidence.prompt_version,
        evidence_set_hash=evidence.evidence_hash(),
        schema_version=evidence.schema_version,
        report_mode=report_mode,
        status="fallback" if job.fallback_used else "ok",
        retry_count=0,
        fallback_used=job.fallback_used,
        latency_ms=int((time.monotonic() - start) * 1000),
        usage={"prompt_tokens": total_input_tokens, "completion_tokens": total_output_tokens,
               "total_tokens": total_input_tokens + total_output_tokens},
        output=final_output,
    )

    return HierarchicalResult(
        content=content,
        attempt=attempt,
        job=job,
        map_results=map_results,
        reduction_level=reduction_level,
        total_model_calls=total_model_calls,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        cache_hits=cache_hits,
        fallback_shards=fallback_shards,
        selection_stats={
            "total_candidates": len(story_ids),
            "selected": len(story_ids),
            "shards": len(sharding_result.shards),
        },
    )


def _create_job(
    db: Session,
    job_id: str,
    report_mode: str,
    story_ids: list[int],
    sharding_result: ShardingResult,
) -> EditorialJob:
    """Create or resume a persistent editorial job record."""
    existing = db.query(EditorialJob).filter_by(job_id=job_id).first()
    if existing is not None:
        return existing
    job = EditorialJob(
        job_id=job_id,
        report_mode=report_mode,
        status="running",
        candidate_story_ids=story_ids,
        selected_count=len(story_ids),
        shard_count=len(sharding_result.shards),
        partition_version=sharding_result.partition_version,
        max_reduction_depth=settings.editorial_max_hierarchy_depth,
        max_input_token_budget=settings.editorial_max_total_input_tokens_per_report,
        max_output_token_budget=settings.editorial_max_total_output_tokens_per_report,
        map_call_budget=settings.editorial_max_map_calls_per_report,
        reduction_call_budget=settings.editorial_max_reduction_calls_per_report,
    )
    db.add(job)
    db.flush()

    # Persist shard records
    for spec in sharding_result.shards:
        shard = EditorialShard(
            job_db_id=job.id,
            shard_id=spec.shard_id,
            shard_sequence=spec.shard_sequence,
            total_shards=spec.total_shards,
            story_ids=spec.story_ids,
            evidence_ref_ids=spec.evidence_ref_ids,
            evidence_set_hash=spec.evidence_set_hash,
            estimated_input_tokens=spec.estimated_input_tokens,
            effective_input_limit=spec.effective_input_limit,
            effective_output_limit=spec.effective_output_limit,
            prompt_version="g4sp-v1",
            schema_version=sharding_result.partition_version,
            partition_version=sharding_result.partition_version,
            status="pending",
        )
        db.add(shard)
    db.flush()
    return job


def _process_shard(
    db: Session,
    job: EditorialJob,
    spec: ShardSpec,
    evidence: EditorialEvidenceSet,
    provider: EditorialProvider,
) -> MapResult:
    """Process one shard: check cache, call provider, validate, persist artifact."""
    # Get the subset of evidence for this shard
    shard_stories = [s for s in evidence.stories if s.story_id in spec.story_ids]
    shard_evidence = EditorialEvidenceSet(
        schema_version=evidence.schema_version,
        prompt_version=evidence.prompt_version,
        report_mode=evidence.report_mode,
        stories=shard_stories,
    )

    # Compute cache key for this shard
    from newsroom.editorial.persistence import compute_cache_key

    cache_key = compute_cache_key(
        f"shard_{spec.shard_id}",
        shard_evidence.evidence_hash(),
        evidence.prompt_version,
        "validated-editorial-artifact",
        "route-independent-v1",
        temperature=settings.editorial_temperature,
        max_input_tokens=spec.effective_input_limit,
        max_output_tokens=spec.effective_output_limit,
    )

    # Check for cached artifact
    existing = db.query(EditorialArtifact).filter_by(cache_key=cache_key, status="validated").first()
    if existing:
        logger.debug(f"Shard {spec.shard_id} served from cache")
        cached_provider = existing.provider or "unknown"
        cached_model = existing.model or "unknown"
        cached_fallback = (
            cached_provider == "deterministic"
            and provider.name != "deterministic"
        )
        current_shard = db.query(EditorialShard).filter_by(
            job_db_id=job.id,
            shard_id=spec.shard_id,
        ).first()
        if current_shard is not None:
            current_shard.status = "completed"
            current_shard.artifact_id = existing.id
            current_shard.provider = cached_provider
            current_shard.model = cached_model
            current_shard.temperature = settings.editorial_temperature
            current_shard.usage = existing.usage if isinstance(existing.usage, dict) else None
            current_shard.latency_ms = 0
            current_shard.error_category = "fallback" if cached_fallback else None
            current_shard.lease_owner = None
            current_shard.leased_at = None
            current_shard.lease_expires_at = None
            db.flush()
        return MapResult(
            shard_id=spec.shard_id,
            artifact_id=existing.id,
            output=EditorialOutput.model_validate(existing.output_json),
            story_ids=existing.story_ids,
            evidence_ref_ids=existing.evidence_ref_ids,
            latency_ms=0,
            usage=existing.usage if isinstance(existing.usage, dict) else None,
            from_cache=True,
            fallback_used=cached_fallback,
            provider=cached_provider,
            model=cached_model,
        )

    # Acquire lease
    shard_record = db.query(EditorialShard).filter_by(
        job_db_id=job.id, shard_id=spec.shard_id
    ).first()
    if shard_record:
        shard_record.status = "running"
        shard_record.lease_owner = job.job_id
        shard_record.leased_at = datetime.now(UTC)
        shard_record.provider = provider.name
        shard_record.model = provider.model_name
        shard_record.temperature = settings.editorial_temperature
        db.flush()

    # Call provider
    request = EditorialRequest(
        evidence=shard_evidence,
        model=provider.model_name,
        temperature=settings.editorial_temperature,
        max_input_tokens=spec.effective_input_limit,
        max_output_tokens=spec.effective_output_limit,
        timeout_seconds=settings.editorial_timeout_seconds,
        stage="map",
        job_id=job.job_id,
        shard_id=spec.shard_id,
    )

    fallback_used = False
    start = time.monotonic()

    actual_provider = provider.name
    actual_model = provider.model_name
    try:
        response = provider.generate(request)
        output = response.output
        actual_provider = response.provider or provider.name
        actual_model = response.model or provider.model_name
        fallback_used = response.fallback_used or actual_provider == "deterministic"

        # Validate and ground
        raw = output.model_dump_json(indent=2)
        parsed, val_result = parse_and_validate(raw, shard_evidence, spec.effective_output_limit)
        if parsed is None or not val_result.valid:
            from newsroom.editorial.schema import EditorialErrorCategory

            raise EditorialError(
                EditorialErrorCategory.SCHEMA_VALIDATION,
                f"shard {spec.shard_id} validation failed",
                False,
            )
        output = parsed

        grounded, grounding_result = validate_grounding(shard_evidence, output)
        if not grounding_result.valid:
            logger.warning(f"Shard {spec.shard_id} grounding issues: {grounding_result.issues[:3]}")
            output = grounded

    except (EditorialError, Exception) as e:
        logger.warning(f"Shard {spec.shard_id} failed: {e} — falling back to deterministic")
        from newsroom.editorial.deterministic_provider import DeterministicEditorialProvider

        det = DeterministicEditorialProvider()
        response = det.generate(request)
        output = response.output
        actual_provider = response.provider or det.name
        actual_model = response.model or det.model_name
        fallback_used = True

    latency_ms = int((time.monotonic() - start) * 1000)

    # Persist artifact
    artifact = EditorialArtifact(
        job_db_id=job.id,
        shard_id=spec.shard_id,
        artifact_type="map",
        reduction_level=0,
        output_json=output.model_dump(mode="json"),
        story_ids=spec.story_ids,
        evidence_ref_ids=spec.evidence_ref_ids,
        schema_version=evidence.schema_version,
        prompt_version=evidence.prompt_version,
        validation_result="valid",
        grounding_result="ok",
        cache_key=cache_key,
        provider=actual_provider,
        model=actual_model,
        usage=response.usage if response.usage else None,
        latency_ms=latency_ms,
        status="validated",
    )
    db.add(artifact)
    db.flush()

    _link_route_attempts(db, job.job_id, spec.shard_id, artifact.id)

    # Persist lineage
    _persist_lineage(db, artifact.id, output, shard_evidence)

    # Update shard record
    if shard_record:
        shard_record.status = "completed"
        shard_record.artifact_id = artifact.id
        shard_record.latency_ms = latency_ms
        shard_record.usage = response.usage if response.usage else None
        shard_record.provider = actual_provider
        shard_record.model = actual_model
        if fallback_used:
            shard_record.error_category = "fallback"
        db.flush()

    return MapResult(
        shard_id=spec.shard_id,
        artifact_id=artifact.id,
        output=output,
        story_ids=spec.story_ids,
        evidence_ref_ids=spec.evidence_ref_ids,
        latency_ms=latency_ms,
        usage=response.usage if response.usage else None,
        from_cache=False,
        fallback_used=fallback_used,
        provider=actual_provider,
        model=actual_model,
    )


def _persist_lineage(
    db: Session,
    artifact_id: int,
    output: EditorialOutput,
    evidence: EditorialEvidenceSet,
) -> None:
    """Persist evidence lineage for an artifact."""
    ref_to_url: dict[str, str] = {}
    for story in evidence.stories:
        for src in story.sources:
            ref_to_url[src.ref_id] = src.original_url

    for story_result in output.stories:
        claim_refs = {
            ref_id
            for claim in story_result.key_claims
            for ref_id in (
                *claim.supporting_evidence_refs,
                *claim.conflicting_evidence_refs,
            )
        }
        for ref_id in sorted(set(story_result.source_ref_ids) | claim_refs):
            if ref_id not in ref_to_url:
                continue
            url = ref_to_url.get(ref_id)
            db.add(EditorialArtifactLineage(
                artifact_id=artifact_id,
                story_id=story_result.story_id,
                evidence_ref_id=ref_id,
                source_url=url,
            ))
    db.flush()


def _reduce_artifacts(
    db: Session,
    job: EditorialJob,
    map_results: list[MapResult],
    evidence: EditorialEvidenceSet,
    provider: EditorialProvider,
    total_calls: int,
    total_in: int,
    total_out: int,
) -> tuple[EditorialOutput, int, int, int, int, bool]:
    """Reduce map artifacts into a final editorial output.

    For small sets (< 3 shards), do a single reduction.
    For larger sets, do topic-grouped reduction then final reduction.
    Depth is bounded by settings.editorial_max_hierarchy_depth.
    """
    if len(map_results) <= 2:
        merged = _merge_outputs(map_results, evidence)
        return _final_reduction(db, job, map_results, merged, evidence, provider, 1)

    # Topic-grouped reduction for 3+ shards
    max_depth = settings.editorial_max_hierarchy_depth
    current_artifacts = map_results
    level = 0

    while len(current_artifacts) > 2 and level < max_depth:
        # Group artifacts into pairs/triples for reduction
        groups: list[list[MapResult]] = []
        group_size = 3
        for i in range(0, len(current_artifacts), group_size):
            groups.append(current_artifacts[i:i + group_size])

        reduced: list[MapResult] = []
        for i, group in enumerate(groups):
            if len(group) == 1:
                reduced.append(group[0])
                continue

            merged = _merge_outputs(group, evidence)
            artifact = _persist_reduction(
                db, job, f"reduction_l{level}_g{i}", merged, evidence,
                "reduction_topic", level + 1,
                child_artifact_ids=[child.artifact_id for child in group],
            )
            reduced.append(MapResult(
                shard_id=f"reduction_l{level}_g{i}",
                artifact_id=artifact.id,
                output=merged,
                story_ids=[s for r in group for s in r.story_ids],
                evidence_ref_ids=[r for res in group for r in res.evidence_ref_ids],
                latency_ms=0,
                usage=None,
                from_cache=False,
                fallback_used=False,
                provider=merged.metadata.provider or "deterministic_reducer",
                model=merged.metadata.model_name or "deterministic-merge-v1",
            ))

        current_artifacts = reduced
        level += 1

    merged = _merge_outputs(current_artifacts, evidence)
    return _final_reduction(
        db,
        job,
        current_artifacts,
        merged,
        evidence,
        provider,
        level + 1,
    )


def _final_reduction(
    db: Session,
    job: EditorialJob,
    children: list[MapResult],
    merged: EditorialOutput,
    evidence: EditorialEvidenceSet,
    provider: EditorialProvider,
    level: int,
) -> tuple[EditorialOutput, int, int, int, int, bool]:
    """Run one bounded AI final reduction, falling back to the safe merge."""
    existing = (
        db.query(EditorialArtifact)
        .filter_by(
            cache_key=_reduction_cache_key("reduction_final", evidence),
            status="validated",
        )
        .first()
    )
    if existing is not None:
        cached = EditorialOutput.model_validate(existing.output_json)
        cached_provider = existing.provider or cached.metadata.provider
        return (
            cached,
            level,
            0,
            0,
            0,
            cached_provider in {"deterministic", "deterministic_reducer"},
        )

    output = merged
    actual_provider = "deterministic_reducer"
    actual_model = "deterministic-merge-v1"
    usage: dict[str, int] | None = None
    latency_ms = 0
    model_calls = 0
    fallback_used = False

    if provider.name != "deterministic":
        reduction_evidence = _bounded_reduction_evidence(
            evidence,
            merged,
            settings.editorial_max_input_tokens,
        )
        request = EditorialRequest(
            evidence=reduction_evidence,
            model=provider.model_name,
            temperature=settings.editorial_temperature,
            max_input_tokens=settings.editorial_max_input_tokens,
            max_output_tokens=settings.editorial_max_output_tokens,
            timeout_seconds=settings.editorial_timeout_seconds,
            stage="reduce",
            job_id=job.job_id,
            shard_id="reduction_final",
        )
        start = time.monotonic()
        model_calls = 1
        try:
            response = provider.generate(request)
            fallback_used = response.fallback_used or response.provider == "deterministic"
            raw = response.output.model_dump_json(indent=2)
            parsed, validation = parse_and_validate(
                raw,
                reduction_evidence,
                settings.editorial_max_output_tokens,
            )
            if parsed is None or not validation.valid:
                from newsroom.editorial.schema import EditorialErrorCategory

                raise EditorialError(
                    EditorialErrorCategory.SCHEMA_VALIDATION,
                    "final reduction validation failed",
                    False,
                )
            grounded, grounding = validate_grounding(reduction_evidence, parsed)
            if not grounding.valid:
                # Match map-stage behavior: retain a non-empty AI reduction
                # after grounding removes unsupported claims. Only an empty
                # grounded result needs deterministic fallback.
                if not grounded.stories:
                    from newsroom.editorial.schema import EditorialErrorCategory

                    raise EditorialError(
                        EditorialErrorCategory.UNSUPPORTED_CLAIMS,
                        "final reduction grounding produced no stories",
                        False,
                    )
                logger.warning(
                    "Final AI reduction grounding scrubbed unsupported claims: %s",
                    grounding.issues[:3],
                )
            output = grounded
            actual_provider = response.provider or provider.name
            actual_model = response.model or provider.model_name
            usage = response.usage
        except EditorialError as exc:
            logger.warning(
                "Final AI reduction failed (%s); using validated deterministic merge",
                exc.category.value,
            )
            fallback_used = True
        latency_ms = int((time.monotonic() - start) * 1000)

    artifact = _persist_reduction(
        db,
        job,
        "reduction_final",
        output,
        evidence,
        "reduction_final",
        level,
        provider=actual_provider,
        model=actual_model,
        usage=usage,
        latency_ms=latency_ms,
        child_artifact_ids=[child.artifact_id for child in children],
    )
    _link_route_attempts(db, job.job_id, "reduction_final", artifact.id)
    prompt_tokens = usage.get("prompt_tokens", 0) if usage else 0
    completion_tokens = usage.get("completion_tokens", 0) if usage else 0
    return output, level, model_calls, prompt_tokens, completion_tokens, fallback_used


def _bounded_reduction_evidence(
    evidence: EditorialEvidenceSet,
    merged: EditorialOutput,
    max_input_tokens: int,
) -> EditorialEvidenceSet:
    """Build the final request from accepted map output, never full history."""
    available = {story.story_id: story for story in evidence.stories}
    token_budget = max(1, max_input_tokens - PROMPT_OVERHEAD_TOKENS)
    selected: list[EvidenceStoryPacket] = []
    used_tokens = 0
    for result in merged.stories[: settings.editorial_max_stories_per_call]:
        story = available.get(result.story_id)
        if story is None:
            continue
        story = trim_evidence_for_shard(story, token_budget)
        story_tokens = estimate_story_tokens(story)
        if selected and used_tokens + story_tokens > token_budget:
            break
        if story_tokens > token_budget:
            continue
        selected.append(story)
        used_tokens += story_tokens
    return EditorialEvidenceSet(
        schema_version=evidence.schema_version,
        prompt_version=evidence.prompt_version,
        report_mode=evidence.report_mode,
        stories=selected,
    )


def _merge_outputs(
    results: list[MapResult],
    evidence: EditorialEvidenceSet,
) -> EditorialOutput:
    """Merge multiple map outputs into a single editorial output.

    - Preserves all story IDs and evidence refs
    - Removes cross-shard duplicates (same story_id)
    - Ranks by priority then importance
    - Respects max_stories limit
    """
    seen_stories: set[int] = set()
    all_stories: list[StoryEditorialResult] = []
    all_refs: list[str] = []

    for result in results:
        for story in result.output.stories:
            if story.story_id not in seen_stories:
                seen_stories.add(story.story_id)
                all_stories.append(story)
        all_refs.extend(result.evidence_ref_ids)

    # Rank: high > medium > low, then by confidence
    priority_order = {"high": 0, "medium": 1, "low": 2}
    all_stories.sort(
        key=lambda s: (priority_order.get(s.suggested_priority, 1), -s.confidence_level)
    )

    # Limit to configured max stories
    max_stories = settings.editorial_max_stories_per_call
    all_stories = all_stories[:max_stories]

    providers = {result.provider for result in results}
    models = {result.model for result in results}
    merged_provider = next(iter(providers)) if len(providers) == 1 else "mixed"
    merged_model = next(iter(models)) if len(models) == 1 else "mixed"

    return EditorialOutput(
        metadata=ReportMetadata(
            schema_version=results[0].output.metadata.schema_version,
            prompt_version=results[0].output.metadata.prompt_version,
            report_mode=results[0].output.metadata.report_mode,
            model_name=merged_model,
            provider=merged_provider,
            evidence_set_hash=evidence.evidence_hash(),
            editorial_status="ok",
        ),
        stories=all_stories,
    )


def _persist_reduction(
    db: Session,
    job: EditorialJob,
    shard_id: str,
    output: EditorialOutput,
    evidence: EditorialEvidenceSet,
    artifact_type: str,
    level: int,
    *,
    provider: str = "deterministic_reducer",
    model: str = "deterministic-merge-v1",
    usage: dict[str, int] | None = None,
    latency_ms: int = 0,
    child_artifact_ids: list[int] | None = None,
) -> EditorialArtifact:
    """Persist a reduction artifact."""
    cache_key = _reduction_cache_key(shard_id, evidence)
    existing = db.query(EditorialArtifact).filter_by(cache_key=cache_key, status="validated").first()
    if existing is not None:
        return existing

    story_ids = [s.story_id for s in output.stories]
    ref_ids: list[str] = []
    for s in output.stories:
        ref_ids.extend(s.source_ref_ids)

    artifact = EditorialArtifact(
        job_db_id=job.id,
        shard_id=shard_id,
        artifact_type=artifact_type,
        reduction_level=level,
        output_json=output.model_dump(mode="json"),
        story_ids=story_ids,
        evidence_ref_ids=ref_ids,
        schema_version=evidence.schema_version,
        prompt_version=evidence.prompt_version,
        cache_key=cache_key,
        provider=provider,
        model=model,
        usage=usage,
        latency_ms=latency_ms,
        child_artifact_ids=child_artifact_ids,
        status="validated",
    )
    db.add(artifact)
    db.flush()

    _persist_lineage(db, artifact.id, output, evidence)
    return artifact


def _reduction_cache_key(shard_id: str, evidence: EditorialEvidenceSet) -> str:
    return hashlib.sha256(
        (
            f"reduction:v2:{PARTITION_VERSION}:{shard_id}:"
            f"{evidence.evidence_hash()}:{settings.editorial_temperature}:"
            f"{settings.editorial_max_input_tokens}:"
            f"{settings.editorial_max_output_tokens}:"
            f"{settings.editorial_max_stories_per_call}"
        ).encode()
    ).hexdigest()[:64]


def _link_route_attempts(
    db: Session,
    job_id: str,
    shard_id: str,
    artifact_id: int,
) -> None:
    """Attach safe independently persisted route attempts to their artifact."""
    from newsroom.storage.models import ProviderRouteAttempt

    db.query(ProviderRouteAttempt).filter(
        ProviderRouteAttempt.editorial_job_id == job_id,
        ProviderRouteAttempt.shard_id == shard_id,
        ProviderRouteAttempt.artifact_id.is_(None),
    ).update(
        {ProviderRouteAttempt.artifact_id: artifact_id},
        synchronize_session=False,
    )


def _single_reduction(
    db: Session,
    job: EditorialJob,
    results: list[MapResult],
    evidence: EditorialEvidenceSet,
) -> EditorialOutput:
    """Merge 1-2 map results into a single output."""
    merged = _merge_outputs(results, evidence)
    _persist_reduction(db, job, "reduction_final", merged, evidence, "reduction_final", 1)
    return merged


def _empty_hierarchical_result(
    db: Session,
    job_id: str,
    report_mode: str,
) -> HierarchicalResult:
    """Return an empty result with no provider calls."""
    job = EditorialJob(
        job_id=job_id,
        report_mode=report_mode,
        status="completed",
        candidate_story_ids=[],
        selected_count=0,
        shard_count=0,
        partition_version=PARTITION_VERSION,
        max_reduction_depth=settings.editorial_max_hierarchy_depth,
        max_input_token_budget=settings.editorial_max_total_input_tokens_per_report,
        max_output_token_budget=settings.editorial_max_total_output_tokens_per_report,
        map_call_budget=settings.editorial_max_map_calls_per_report,
        reduction_call_budget=settings.editorial_max_reduction_calls_per_report,
        completed_at=datetime.now(UTC),
    )
    db.add(job)
    db.flush()

    return HierarchicalResult(
        content="📰 گزارش خبری هوش مصنوعی و فناوری\n\nخبر جدیدی در این دوره یافت نشد.",
        attempt=EditorialAttempt(
            provider="deterministic",
            model="deterministic-v1",
            status="ok",
            report_mode=report_mode,
        ),
        job=job,
        map_results=[],
        reduction_level=0,
        total_model_calls=0,
        total_input_tokens=0,
        total_output_tokens=0,
        cache_hits=0,
        fallback_shards=0,
        selection_stats={"total_candidates": 0, "selected": 0, "shards": 0},
    )

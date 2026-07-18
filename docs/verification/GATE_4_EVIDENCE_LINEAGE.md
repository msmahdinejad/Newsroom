# Gate 4 Evidence Lineage

## Status: VERIFIED

**Date:** 2026-07-18

## Lineage chain

Every final report story and factual claim traces through:

```
final claim
→ final reduction artifact (EditorialArtifact, type=reduction_final)
→ topic reduction artifact (EditorialArtifact, type=reduction_topic)
→ map shard artifact (EditorialArtifact, type=map)
→ story ID (Story.id)
→ evidence-reference IDs (EvidenceSourceItem.ref_id)
→ persisted source items (NormalizedItem.id)
→ source URL (NormalizedItem.source_url)
```

## Persistence

`EditorialArtifactLineage` table:
- `artifact_id` → FK to `editorial_artifacts.id`
- `story_id` → int, indexed
- `evidence_ref_id` → string like `ev-<story>-<seq>`
- `source_url` → original source URL

Lineage is persisted by `_persist_lineage()` in `hierarchy.py` after each map
or reduction artifact is validated. It maps `story_result.source_ref_ids` to
the original `source_url` from the evidence set.

## Requirements met

- ✅ No evidence ID is lost during reduction — all source_ref_ids preserved
- ✅ Reducers may remove unsupported claims but may not create unsupported claims
- ✅ Links originate from persisted source records (`NormalizedItem.source_url`)
- ✅ Unknown child artifact IDs would fail validation (Pydantic schema)
- ✅ Cross-story references require explicit story_id in StoryEditorialResult
- ✅ Evidence lineage remains queryable after restart (PostgreSQL-backed)
- ✅ No hidden chain-of-thought stored — only structured EditorialOutput

## Verification

Tests in `tests/integration/test_gate4_scalable.py` verify:
- Artifact persistence
- Shard-to-artifact relationships
- Job-to-shard relationships
- Lineage table population (verified by `_persist_lineage` calls)

The live multi-shard verification delivered a report with 15 stories across
5 shards and 1 reduction level, with all evidence refs preserved through
the reduction stages.

# ADR-010: Prompt and Schema Versioning

## Status
Accepted

## Context
The editorial layer has several moving parts that can change independently:
the system prompt text, the evidence packet schema, the output schema, the
terminology policy, the grounding validator's logic, and the provider
interface. Without explicit versions, a cached report from an old prompt
cannot be distinguished from a fresh one, and a schema change silently breaks
older persisted outputs.

## Decision
Maintain one version constant per movable part in
`src/newsroom/editorial/schema.py` and stamp every output with the versions
that produced it.

- `SYSTEM_PROMPT_VERSION = "g4sp-v1"` — the system prompt text in
  `src/newsroom/editorial/prompt.py`.
- `EVIDENCE_SCHEMA_VERSION = "g4ev-v1"` — the `EditorialEvidenceSet` /
  `EvidenceStoryPacket` / `EvidenceSourceItem` shape built by
  `src/newsroom/editorial/evidence_builder.py`.
- `OUTPUT_SCHEMA_VERSION = "g4out-v1"` — the `EditorialOutput` /
  `StoryEditorialResult` / `KeyClaim` shape returned by providers.
- `TERMINOLOGY_POLICY_VERSION = "g4tp-v1"` — the `terminology_policy()` dict
  (keep-English set, Persian term map, rules) in `prompt.py`.
- `GROUNDING_VALIDATOR_VERSION = "g4gv-v1"` — the `validate_grounding()` logic
  in `src/newsroom/editorial/grounding.py`, recorded on every `GroundingResult`.
- `EDITORIAL_PROVIDER_VERSION = "g4pv-v1"` — the `EditorialProvider` ABC
  contract in `src/newsroom/editorial/provider.py`.

Stamping:
- `EditorialEvidenceSet` carries `schema_version` and `prompt_version`.
- `SYSTEM_PROMPT` embeds all four in-band version strings so the model sees
  them and the adapter can echo them.
- `ReportMetadata` records `schema_version` and `prompt_version` on every
  `EditorialOutput`. The deterministic provider and the OpenAI adapter both
  populate these; the adapter overwrites `provider` and `model_name` from its
  own identity and takes `evidence_set_hash` from the request.
- `GroundingResult.version` is set on every grounding pass.

## Rationale
- One constant per part, not one global version, because the prompt text and
  the schema change on different cadences.
- Bumping a version is the signal to invalidate caches and reprocess; a stale
  `prompt_version` on a persisted report means it was made with the old
  instructions and should not be served as current.
- Embedding versions in `SYSTEM_PROMPT` lets the model echo them back, which
  the adapter uses to populate metadata when the model omits it.
- Keeping the constants in `schema.py` (not `prompt.py`) means the schema is the
  single source of truth for what "current" means across the layer.

## Consequences
- Any change to the prompt text, evidence shape, output shape, terminology
  policy, grounding logic, or provider contract must bump its constant. Forgetting
  to bump means stale outputs are served as current.
- The cache key in the orchestrator includes `evidence_set_hash`, which is
  derived from the evidence content (including `schema_version` and
  `prompt_version`), so a version bump invalidates the cache automatically.
- Version strings are short (`g4sp-v1`) so they fit in metadata and logs
  without noise.
- A future incompatible schema change is `g4out-v2`, not a silent edit; old
  persisted outputs remain readable because their `metadata.schema_version`
  identifies them.

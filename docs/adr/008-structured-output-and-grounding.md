# ADR-008: Structured Output and Grounding

## Status
Accepted

## Context
The AI provider returns free-form text. Without a strict schema and a
grounding check, the model can invent facts, numbers, dates, links, and
evidence references that never existed in the source material. A
confidence score is not proof.

## Decision
Force a versioned output schema and validate every claim against the evidence
set.

- `EditorialOutput` in `src/newsroom/editorial/schema.py` is the canonical
  response shape, versioned via `OUTPUT_SCHEMA_VERSION = "g4out-v1"`. It carries
  `ReportMetadata` and a list of `StoryEditorialResult`. Each story has
  `KeyClaim` entries with `supporting_evidence_refs`, `conflicting_evidence_refs`,
  `support_status` (a `ClaimStatus` enum), and a clamped `confidence` in
  `[0.0, 1.0]`.
- `OpenAICompatibleEditorialProvider` requests `response_format:
  {"type": "json_object"}` and parses the content into `EditorialOutput` via
  Pydantic. Metadata fields (`evidence_set_hash`, `prompt_version`, `provider`,
  `model_name`) are enforced by the adapter, not trusted from the model.
- `parse_and_validate()` in `src/newsroom/editorial/validation.py` rejects
  malformed JSON, missing fields, unknown story IDs, unknown evidence refs,
  invented links, duplicate stories, bad enums, and oversized output. It
  performs bounded repair (e.g. markdown code-block extraction, defaulting
  invalid priority to `"medium"`) and records what it repaired.
- `validate_grounding()` in `src/newsroom/editorial/grounding.py` is the second
  pass. It removes claims whose `supporting_evidence_refs` do not exist in the
  evidence set, belong to a different story, or contain numbers/dates/versions
  absent from evidence. Stories left with no claims have their confidence
  downgraded. `GroundingResult` records `removed_claims`, `removed_stories`, and
  `issues`. It is versioned via `GROUNDING_VALIDATOR_VERSION = "g4gv-v1"`.
- The orchestrator runs both passes for AI providers; the deterministic
  provider is already structured so it skips re-validation but still runs
  grounding.

## Rationale
- A versioned schema makes output comparable across runs and providers, and
  lets the delivery layer render without guessing field names.
- Claim-to-evidence mapping (`supporting_evidence_refs`) is what makes the
  report auditable: every claim points back to a real source item.
- The grounding validator is the trust boundary. Model confidence is treated as
  a hint, not as proof; only evidence refs are proof.
- Removing unsupported claims is safer than rewriting them — rewrite risks
  introducing new unsupported content.

## Consequences
- A claim with no valid supporting refs and `support_status == SUPPORTED` is
  removed, not downgraded.
- The number/date heuristic in `_has_unsupported_numbers()` is deliberately
  conservative: false positives (removing a claim that mentioned "2" in a date)
  are preferred over letting an invented figure through. Common small numbers
  (`0,1,2,3,100`) are whitelisted.
- `GroundingResult.issues` is persisted on the `EditorialAttempt` record for
  audit.
- If grounding fails and fallback is enabled, the orchestrator regenerates with
  the deterministic provider and re-grounds (see ADR-009).

# Gate 4 Grounding Validator

Version: `g4gv-v1`

Location: `src/newsroom/editorial/grounding.py`

## Validation checks

For every factual claim:
1. Supporting evidence IDs must exist in the evidence set
2. Evidence must belong to the same story (not a different story)
3. Links must come from persisted source records
4. Numbers/dates/versions in claims must appear in evidence
5. Unsupported claims are removed or cause fallback
6. Disagreement between sources remains visible

## GroundingResult

- `valid`: bool
- `removed_claims`: list of removed claim texts
- `removed_stories`: list of removed story IDs
- `issues`: list of issue descriptions

## Unsupported number detection

Extracts all numbers from claim text via regex.
Checks each against numbers in evidence (headlines, facts, excerpts, release versions).
Common small numbers (0-3, 100) are allowed.
Unsupported numbers cause claim removal.

## Link validation

All `source_links` in the output are checked against the set of URLs in the evidence.
Invented links are removed.

## Ref ID validation

All `supporting_evidence_refs` and `conflicting_evidence_refs` are checked:
- Must exist in the evidence set's `all_ref_ids()`
- Must belong to the same story (not cross-story)

## Conflict preservation

When evidence has `contradictions`, the output must preserve uncertainty.
The deterministic provider labels such stories as `CONFLICTING`.

# Gate 4 Report New Semantics

## Status: VERIFIED

**Date:** 2026-07-18

## Previous /report new defect

The prior implementation wrote delivery cursor state but did not use successfully
delivered story state during story selection. The `/report new` mode selected the same
30 most-recent stories regardless of mode — delivered stories were never excluded.

## Delivered-story definition

A story counts as "delivered" if and only if:

- ✅ It appears in `reports.story_ids` (JSONB array)
- ✅ A `deliveries` record for that report has `status = 'delivered'`
- ✅ Complete delivery (all chunks sent)

A story does NOT count as delivered when:

- ❌ Report generated but not delivered (no `deliveries` row with status='delivered')
- ❌ Editorial attempt alone (no report generated)
- ❌ Failed delivery (`status = 'failed'`)
- ❌ Partial delivery (`status = 'partial'`)
- ❌ Pending delivery (`status = 'pending'`)

Both deterministic fallback reports and AI-edited reports count as delivered when
completely delivered.

## Materially updated story policy

A delivered story can become eligible for `/report new` again only under an explicit
material change, tracked by `Story.material_version` and `Story.material_change_at`:

| Change type | Material? | Rationale |
|-----------|----------|----------|
| New official source added | ✅ Yes | `source_count` increased → `detect_material_change` returns True |
| New fact in evidence packet | ✅ Yes | `facts` set changed |
| New contradiction | ✅ Yes | `contradictions` count increased |
| Duplicate coverage (same story, new source) | ❌ No | Same facts, same source_count |
| Formatting edit (Telegram post edited) | ❌ No | Same facts, same source_count |
| Same facts rephrased | ❌ No | `facts` set unchanged |
| Failed report | N/A | No delivery → story not excluded |
| Partial delivery | N/A | Not delivered → story not excluded |
| Deterministic fallback report | ✅ Yes | Counts as delivered |
| AI-edited report | ✅ Yes | Counts as delivered |

`detect_material_change()` compares old and new evidence packets:
- New source → `source_count` increased
- New fact → `facts` set has new elements
- New contradiction → `contradictions` count increased

`bump_material_version()` increments `Story.material_version` and sets
`Story.material_change_at = now()` when a material change is detected.

## Efficient selection

`select_stories_for_report()` uses set-based SQL:

1. Single query expands `reports.story_ids` JSONB array via `jsonb_array_elements_text`
2. Joins to `deliveries` filtered by `status = 'delivered'`
3. Returns a set of delivered story IDs — no per-story queries
4. Material-change check: single query for most-recent delivery time per story
5. Stories with `material_change_at > delivery_time` are re-included

No loading of all delivery history into memory. No one query per story.
No global timestamp as the only authority.

Recorded counts: `excluded_as_delivered`, `materially_updated`, `selected`, `omitted`.

## No-new-items behavior

When no genuinely new material exists:
- `SelectionResult.no_new_items = True`
- `story_ids = []`
- No provider call is made
- No empty report delivery is created
- No cursors are advanced
- Pipeline returns `status = "ok_empty"` with `no_new_items = True`

## Live verification

The focused live test delivered a report via Telegram and then verified `/report new`:
- Before delivery: 15 stories selected, 0 excluded
- After delivery: `/report new` correctly excluded 15 delivered stories, selected 30 others

Tests: `tests/integration/test_gate4_report_new.py` (16 integration tests)
       `tests/test_editorial_selection.py` (6 unit tests)

# Gate 6 — Source Import Verification

## Workbook location

- Original: `tech_ai_programming_source_radar_global_2026.xlsx` (repo root)
- Import copy: `config/import/source-radar.xlsx` (created by the importer;
  original unchanged; both gitignored as source/derived data)

## Authoritative sheet

`All Sources` — 1 header row + 1344 data rows, 20 columns.

## Row reconciliation (all 1344 accounted for)

| Platform | Workbook count | Inventory rows | Notes |
|---|---|---|---|
| Telegram | 159 | 159 | 157 active + 2 duplicate_identity |
| Reddit | 204 | 204 | 204 active |
| Community | 45 | 45 | 36 active + 9 access_required |
| Community / Forum | 19 | 19 | 19 active |
| X / Twitter | 144 | 144 | 0 active + 144 x_auth_not_configured |
| Website / Newsletter | 464 | 464 | 462 active + 2 duplicate_identity |
| GitHub | 246 | 246 | 244 active + 2 not_a_repo |
| YouTube / Social | 63 | 63 | 63 active |
| **Total** | **1344** | **1344** | reconciled ✓ |

- `validation_counts`: ok=1340, duplicate=4 (all 1344 rows retained; the 4
  duplicate stable identities are marked `operational_state=duplicate`,
  `inactive_reason=duplicate_identity`).
- `SELECT count(*) FROM source_inventory = 1344` ✓ (reconciled with expected total).

## Idempotency

Re-running `uv run newsroom sources import` produces no duplicates: the
idempotency key is `workbook_id` (one inventory row per workbook row). The
second import updates workbook metadata and preserves activation links.
Verified by integration test `test_reimport_is_idempotent` (count stable).

## Preserved workbook fields (per row)

workbook_id, platform, workbook_type (Type), name, handle (Handle/ID),
public_url (Direct URL), topic (Primary Topic), tags, language, content_mode,
speed/informal/noise, is_community, is_opensource_api, risk, review_level
(derived category from Verification), verification (full text),
discovery_source, tier (Core/Discovery/Community/Watchlist), coverage_score,
stable_identity (deterministic hash of platform+normalized handle/URL —
independent of display name), mapped_type, validation_result,
validation_detail, operational_state, inactive_reason.

## Invalid-row handling

Invalid rows are reported individually and do not stop the import
(`report.invalid` lists each with workbook_id, name, platform, result,
detail). One invalid row never blocks the remaining import. In this workbook
all rows validated (ok or duplicate); zero invalid rows.

## Commands

```powershell
uv run newsroom sources import      # parse + upsert inventory
uv run newsroom sources status      # reconciliation summary (JSON)
```

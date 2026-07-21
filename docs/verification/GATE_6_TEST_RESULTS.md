# Gate 6 — Test Results

## Summary

| Suite | Result |
|---|---|
| Deterministic (non-integration) | 583 passed |
| Integration (real PostgreSQL) | 131 passed |
| **Full regression suite** | **714 passed** (0 failed, 3 warnings) |

Run: `uv run pytest tests/ -q` → `714 passed in 203s`.

## Deterministic Gate 6 coverage

- `test_workbook_inventory.py` (18): stable identity per platform, platform→type
  mapping, row validation, synthetic-workbook parsing, expected constants.
- `test_native_adapters.py` (11): HTML reader link/feed extraction + SSRF
  rejection; Reddit RSS parsing + 429/403 recoverable + missing-subreddit;
  YouTube RSS parsing + handle resolution + missing-handle.
- `test_gate6_scheduler_and_commands.py` (12): six-hour schedule specs,
  job IDs, help text, status/sources/schedule text (no secrets), bot dispatch
  of `/status` `/collect` `/sources` `/schedule`.
- `test_command_handlers.py` (13): dispatch routing, access control.
- Existing suites (editorial, dedupe, cluster, normalize, evidence, delivery,
  idempotency, security_redaction, cursors, x_timeline, agent_reach, etc.):
  all green.

## Integration (real PostgreSQL) Gate 6 coverage

- `test_gate6_source_inventory.py` (6): import 1344 + reconcile; idempotent
  re-import; activation links sources + inactive reasons; disabling preserves
  historical items; cursor survives a fresh session (restart); scheduled
  boundary no-news selection.
- `test_gate6_scheduler.py` (1): four six-hour jobs (00/06/12/18) persist in
  `apscheduler_jobs` with coalesce + max_instances.
- Updated gate2/3/5/5x alembic-revision tests accept the 0009 head.

## Ruff

`uv run ruff check` → `All checks passed!` (line-length 100, py312 target).

## MyPy

`uv run mypy` on Gate 6 modules → `Success: no issues found`.

## Migration validation

`uv run alembic upgrade head` → `0008_gate5x_x_ingestion -> 0009_gate6_source_inventory`
applied cleanly. `source_inventory` table + `sources` new columns present
(verified via `inspect`). Downgrade path implemented.

## Docker Compose validation

`docker compose config --quiet` → exit 0 (valid). Services: postgres,
migrate, collector, report-worker, scheduler, telegram-bot,
telegram-ingestor, agent-reach-worker, telegram-authorize — with health
checks, restart policies, and dependency ordering on health.

## Configuration exposure checks

- Bot token / API keys scrubbed from logs (RedactingFilter + httpx→WARNING).
- `/status` `/sources` `/schedule` responses carry no secrets (deterministic
  test `test_status_text_has_no_secrets`).
- `.env`, sessions, Agent-Reach config, `.qwen/`, `.specify/` untracked /
  unchanged (see GATE_6_ACCESS_SAFETY).
- Test placeholders are synthetic and limited to tests.

## Git status

Working tree clean except the gitignored workbook + import copy (excluded
locally). `.qwen/` and `.specify/` unchanged across all commits.

## Soak test (bounded)

`scripts/gate6_soak.py` — 3 cycles, RSS (8 sources):

| Cycle | new | failed | healthy | degraded |
|---|---|---|---|---|
| 1 | 1 | 1 | 34 | 3 |
| 2 | 0 | 1 | 34 | 3 |
| 3 | 1 | 1 | 34 | 3 |

Cycle 2 returned 0 new from the same sources → cursor idempotency confirmed
(no full-history re-scan). Health stable (no error escalation).

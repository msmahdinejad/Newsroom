# ADR: Production Execution Path

**Date**: 2026-07-16
**Status**: Accepted
**Gate**: Gate 1

## Context

Gate 0 found multiple execution paths: `scripts/run_pipeline.py` (standalone), `cli/commands/pipeline.py` (subprocess to script), `scheduler.py` (subprocess to script), `bot.py` (subprocess to script), `scripts/cron_pipeline.py` (subprocess to script). Each path had its own asyncio lifecycle and could diverge.

## Decision

Establish **one authoritative pipeline entrypoint**: `newsroom.pipeline.runner.run_pipeline()`.

### All callers invoke the same function

| Caller | How |
|---|---|
| Scheduled execution | `scheduler.run_scheduled_pipeline` → `run_pipeline()` (in-process, via executor) |
| Manual CLI | `newsroom pipeline run` → `pipeline_run_command` → `run_pipeline()` |
| Telegram bot | `bot._handle_report` → `run_pipeline()` (via executor) |
| Hermes cron | `scripts/cron_pipeline.py` → `scripts/run_pipeline.py` → `run_pipeline()` |
| PowerShell wrappers | `scripts/run-pipeline.ps1` → `scripts/run_pipeline.py` → `run_pipeline()` |

### `scripts/run_pipeline.py`

Thin wrapper that imports and calls `newsroom.pipeline.runner.main`. No business logic. Required for host-side and Hermes execution where the package may not be installed.

### Lifecycle

- Single `asyncio.run(_run_async(...))` per invocation — no nested event loops
- One correlation ID (`NEWSROOM_JOB_ID` or generated)
- Deterministic exit codes: 0 (ok), 1 (error), 2 (busy)
- PostgreSQL advisory lock acquired before any pipeline work
- JobRun record created in the same session

## Consequences

- All paths share the same lock, cursor, and error handling behavior
- No divergence between scheduled and manual execution
- Delivery uses a single async lifecycle (no double `asyncio.run`)
- Native host Python remains a development convenience; Docker is the tested production path

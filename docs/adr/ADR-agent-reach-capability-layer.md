# ADR: Agent-Reach as a Capability Layer

**Status:** accepted
**Date:** 2026-07-18
**Pinned revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)

## Context

The Persian AI Newsroom needs to ingest from external internet and social-platform sources (web pages, RSS, GitHub, YouTube, X, Reddit, LinkedIn, etc.). Building and maintaining individual collectors for every platform is expensive and fragile. Agent-Reach (https://github.com/Panniantong/Agent-Reach) is an upstream capability-selection, installation, diagnostics, and backend-routing layer that wraps platform-specific tools (yt-dlp, gh, feedparser, twitter-cli, OpenCLI, rdt-cli, etc.).

However, Agent-Reach is NOT a stable unified ingestion API. Its platform capabilities may call upstream tools that are mutable, untrusted, and under active development. Treating Agent-Reach as a black-box ingestion source would cede control of source configuration, cursors, retries, normalization, persistence, health, auditability, and security to an upstream tool — unacceptable for a production newsroom.

## Decision

Integrate Agent-Reach as a **capability-selection, installation, diagnostics, and backend-routing layer only**. The Newsroom owns:

- source configuration
- schedules
- durable cursors
- retries
- timeouts
- normalized output
- deduplication
- persistence
- health state
- auditability
- security policy

Agent-Reach may select or diagnose an upstream backend, but it does not own ingestion.

## Integration boundary

```
Newsroom source registry
  -> AgentReach capability resolver
  -> allowlisted platform adapter
  -> fixed upstream command (shell=False, arg array)
  -> bounded structured result
  -> Newsroom normalized item
```

Agent-Reach-specific types never leak past `src/newsroom/sources/agent_reach/` into the core pipeline. The adapters in `adapters.py` produce plain dicts that the existing `Normalizer`, `dedupe`, `cluster`, `evidence`, and `editorial` modules consume without any Agent-Reach dependency.

## Pinned revision

Agent-Reach is pinned to an immutable revision (commit SHA `1494c2ab239e7355a77e7cceaf3271453a1f34b5`, release v1.5.0). The Newsroom does NOT depend on mutable `main`. The Newsroom does NOT enable automatic Agent-Reach self-updates. The Newsroom does NOT vendor the full upstream Git history into the repository (a shallow clone in `agent_reach_audit/` is used for audit only, and is gitignored).

The pinned revision is recorded in:

- `AGENT_REACH_PINNED_VERSION` env var
- `.env.example`
- `agent_reach_backend_state.pinned_version` column
- `docs/verification/GATE_5_AGENT_REACH_AUDIT.md`

## Controlled command runner

The only path that executes Agent-Reach or its upstream backends is `ControlledRunner` (`src/newsroom/sources/agent_reach/runner.py`). It enforces:

- `shell=False` always
- fixed executable allowlist
- fixed operation allowlist per executable
- per-argument validation (URLs, channel IDs, video IDs, repo identifiers, queries)
- sanitized environment (no inherited application secrets)
- timeout, bounded output, child-process termination on timeout
- credential redaction for safe error logging

The editorial AI and source content never produce executable commands. Only typed application code may invoke the runner.

## Consequences

- The Newsroom can safely use Agent-Reach's capability selection without ceding ownership of ingestion.
- Adding a new platform requires a new adapter in `adapters.py` that uses the controlled runner; the core pipeline is untouched.
- Updating Agent-Reach requires re-audit and re-pin (see `GATE_5_AGENT_REACH_AUDIT.md` section 13).
- A channel is NOT production-ready just because `agent-reach doctor` detects it. The `production_ready` flag flips to True only after a bounded real read succeeds.

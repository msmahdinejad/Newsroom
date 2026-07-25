# Gate 7 Release Candidate

## Version and upgrade

Proposed release: **2.0.0**. Upgrade with `uv sync --frozen --extra dev
--extra telegram`, then `uv run alembic upgrade head`. Migration
`0011_gate7_identity_privacy` replaces durable raw Telegram owner/chat fields
with one-way fingerprints; it does not reauthorize, delete, or recreate the
MTProto session.

Use `scripts/up-production.ps1` to start, `scripts/health.ps1` to inspect, and
`docker compose down` for a safe shutdown. Production configuration stays in
ignored local files; copy only the published safe examples on a fresh host.

## Release notes

- Persistent multi-provider editorial router with bounded queue, quotas,
  cooldowns, safe key state, model validation, and idempotent lineage.
- Restored production Telegram MTProto, X/Agent-Reach, native collectors,
  source reconciliation, restart recovery, and full Tehran schedule.
- Hardened Telegram command persistence and proxy/credential redaction.
- Added public governance, CI, release, source, provider, architecture, and
  operational documentation.

## Known limitations

Only Gemini has a validated local provider access value at release time.
Mistral and NVIDIA configured values are provider-account failures; Groq is
not configured. Cross-provider fallback is fully deterministic-tested but not
live-demonstrated until the owner supplies a second working provider. Live
collection remains bounded by upstream availability, rate limits, and the
owner's network routes.

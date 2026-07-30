# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Named digests with independent topics, source membership, language,
  timezone, report size, Telegram minimum, and delivery schedule.
- Code-owned source platform registry for Telegram, X, Reddit, GitHub, and
  websites/feeds.
- Bounded provider model discovery for OpenAI-compatible, Gemini-native, and
  Anthropic-native protocols; discovered routes still require validation.
- Grounded Gemini Search and Deep Research source suggestions with bounded
  probing and explicit operator approval.
- CodeQL, dependency auditing, and SPDX SBOM generation in CI.

### Changed

- Editorial selection, prompting, rendering, scheduling, and lineage are
  digest-aware and no longer limited to programming subjects.
- Report generation receives immutable request data instead of mutating
  process-wide environment variables.
- Reader-facing stories use a localized headline, concise summary, and source
  links; legacy editorial field aliases remain readable for upgrade safety.

### Removed

- The obsolete single-provider editorial adapter and its duplicate test suite.
- User creation of legacy YouTube source entries; existing upgraded entries
  remain collectable.

## [3.0.0] - 2026-07-27

### Added

- Cross-platform idempotent bootstrap with empty, default, selected-default,
  and custom source modes.
- Credential-free starter source catalog and generic CLI source lifecycle.
- Safe provider validation and health commands.
- English-only public repository audit for tracked data and protected values.

### Changed

- Public documentation and project structure were consolidated around supported
  operator and contributor workflows.
- Production images no longer contain tests, developer tooling, or maintenance
  scripts.
- Authenticated social collection is disabled by default.
- Report and bot localization now supports English and Persian by configuration.

### Removed

- Historical gate evidence, local diagnostics, agent-specific skills,
  production snapshots, and duplicate command wrappers.

## [2.0.0] - 2026-07-24

### Added

- Durable PostgreSQL source inventory, item identities, cursors, health,
  evidence lineage, editorial artifacts, reports, and delivery state.
- Bounded native collectors for RSS/Atom, websites, public newsletters,
  GitHub releases, YouTube feeds, Reddit, and Telegram MTProto.
- Isolated X ingestion and an audited Agent-Reach integration pinned to
  revision `1494c2ab239e7355a77e7cceaf3271453a1f34b5`.
- Persistent Gemini, Mistral, Groq, and NVIDIA editorial routing with bounded
  queues, safe key pools, quota accounting, cooldowns, circuit breakers,
  schema repair, and deterministic fallback.
- Hierarchical evidence-grounded localized report generation.
- Tehran 00:00/06:00/12:00/18:00 scheduling and idempotent Telegram delivery.
- Owner-restricted Telegram operational commands.
- Docker Compose production services, health checks, persistent volumes, and
  restart recovery.
- Open-source governance, security, support, CI, release, and third-party
  attribution documentation.

### Security

- Local provider, Telegram, X, proxy, and session values are excluded from Git
  and are not persisted in safe health/audit metadata.
- Collector and editorial inputs are bounded and treated as untrusted data.
- Services run without root privileges and receive integration-specific
  configuration.

### Upgrade notes

- Back up PostgreSQL and Docker volumes before upgrading.
- Run `uv sync --frozen` for host installs and `uv run alembic upgrade head`
  before starting workers.
- Copy new variable names from the example files into ignored local
  configuration; never overwrite existing access values with examples.
- Optional operator source workbooks remain local and must be supplied per deployment.

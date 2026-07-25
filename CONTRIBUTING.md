# Contributing

Thank you for helping improve Persian AI Newsroom. Contributions should keep
collection bounded, preserve evidence and identity, and avoid requiring live
private access in the default test suite.

## Before you start

- Search existing issues before opening a new one.
- Use the bug or feature issue form for substantive changes.
- Discuss architecture changes before implementing a broad rewrite.
- Never include tokens, cookies, proxy credentials, Telegram session data,
  private source inventories, collected content, or production logs.
- Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) and use
  [SECURITY.md](SECURITY.md) for vulnerabilities.

## Development setup

```powershell
Copy-Item .env.example .env
Copy-Item .env.providers.example .env.providers.local
uv sync --frozen --extra dev --extra telegram
docker compose up -d postgres
uv run alembic upgrade head
```

On POSIX systems, use `cp` instead of `Copy-Item`. Leave access-dependent
integrations disabled. A full production inventory is not required for
deterministic tests.

## Making a change

1. Create a focused branch from the current default branch.
2. Add or update tests for behavior changes.
3. Preserve stable IDs, cursors, evidence lineage, retry bounds, and
   idempotency at collector/editorial/delivery boundaries.
4. Add an ADR under `docs/adr/` for an enduring architectural decision.
5. Update user-facing documentation and `CHANGELOG.md` when behavior changes.
6. Keep live checks opt-in and redact all protected values.

## Required checks

```powershell
uv run ruff check src tests
uv run mypy src/newsroom
uv run pytest tests -m "not integration"
uv run pytest tests/integration
docker compose config --quiet
```

Run `docker build --tag newsroom:local .` when changing dependencies,
packaging, Docker, or production runtime behavior. PostgreSQL integration tests
must target an isolated test database, never production.

## Pull requests

Keep pull requests reviewable and explain:

- the problem and the chosen solution;
- user-visible, schema, deployment, or security impact;
- tests and manual verification performed;
- migration, rollback, and access-value implications;
- documentation and changelog updates.

Maintainers may ask for changes when a contribution adds unbounded upstream
work, weakens failure isolation, loses lineage, broadens access exposure, or
depends on private live services in CI.

By contributing, you agree that your contribution is licensed under the MIT
License in [LICENSE](LICENSE), and that you have the right to submit it.

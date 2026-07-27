# Contributing

Thank you for helping improve Newsroom. Contributions should keep
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

```bash
python scripts/bootstrap.py --configuration-only --source-mode empty
uv sync --frozen --extra dev --extra telegram
docker compose up -d --wait postgres
uv run alembic upgrade head
```

Leave access-dependent integrations disabled. A production inventory is not
required for deterministic tests.

## Making a change

1. Create a focused branch from the current default branch.
2. Add or update tests for behavior changes.
3. Preserve stable IDs, cursors, evidence lineage, retry bounds, and
   idempotency at collector/editorial/delivery boundaries.
4. Update architecture documentation for an enduring design change.
5. Update user-facing documentation and `CHANGELOG.md` when behavior changes.
6. Keep live checks opt-in and redact all protected values.

## Required checks

```bash
uv run ruff check src tests
uv run mypy src/newsroom
uv run pytest tests -m "not integration"
uv run pytest tests/integration
docker compose config --quiet
uv run python scripts/audit_public_release.py
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

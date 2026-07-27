# Development

## Environment

```bash
python scripts/bootstrap.py --configuration-only --source-mode empty
uv sync --frozen --extra dev --extra telegram
docker compose up -d --wait postgres
uv run alembic upgrade head
```

## Quality checks

```bash
uv run ruff check src tests
uv run mypy src/newsroom
uv run pytest tests -m "not integration"
uv run pytest tests/integration
docker compose config --quiet
docker build --tag newsroom:local .
uv run python scripts/audit_public_release.py
```

## Design rules

- Put behavior behind a small module interface.
- Keep provider and transport details inside their adapters.
- Inject true external dependencies into testable seams.
- Return structured results instead of parsing log text.
- Keep transaction ownership explicit.
- Use bounded queues, reads, retries, payloads, and file imports.
- Preserve idempotency and evidence lineage across retries.
- Store no credentials in application tables.
- Keep source code, comments, tests, and documentation in English.
- Add localized user-facing text through the localization catalog, not business
  logic.

## Tests

Deterministic tests do not perform live network calls. PostgreSQL integration
tests use an isolated database. Live provider and platform validation is
explicit, bounded, and reads only ignored local configuration.

Tests should assert behavior through module interfaces and observable
persistence outcomes. Avoid tests tied to private production inventories or
operator-specific values.

## Pull requests

Keep changes focused, add a migration for schema changes, include regression
tests, update public documentation, and run the complete quality suite.

## Summary

<!-- What problem does this change solve, and why is this approach appropriate? -->

## Change type

- [ ] Bug fix
- [ ] Feature
- [ ] Refactor
- [ ] Database migration
- [ ] Operations/security
- [ ] Documentation

## Verification

- [ ] Tests cover behavior changes
- [ ] `uv run ruff check src tests`
- [ ] `uv run mypy src/newsroom`
- [ ] `uv run pytest tests -m "not integration"`
- [ ] PostgreSQL integration tests (when relevant)
- [ ] `docker compose config --quiet` (when relevant)
- [ ] Documentation and changelog updated

Commands/results:

```text
Add concise, sanitized results here.
```

## Operational review

- [ ] Work remains bounded; retries/backoff and failure isolation are explicit
- [ ] Stable identities, cursors, evidence lineage, and idempotency are preserved
- [ ] Migration and rollback impact is documented
- [ ] No live integration became mandatory in public CI
- [ ] No credentials, sessions, private inventory/content, personal IDs, or logs are included
- [ ] Third-party terms and licenses were reviewed for new dependencies/services

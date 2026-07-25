# Open-Source Release Guide

This guide is the publication checklist for Persian AI Newsroom. It covers the
repository artifact, not the owner's private production state.

## Release target

- Recommended first public production release: `v2.0.0`
- License for original project code and documentation: MIT
- Supported Python: 3.12 and 3.13 in CI
- Production database: PostgreSQL 16
- Public CI: deterministic and PostgreSQL tests only
- Live provider/platform validation: explicit local opt-in

The version recommendation reflects the mature persistent schema and production
worker architecture. It does not claim unlimited upstream availability or
capacity.

## Files intentionally excluded

The public repository and Docker build context must exclude:

- `.env`, `.env.providers.local`, and `.env.x.local`;
- provider, Telegram, X, proxy, and platform access values;
- Telethon session files and browser/platform state;
- the production source workbook and its imported copy;
- collected source content, generated reports, production logs, and backups;
- local audit clones, caches, diagnostics, and editor/agent state.

The public `.env.example` and `.env.providers.example` contain variable names
and safe defaults/placeholders only. The source inventory documentation
describes the private workbook schema without redistributing owner data.

## Content and data rights

The MIT License covers only original project code and documentation. It does
not grant rights to collected articles, posts, media, model output, platform
data, trademarks, or the private source inventory. Do not add production
database dumps, screenshots containing private IDs, or representative content
without confirming redistribution rights.

See `THIRD_PARTY_NOTICES.md` for direct dependencies and optional external
tools. Preserve upstream license notices when redistributing built artifacts.

## Pre-publication audit

Run from a clean branch:

```powershell
git status --short
git ls-files
git check-ignore .env .env.providers.local .env.x.local
git check-ignore tech_ai_programming_source_radar_global_2026.xlsx
docker compose config --quiet
uv lock --check
uv run ruff check src tests
uv run mypy src/newsroom
uv run pytest tests -m "not integration"
uv run pytest tests/integration
docker build --tag newsroom:release-candidate .
```

Review tracked files and history using secret-scanning tools without printing
matches that may contain protected values. If a real access value ever entered
Git history:

1. make a local backup bundle or protected backup tag;
2. rotate/revoke the exposed value first;
3. rewrite the affected history with `git filter-repo`;
4. rescan the complete rewritten history;
5. coordinate the force-push with collaborators;
6. never push rewritten history automatically from an audit task.

Public publication remains blocked until the rewritten history and all local
artifacts are independently scanned.

## Clean-clone reproduction

Use a disposable directory outside the working copy:

```powershell
git clone --no-local <repository-url> newsroom-release-check
Set-Location newsroom-release-check
Copy-Item .env.example .env
Copy-Item .env.providers.example .env.providers.local
uv sync --frozen --extra dev --extra telegram
docker compose up -d postgres
uv run alembic upgrade head
uv run pytest tests -m "not integration"
uv run pytest tests/integration
docker compose config --quiet
docker build --tag newsroom:clean-clone .
docker compose down
```

Use a dedicated empty database for integration tests. Do not point the clone at
production. A clean clone does not need live Telegram, X, provider, proxy, or
source-workbook access to pass public CI.

## GitHub repository settings

Before publication:

- enable Private Vulnerability Reporting;
- enable Dependabot alerts and security updates;
- require the CI workflow on the default branch;
- require review and dismiss stale approvals for protected branches;
- disable force-push and deletion on the default branch;
- enable secret scanning and push protection where available;
- add a repository description and topics without personal contact data;
- verify issue forms, the pull request template, support, security, and conduct
  links render correctly.

The workflow uses read-only repository permissions and has no live credentials.
Do not add production secrets to the CI repository or environment.

## Release procedure

1. Complete Gate 7 verification and resolve all critical/high findings.
2. Confirm `pyproject.toml`, `CHANGELOG.md`, and release notes agree on `2.0.0`.
3. Back up production PostgreSQL and Docker volumes.
4. Re-run the public and production verification suites.
5. Confirm the working tree is clean and the release commit is signed off.
6. Create an annotated local tag:

   ```powershell
   git tag -a v2.0.0 -m "Persian AI Newsroom 2.0.0"
   ```

7. Inspect the tag, archive contents, license, and notices.
8. Push the branch and tag only after explicit owner approval.
9. Publish release notes with upgrade, migration, and known-limitations sections.

## Upgrade notes for operators

- Back up PostgreSQL and the `telegram_sessions` and Agent-Reach volumes.
- Pull/build the exact release tag; do not deploy a mutable branch.
- Merge new example variable names into ignored local files without overwriting
  working access values.
- Run `uv run alembic upgrade head` (or the Compose `migrate` service) before
  starting workers.
- Reconcile the private source workbook after the migration.
- Verify health, schedule, cursors, provider routes, and a bounded collection
  before enabling scheduled delivery.
- Roll back application code only with a database/volume backup compatible with
  the earlier release; Alembic downgrade is not an automatic data recovery plan.

## Known publication limitations

- Live provider and platform access is owner-specific and cannot be reproduced
  by anonymous CI.
- Upstream sites, APIs, quotas, and access policies can change independently.
- A public clone contains no production source inventory or collected content.
- Community support is best-effort; the system targets a single trusted
  operator rather than untrusted multi-tenancy.

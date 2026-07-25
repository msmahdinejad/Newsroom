# Gate 7 Open-Source Audit

The public release surface includes README, MIT license, changelog,
contributing guide, code of conduct, security and support policies, third-party
notices, EditorConfig, safe environment examples, GitHub issue/PR templates,
Dependabot, and CI for Python 3.12/3.13 deterministic checks, PostgreSQL
integration/migrations, Compose validation, and a production-image build.

The private production workbook, local environments, session material, logs,
backups, and Agent-Reach state are ignored and excluded from Docker context.
The repository ships a synthetic two-row source-inventory example and schema
documentation instead of the private workbook.

An isolated clean clone was exercised with only `.env.example` and
`.env.providers.example`: frozen dependency installation, an empty PostgreSQL
migration, the complete 695-test deterministic suite, Compose validation, and
full safe development-stack startup all passed. Its optional X worker correctly
reported `x_auth_not_configured` rather than using production access.

An exact-value exposure scanner read ignored local configuration without
printing values, then checked tracked files, all reachable Git history,
Compose logs, and a PostgreSQL data dump. Final result: zero matches in every
surface. Before history cleanup a local bundle was written outside the
repository; history was then rewritten to redact prior owner identifiers and
machine paths, repacked, and scanned again. No remote was pushed.

Dependency review confirms locked application dependencies, the pinned
Agent-Reach revision, `twitter-cli` 0.8.5, and SOCKS support are disclosed in
`THIRD_PARTY_NOTICES.md`. Collected source content remains subject to its own
upstream rights and is not relicensed by this repository.

# Gate 7 Final Test Evidence

| Check | Result |
| --- | --- |
| Deterministic suite | 695 passed, 152 integration tests deselected |
| Fresh PostgreSQL integration suite | 152 passed after empty-database migration to `0011_gate7_identity_privacy` |
| Current production-schema Gate 7 integration checks | 5 passed |
| Ruff | passed |
| MyPy | passed for 96 source files |
| Lock verification | `uv lock --check` passed |
| Package build | source distribution and wheel built for 2.0.0 |
| Compose validation | `docker compose config --quiet` passed |
| Production image | `newsroom:gate7-rc` built successfully |
| Router and no-news behavior | deterministic queue/fallback suite passed; no-news pipeline test asserts zero editorial provider calls |

The fresh PostgreSQL run initially exposed three stale assertions that excluded
the new Gate 7 migration head. They were corrected; the rerun passed all 152
tests. Tests use no live provider, Telegram, X, or private session access.

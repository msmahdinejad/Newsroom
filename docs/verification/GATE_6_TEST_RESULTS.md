# Gate 6 — Final Test Results

## Regression suites

| Suite | Result |
|---|---:|
| Non-integration deterministic suite | 640 passed |
| Real PostgreSQL integration tests | 144 passed |
| Full regression suite | **784 passed** |
| Warnings | 3 existing pytest fixture deprecations |

The full suite ran against a freshly created PostgreSQL database migrated from
0001 through `0010_gate6_router_reliability`; the disposable database was
removed afterward. Production state was not used for test cleanup.

The 41 deterministic router cases cover multiple keys, rotation/cooldown,
shared project quota, RPM/TPM/RPD admission, queue backpressure, Gemini
concurrency/spacing, `Retry-After`, invalid-key/model isolation, transient
retry, all provider fallbacks, circuit half-open recovery, schema repair,
idempotent artifacts/delivery, safe metadata, and Gemini sampling omission.

The 11 router persistence integrations cover model/key/quota/circuit state,
usage reconciliation, route/artifact/report lineage, mixed-provider lineage,
restart recovery, delivery-boundary success, rollback, and absence of provider
access values. Gate 5/5X PostgreSQL tests and the connector/X/Telegram focused
suites also pass.

## Build and static checks

- Ruff: all repository paths pass (diagnostic scratch files are excluded).
- MyPy: all 92 source files pass.
- Docker Compose configuration: valid.
- Frozen dependency lock/sync: pass.
- Production image build: pass, including Agent-Reach/twitter-cli version
  assertions.
- Migration head: `0010_gate6_router_reliability`.
- Exact protected-value scan: tracked files, docs, Docker logs, PostgreSQL, and
  health output contain no provider or X access values.

## Status

Software, routing, X ingestion, reporting, Bot API delivery, persistence, and
restart checks pass. Gate 6 remains **NOT VERIFIED** solely because a real new
Telegram MTProto item cannot be collected through the host's blocked external
network path.

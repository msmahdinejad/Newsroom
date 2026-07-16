# Gate 2 — Test Count Accounting

## Unique total

**218 unique tests** collected by `uv run pytest tests/` (no double-count).

Subset labels below are **partitions or named slices**, not additive to 218.

## Partitions (non-overlapping)

| Partition | Count | Paths |
|---|---:|---|
| Unit (non-Telegram domain) | 101 | `test_cluster`, `test_cursors`, `test_dedupe`, `test_evidence`, `test_normalize`, `test_sources`, `test_no_eval` |
| Telegram unit (delivery/render) | 32 | `test_delivery` (12) + `test_render` (18) + shared hash/chunk checks in delivery |
| Bot API client (mocked) | 15 | `test_bot_client.py` |
| Command handlers | 13 | `test_command_handlers.py` |
| Authorization | 14 | `test_access_control.py` |
| Idempotency (unit) | 9 | `test_idempotency.py` |
| Security/redaction | 8 | `test_security_redaction.py` |
| PostgreSQL integration | 26 | `tests/integration/*` (includes Gate 2 schema + partial delivery + Gate 1 suites) |
| **Unique total** | **218** | sum of collected items |

Recount check: 101 + 32 + 15 + 13 + 14 + 9 + 8 + 26 = **218**.

## Named slices (may overlap partitions — do not add)

| Slice | Count | Note |
|---|---:|---|
| Telegram deterministic (client + commands + auth + idempotency + security + delivery/render + Gate2 integration subset) | ~91 | subset of 218, not extra |
| Partial-delivery integration | 5 | inside the 26 PG integration |
| Gate 2 schema integration | 6 | inside the 26 PG integration |
| Live Telegram | 0 | blocked until credentials |

## Live tests

**0** unique live tests executed until credentials present.

## Parametrization

No parametrized multipliers inflate the unique total beyond pytest collection count.

## Earlier reporting note

Prior “218” was the unique pytest collection total. Subtotals listed separately (unit / PG / Telegram) must not be summed again on top of 218.

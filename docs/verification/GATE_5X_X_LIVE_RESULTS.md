# Gate 5X — X/Twitter Live Verification Results

**Date:** 2026-07-20
**Status:** BLOCKED — pending owner configuration

## 1. Current status

Live verification has NOT been performed. It is blocked on two prerequisites that the owner must supply:

1. **Local X auth configured** — the owner must set `TWITTER_AUTH_TOKEN` and `TWITTER_CT0` environment variables in the worker's shell from a dedicated operational X account (not the primary account). The owner confirmed auth is **not yet configured**.

2. **Reviewed curated account list (5–30 public X handles)** — the owner indicated they will provide the list after configuring auth.

## 2. Live verification procedure (to run when prerequisites are met)

Per gate spec section "Live verification":

1. run `agent-reach doctor` (verify twitter-cli backend is available)
2. resolve each configured account (handle → stable numeric account ID via `twitter user --json`)
3. run three bounded polling cycles (`twitter user-posts -n 20 --json` per account)
4. restart the worker between cycles (verify cursor persistence and continuation)
5. verify no duplicates and cursor continuation across restarts
6. include one invalid handle and prove failure isolation (one bad account does not block others)
7. process real X items through normalization, dedup, evidence, AI editorial
8. deliver one Persian report through Telegram (record report_id, delivery_id, message_ids)
9. persist report, delivery, and real Telegram message IDs
10. scan Git, Docker, logs, DB, docs, and health output for cookie/credential leaks

## 3. Script prepared

`scripts/gate5x_live_verification.py` is prepared to run the full live verification procedure. It will be executed once the owner supplies auth + accounts.

## 4. Gate 5X verification criteria

Gate 5X is verified only if timeline reads operate unattended across restart and three polling cycles. Specifically:

- ✅ `agent-reach doctor` shows twitter-cli backend available
- ✅ all configured accounts resolve to stable numeric account IDs
- ✅ three polling cycles complete without operator intervention
- ✅ worker restart between cycles does not lose cursor state
- ✅ no duplicate posts across cycles (content_hash dedup)
- ✅ one invalid handle is isolated (does not block other accounts)
- ✅ at least one real X item flows through normalization, evidence, and AI editorial
- ✅ one Persian report is delivered through Telegram with real message IDs
- ✅ Git, Docker, logs, DB, docs, and health output contain no cookies or credentials

## 5. Result placeholders

The following fields will be populated after live verification:

- doctor results: _pending_
- account resolution results: _pending_
- three polling-cycle results: _pending_
- cursor/restart/duplicate results: _pending_
- failure isolation result: _pending_
- pipeline and Telegram delivery IDs: _pending_

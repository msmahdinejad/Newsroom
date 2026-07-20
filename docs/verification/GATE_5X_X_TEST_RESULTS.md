# Gate 5X — X/Twitter Test Results

**Test run date:** 2026-07-20
**Pinned Agent-Reach revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)
**twitter-cli version:** v0.8.5 (Apache-2.0)

## 1. Deterministic credential-independent tests

**File:** `tests/test_x_timeline.py`
**Count:** 55 tests
**Runner:** `FakeRunner` (no real subprocesses, no network, no credentials)
**Result:** all 55 pass

### Coverage matrix

| Test case | Test names | Result |
|---|---|---|
| Missing auth/backend | `test_missing_auth_raises_collection_error`, `test_missing_handle_raises_collection_error`, `test_missing_backend_raises_runner_error` | ✅ |
| Account resolution | `test_account_resolution_caches_numeric_id`, `test_account_resolution_via_twitter_user`, `test_account_resolution_failure_raises_error` | ✅ |
| Stable IDs | `test_stable_post_id_identity`, `test_stable_account_id_preserved`, `test_handle_not_used_as_identity` | ✅ |
| Original/reply/repost/quote normalization | `test_original_post_classified`, `test_reply_post_classified`, `test_reply_post_included_when_configured`, `test_repost_excluded_by_default`, `test_repost_included_when_configured`, `test_quote_post_included_with_metadata` | ✅ |
| Duplicate overlap | `test_duplicate_post_id_deduped_within_poll` | ✅ |
| Restart cursor | `test_restart_cursor_filters_seen_posts`, `test_restart_cursor_advance` | ✅ |
| Handle change | `test_handle_change_does_not_break_dedup`, `test_handle_resolution_uses_cached_account_id` | ✅ |
| Edit-in-place | `test_edited_post_same_id_same_hash` | ✅ |
| Malformed/oversized output | `test_malformed_json_raises_error`, `test_empty_output_returns_no_items`, `test_non_array_output_returns_no_items`, `test_malformed_post_id_skipped`, `test_oversized_text_truncated` | ✅ |
| Timeout/rate limit/challenge | `test_rate_limit_classified`, `test_challenge_classified`, `test_auth_failure_classified`, `test_rate_limit_recoverable` | ✅ |
| Failure isolation | `test_source_failure_isolated` | ✅ |
| Prompt injection | `test_prompt_injection_in_text_remains_data`, `test_prompt_injection_text_rejected_as_command` | ✅ |
| Forbidden write/search operations | `test_forbidden_operations_not_in_allowlist`, `test_forbidden_executable_not_in_allowlist`, `test_search_operation_rejected`, `test_post_operation_rejected` | ✅ |
| No cookie persistence/leakage | `test_auth_tokens_not_in_source_config`, `test_auth_tokens_passed_only_via_extra_env`, `test_no_cookie_field_in_x_account_state_model`, `test_auth_tokens_never_logged` | ✅ |
| Handle validation | `test_validate_x_handle_accepts_bare`, `test_validate_x_handle_strips_at`, `test_validate_x_handle_rejects_too_long`, `test_validate_x_handle_rejects_special_chars`, `test_validate_x_handle_rejects_empty` | ✅ |
| Post ID validation | `test_validate_x_post_id_accepts_numeric`, `test_validate_x_post_id_rejects_alpha`, `test_validate_x_post_id_rejects_empty` | ✅ |
| Bounded defaults | `test_bounded_defaults_match_spec`, `test_max_posts_bounded` | ✅ |
| Canonical URL | `test_canonical_url_format`, `test_canonical_url_strips_at` | ✅ |
| Media metadata | `test_media_metadata_bounded` | ✅ |
| Adapter close | `test_adapter_close_without_error` | ✅ |

## 2. PostgreSQL integration tests

**File:** `tests/integration/test_gate5x_x_ingestion.py`
**Count:** 15 tests
**Runner:** real PostgreSQL (no MagicMock sessions)
**Result:** all 15 pass

### Coverage matrix

| Test case | Test name | Result |
|---|---|---|
| Schema | `test_x_account_state_table_exists`, `test_alembic_at_gate5x_revision` | ✅ |
| Source import | `test_x_timeline_source_imported` | ✅ |
| Account state persistence | `test_x_account_state_persisted` | ✅ |
| Account/post uniqueness | `test_source_id_unique_in_x_account_state`, `test_post_id_unique_by_content_hash` | ✅ |
| Cursor persistence | `test_cursor_persisted_for_x_source` | ✅ |
| Restart continuation | `test_restart_continues_from_cursor` | ✅ |
| Edit update | `test_edited_x_post_updates_in_place` | ✅ |
| Quote provenance | `test_quote_post_provenance_persisted` | ✅ |
| Health and retry state | `test_health_and_retry_state_persisted` | ✅ |
| Normalized/evidence flow | `test_x_post_flows_to_normalized` | ✅ |
| Transaction rollback | `test_transaction_rollback_on_duplicate_source_id` | ✅ |
| No credentials persisted | `test_no_credential_fields_in_x_account_state`, `test_source_config_no_token_values` | ✅ |

## 3. Regression check

All existing Gate 5 tests continue to pass:
- `tests/test_agent_reach.py` — 103 tests ✅
- `tests/integration/test_gate5_agent_reach.py` — 23 tests ✅
- `tests/integration/test_gate2_schema.py` — 6 tests ✅ (updated for 0008 revision)
- `tests/integration/test_gate3_mtproto.py` — 15 tests ✅ (updated for 0008 revision)

**Total: 173 tests pass** (55 X timeline + 15 X integration + 103 Gate 5 agent_reach).

## 4. Lint and type checks

- `ruff check`: all checks passed
- `mypy`: Success — no issues found in 4 source files

## 5. Secret scanning

Before every commit:
- `git diff` inspected for `BEGIN PRIVATE KEY`, `sk-`, `gsk_`, Telegram bot tokens, `password=` literals — none found.
- `.env` verified untracked.
- `data/agent-reach/` verified untracked.
- `.agent-reach-venv/` verified untracked.
- Telegram sessions verified untracked.
- `.qwen/` and `.specify/` local tooling files verified untouched.

## 6. Live verification tests

**BLOCKED** — pending owner configuration of local X auth and curated account list. The live verification procedure is defined and ready to run once prerequisites are met.

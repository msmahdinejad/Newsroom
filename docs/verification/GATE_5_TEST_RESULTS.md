# Gate 5 — Test Results

**Test run date:** 2026-07-18
**Pinned Agent-Reach revision:** `1494c2ab239e7355a77e7cceaf3271453a1f34b5` (v1.5.0)

## 1. Deterministic credential-independent tests

**File:** `tests/test_agent_reach.py`
**Count:** 103 tests
**Runner:** `FakeRunner` (no real subprocesses, no network, no credentials)
**Result:** all 103 pass

### Coverage matrix (gate spec section 12)

| Test case | Test name | Result |
|---|---|---|
| Agent-Reach disabled | `test_agent_reach_disabled_runner_refuses` | ✅ |
| Agent-Reach executable absent | `test_executable_absent_raises_specific_category` | ✅ |
| Doctor success | `test_doctor_success_parses_channels` | ✅ |
| Doctor malformed output | `test_doctor_malformed_json_records_error` | ✅ |
| Doctor missing channels | `test_doctor_missing_channels_key_records_error` | ✅ |
| Doctor empty output | `test_doctor_empty_output_records_error` | ✅ |
| Doctor non-object output | `test_doctor_non_object_output_records_error` | ✅ |
| Doctor list-shape | `test_doctor_channels_as_list_is_handled` | ✅ |
| Backend unavailable | `test_backend_unavailable_marks_channel_unhealthy` | ✅ |
| Backend fallback | `test_backend_fallback_listed_in_registry` | ✅ |
| Unsupported backend | `test_unsupported_backend_operation_rejected`, `test_unknown_channel_in_doctor_ignored` | ✅ |
| Pinned-version mismatch | `test_pinned_version_required_for_ready`, `test_registry_records_pinned_version` | ✅ |
| Command allowlist | `test_executable_not_in_allowlist_rejected`, `test_executable_allowlist_is_fixed` | ✅ |
| Operation allowlist | `test_operation_allowlist_per_executable` | ✅ |
| `shell=False` | `test_build_command_returns_list_not_string`, `test_build_command_never_includes_shell_metacharacters_as_ops` | ✅ |
| Argument injection | `test_argument_injection_rejected_control_chars`, `test_argument_injection_rejected_semicolon`, `test_argument_injection_rejected_pipe` | ✅ |
| Newline injection | `test_newline_injection_rejected_in_url`, `test_newline_injection_rejected_in_query`, `test_newline_injection_rejected_in_repo_identifier` | ✅ |
| Timeout | `test_timeout_raises_with_timeout_category` | ✅ |
| Process termination | `test_terminate_calls_kill_on_timeout` | ✅ |
| Oversized stdout | `test_oversized_stdout_truncated` | ✅ |
| Oversized stderr | `test_oversized_stderr_truncated` | ✅ |
| Non-zero exit | `test_nonzero_exit_recorded_in_result` | ✅ |
| Credential redaction | `test_redact_bearer_token`, `test_redact_telegram_bot_token`, `test_redact_groq_key`, `test_redact_cookie_header`, `test_redact_authorization_header`, `test_redact_empty_string_passthrough` | ✅ |
| Sanitized environment | `test_sanitized_environment_excludes_secrets`, `test_sanitized_environment_includes_agent_reach_config_dir`, `test_sanitized_environment_rejects_control_chars_in_extra`, `test_sanitized_environment_rejects_non_string_values` | ✅ |
| Web SSRF protection | `test_web_ssrf_rejects_private_ip_literal`, `test_web_ssrf_rejects_localhost`, `test_web_ssrf_rejects_non_http_scheme`, `test_web_ssrf_rejects_ftp_scheme`, `test_is_private_ip_detects_private_ranges`, `test_web_ssrf_accepts_public_domain`, `test_web_adapter_rejects_url_with_control_chars` | ✅ |
| Redirect to private IP | `test_redirect_to_private_ip_rejected` | ✅ |
| YouTube normalization | `test_youtube_normalization_uses_stable_video_id`, `test_youtube_normalization_ai_title_not_used_as_identity`, `test_youtube_adapter_validates_video_id_format` | ✅ |
| X post normalization | `test_x_post_normalization_uses_stable_post_id`, `test_x_adapter_extracts_post_id_from_url`, `test_x_adapter_rejects_non_x_url`, `test_x_adapter_rejects_profile_url` | ✅ |
| Reddit normalization | `test_reddit_post_normalization_uses_stable_post_id`, `test_reddit_adapter_extracts_post_id`, `test_reddit_adapter_extracts_subreddit` | ✅ |
| GitHub normalization | `test_github_discovery_normalization_uses_full_name`, `test_github_discovery_adapter_rejects_long_query`, `test_github_discovery_adapter_rejects_missing_query` | ✅ |
| RSS normalization | `test_rss_normalization_still_works` | ✅ |
| LinkedIn normalization | `test_linkedin_public_normalization_uses_url`, `test_linkedin_adapter_rejects_profile_url` | ✅ |
| Web page normalization | `test_web_page_normalization_uses_url_as_identity` | ✅ |
| Duplicate item | `test_duplicate_youtube_item_skipped_by_content_hash`, `test_duplicate_x_post_skipped_by_post_id` | ✅ |
| Durable cursor | `test_durable_cursor_advances_for_youtube`, `test_durable_cursor_filters_seen_items`, `test_durable_cursor_keeps_overlap_for_idempotency` | ✅ |
| Repeated polling | `test_repeated_polling_advances_cursor` | ✅ |
| Edit behavior | `test_youtube_edit_changes_raw_content_hash_only_if_id_changes` | ✅ |
| Rate limit | `test_rate_limit_state_recorded_in_backend_state` | ✅ |
| Source failure isolation | `test_source_failure_does_not_stop_other_sources` | ✅ |
| Prompt injection remains inert | `test_prompt_injection_in_source_content_does_not_affect_command`, `test_prompt_injection_text_rejected_as_command_argument`, `test_ai_generated_command_string_never_reaches_runner` | ✅ |
| No credential persistence | `test_no_credential_fields_in_backend_state_model`, `test_no_credential_fields_in_source_state_model` | ✅ |
| Provider-disabled stack startup | `test_provider_disabled_stack_startup_is_healthy` | ✅ |
| Authentication enforcement | `test_authenticated_operations_blocked_by_default`, `test_authenticated_operations_allowed_when_opted_in` | ✅ |
| curl restricted to r.jina.ai | `test_curl_rejected_when_not_jina`, `test_curl_allowed_for_jina` | ✅ |
| Doctor run via fake runner | `test_doctor_run_with_fake_runner`, `test_doctor_run_with_failing_result_records_error` | ✅ |
| Web adapter domain allowlist | `test_web_adapter_rejects_unallowlisted_domain`, `test_web_adapter_accepts_allowlisted_domain`, `test_web_adapter_extra_domains_can_be_added` | ✅ |
| Adapter close is safe | `test_adapters_close_without_error` | ✅ |
| Identifier validation | `test_validate_youtube_channel_id_accepts_uc_format`, `test_validate_youtube_channel_id_rejects_short`, `test_validate_youtube_video_id_accepts_11_chars`, `test_validate_youtube_video_id_rejects_10_chars`, `test_validate_repo_identifier_accepts_owner_slash_name`, `test_validate_repo_identifier_rejects_three_segments`, `test_validate_repo_identifier_rejects_empty` | ✅ |
| Production decisions | `test_default_production_decisions_match_preferred_scope`, `test_channels_list_complete`, `test_mark_success_flips_production_ready`, `test_mark_failure_clears_production_ready`, `test_backend_state_serialization_round_trip` | ✅ |

## 2. PostgreSQL integration tests

**File:** `tests/integration/test_gate5_agent_reach.py`
**Count:** 23 tests
**Runner:** real PostgreSQL (no MagicMock sessions)
**Result:** all 23 pass

### Coverage matrix (gate spec section 13)

| Test case | Test name | Result |
|---|---|---|
| Schema exists | `test_gate5_tables_exist` | ✅ |
| Alembic at gate 5 | `test_alembic_at_gate5_revision` | ✅ |
| Agent-Reach source registration | `test_youtube_source_registered`, `test_web_page_source_registered` | ✅ |
| Backend state persistence | `test_backend_state_persisted`, `test_backend_state_channel_unique` | ✅ |
| Stable source identity | `test_youtube_source_url_stable_identity` | ✅ |
| Stable item identity | `test_youtube_raw_item_stable_identity` | ✅ |
| Duplicate prevention | `test_duplicate_video_id_prevented_by_content_hash`, `test_duplicate_prevention_by_content_hash` | ✅ |
| Cursor persistence | `test_cursor_persisted_for_youtube_source` | ✅ |
| Restart continuation | `test_restart_continues_from_persisted_cursor` | ✅ |
| Item-edit update | `test_item_edit_updates_existing_raw_item` | ✅ |
| Source failure isolation | `test_source_failure_does_not_block_other_sources` | ✅ |
| Rate-limit persistence | `test_rate_limit_state_persisted_in_source_state` | ✅ |
| Normalized item flow | `test_youtube_item_flows_to_normalized` | ✅ |
| Evidence linkage | `test_evidence_links_to_youtube_story` | ✅ |
| No cookie persistence | `test_no_cookie_field_in_source_state`, `test_no_cookie_field_in_backend_state`, `test_source_config_does_not_persist_credentials` | ✅ |
| No authorization-header persistence | (covered by `test_no_cookie_field_*`) | ✅ |
| Transaction rollback | `test_transaction_rollback_on_failure` | ✅ |
| Indexes used for scheduled lookup | `test_indexes_exist_for_scheduled_lookup`, `test_index_used_for_channel_health_query` | ✅ |

## 3. Existing test suite (regression check)

The full existing test suite continues to pass. Two pre-existing tests that hard-coded the list of valid alembic revisions were updated to accept `0007_gate5_agent_reach`:

- `tests/integration/test_gate2_schema.py::test_alembic_at_gate2_revision`
- `tests/integration/test_gate3_mtproto.py::test_alembic_at_gate3_revision`

The gate 2 and gate 3 tables continue to exist under the new revision.

## 4. Lint and type checks

- `ruff check`: all checks passed
- `mypy`: all checks passed (on Windows; POSIX-only signal calls guarded by `os.name == "posix"`)

## 5. Secret scanning

Before every commit:

- `git diff` inspected for `BEGIN PRIVATE KEY`, `password=`, `api_key=`, `secret=`, `sk-`, `gsk_` patterns — none found.
- `.env` verified untracked.
- `data/agent-reach/` verified untracked.
- `.agent-reach-venv/` verified untracked.
- `data/sessions/` (Telegram sessions) verified untracked.
- `.qwen/` and `.specify/` local tooling files verified untouched.

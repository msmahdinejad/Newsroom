# Gate 2 — Authorization Verification

## Access Control Design

### Principles
- Fail closed: empty or malformed allowlist denies everyone
- No wildcard or allow-all mode exists
- Authorization checked on EVERY command and EVERY callback, not only /start
- Unauthorized users receive no infrastructure details
- Unauthorized callback attempts are denied

### Implementation (delivery/access.py)

```python
def is_authorized(user_id: int | None) -> bool:
    if user_id is None:
        return False
    allowed = settings.authorized_user_ids()
    if not allowed:
        return False
    return user_id in allowed
```

### Config Parsing (config.py)

- `telegram_authorized_users`: comma-separated numeric IDs
- `authorized_user_ids()`: parses to `set[int]`, skips malformed entries
- Empty string → empty set → deny all
- Malformed entries ("abc", "xyz") skipped, not treated as wildcards
- Whitespace trimmed
- Duplicates deduplicated

## Test Evidence

### Access control tests (14 tests, all pass)
- `test_empty_allowlist_denies_everyone` — empty set denies all
- `test_authorized_user_allowed` — listed ID allowed
- `test_unauthorized_user_denied` — unlisted ID denied
- `test_none_user_id_denied` — None denied
- `test_no_wildcard_mode` — no wildcard, "*", 0 all denied
- `test_malformed_allowlist_denies_safely` — malformed entries don't grant access
- `test_multiple_authorized_users` — multiple IDs work
- `test_deny_message_no_infrastructure_details` — no token/db/api/config in message
- `test_authorized_user_ids_returns_set` — returns set type
- `test_config_parsing_numeric_ids` — "123,456,789" → {123,456,789}
- `test_config_parsing_empty_string` — "" → set()
- `test_config_parsing_malformed_entries_skipped` — "123,abc,456" → {123,456}
- `test_config_parsing_whitespace_trimmed` — " 123 , 456 " → {123,456}
- `test_config_parsing_duplicates_deduped` — "123,123,456" → {123,456}

### Bot-level authorization
- `_handle_update()`: checks `is_authorized(user_id)` for every message and callback
- Unauthorized: records `result="denied"` in `telegram_updates`, sends generic denial
- No infrastructure details leaked to unauthorized users

## Live Verification

Status: pending credentials

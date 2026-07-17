# Gate 3 Channel Registry

**Status**: NOT YET POPULATED

## Channel Registry Schema
The telegram_channels table stores:
- Stable numeric Telegram channel ID (primary identity)
- Public username (mutable, updated on change)
- Display name, language, category
- Trust class: official/community/unverified
- Source state: candidate/configured/enabled/healthy/degraded/auth_required/inaccessible/rate_limited/disabled/invalid
- Cursor: last_message_id, last_observed_ts
- Health: current_error, error_category, floodwait_until
- Stats: posting_frequency, duplicate_rate, spam_rate

## Test Channel Set (not yet provided)
Requires 5-10 authorized public test channels:
- At least 2 Persian technology/AI channels
- At least 2 English technology/AI channels
- 1 official channel
- 1 community channel
- 1 high-volume channel
- 1 low-volume channel
- Channels with forwarded messages, edited posts, external links

## Blocked
Channel registry population is blocked pending test channel username provision.

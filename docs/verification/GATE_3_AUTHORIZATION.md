# Gate 3 Authorization

**Status**: NOT YET EXECUTED

## Authorization Command
- Command: `python -m newsroom.sources.authorize_telegram`
- Requires: TELEGRAM_INGESTOR_ENABLED=true, TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE in .env
- Interactive: login code via getpass (never echoed), 2FA password via getpass (never echoed)
- Lock file prevents concurrent authorization
- Result recorded to /tmp/newsroom_telegram_auth_result.json

## Required Credentials (not yet provided)
- TELEGRAM_API_ID
- TELEGRAM_API_HASH
- TELEGRAM_PHONE
- 5-10 public test channel usernames

## Blocked
Authorization is blocked pending credential provision.
All credential-independent work is complete and tested.

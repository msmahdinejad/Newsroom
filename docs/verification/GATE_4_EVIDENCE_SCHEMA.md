# Gate 4 Evidence Schema

Version: `g4ev-v1`

## EditorialEvidenceSet

Location: `src/newsroom/editorial/schema.py`

Top-level structure sent to the provider:
- `schema_version`: `g4ev-v1`
- `prompt_version`: `g4sp-v1`
- `report_mode`: scheduled/manual/manual_new/manual_comprehensive
- `stories`: list of EvidenceStoryPacket

## EvidenceStoryPacket (per story)

- `story_id`: internal story ID
- `headline`: story headline
- `keywords`: cluster keywords
- `trust_status`: official/confirmed/likely/unconfirmed/rumor
- `confidence`: 0.0-1.0
- `importance_score`: 0.0-1.0
- `source_count`: number of independent sources
- `sources`: list of EvidenceSourceItem (bounded)
- `facts`: extracted facts (max 10)
- `contradictions`: disagreement notes
- `evidence_freshness`: most recent source timestamp

## EvidenceSourceItem (per source)

- `ref_id`: stable reference ID `ev-<story_id>-<seq>`
- `item_id`: internal normalized item ID
- `source_name`: source name
- `source_type`: rss/github_releases/telegram
- `source_trust`: official/community/unverified/reputable
- `source_trust_score`: 0.0-1.0
- `published_at`: ISO timestamp
- `original_title`: bounded to 200 chars
- `excerpt`: bounded to 300 chars
- `original_url`: source URL
- `telegram_permalink`: public Telegram channel URL if available
- `repo_name`: GitHub repo name if applicable
- `release_version`: release version if applicable
- `detected_language`: fa/en

## What is NOT sent

- Telegram session data
- Phone numbers
- API keys, Bot Tokens
- Private messages
- Database credentials
- Environment contents
- Operational logs
- Unrelated source items
- Raw HTML beyond excerpt
- Executable content

## Evidence set hash

`evidence_hash()` produces a SHA-256 of the canonical JSON for caching and audit.

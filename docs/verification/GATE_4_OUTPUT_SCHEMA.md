# Gate 4 Output Schema

Version: `g4out-v1`

## EditorialOutput

Location: `src/newsroom/editorial/schema.py`

### ReportMetadata
- `schema_version`: `g4out-v1`
- `report_mode`: from evidence set
- `generated_at`: ISO timestamp
- `model_name`: provider model name
- `provider`: provider name
- `evidence_set_hash`: from evidence set
- `prompt_version`: `g4sp-v1`
- `editorial_status`: ok/fallback/validation_failed

### StoryEditorialResult (per story)
- `story_id`: matches evidence
- `headline_fa`: Persian headline
- `summary_fa`: concise Persian summary
- `why_it_matters_fa`: concrete importance
- `practical_impact_fa`: specific to audience
- `target_audience`: developers/businesses/researchers/users
- `confidence_level`: 0.0-1.0
- `verification_status`: verified/unverified/conflicting/community
- `classification`: EditorialClassification enum
- `source_ref_ids`: evidence reference IDs
- `source_links`: URLs from evidence
- `key_claims`: list of KeyClaim
- `uncertainty_notes`: disagreement notes
- `suggested_priority`: high/medium/low
- `watch_next_note`: optional

### KeyClaim
- `claim_text`: factual claim in Persian
- `supporting_evidence_refs`: evidence ref IDs
- `support_status`: supported/conflicting/unsupported/unverified
- `confidence`: 0.0-1.0
- `conflicting_evidence_refs`: evidence refs for conflicting sources

### EditorialClassification enum
- OFFICIAL, CORROBORATED, SINGLE_REPUTABLE, COMMUNITY
- CONFLICTING, UNVERIFIED, UNAVAILABLE

### ClaimStatus enum
- SUPPORTED, CONFLICTING, UNSUPPORTED, UNVERIFIED

## No chain-of-thought

The schema does not include any reasoning/thought/chain fields.
Only conclusions and evidence mappings are stored.

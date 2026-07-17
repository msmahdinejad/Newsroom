# Gate 4 Cost and Resource Controls

## Configuration variables

| Variable | Default | Description |
|---|---|---|
| EDITORIAL_MAX_STORIES_PER_CALL | 15 | Maximum stories per editorial call |
| EDITORIAL_MAX_EVIDENCE_PER_STORY | 10 | Maximum evidence items per story |
| EDITORIAL_MAX_EXCERPT_LENGTH | 300 | Maximum excerpt length in chars |
| EDITORIAL_MAX_INPUT_TOKENS | 12000 | Maximum input tokens |
| EDITORIAL_MAX_OUTPUT_TOKENS | 4000 | Maximum output tokens |
| EDITORIAL_TIMEOUT_SECONDS | 60 | Request timeout |
| EDITORIAL_MAX_RETRIES | 2 | Bounded retry count |
| EDITORIAL_CONCURRENCY_LIMIT | 1 | Concurrency limit |
| EDITORIAL_SCHEDULED_RUN_BUDGET | 1 | Model calls per scheduled run |
| EDITORIAL_MANUAL_RUN_BUDGET | 3 | Model calls per manual run |

## Bounding strategy

- Stories are ordered by importance_score desc, then created_at desc
- Only top N stories are included (max_stories_per_call)
- Each story gets at most max_evidence_per_story source items
- Excerpts are truncated to max_excerpt_length chars
- Total input size is bounded by max_input_tokens
- Output is validated against max_output_tokens

## When limits are reached

- Prioritize stories deterministically (importance + recency)
- Record omitted counts in editorial attempt
- Do not silently truncate in the middle of an evidence item
- Retain deterministic fallback

## Model call budget

- Scheduled runs: 1 model call per run
- Manual runs: 3 model calls per run
- The entire database is never sent to one model call

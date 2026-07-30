# Source management

Source configuration is runtime state. The repository ships only a small
credential-free starter catalog and a synthetic custom-file example.

## Initialize a registry

```bash
# Empty
uv run newsroom sources initialize --mode empty --replace

# Default starter subset
uv run newsroom sources initialize --mode default --replace

# Selected starter entries
uv run newsroom sources initialize \
  --mode default \
  --select python-insider,uv,telegram-coding-news \
  --replace

# Custom file
uv run newsroom sources initialize \
  --mode custom \
  --file ./sources.csv \
  --replace
```

`--replace` disables existing sources without deleting collected items,
cursors, or lineage.

## File format

CSV and the first sheet of XLSX files support these columns:

| Column | Required | Notes |
| --- | --- | --- |
| `name` | yes | Unique display name |
| `type` | yes | Supported collector type |
| `url` | yes | Public HTTP(S) source URL |
| `language` | no | Short language tag; defaults to `en` |
| `category` | no | Operator-defined topic |
| `trust_class` | no | `official`, `reputable`, or `community` |
| `enabled` | no | Safe default is disabled |

Supported types:

- `rss`
- `web_page`
- `github_releases`
- `reddit_subreddit`
- `telegram`
- `x_timeline`

These types map to the five code-owned platforms: Telegram, X, Reddit, GitHub,
and websites. Imported files cannot register new executable adapter types.
Older installations may retain legacy collectable types, but new user imports
cannot create them.

Imports are bounded to 5 MiB and 2,000 rows. URLs are normalized and validated.
Source files must never contain cookies, tokens, headers, or proxy credentials.

## Lifecycle

```bash
uv run newsroom sources list --enabled all
uv run newsroom sources add \
  --name "Example channel" \
  --type telegram \
  --url https://t.me/example_channel
uv run newsroom sources list --type telegram
uv run newsroom sources enable 42
uv run newsroom sources disable 42
uv run newsroom sources delete 42 --confirm
```

Archive is preferred to physical deletion because collected evidence and
delivery lineage may reference the source.

The optional extended inventory workbook remains available through
`inventory-import`, `inventory-activate`, `inventory-reconcile`, and
`inventory-status`. It is intended for operators who need row-for-row
accounting of a large private inventory.

## Grounded discovery

Gemini Search can propose bounded candidates for the same five supported
platforms. Suggestions are normalized, checked against private-network
targets, probed with bounded public requests, and stored as pending candidates.
They do not become active sources until an operator approves them.

See [source discovery](source-discovery.md).

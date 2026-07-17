# Gate 3 Cursors

**Status**: COMPLETED

## Live Cursor Verification
- Initial collection: cursors set for 7/8 channels (hackersfeed had no text posts)
- Second collection: 1 new item collected, 30 skipped (overlap idempotent)
- Restart: cursors persisted, collection continued from durable state
- Invalid channel: failed without affecting other channel cursors

## Per-Channel Cursor Values
| Channel | Last Message ID |
|---|---|
| @githubtrending | 15851 |
| @python | 2258955 |
| @hackersfeed | (none) |
| @aipost | 7547 |
| @sabzlearn | 4082 |
| @tproger_official | 14632 |
| @proglib | 11748 |
| @theglitchjournal | 39 |

## Deterministic + Integration Tests
- Cursor advance after persist: PASS
- Cursor isolation between sources: PASS
- Cursor no advance on empty: PASS
- Cursor filter drops older: PASS
- Restart continues from cursor: PASS
